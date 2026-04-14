from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import tomllib

from payload2recovery.errors import ValidationError

from port2recovery.models import PortManifest, RawImageSpec


@dataclass(slots=True)
class Settings:
    default_partitions: list[str] = field(default_factory=list)
    brotli_level: int = 5
    zip_level: int = 6
    converter_workers: int = 0
    brotli_workers: int = 0
    compression: bool = True
    verbose: bool = True
    group_table: str = "main"
    group_table_size: int | None = None

    def resolved_converter_workers(self, partition_count: int) -> int:
        _ = partition_count
        return self.converter_workers if self.converter_workers > 0 else max(1, os.cpu_count() or 4)

    def resolved_brotli_workers(self, partition_count: int) -> int:
        _ = partition_count
        return self.brotli_workers if self.brotli_workers > 0 else max(1, os.cpu_count() or 4)


def load_settings(config_dir: Path, default_partitions_file: Path) -> Settings:
    settings = Settings(default_partitions=_load_default_partitions(default_partitions_file))
    toml_path = config_dir / "port2recovery.toml"
    if not toml_path.exists():
        return settings

    data = tomllib.loads(toml_path.read_text())
    tool = data.get("tool", {}).get("port2recovery", {})
    settings.brotli_level = int(tool.get("brotli_level", settings.brotli_level))
    settings.zip_level = int(tool.get("zip_level", settings.zip_level))
    settings.converter_workers = int(tool.get("converter_workers", settings.converter_workers))
    settings.brotli_workers = int(tool.get("brotli_workers", settings.brotli_workers))
    settings.compression = bool(tool.get("compression", settings.compression))
    settings.verbose = bool(tool.get("verbose", settings.verbose))
    settings.group_table = str(tool.get("group_table", settings.group_table))
    size = tool.get("group_table_size", settings.group_table_size)
    settings.group_table_size = int(size) if size not in (None, "") else None
    return settings


def load_manifest(rom_dir: Path) -> PortManifest:
    manifest_path = rom_dir / "port2recovery.toml"
    if not manifest_path.exists():
        return PortManifest()

    data = tomllib.loads(manifest_path.read_text())
    device = data.get("device", {})
    dynamic = data.get("dynamic_partitions", {})
    raw_images = [
        _load_raw_image(item, manifest_path)
        for item in data.get("raw_images", [])
    ]
    size = dynamic.get("group_table_size")
    return PortManifest(
        assert_devices=[str(item) for item in device.get("assert_devices", [])],
        group_table=str(dynamic["group_table"]) if "group_table" in dynamic else None,
        group_table_size=int(size) if size not in (None, "") else None,
        raw_images=raw_images,
    )


def _load_raw_image(item: object, manifest_path: Path) -> RawImageSpec:
    if not isinstance(item, dict):
        raise ValidationError(f"Invalid raw_images entry in {manifest_path}")
    file_name = str(item.get("file", "")).strip()
    target = str(item.get("target", "")).strip()
    slot_policy = str(item.get("slot_policy", "none")).strip() or "none"
    if not file_name:
        raise ValidationError(f"raw_images.file is required in {manifest_path}")
    if not target:
        raise ValidationError(f"raw_images.target is required for {file_name} in {manifest_path}")
    if slot_policy not in {"none", "active"}:
        raise ValidationError(
            f"Unsupported slot_policy for {file_name} in {manifest_path}: {slot_policy}"
        )
    if Path(file_name).is_absolute() or ".." in Path(file_name).parts:
        raise ValidationError(f"raw_images.file must stay inside the ROM directory: {file_name}")
    return RawImageSpec(file=file_name, target=target, slot_policy=slot_policy, source="manifest")


def _load_default_partitions(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]
