from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys

from payload2recovery.errors import Payload2RecoveryError
from payload2recovery.logging import configure_logging

from port2recovery.config import load_settings
from port2recovery.models import BuildOptions
from port2recovery.pipeline import benchmark, build, doctor, inspect_rom, list_partitions
from port2recovery.resources import ResourceManager


LOGGER = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    argv = _normalize_argv(argv)
    parser = _build_parser()
    args = parser.parse_args(argv)
    configure_logging(verbose=True)

    resources = ResourceManager()
    try:
        resource_paths = resources.open()
        settings = load_settings(Path("config"), resource_paths.default_partitions)
        settings.verbose = True
        if getattr(args, "command", None) == "doctor":
            info = doctor(settings)
            print(json.dumps(info, indent=2, sort_keys=True))
            return 0
        if args.command == "inspect":
            info = inspect_rom(args.rom_dir, settings)
            print(json.dumps(info, indent=2, sort_keys=True))
            return 0

        options = _options_from_args(args, settings)
        if args.command == "list-partitions":
            for partition in list_partitions(options, settings):
                print(f"{partition.name} [{'supported' if partition.supported else 'unsupported'}]")
            return 0
        if args.command == "build":
            result = build(options, settings, resource_paths)
            print(result.output_path)
            return 0
        if args.command == "benchmark":
            result = benchmark(options, settings, resource_paths)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        parser.error("missing command")
    except Payload2RecoveryError as exc:
        LOGGER.error("%s", exc)
        return 1
    finally:
        resources.close()
    return 0


def _normalize_argv(argv: list[str] | None) -> list[str] | None:
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        return argv
    commands = {"build", "benchmark", "inspect", "list-partitions", "doctor", "-h", "--help"}
    if argv[0] not in commands:
        return ["build", *argv]
    return argv


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="port2recovery",
        description="Repackage a port ROM directory into a custom-recovery flashable ZIP.",
    )
    subparsers = parser.add_subparsers(dest="command")

    doctor_parser = subparsers.add_parser("doctor", help="Check host dependencies")
    doctor_parser.add_argument("-v", "--verbose", action="store_true", help="Ignored; verbose logging is the default")

    inspect_parser = subparsers.add_parser("inspect", help="Inspect a port ROM directory")
    inspect_parser.add_argument("rom_dir", type=Path)
    inspect_parser.add_argument("-v", "--verbose", action="store_true", help="Ignored; verbose logging is the default")

    list_parser = subparsers.add_parser("list-partitions", help="List partition images in the ROM directory")
    _add_common_build_args(list_parser)

    build_parser = subparsers.add_parser("build", help="Generate a recovery-flashable ZIP")
    _add_common_build_args(build_parser)
    _add_build_output_args(build_parser)

    benchmark_parser = subparsers.add_parser("benchmark", help="Run a timed build and emit JSON metrics")
    _add_common_build_args(benchmark_parser)
    _add_build_output_args(benchmark_parser)
    benchmark_parser.add_argument(
        "--benchmark-report",
        type=Path,
        help="Optional JSON file path for benchmark results",
    )
    return parser


def _add_build_output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--output-name",
        help="Final ZIP filename. Defaults to <rom_dir>_recovery.zip",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep the temporary workspace after the build completes",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        help="Use an explicit workspace directory instead of a temporary one",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for final ZIP artifacts. Defaults to ./output inside the ROM directory",
    )


def _add_common_build_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("rom_dir", type=Path, help="Input directory containing ROM images")
    selection_group = parser.add_mutually_exclusive_group()
    selection_group.add_argument(
        "--all",
        action="store_true",
        help="Use all discovered partitions supported by the current package generator.",
    )
    selection_group.add_argument(
        "-p",
        "--partitions",
        nargs="+",
        help="Space-separated partition names. Defaults to the configured template.",
    )
    parser.add_argument("-b", "--brotli-level", type=int, default=None, help="Brotli level 0-11")
    parser.add_argument("-z", "--zip-level", type=int, default=None, help="ZIP level 0-9")
    parser.add_argument(
        "--converter-workers",
        type=int,
        default=0,
        help="Concurrent partition conversion workers",
    )
    parser.add_argument(
        "--brotli-workers",
        type=int,
        default=0,
        help="Maximum concurrent brotli jobs across selected partitions",
    )
    parser.add_argument(
        "-j",
        "--workers",
        type=int,
        default=0,
        help="Alias for --converter-workers",
    )
    parser.add_argument("--group-table", default=None, help="Dynamic partition group name")
    parser.add_argument(
        "--group-table-size",
        type=int,
        default=None,
        help="Explicit group size in bytes. Defaults to computed size.",
    )
    parser.add_argument(
        "--no-brotli",
        action="store_true",
        help="Skip brotli compression and keep *.new.dat.br as a renamed dat file",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Ignored; verbose logging is the default")


def _options_from_args(args: argparse.Namespace, settings) -> BuildOptions:
    partitions = args.partitions or []
    mode = "all" if getattr(args, "all", False) else "manual" if partitions else "template"
    converter_workers = args.converter_workers or args.workers
    return BuildOptions(
        rom_dir=args.rom_dir,
        mode=mode,
        custom_partitions=partitions,
        brotli_level=args.brotli_level if args.brotli_level is not None else settings.brotli_level,
        zip_level=args.zip_level if args.zip_level is not None else settings.zip_level,
        converter_workers=converter_workers,
        brotli_workers=args.brotli_workers,
        workers=args.workers,
        group_table=args.group_table,
        group_table_size=args.group_table_size,
        no_brotli=args.no_brotli,
        keep_temp=getattr(args, "keep_temp", False),
        output_dir=getattr(args, "output_dir", None),
        work_dir=getattr(args, "work_dir", None),
        output_name=getattr(args, "output_name", None),
        benchmark_report=getattr(args, "benchmark_report", None),
    )
