from __future__ import annotations

from pathlib import Path

from payload2recovery.models import BuildOptions, PartitionArtifact, RawImageSpec


def build_metadata(
    options: BuildOptions,
    extractor_binary: Path,
    _selected: list[Path],
    artifacts: list[PartitionArtifact],
    staged_raw_images: list[RawImageSpec],
    logical_partitions: set[str],
    default_raw_images: set[str],
    explicit_raw_images: set[str],
    unsupported_partitions: set[str],
    partition_metrics: list[dict[str, float | int | str | bool]],
    device_assertion_enabled: bool,
    device_assertion_names: list[str],
    device_assertion_source: str,
    extractor_workers: int,
    converter_workers: int,
    brotli_workers: int,
    final_output: Path,
) -> dict[str, object]:
    return {
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
        "extractor_workers": extractor_workers,
        "converter_workers": converter_workers,
        "brotli_workers": brotli_workers,
        "device_assertion_enabled": device_assertion_enabled,
        "device_assertion_names": device_assertion_names,
        "device_assertion_source": device_assertion_source,
        "artifact_size_bytes": final_output.stat().st_size,
        "converter_version": artifacts[0].converter_version if artifacts else "",
        "brotli_backend": "python-brotli",
        "brotli_backend_version": artifacts[0].metrics.get("brotli_backend_version", "") if artifacts else "",
        "partition_metrics": partition_metrics,
        "total_raw_dat_bytes": sum(artifact.raw_dat_size for artifact in artifacts),
        "total_compressed_bytes": sum(artifact.compressed_size for artifact in artifacts),
    }
