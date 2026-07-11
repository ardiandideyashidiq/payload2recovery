from __future__ import annotations

import json
import logging
import shutil
from threading import BoundedSemaphore
import time
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from payload2recovery.backends import (
    benchmark_converter,
    compress_brotli,
    require_host_dependencies,
)
from payload2recovery.errors import ValidationError
from payload2recovery.logging import stage_timer
from payload2recovery.metrics import MetricsCollector
from payload2recovery.models import DeviceAssertion, PartitionArtifact
from payload2recovery.packaging import (
    build_flashable_zip,
    calculate_group_table_size,
    discover_banner_lines,
    human_size,
    validate_partition_layout,
    write_dynamic_partitions_op_list,
)
from payload2recovery.progress import LiveProgress

from port2recovery import __version__
from port2recovery.config import Settings, load_manifest
from port2recovery.models import BuildOptions, BuildResult, ListedPartition, RawImageSpec
from port2recovery.packaging import write_updater_script
from port2recovery.resources import ResourcePaths


LOGGER = logging.getLogger(__name__)


def doctor(settings: Settings | None = None) -> dict[str, object]:
    _ = settings
    require_host_dependencies()
    return {
        "status": "ok",
        "version": __version__,
        "converter": "python",
        "compression": "python-brotli",
    }


def inspect_rom(rom_dir: Path, settings: Settings) -> dict[str, object]:
    manifest = load_manifest(rom_dir)
    raw_images = _effective_raw_images(rom_dir, manifest)
    logical_images = _discover_logical_images(rom_dir)
    supported, unsupported = _partition_support(logical_images)
    return {
        "rom_dir": str(rom_dir.resolve()),
        "logical_images": sorted(path.name for path in logical_images),
        "supported_partitions": sorted(supported),
        "unsupported_partitions": sorted(unsupported),
        "raw_images": [
            {
                "file": raw_image.file,
                "target": raw_image.target,
                "slot_policy": raw_image.slot_policy,
                "source": raw_image.source,
                "exists": (rom_dir / raw_image.file).exists(),
            }
            for raw_image in raw_images
        ],
        "manifest_present": (rom_dir / "port2recovery.toml").exists(),
        "assert_devices": manifest.assert_devices,
        "group_table": manifest.group_table or settings.group_table,
        "group_table_size": manifest.group_table_size
        if manifest.group_table_size is not None
        else settings.group_table_size,
    }


def list_partitions(options: BuildOptions, settings: Settings) -> list[ListedPartition]:
    require_host_dependencies()
    logical_images = _discover_logical_images(options.rom_dir)
    supported, _ = _partition_support(logical_images)
    return [
        ListedPartition(
            name=path.stem,
            supported=path.stem in supported,
        )
        for path in logical_images
    ]


