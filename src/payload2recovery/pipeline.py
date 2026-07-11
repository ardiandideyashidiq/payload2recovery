from __future__ import annotations

import json
import logging
import shutil
from threading import BoundedSemaphore
import time
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from payload2recovery import __version__
from payload2recovery.backends import (
    benchmark_converter,
    compress_brotli,
    extract_payload_bin,
    require_host_dependencies,
    resolve_payload_dumper_go_binary,
    run_payload_extractor,
)
from payload2recovery.config import Settings
from payload2recovery.errors import ValidationError
from payload2recovery.logging import stage_timer
from payload2recovery.metrics import MetricsCollector
from payload2recovery.models import (
    BuildOptions,
    BuildResult,
    DeviceAssertion,
    ListedPartition,
    PartitionArtifact,
    RawImageSpec,
)
from payload2recovery.packaging import (
    build_flashable_zip,
    calculate_group_table_size,
    discover_banner_lines,
    human_size,
    validate_partition_layout,
    write_dynamic_partitions_op_list,
    write_updater_script,
)
from payload2recovery.progress import LiveProgress
from payload2recovery.resources import ResourcePaths


LOGGER = logging.getLogger(__name__)

_UNSUPPORTED_PARTITIONS = {"super", "userdata", "metadata"}
_ALWAYS_DEFAULT_RAW_PARTITIONS = {"logo", "lk"}
_CONDITIONAL_DEFAULT_RAW_PARTITIONS = {"boot"}
_EXPLICIT_RAW_PARTITIONS = {"boot", "init_boot", "vendor_boot", "dtbo", "recovery"}
_EXPLICIT_RAW_PREFIXES = ("vbmeta",)
_KNOWN_LOGICAL_PARTITIONS = {
    "system", "system_ext", "product", "vendor",
    "odm", "odm_dlkm", "vendor_dlkm", "system_dlkm",
}
_DEFAULT_RAW_PROBES = {
    "boot",
    "vendor_boot",
}


def doctor(settings: Settings | None = None) -> dict[str, object]:
    require_host_dependencies()
    if settings is None:
        raise ValidationError("Settings are required for doctor")
    binary = resolve_payload_dumper_go_binary(
        settings.payload_dumper_go_binary or Path("missing"),
        settings.payload_dumper_go_binary,
    )
    return {
        "status": "ok",
        "version": __version__,
        "extractor": str(binary),
    }


def inspect_ota(ota_zip: Path) -> dict[str, str | int]:
    if not ota_zip.exists():
        raise ValidationError(f"File not found: {ota_zip}")
    return {"ota_zip": str(ota_zip), "size": ota_zip.stat().st_size}


def detect_device_assertion(ota_zip: Path) -> DeviceAssertion:
    import zipfile

    candidates: set[str] = set()
    source = ""
    with zipfile.ZipFile(ota_zip) as archive:
        metadata_name = "META-INF/com/android/metadata"
        if metadata_name in archive.namelist():
            metadata = archive.read(metadata_name).decode("utf-8", errors="replace")
            for raw_line in metadata.splitlines():
                line = raw_line.strip()
                if not line or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if key == "pre-device" and value:
                    candidates.update(
                        device.strip() for device in value.split(",") if device.strip()
                    )
                    source = metadata_name
    return DeviceAssertion(
        device_names=sorted(candidates),
        source=source,
        enabled=bool(candidates),
    )


