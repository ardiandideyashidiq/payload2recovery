import os
from pathlib import Path

from payload2recovery.config import Settings, load_settings


def test_load_settings_from_toml(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "settings.toml").write_text(
        "\n".join(
            [
                "[tool.payload2recovery]",
                "extractor_workers = 5",
                "converter_workers = 3",
                "brotli_workers = 2",
                'payload_dumper_go_binary = "/tmp/payload-dumper-go"',
            ]
        )
    )
    defaults = tmp_path / "default_partitions.txt"
    defaults.write_text("system\nvendor\n")
    settings = load_settings(config_dir, defaults)
    assert settings.extractor_workers == 5
    assert settings.converter_workers == 3
    assert settings.brotli_workers == 2
    assert settings.payload_dumper_go_binary == Path("/tmp/payload-dumper-go")


def test_default_runtime_uses_all_logical_cpus() -> None:
    settings = Settings()
    expected = max(1, os.cpu_count() or 4)
    assert settings.verbose is True
    assert settings.brotli_level == 5
    assert settings.resolved_payload_threads() == expected
    assert settings.resolved_extractor_workers() == expected
    assert settings.resolved_converter_workers() == expected
    assert settings.resolved_brotli_workers() == expected
