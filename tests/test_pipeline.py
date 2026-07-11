from pathlib import Path
import json
import zipfile

import payload2recovery.pipeline as pipeline
from payload2recovery.config import Settings
from payload2recovery.models import BuildOptions, BuildResult, CompressionResult, ConverterResult
from payload2recovery.pipeline import (
    _output_name,
    _partition_support,
    _classify_extracted_partitions,
    _write_benchmark_report,
    detect_device_assertion,
)
from payload2recovery.resources import ResourceManager


def test_write_benchmark_report(tmp_path: Path) -> None:
    report_path = tmp_path / "benchmark.json"
    options = BuildOptions(ota_zip=Path("input/test.zip"), mode="template")
    result = BuildResult(
        output_path=Path("output/test.zip"),
        stage_timings={"extract": 1.2, "package": 3.4},
        build_metadata={"extractor": "payload-dumper-go"},
    )
    _write_benchmark_report(report_path, options, result)
    payload = json.loads(report_path.read_text())
    assert payload["ota_zip"] == "input/test.zip"
    assert payload["metadata"]["extractor"] == "payload-dumper-go"
    assert payload["stage_timings"]["package"] == 3.4


def test_write_benchmark_report_keeps_partition_metrics(tmp_path: Path) -> None:
    report_path = tmp_path / "benchmark.json"
    options = BuildOptions(ota_zip=Path("input/test.zip"), mode="template")
    result = BuildResult(
        output_path=Path("output/test.zip"),
        stage_timings={"convert": 2.1},
        build_metadata={
            "extractor": "payload-dumper-go",
            "partition_metrics": [
                {
                    "partition": "system_ext",
                    "backend": "python",
                    "brotli_backend": "python-brotli",
                    "valid": True,
                    "new_dat_size_bytes": 123,
                }
            ],
        },
    )
    _write_benchmark_report(report_path, options, result)
    payload = json.loads(report_path.read_text())
    assert payload["metadata"]["partition_metrics"][0]["backend"] == "python"


def test_detect_device_assertion_from_metadata(tmp_path: Path) -> None:
    ota_zip = tmp_path / "test.zip"
    with zipfile.ZipFile(ota_zip, "w") as archive:
        archive.writestr(
            "META-INF/com/android/metadata",
            "ota-type=AB\npre-device=P661N,P661N-GL\npost-build=google/blazer_beta/blazer:17/build\n",
        )
    assertion = detect_device_assertion(ota_zip)
    assert assertion.enabled is True
    assert "P661N" in assertion.device_names
    assert "P661N-GL" in assertion.device_names
    assert "blazer_beta" not in assertion.device_names


def test_partition_support_marks_raw_boot_artifacts_unsupported(tmp_path: Path) -> None:
    extracted = [
        tmp_path / "system.img",
        tmp_path / "product.img",
        tmp_path / "logo.bin",
        tmp_path / "lk.img",
        tmp_path / "boot.img",
        tmp_path / "vendor_boot.img",
        tmp_path / "vbmeta.img",
    ]
    supported, unsupported = _partition_support(extracted)
    assert supported == {"system", "product"}
    assert unsupported == {"logo", "lk", "boot", "vendor_boot", "vbmeta"}


def test_classify_extracted_partitions_separates_default_and_explicit_raw(tmp_path: Path) -> None:
    extracted = [
        tmp_path / "system.img",
        tmp_path / "logo.bin",
        tmp_path / "lk.img",
        tmp_path / "boot.img",
        tmp_path / "vendor_boot.img",
        tmp_path / "vbmeta.img",
        tmp_path / "super.img",
    ]
    supported, default_raw, explicit_raw, unsupported, auto_raw, skipped = _classify_extracted_partitions(extracted)
    assert supported == {"system"}
    assert default_raw == {"logo", "lk", "boot"}
    assert explicit_raw == {"vbmeta"}
    assert unsupported == {"super"}
    assert auto_raw == set()
    assert skipped == {"vendor_boot"}


