from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from payload2recovery.cli import _build_parser, _normalize_argv, _options_from_args
from payload2recovery.config import Settings


def _make_args(**overrides: object) -> argparse.Namespace:
    namespace = argparse.Namespace()
    namespace.all = False
    namespace.partitions = None
    namespace.ota_zip = Path("ota.zip")
    namespace.zstd_level = None
    namespace.zip_level = None
    namespace.payload_threads = 0
    namespace.extractor_workers = 0
    namespace.converter_workers = 0
    namespace.zstd_workers = 0
    namespace.workers = 0
    namespace.payload_dumper_go_binary = None
    namespace.group_table = None
    namespace.group_table_size = None
    namespace.no_zstd = False
    namespace.raw_partitions = []
    namespace.keep_temp = False
    namespace.output_dir = None
    namespace.work_dir = None
    namespace.output_name = None
    namespace.benchmark_report = None
    for key, value in overrides.items():
        setattr(namespace, key, value)
    return namespace


def test_normalize_argv_bare_ota_zip() -> None:
    assert _normalize_argv(["ota.zip"]) == ["build", "ota.zip"]


def test_normalize_argv_with_options() -> None:
    assert _normalize_argv(["ota.zip", "-p", "system"]) == ["build", "ota.zip", "-p", "system"]


@pytest.mark.parametrize("cmd", ["build", "benchmark", "inspect", "list-partitions", "doctor", "-h", "--help"])
def test_normalize_argv_passes_known_commands_unchanged(cmd: str) -> None:
    assert _normalize_argv([cmd, "arg"])[0] == cmd


def test_normalize_argv_empty() -> None:
    assert _normalize_argv([]) == ["--help"]


def test_normalize_argv_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["prog", "ota.zip"])
    assert _normalize_argv(None) == ["build", "ota.zip"]


def test_parser_build_arguments() -> None:
    args = _build_parser().parse_args(["build", "ota.zip"])
    assert args.command == "build"
    assert args.ota_zip == Path("ota.zip")
    assert args.partitions is None
    assert args.zstd_level is None


def test_parser_mutually_exclusive_all() -> None:
    args = _build_parser().parse_args(["build", "ota.zip", "--all"])
    assert args.all is True


def test_parser_mutually_exclusive_partitions() -> None:
    args = _build_parser().parse_args(["build", "ota.zip", "-p", "system", "vendor"])
    assert args.partitions == ["system", "vendor"]


def test_parser_mutually_exclusive_conflict() -> None:
    with pytest.raises(SystemExit):
        _build_parser().parse_args(["build", "ota.zip", "--all", "-p", "system"])


def test_parser_inspect() -> None:
    args = _build_parser().parse_args(["inspect", "ota.zip"])
    assert args.command == "inspect"


def test_parser_doctor() -> None:
    args = _build_parser().parse_args(["doctor"])
    assert args.command == "doctor"


def test_options_from_args_template_mode() -> None:
    args = _make_args(all=False, partitions=None)
    settings = Settings()
    options = _options_from_args(args, settings)
    assert options.mode == "template"
    assert options.zstd_level == settings.zstd_level
    assert options.zip_level == settings.zip_level


def test_options_from_args_manual_mode() -> None:
    args = _make_args(partitions=["system"], all=False)
    settings = Settings()
    options = _options_from_args(args, settings)
    assert options.mode == "manual"
    assert options.custom_partitions == ["system"]


def test_options_from_args_all_mode() -> None:
    args = _make_args(all=True)
    settings = Settings()
    options = _options_from_args(args, settings)
    assert options.mode == "all"


def test_options_from_args_workers_alias() -> None:
    args = _make_args(workers=4, converter_workers=0)
    settings = Settings()
    options = _options_from_args(args, settings)
    assert options.converter_workers == 4


def test_options_from_args_group_table_size() -> None:
    args = _make_args(group_table_size=12345678)
    settings = Settings()
    options = _options_from_args(args, settings)
    assert options.group_table_size == 12345678


def test_options_from_args_raw_partitions_default_empty() -> None:
    args = _make_args(raw_partitions=[])
    settings = Settings()
    options = _options_from_args(args, settings)
    assert options.raw_partitions == []