def build(
    options: BuildOptions, settings: Settings, resources: ResourcePaths
) -> BuildResult:
    require_host_dependencies()
    if not options.rom_dir.exists():
        raise ValidationError(f"Directory not found: {options.rom_dir}")
    if not options.rom_dir.is_dir():
        raise ValidationError(f"Input is not a directory: {options.rom_dir}")

    manifest = load_manifest(options.rom_dir)
    device_assertion = _manifest_device_assertion(manifest)
    banner_lines = discover_banner_lines(options.rom_dir)
    output_dir = (options.output_dir or options.rom_dir / "output").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics = MetricsCollector()
    logical_images = _discover_logical_images(options.rom_dir)
    if not logical_images:
        raise ValidationError(f"No logical partition images found in {options.rom_dir}")

    selected = _select_partitions(logical_images, options, settings)
    validate_partition_layout([path.stem for path in selected])
    raw_images = _resolve_raw_images(options.rom_dir, _effective_raw_images(options.rom_dir, manifest))

    with _workspace(options) as workspace:
        logical_input_dir = workspace / "logical_images"
        stage_output_dir = workspace / "package"
        logical_input_dir.mkdir(parents=True, exist_ok=True)
        stage_output_dir.mkdir(parents=True, exist_ok=True)

        with (
            stage_timer("Staging logical images", LOGGER),
            metrics.stage("stage_logical_images"),
        ):
            staged_selected, padding_metadata = _stage_logical_images(
                options.rom_dir,
                logical_input_dir,
                selected,
            )

        with (
            stage_timer("Converting selected partitions", LOGGER),
            metrics.stage("convert_partitions"),
        ):
            artifacts, partition_metrics = _process_partitions(
                staged_selected,
                stage_output_dir,
                options,
                settings,
                resources,
            )

        with (
            stage_timer("Staging raw images", LOGGER),
            metrics.stage("stage_raw_images"),
        ):
            staged_raw_images = _stage_raw_images(options.rom_dir, stage_output_dir, raw_images)

        group_table = options.group_table or manifest.group_table or settings.group_table
        group_size = options.group_table_size
        if group_size is None:
            group_size = manifest.group_table_size
        if group_size is None:
            group_size = settings.group_table_size
        if group_size is None:
            group_size = calculate_group_table_size(
                [artifact.image_size for artifact in artifacts]
            )
        op_list = stage_output_dir / "dynamic_partitions_op_list"
        updater_script = stage_output_dir / "updater-script"
        write_dynamic_partitions_op_list(
            op_list, group_table, group_size, artifacts
        )
        write_updater_script(
            updater_script,
            artifacts,
            staged_raw_images,
            device_assertion=device_assertion,
            banner_lines=banner_lines,
        )

        output_name = _output_name(options)
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
                "selection_mode": options.mode,
                "partition_count": len(artifacts),
                "selected_partitions": [artifact.name for artifact in artifacts],
                "padded_logical_images": padding_metadata,
                "raw_images": [
                    {
                        "file": item.file,
                        "target": item.target,
                        "slot_policy": item.slot_policy,
                        "source": item.source,
                    }
                    for item in staged_raw_images
                ],
                "converter_workers": _resolved_converter_workers(
                    options, settings, len(selected)
                ),
                "brotli_workers": _resolved_brotli_workers(
                    options, settings, len(selected)
                ),
                "device_assertion_enabled": device_assertion.enabled,
                "device_assertion_names": device_assertion.device_names,
                "artifact_size_bytes": final_output.stat().st_size,
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


def _discover_logical_images(rom_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in rom_dir.iterdir()
        if path.is_file() and path.suffix == ".img"
    )


_KNOWN_LOGICAL_PARTITIONS = {
    "system", "system_ext", "product", "vendor",
    "odm", "odm_dlkm", "vendor_dlkm", "system_dlkm",
}

# Firmware image file names that should be auto-detected as raw images
_AUTO_DETECT_FIRMWARE = {
    "abl", "xbl", "xbl_config", "tz", "hyp", "keymaster",
    "cmnlib", "cmnlib64", "modem", "bluetooth", "dsp",
    "devcfg", "storsec", "mba", "wcnss", "cdt", "qupfw",
    "uefi", "aop", "cpucp", "shrm", "imagefv",
}


def _partition_support(extracted: list[Path]) -> tuple[set[str], set[str]]:
    names = [path.stem for path in extracted]
    supported: set[str] = set()
    unsupported: set[str] = set()
    banned = {"super", "userdata", "metadata"}
    raw_only_prefixes = ("vbmeta",)
    raw_only_exact = {"boot", "init_boot", "vendor_boot", "dtbo", "recovery", "lk"}

    for name in names:
        if name in banned:
            unsupported.add(name)
        elif name in raw_only_exact or name.startswith(raw_only_prefixes):
            unsupported.add(name)
        elif name in _KNOWN_LOGICAL_PARTITIONS:
            supported.add(name)
        else:
            unsupported.add(name)
    return supported, unsupported


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
    extracted: list[Path], options: BuildOptions, settings: Settings
) -> list[Path]:
    available = {path.stem: path for path in extracted}
    supported, unsupported = _partition_support(extracted)
    if options.mode == "manual":
        requested = options.custom_partitions
        selected = [available[name] for name in requested if name in available]
        skipped = [name for name in requested if name not in available]
    elif options.mode == "all":
        selected = [available[name] for name in sorted(supported)]
        skipped = sorted(unsupported)
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
            "None of the requested partitions were found in the ROM directory"
        )
    if skipped:
        LOGGER.warning("Skipping unavailable partitions: %s", ", ".join(skipped))
    return selected