def test_classify_extracted_partitions_keeps_boot_explicit_without_vendor_boot(
    tmp_path: Path,
) -> None:
    extracted = [
        tmp_path / "system.img",
        tmp_path / "boot.img",
        tmp_path / "vbmeta.img",
    ]
    supported, default_raw, explicit_raw, unsupported, auto_raw, skipped = _classify_extracted_partitions(extracted)
    assert supported == {"system"}
    assert default_raw == set()
    assert explicit_raw == {"boot", "vbmeta"}
    assert unsupported == set()
    assert auto_raw == set()
    assert skipped == set()

def test_output_name_keeps_full_long_ota_stem() -> None:
    options = BuildOptions(
        ota_zip=Path("ota_super_extraordinarily_verbose_release_candidate_build_name_2026.zip"),
        mode="template",
    )

    assert (
        _output_name(options, Settings())
        == "super_extraordinarily_verbose_release_candidate_build_name_2026-recovery.zip"
    )


def test_list_partitions_reports_supported_excluded_and_unsupported(tmp_path: Path, monkeypatch) -> None:
    ota_zip = tmp_path / "ota.zip"
    ota_zip.write_bytes(b"zip")

    def fake_extract_payload_bin(input_zip: Path, workspace: Path) -> Path:
        _ = input_zip
        payload = workspace / "payload.bin"
        payload.write_bytes(b"payload")
        return payload

    def fake_run_payload_extractor(
        extractor: Path,
        payload_path: Path,
        output_dir: Path,
        workers: int,
        verbose: bool,
        selected_partitions=None,
    ) -> list[Path]:
        _ = extractor, payload_path, workers, verbose, selected_partitions
        files = []
        for name in ("system.img", "logo.bin", "vendor_boot.img", "super.img"):
            path = output_dir / name
            output_dir.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode())
            files.append(path)
        return files

    monkeypatch.setattr(pipeline, "require_host_dependencies", lambda: None)
    monkeypatch.setattr(pipeline, "resolve_payload_dumper_go_binary", lambda bundled, override: bundled)
    monkeypatch.setattr(pipeline, "extract_payload_bin", fake_extract_payload_bin)
    monkeypatch.setattr(pipeline, "run_payload_extractor", fake_run_payload_extractor)

    settings = Settings(default_partitions=["system"], verbose=False)
    options = BuildOptions(ota_zip=ota_zip, mode="template")
    resources = ResourceManager()
    resource_paths = resources.open()
    try:
        listed = pipeline.list_partitions(options, settings, resource_paths)
    finally:
        resources.close()

    assert [(item.name, item.status) for item in listed] == [
        ("system", "supported"),
        ("logo", "supported"),
        ("vendor_boot", "skipped-recovery"),
        ("super", "unsupported"),
    ]