def build(
    options: BuildOptions, settings: Settings, resources: ResourcePaths
) -> BuildResult:
    require_host_dependencies()
    if not options.ota_zip.exists():
        raise ValidationError(f"File not found: {options.ota_zip}")
    if options.ota_zip.suffix.lower() != ".zip":
        raise ValidationError("Only .zip OTA inputs are supported")

    extractor_binary = resolve_payload_dumper_go_binary(
        resources.payload_extractor,
        options.payload_dumper_go_binary or settings.payload_dumper_go_binary,
    )
    device_assertion = detect_device_assertion(options.ota_zip)
    banner_lines = discover_banner_lines(options.ota_zip.parent)
    output_dir = (options.output_dir or options.ota_zip.parent / "output").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics = MetricsCollector()

    with _workspace(options) as workspace:
        partitions_dir = workspace / "partitions"
        stage_output_dir = workspace / "package"
        partitions_dir.mkdir(parents=True, exist_ok=True)
        stage_output_dir.mkdir(parents=True, exist_ok=True)

        with (
            stage_timer("Extracting payload.bin", LOGGER),
            metrics.stage("extract_payload_bin"),
        ):
            payload_bin = extract_payload_bin(options.ota_zip, workspace)

        with (
            stage_timer("Extracting partition images", LOGGER),
            metrics.stage("extract_partitions"),
        ):
            extracted = run_payload_extractor(
                extractor=extractor_binary,
                payload_path=payload_bin,
                output_dir=partitions_dir,
                workers=_resolved_extractor_workers(options, settings),
                verbose=settings.verbose,
                selected_partitions=_extractor_selected_partitions(options),
            )
        if not extracted:
            raise ValidationError("No partition images were extracted from payload.bin")

        (
            logical_partitions,
            default_raw_images,
            explicit_raw_images,
            unsupported_partitions,
            auto_raw_images,
        ) = _classify_extracted_partitions(extracted)
        selected, staged_raw_images = _select_partitions(
            extracted,
            options,
            settings,
            default_raw_images,
            explicit_raw_images,
            unsupported_partitions,
            auto_raw_images,
        )
        if auto_raw_images:
            LOGGER.info(
                "Auto-detected firmware partitions (will flash to both slots): %s",
                ", ".join(sorted(auto_raw_images)),
            )
        validate_partition_layout([path.stem for path in selected])

        with (
            stage_timer("Converting selected partitions", LOGGER),
            metrics.stage("convert_partitions"),
        ):
            artifacts, partition_metrics = _process_partitions(
                selected,
                stage_output_dir,
                options,
                settings,
                resources,
            )

        with (
            stage_timer("Staging raw images", LOGGER),
            metrics.stage("stage_raw_images"),
        ):
            staged_raw_images = _stage_raw_images(stage_output_dir, staged_raw_images)

        group_size = options.group_table_size or settings.group_table_size
        if group_size is None:
            group_size = calculate_group_table_size(
                [artifact.image_size for artifact in artifacts]
            )
        op_list = stage_output_dir / "dynamic_partitions_op_list"
        updater_script = stage_output_dir / "updater-script"
        write_dynamic_partitions_op_list(
            op_list, options.group_table, group_size, artifacts
        )
        if device_assertion.enabled:
            LOGGER.info(
                "Adding device assertion for %s from %s",
                ", ".join(device_assertion.device_names),
                device_assertion.source,
            )
        else:
            LOGGER.warning(
                "Skipping device assertion: no reliable OTA device metadata found"
            )
        write_updater_script(
            updater_script,
            artifacts,
            raw_images=staged_raw_images,
            device_assertion=device_assertion,
            banner_lines=banner_lines,
        )

        output_name = _output_name(options, settings)
        final_output = (output_dir / output_name).resolve()
        meta_dir = stage_output_dir / "META-INF" / "com" / "google" / "android"
        meta_dir.mkdir(parents=True, exist_ok=True)
        updater_script.replace(meta_dir / "updater-script")

        with (
            stage_timer("Building flashable ZIP", LOGGER),
            metrics.stage("package_zip"),
        ):
            zip_progress = LiveProgress(enabled=settings.verbose)
            try:
                build_flashable_zip(
                    stage_output_dir,
                    resources.update_binary,
                    resources.avbctl,
                    final_output,
                    options.zip_level,
                    progress_callback=lambda current_file,
                    files_done,
                    total_files,
                    bytes_done,
                    total_bytes,
                    store_entry: zip_progress.update_package(
                        current_file,
                        files_done,
                        total_files,
                        bytes_done,
                        total_bytes,
                        store_entry=store_entry,
                    ),
                )
            finally:
                zip_progress.close()

        LOGGER.info("Created %s (%s)", final_output, human_size(final_output))
        result = BuildResult(
            output_path=final_output,
            stage_timings=metrics.stage_timings,
            build_metadata={
                "extractor": "payload-dumper-go",
                "extractor_binary": str(extractor_binary),
                "converter": "python",
                "selection_mode": options.mode,
                "partition_count": len(artifacts),
                "selected_partitions": [artifact.name for artifact in artifacts],
                "supported_extracted_partitions": sorted(logical_partitions),
                "default_raw_extracted_partitions": sorted(default_raw_images),
                "excluded_raw_extracted_partitions": sorted(explicit_raw_images),
                "unsupported_extracted_partitions": sorted(unsupported_partitions),
                "raw_images": [
                    {
                        "file": item.file,
                        "target": item.target,
                        "slot_policy": item.slot_policy,
                        "source": item.source,
                    }
                    for item in staged_raw_images
                ],
                "extractor_workers": _resolved_extractor_workers(options, settings),
                "converter_workers": _resolved_converter_workers(
                    options, settings, len(selected)
                ),
                "brotli_workers": _resolved_brotli_workers(
                    options, settings, len(selected)
                ),
                "device_assertion_enabled": device_assertion.enabled,
                "device_assertion_names": device_assertion.device_names,
                "device_assertion_source": device_assertion.source,
                "artifact_size_bytes": final_output.stat().st_size,
                "converter_version": artifacts[0].converter_version
                if artifacts
                else "",
                "brotli_backend": "python-brotli",
                "brotli_backend_version": artifacts[0].metrics.get(
                    "brotli_backend_version", ""
                )
                if artifacts
                else "",
                "partition_metrics": partition_metrics,
                "total_raw_dat_bytes": sum(
                    artifact.raw_dat_size for artifact in artifacts
                ),
                "total_compressed_bytes": sum(
                    artifact.compressed_size for artifact in artifacts
                ),
            },
        )
        if options.benchmark_report:
            _write_benchmark_report(options.benchmark_report, options, result)
        return result


