from pathlib import Path
import json
import zipfile

from payload2recovery.models import BuildOptions, BuildResult
from payload2recovery.pipeline import _partition_support, _write_benchmark_report, detect_device_assertion


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
            "ota-type=AB\npre-device=P661N\npost-build=Itel/P661N-GL/itel-P661N:12/build\n",
        )
    assertion = detect_device_assertion(ota_zip)
    assert assertion.enabled is True
    assert "P661N" in assertion.device_names
    assert "P661N-GL" in assertion.device_names


def test_partition_support_marks_raw_boot_artifacts_unsupported(tmp_path: Path) -> None:
    extracted = [
        tmp_path / "system.img",
        tmp_path / "product.img",
        tmp_path / "boot.img",
        tmp_path / "vendor_boot.img",
        tmp_path / "vbmeta.img",
    ]
    supported, unsupported = _partition_support(extracted)
    assert supported == {"system", "product"}
    assert unsupported == {"boot", "vendor_boot", "vbmeta"}
