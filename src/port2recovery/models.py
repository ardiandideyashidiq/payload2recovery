from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from payload2recovery.models import RawImageSpec


@dataclass(slots=True)
class ListedPartition:
    name: str
    supported: bool


@dataclass(slots=True)
class PortManifest:
    assert_devices: list[str] = field(default_factory=list)
    group_table: str | None = None
    group_table_size: int | None = None
    raw_images: list[RawImageSpec] = field(default_factory=list)


@dataclass(slots=True)
class BuildOptions:
    rom_dir: Path
    mode: str
    custom_partitions: list[str] = field(default_factory=list)
    brotli_level: int = 6
    zip_level: int = 6
    converter_workers: int = 0
    brotli_workers: int = 0
    workers: int = 0
    group_table: str | None = None
    group_table_size: int | None = None
    no_brotli: bool = False
    keep_temp: bool = False
    output_dir: Path | None = None
    work_dir: Path | None = None
    output_name: str | None = None
    benchmark_report: Path | None = None


@dataclass(slots=True)
class BuildResult:
    output_path: Path
    stage_timings: dict[str, float]
    build_metadata: dict[str, object] = field(default_factory=dict)