def benchmark(
    options: BuildOptions, settings: Settings, resources: ResourcePaths
) -> dict[str, object]:
    result = build(options, settings, resources)
    return {
        "output_path": str(result.output_path),
        "stage_timings": result.stage_timings,
        "metadata": result.build_metadata,
    }


def list_partitions(
    options: BuildOptions, settings: Settings, resources: ResourcePaths
) -> list[ListedPartition]:
    require_host_dependencies()
    extractor_binary = resolve_payload_dumper_go_binary(
        resources.payload_extractor,
        options.payload_dumper_go_binary or settings.payload_dumper_go_binary,
    )
    with _workspace(options) as workspace:
        payload_bin = extract_payload_bin(options.ota_zip, workspace)
        extracted = run_payload_extractor(
            extractor=extractor_binary,
            payload_path=payload_bin,
            output_dir=workspace / "partitions",
            workers=_resolved_extractor_workers(options, settings),
            verbose=settings.verbose,
            selected_partitions=_extractor_selected_partitions(options),
        )
        supported, default_raw, excluded_raw, unsupported, auto_raw = _classify_extracted_partitions(extracted)
        return [
            ListedPartition(
                name=path.stem,
                supported=path.stem in supported or path.stem in default_raw or path.stem in auto_raw,
                status=_list_partition_status(path.stem, supported, default_raw, excluded_raw, unsupported, auto_raw),
            )
            for path in extracted
        ]


