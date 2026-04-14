from pathlib import Path

import pytest

from payload2recovery.errors import ValidationError

from port2recovery.config import Settings, load_manifest, load_settings


def test_load_settings_from_toml(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "port2recovery.toml").write_text(
        "\n".join(
            [
                "[tool.port2recovery]",
                "converter_workers = 3",
                "brotli_workers = 2",
                'group_table = "qti_dynamic"',
            ]
        )
    )
    defaults = tmp_path / "port2recovery_default_partitions.txt"
    defaults.write_text("system\nvendor\n")
    settings = load_settings(config_dir, defaults)
    assert settings.converter_workers == 3
    assert settings.brotli_workers == 2
    assert settings.group_table == "qti_dynamic"


def test_load_manifest_reads_raw_images_and_devices(tmp_path: Path) -> None:
    rom_dir = tmp_path / "rom"
    rom_dir.mkdir()
    (rom_dir / "port2recovery.toml").write_text(
        "\n".join(
            [
                "[device]",
                'assert_devices = ["P13001L-GL"]',
                "",
                "[dynamic_partitions]",
                'group_table = "main"',
                "group_table_size = 1234",
                "",
                "[[raw_images]]",
                'file = "logo.bin"',
                'target = "/dev/block/by-name/logo"',
                'slot_policy = "none"',
                "",
                "[[raw_images]]",
                'file = "lk.img"',
                'target = "/dev/block/by-name/lk"',
                'slot_policy = "active"',
            ]
        )
    )
    manifest = load_manifest(rom_dir)
    assert manifest.assert_devices == ["P13001L-GL"]
    assert manifest.group_table == "main"
    assert manifest.group_table_size == 1234
    assert manifest.raw_images[0].file == "logo.bin"
    assert manifest.raw_images[1].slot_policy == "active"
    assert manifest.raw_images[0].source == "manifest"


def test_load_manifest_rejects_parent_path_escape(tmp_path: Path) -> None:
    rom_dir = tmp_path / "rom"
    rom_dir.mkdir()
    (rom_dir / "port2recovery.toml").write_text(
        "\n".join(
            [
                "[[raw_images]]",
                'file = "../logo.bin"',
                'target = "/dev/block/by-name/logo"',
            ]
        )
    )
    with pytest.raises(ValidationError):
        load_manifest(rom_dir)


def test_default_runtime_uses_all_logical_cpus() -> None:
    settings = Settings()
    assert settings.resolved_converter_workers(1) >= 1
    assert settings.resolved_brotli_workers(1) >= 1
