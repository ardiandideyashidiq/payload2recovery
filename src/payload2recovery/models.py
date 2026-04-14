from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class ListedPartition:
    name: str
    supported: bool
    status: str = "supported"


@dataclass(slots=True)
class DeviceAssertion:
    device_names: list[str] = field(default_factory=list)
    source: str = ""
    enabled: bool = False


@dataclass(slots=True)
class RawImageSpec:
    file: str
    target: str
    slot_policy: str = "none"
    source: str = ""


@dataclass(slots=True)
class BuildOptions:
    ota_zip: Path
    mode: str
    custom_partitions: list[str] = field(default_factory=list)
    raw_partitions: list[str] = field(default_factory=list)
    brotli_level: int = 6
    zip_level: int = 6
    payload_threads: int = 0
    extractor_workers: int = 0
    converter_workers: int = 0
    brotli_workers: int = 0
    workers: int = 0
    payload_dumper_go_binary: Path | None = None
    group_table: str = "main"
    group_table_size: int | None = None
    no_brotli: bool = False
    keep_temp: bool = False
    output_dir: Path | None = None
    work_dir: Path | None = None
    output_name: str | None = None
    benchmark_report: Path | None = None


@dataclass(slots=True)
class ConverterResult:
    transfer_list: Path
    new_dat: Path
    backend: str
    backend_version: str
    validation: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class CompressionResult:
    output_file: Path
    backend: str
    backend_version: str
    input_size: int
    output_size: int
    level: int
    enabled: bool


@dataclass(slots=True)
class PartitionArtifact:
    name: str
    image_path: Path
    image_size: int
    transfer_list: Path
    new_dat_br: Path
    patch_dat: Path | None = None
    converter: str = ""
    converter_version: str = ""
    raw_dat_size: int = 0
    compressed_size: int = 0
    validation: dict[str, object] = field(default_factory=dict)
    metrics: dict[str, float | int | str | bool] = field(default_factory=dict)


@dataclass(slots=True)
class BuildResult:
    output_path: Path
    stage_timings: dict[str, float]
    build_metadata: dict[str, object] = field(default_factory=dict)