def _process_partitions(
    selected: list[Path],
    stage_output_dir: Path,
    options: BuildOptions,
    settings: Settings,
    resources: ResourcePaths,
) -> tuple[list[PartitionArtifact], list[dict[str, float | int | str | bool]]]:
    workers = _resolved_converter_workers(options, settings, len(selected))
    brotli_slots = _resolved_brotli_workers(options, settings, len(selected))
    LOGGER.info("Using %d conversion workers", workers)
    LOGGER.info("Using %d brotli slots", brotli_slots)
    brotli_gate = BoundedSemaphore(brotli_slots)
    progress = LiveProgress(enabled=settings.verbose)
    results: list[PartitionArtifact] = []
    partition_metrics: list[dict[str, float | int | str | bool]] = []
    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(
                    _build_partition_artifact,
                    image_path,
                    stage_output_dir,
                    options,
                    settings,
                    resources,
                    brotli_gate,
                    progress,
                )
                for image_path in selected
            ]
            for future in futures:
                artifact = future.result()
                results.append(artifact)
                partition_metrics.append(artifact.metrics)
    finally:
        progress.close()
    return sorted(results, key=lambda artifact: artifact.name), sorted(
        partition_metrics, key=lambda metric: str(metric["partition"])
    )


def _build_partition_artifact(
    image_path: Path,
    stage_output_dir: Path,
    options: BuildOptions,
    settings: Settings,
    resources: ResourcePaths,
    brotli_gate: BoundedSemaphore,
    progress: LiveProgress,
) -> PartitionArtifact:
    partition = image_path.stem
    image_size = image_path.stat().st_size
    try:
        converter_result, metrics = benchmark_converter(
            resources.scripts_dir,
            image_path,
            stage_output_dir,
            partition,
            stage_callback=lambda stage: progress.update(partition, stage),
        )
        new_dat = converter_result.new_dat
        progress.update(partition, "waiting-brotli")
        with brotli_gate:
            progress.update(
                partition,
                "brotli",
                processed_bytes=0,
                total_bytes=new_dat.stat().st_size,
                output_bytes=0,
            )
            brotli_started = time.perf_counter()
            compression_result = compress_brotli(
                new_dat,
                level=options.brotli_level,
                enabled=settings.compression and not options.no_brotli,
                verbose=False,
                workers=_resolved_brotli_workers(options, settings, 1),
                progress_callback=lambda processed, total, written: progress.update(
                    partition,
                    "brotli",
                    processed_bytes=processed,
                    total_bytes=total,
                    output_bytes=written,
                ),
            )
            metrics["brotli_seconds"] = time.perf_counter() - brotli_started
        metrics["brotli_backend"] = compression_result.backend
        metrics["brotli_backend_version"] = compression_result.backend_version
        metrics["brotli_level"] = compression_result.level
        metrics["compressed_size_bytes"] = compression_result.output_size
        metrics["compression_ratio"] = (
            compression_result.output_size / compression_result.input_size
            if compression_result.input_size
            else 0.0
        )
        metrics["compression_mib_per_sec"] = (
            compression_result.input_size / (1024 * 1024)
        ) / max(metrics["brotli_seconds"], 0.000001)
        patch_dat = stage_output_dir / f"{partition}.patch.dat"
        if not patch_dat.exists():
            patch_dat.write_bytes(b"")
        artifact = PartitionArtifact(
            name=partition,
            image_path=image_path,
            image_size=image_size,
            transfer_list=converter_result.transfer_list,
            new_dat_br=compression_result.output_file,
            patch_dat=patch_dat,
            converter=converter_result.backend,
            converter_version=converter_result.backend_version,
            raw_dat_size=int(converter_result.validation.get("new_dat_size_bytes", 0)),
            compressed_size=compression_result.output_size,
            validation=converter_result.validation,
            metrics=metrics,
        )
        progress.update(partition, "done")
        return artifact
    except Exception as exc:
        progress.fail(partition, progress.stage(partition), str(exc))
        raise