def _resolve_raw_images(rom_dir: Path, raw_images: list[RawImageSpec]) -> list[RawImageSpec]:
    for raw_image in raw_images:
        source_path = rom_dir / raw_image.file
        if not source_path.exists():
            raise ValidationError(f"Missing raw image referenced by manifest: {source_path}")
        if not source_path.is_file():
            raise ValidationError(f"Raw image path is not a file: {source_path}")
    return raw_images


def _effective_raw_images(rom_dir: Path, manifest) -> list[RawImageSpec]:
    if manifest.raw_images:
        return manifest.raw_images
    return _autodetect_raw_images(rom_dir)


def _autodetect_raw_images(rom_dir: Path) -> list[RawImageSpec]:
    has_vendor_boot = (rom_dir / "vendor_boot.img").is_file()
    definitions = [
        ("logo.bin", "/dev/block/by-name/logo", "none"),
        ("lk.img", "/dev/block/by-name/lk", "both"),
    ]
    if has_vendor_boot:
        definitions.append(("boot.img", "/dev/block/by-name/boot", "both"))
    definitions.extend(
        [
            ("init_boot.img", "/dev/block/by-name/init_boot", "both"),
            ("dtbo.img", "/dev/block/by-name/dtbo", "both"),
        ]
    )
    for firmware_name in sorted(_AUTO_DETECT_FIRMWARE):
        definitions.append(
            (f"{firmware_name}.img", f"/dev/block/by-name/{firmware_name}", "both")
        )
    detected: list[RawImageSpec] = []
    for file_name, target, slot_policy in definitions:
        if (rom_dir / file_name).is_file():
            detected.append(
                RawImageSpec(
                    file=file_name,
                    target=target,
                    slot_policy=slot_policy,
                    source="autodetect",
                )
            )
    return detected


def _stage_logical_images(
    rom_dir: Path,
    destination_dir: Path,
    selected: list[Path],
) -> tuple[list[Path], list[dict[str, int | str]]]:
    _ = rom_dir
    staged: list[Path] = []
    padded: list[dict[str, int | str]] = []
    blocksize = 4096

    for source_path in selected:
        destination = destination_dir / source_path.name
        shutil.copy2(source_path, destination)
        original_size = destination.stat().st_size
        remainder = original_size % blocksize
        if remainder:
            padding_bytes = blocksize - remainder
            with destination.open("ab") as handle:
                handle.write(b"\0" * padding_bytes)
            padded_size = original_size + padding_bytes
            LOGGER.info(
                "Padding staged logical image %s by %d bytes to reach %d-byte alignment",
                source_path.name,
                padding_bytes,
                blocksize,
            )
            padded.append(
                {
                    "partition": source_path.stem,
                    "original_size": original_size,
                    "padded_size": padded_size,
                    "padding_bytes": padding_bytes,
                }
            )
        staged.append(destination)
    return staged, padded


def _stage_raw_images(
    rom_dir: Path, stage_output_dir: Path, raw_images: list[RawImageSpec]
) -> list[RawImageSpec]:
    staged: list[RawImageSpec] = []
    for raw_image in raw_images:
        destination = stage_output_dir / raw_image.file
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(rom_dir / raw_image.file, destination)
        staged.append(raw_image)
    return staged


def _manifest_device_assertion(manifest) -> DeviceAssertion:
    return DeviceAssertion(
        device_names=sorted(set(manifest.assert_devices)),
        source="port2recovery.toml",
        enabled=bool(manifest.assert_devices),
    )


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
        self._tempdir = tempfile.TemporaryDirectory(prefix="port2recovery-")
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


def _output_name(options: BuildOptions) -> str:
    if options.output_name:
        name = options.output_name
    else:
        name = f"{options.rom_dir.name}-recovery.zip"
    return name if name.endswith(".zip") else f"{name}.zip"


def _write_benchmark_report(
    path: Path, options: BuildOptions, result: BuildResult
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "rom_dir": str(options.rom_dir),
        "output_path": str(result.output_path),
        "stage_timings": result.stage_timings,
        "metadata": result.build_metadata,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