def test_build_stages_default_and_explicit_raw_images(tmp_path: Path, monkeypatch) -> None:
    ota_zip = tmp_path / "ota.zip"
    ota_zip.write_bytes(b"zip")

    def fake_extract_payload_bin(input_zip: Path, workspace: Path) -> Path:
        _ = input_zip
        payload = workspace / "payload.bin"
        payload.write_bytes(b"payload")
        return payload

    def fake_run_payload_extractor(
        extractor: Path,
        payload_path: Path,
        output_dir: Path,
        workers: int,
        verbose: bool,
        selected_partitions=None,
    ) -> list[Path]:
        _ = extractor, payload_path, workers, verbose
        output_dir.mkdir(parents=True, exist_ok=True)
        created: list[Path] = []
        for name in (
            "system.img",
            "logo.bin",
            "lk.img",
            "boot.img",
            "vendor_boot.img",
        ):
            path = output_dir / name
            path.write_bytes(name.encode())
            created.append(path)
        return created

    def fake_benchmark_converter(
        script_dir: Path,
        image_path: Path,
        output_dir: Path,
        partition: str,
        stage_callback=None,
    ):
        _ = script_dir
        if stage_callback is not None:
            stage_callback("dat")
        transfer = output_dir / f"{partition}.transfer.list"
        new_dat = output_dir / f"{partition}.new.dat"
        transfer.write_text("4\n1\n0\n")
        new_dat.write_bytes(f"{partition}-dat".encode())
        return (
            ConverterResult(
                transfer_list=transfer,
                new_dat=new_dat,
                backend="python",
                backend_version="test",
                validation={"new_dat_size_bytes": new_dat.stat().st_size, "valid": True},
            ),
            {"partition": partition, "backend": "python"},
        )

    def fake_compress_brotli(
        input_file: Path,
        level: int,
        enabled: bool,
        verbose: bool,
        workers: int = 0,
        progress_callback=None,
    ):
        _ = verbose, workers
        output_file = input_file.with_suffix(input_file.suffix + ".br")
        data = input_file.read_bytes()
        output_file.write_bytes(data)
        input_file.unlink()
        if progress_callback is not None:
            progress_callback(len(data), len(data), len(data))
        return CompressionResult(
            output_file=output_file,
            backend="python-brotli",
            backend_version="test",
            input_size=len(data),
            output_size=len(data),
            level=level,
            enabled=enabled,
        )

    monkeypatch.setattr(pipeline, "require_host_dependencies", lambda: None)
    monkeypatch.setattr(pipeline, "resolve_payload_dumper_go_binary", lambda bundled, override: bundled)
    monkeypatch.setattr(pipeline, "extract_payload_bin", fake_extract_payload_bin)
    monkeypatch.setattr(pipeline, "run_payload_extractor", fake_run_payload_extractor)
    monkeypatch.setattr(pipeline, "benchmark_converter", fake_benchmark_converter)
    monkeypatch.setattr(pipeline, "compress_brotli", fake_compress_brotli)
    monkeypatch.setattr(pipeline, "detect_device_assertion", lambda ota: pipeline.DeviceAssertion())

    settings = Settings(default_partitions=["system"], verbose=False)
    options = BuildOptions(
        ota_zip=ota_zip,
        mode="manual",
        custom_partitions=["system"],
        raw_partitions=["vendor_boot"],
        output_dir=tmp_path / "dist",
    )
    resources = ResourceManager()
    resource_paths = resources.open()
    try:
        result = pipeline.build(options, settings, resource_paths)
    finally:
        resources.close()

    with zipfile.ZipFile(result.output_path) as archive:
        names = set(archive.namelist())
        assert "bin/avbctl" in names
        assert "boot.img" in names
        assert "logo.bin" in names
        assert "lk.img" in names
        assert "system.transfer.list" in names
        updater_script = archive.read("META-INF/com/google/android/updater-script").decode()
    assert 'package_extract_file("logo.bin", "/dev/block/by-name/logo");' in updater_script
    assert 'package_extract_file("lk.img", "/dev/block/by-name/lk_a")' in updater_script
    assert 'package_extract_file("lk.img", "/dev/block/by-name/lk_b")' in updater_script
    assert 'package_extract_file("boot.img", "/dev/block/by-name/boot_a")' in updater_script
    assert 'package_extract_file("boot.img", "/dev/block/by-name/boot_b")' in updater_script
    assert result.build_metadata["raw_images"] == [
        {
            "file": "boot.img",
            "target": "/dev/block/by-name/boot",
            "slot_policy": "both",
            "source": "default",
        },
        {
            "file": "lk.img",
            "target": "/dev/block/by-name/lk",
            "slot_policy": "both",
            "source": "default",
        },
        {
            "file": "logo.bin",
            "target": "/dev/block/by-name/logo",
            "slot_policy": "none",
            "source": "default",
        },
    ]