def _select_partitions(
    extracted: list[Path],
    options: BuildOptions,
    settings: Settings,
    default_raw_images: set[str],
    explicit_raw_images: set[str],
    unsupported_partitions: set[str],
    auto_raw_images: set[str] | None = None,
) -> tuple[list[Path], list[RawImageSpec]]:
    available = {path.stem: path for path in extracted}
    supported, _, _, _, _ = _classify_extracted_partitions(extracted)
    if options.mode == "manual":
        requested = options.custom_partitions
        selected = [available[name] for name in requested if name in supported]
        skipped = [name for name in requested if name not in available or name not in supported]
    elif options.mode == "all":
        selected = [available[name] for name in sorted(supported)]
        skipped = sorted(unsupported_partitions)
        if skipped:
            LOGGER.warning(
                "Skipping unsupported partitions in --all mode: %s", ", ".join(skipped)
            )
    else:
        requested = settings.default_partitions
        selected = [available[name] for name in requested if name in available]
        skipped = [name for name in requested if name not in available]
    if not selected:
        raise ValidationError(
            "None of the requested partitions were found in the OTA payload"
        )
    if skipped:
        if options.mode == "manual":
            LOGGER.warning("Skipping unavailable partitions: %s", ", ".join(skipped))
        elif options.mode == "template":
            LOGGER.warning("Skipping unavailable partitions: %s", ", ".join(skipped))
    raw_images = _selected_raw_images(
        available,
        default_raw_images,
        explicit_raw_images,
        unsupported_partitions,
        options.raw_partitions,
        auto_raw_images,
    )
    return selected, raw_images


def _partition_support(extracted: list[Path]) -> tuple[set[str], set[str]]:
    logical_supported, default_raw, explicit_raw, denied, auto_raw = _classify_extracted_partitions(extracted)
    unsupported = set(default_raw)
    unsupported.update(explicit_raw)
    unsupported.update(denied)
    unsupported.update(auto_raw)
    return logical_supported, unsupported


def _classify_extracted_partitions(
    extracted: list[Path],
) -> tuple[set[str], set[str], set[str], set[str], set[str]]:
    extracted_names = {path.stem for path in extracted}
    logical_supported: set[str] = set()
    default_raw: set[str] = set()
    explicit_raw: set[str] = set()
    unsupported: set[str] = set()
    auto_raw: set[str] = set()

    for path in extracted:
        name = path.stem
        if name in _UNSUPPORTED_PARTITIONS:
            unsupported.add(name)
        elif _is_default_raw_partition(name, extracted_names):
            default_raw.add(name)
        elif _is_explicit_raw_partition(name):
            explicit_raw.add(name)
        elif name in _KNOWN_LOGICAL_PARTITIONS:
            logical_supported.add(name)
        else:
            auto_raw.add(name)
    return logical_supported, default_raw, explicit_raw, unsupported, auto_raw


def _selected_raw_images(
    available: dict[str, Path],
    default_raw_images: set[str],
    explicit_raw_images: set[str],
    unsupported_partitions: set[str],
    requested_raw_partitions: list[str],
    auto_raw_images: set[str] | None = None,
) -> list[RawImageSpec]:
    auto_raw_images = auto_raw_images or set()
    selected_names = sorted(default_raw_images | auto_raw_images)
    skipped_explicit: list[str] = []
    missing: list[str] = []
    for name in requested_raw_partitions:
        if name in default_raw_images or name in explicit_raw_images or name in auto_raw_images:
            if name not in selected_names:
                selected_names.append(name)
        elif name in unsupported_partitions:
            skipped_explicit.append(name)
        else:
            missing.append(name)

    if skipped_explicit:
        LOGGER.warning(
            "Skipping unsupported raw partitions: %s", ", ".join(sorted(skipped_explicit))
        )
    if missing:
        LOGGER.warning(
            "Skipping unavailable raw partitions: %s", ", ".join(sorted(missing))
        )

    raw_images: list[RawImageSpec] = []
    for name in selected_names:
        if name in auto_raw_images:
            raw_spec = _raw_image_spec_for_path(available[name], source="default", slot_policy="both")
        else:
            raw_spec = _raw_image_spec_for_path(available[name], source="default")
        if name in requested_raw_partitions:
            raw_spec.source = "explicit"
        raw_images.append(raw_spec)
    return raw_images


def _extractor_selected_partitions(options: BuildOptions) -> list[str] | None:
    if options.mode != "manual":
        return None
    selected = sorted(
        set(options.custom_partitions)
        | _ALWAYS_DEFAULT_RAW_PARTITIONS
        | _DEFAULT_RAW_PROBES
        | set(options.raw_partitions)
    )
    return selected or None


