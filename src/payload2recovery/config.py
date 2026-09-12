from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class Settings:
    default_partitions: list[str] = field(default_factory=list)
    zstd_level: int = 5
    zip_level: int = 6
    payload_threads: int = 0
    extractor_workers: int = 0
    converter_workers: int = 0
    zstd_workers: int = 0
    compression: bool = True
    verbose: bool = True
    group_table: str = "main"
    group_table_size: int | None = None
    payload_dumper_go_binary: Path | None = None

    def resolved_payload_threads(self) -> int:
        return self.payload_threads if self.payload_threads > 0 else max(1, os.cpu_count() or 4)

    def resolved_extractor_workers(self) -> int:
        return self.extractor_workers if self.extractor_workers > 0 else max(1, os.cpu_count() or 4)

    def resolved_converter_workers(self) -> int:
        return self.converter_workers if self.converter_workers > 0 else max(1, os.cpu_count() or 4)

    def resolved_zstd_workers(self) -> int:
        return self.zstd_workers if self.zstd_workers > 0 else max(1, os.cpu_count() or 4)


def load_settings(config_dir: Path, default_partitions_file: Path) -> Settings:
    settings = Settings(default_partitions=_load_default_partitions(default_partitions_file))
    toml_path = config_dir / "settings.toml"

    if toml_path.exists():
        data = tomllib.loads(toml_path.read_text())
        tool = data.get("tool", {}).get("payload2recovery", {})
        settings.zstd_level = int(tool.get("zstd_level", settings.zstd_level))
        settings.zip_level = int(tool.get("zip_level", settings.zip_level))
        settings.payload_threads = int(tool.get("payload_threads", settings.payload_threads))
        settings.extractor_workers = int(tool.get("extractor_workers", settings.extractor_workers))
        settings.converter_workers = int(tool.get("converter_workers", settings.converter_workers))
        settings.zstd_workers = int(tool.get("zstd_workers", settings.zstd_workers))
        settings.compression = bool(tool.get("compression", settings.compression))
        settings.verbose = bool(tool.get("verbose", settings.verbose))
        settings.group_table = str(tool.get("group_table", settings.group_table))
        raw_binary = tool.get("payload_dumper_go_binary")
        if raw_binary:
            settings.payload_dumper_go_binary = Path(str(raw_binary))
        size = tool.get("group_table_size", settings.group_table_size)
        settings.group_table_size = int(size) if size not in (None, "") else None

    return settings


def _load_default_partitions(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]