def _is_default_raw_partition(name: str, extracted_names: set[str]) -> bool:
    if name in _ALWAYS_DEFAULT_RAW_PARTITIONS:
        return True
    if name in _CONDITIONAL_DEFAULT_RAW_PARTITIONS and "vendor_boot" in extracted_names:
        return True
    return False


def _is_explicit_raw_partition(name: str) -> bool:
    return name in _EXPLICIT_RAW_PARTITIONS or name.startswith(_EXPLICIT_RAW_PREFIXES)


def _raw_image_spec_for_path(path: Path, source: str, slot_policy: str = "active") -> RawImageSpec:
    name = path.stem
    if name == "logo":
        return RawImageSpec(
            file=path.name,
            target="/dev/block/by-name/logo",
            slot_policy="none",
            source=source,
        )
    return RawImageSpec(
        file=path.name,
        target=f"/dev/block/by-name/{name}",
        slot_policy=slot_policy,
        source=source,
    )


def _stage_raw_images(stage_output_dir: Path, raw_images: list[RawImageSpec]) -> list[RawImageSpec]:
    staged: list[RawImageSpec] = []
    for raw_image in raw_images:
        source_path = stage_output_dir.parent / "partitions" / raw_image.file
        if not source_path.exists():
            raise ValidationError(f"Missing extracted raw image: {source_path.name}")
        destination = stage_output_dir / raw_image.file
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
        staged.append(raw_image)
    return staged


def _list_partition_status(
    name: str,
    supported: set[str],
    default_raw: set[str],
    excluded_raw: set[str],
    unsupported: set[str],
    auto_raw: set[str] | None = None,
) -> str:
    if name in supported or name in default_raw or (auto_raw and name in auto_raw):
        return "supported"
    if name in excluded_raw:
        return "excluded-by-default"
    return "unsupported"


class _workspace:
    def __init__(self, options: BuildOptions) -> None:
        self.options = options
        self.path: Path | None = None
        self._tempdir: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> Path:
        if self.options.work_dir is not None:
            self.path = self.options.work_dir
            self.path.mkdir(parents=True, exist_ok=True)
            return self.path
        self._tempdir = tempfile.TemporaryDirectory(prefix="payload2recovery-")
        self.path = Path(self._tempdir.name)
        return self.path

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.path and (self.options.keep_temp or self.options.work_dir is not None):
            LOGGER.info("Keeping workspace at %s", self.path)
            return
        if self._tempdir is not None:
            self._tempdir.cleanup()
        elif self.path and self.path.exists():
            shutil.rmtree(self.path, ignore_errors=True)


def _resolved_extractor_workers(options: BuildOptions, settings: Settings) -> int:
    if options.extractor_workers > 0:
        return options.extractor_workers
    if options.payload_threads > 0:
        return options.payload_threads
    return settings.resolved_extractor_workers()


def _resolved_converter_workers(
    options: BuildOptions, settings: Settings, partition_count: int
) -> int:
    _ = partition_count
    if options.converter_workers > 0:
        return max(1, options.converter_workers)
    if options.workers > 0:
        return max(1, options.workers)
    return settings.resolved_converter_workers(partition_count)


def _resolved_brotli_workers(
    options: BuildOptions, settings: Settings, partition_count: int
) -> int:
    _ = partition_count
    if options.brotli_workers > 0:
        return max(1, options.brotli_workers)
    return settings.resolved_brotli_workers(partition_count)


def _output_name(options: BuildOptions, settings: Settings) -> str:
    if options.output_name:
        name = options.output_name
    else:
        base = options.ota_zip.stem.removesuffix("_ota").removeprefix("ota_")
        name = f"{base}-recovery.zip"
    return name if name.endswith(".zip") else f"{name}.zip"


def _write_benchmark_report(
    path: Path, options: BuildOptions, result: BuildResult
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ota_zip": str(options.ota_zip),
        "output_path": str(result.output_path),
        "stage_timings": result.stage_timings,
        "metadata": result.build_metadata,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
