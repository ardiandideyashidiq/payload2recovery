from __future__ import annotations

import importlib
import logging
import re
import shutil
import subprocess
import sys
import types
import zipfile
from collections.abc import Callable
from pathlib import Path
from threading import Lock
from time import perf_counter

import brotli  # type: ignore[import-untyped]

from payload2recovery.errors import ValidationError
from payload2recovery.models import CompressionResult, ConverterResult

LOGGER = logging.getLogger(__name__)
_CONVERTER_IMPORT_LOCK = Lock()
_CONVERTER_VERSION = "img2sdat-1.7-captured"
_BROTLI_BACKEND_VERSION = f"brotli-{brotli.__version__}"
_ZSTD_BACKEND_VERSION = _BROTLI_BACKEND_VERSION


def require_host_dependencies() -> None:
    missing = [tool for tool in ("python3",) if shutil.which(tool) is None]
    if missing:
        raise ValidationError(f"Missing host dependencies: {', '.join(missing)}")


def resolve_payload_dumper_go_binary(vendored_binary: Path, override_binary: Path | None = None) -> Path:
    candidate = override_binary or vendored_binary
    if not candidate.exists():
        raise ValidationError(f"payload-dumper-go binary not found: {candidate}")
    return candidate


def list_payload_partitions(extractor: Path, payload_path: Path) -> list[str]:
    cmd = [str(extractor), "-l", str(payload_path)]
    completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        return []
    match = re.search(r"Found partitions:\s*([^\n]+(?:\n\s*[^\n]+)*)", completed.stdout)
    if not match:
        return []
    return re.findall(r"(\b[a-zA-Z0-9_]+)\s+\([0-9.]+\s+[kKMGT]?B\)", match.group(0))


def extract_payload_bin(ota_zip: Path, work_dir: Path) -> Path:
    payload_path = work_dir / "payload.bin"
    unzip_bin = shutil.which("unzip")
    if unzip_bin:
        result = subprocess.run(
            [unzip_bin, "-q", "-o", str(ota_zip), "payload.bin", "-d", str(work_dir)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode == 0 and payload_path.is_file():
            return payload_path

    with zipfile.ZipFile(ota_zip) as archive:
        try:
            with archive.open("payload.bin") as src, payload_path.open("wb") as dst:
                while chunk := src.read(8 * 1024 * 1024):
                    dst.write(chunk)
        except KeyError as exc:
            raise ValidationError("OTA zip does not contain payload.bin") from exc
    return payload_path


def run_payload_extractor(
    extractor: Path,
    payload_path: Path,
    output_dir: Path,
    workers: int,
    verbose: bool,
    selected_partitions: list[str] | None = None,
) -> list[Path]:
    cmd = [str(extractor), "-o", str(output_dir), "-c", str(workers)]
    if selected_partitions:
        cmd.extend(["-p", ",".join(selected_partitions)])
    cmd.append(str(payload_path))
    LOGGER.debug("Running extractor: %s", " ".join(cmd))
    _run(cmd, verbose=verbose)
    images = _sorted_images(output_dir)
    if not images:
        raise ValidationError("payload-dumper-go did not produce any partition images")
    return images


def convert_img_to_sparse(script_dir: Path, image_path: Path, img2simg_bin: Path | None = None) -> None:
    native_binary = img2simg_bin if (img2simg_bin and img2simg_bin.is_file()) else shutil.which("img2simg")
    if native_binary:
        output_path = image_path.with_suffix(".img.sparse")
        _run([str(native_binary), str(image_path), str(output_path)], verbose=False)
        output_path.replace(image_path)
        return

    module = _load_script_module(script_dir, "img2simg")
    output_path = image_path.with_suffix(".img.sparse")
    blocksize = 4096
    with image_path.open("rb") as src, output_path.open("wb") as dst:
        writer = module.SimgWriter(dst, blocksize=blocksize)
        while chunk := src.read(8 * 1024 * 1024):
            writer.write(chunk)
        writer.close()
    output_path.replace(image_path)


def convert_sparse_to_dat(
    script_dir: Path,
    image_path: Path,
    output_dir: Path,
    partition: str,
) -> ConverterResult:
    _convert_sparse_to_dat_subprocess(script_dir, image_path, output_dir, partition)
    transfer = output_dir / f"{partition}.transfer.list"
    new_dat = output_dir / f"{partition}.new.dat"
    if not transfer.exists():
        raise ValidationError(f"Missing transfer list: {transfer}")
    if not new_dat.exists():
        raise ValidationError(f"Missing new.dat output: {new_dat}")
    transfer_lines = [line.strip() for line in transfer.read_text().splitlines() if line.strip()]
    if len(transfer_lines) < 2:
        raise ValidationError(f"Transfer list is too short: {transfer}")
    try:
        transfer_version = int(transfer_lines[0])
        total_blocks = int(transfer_lines[1])
    except ValueError as exc:
        raise ValidationError(f"Transfer list header is invalid: {transfer}") from exc
    if total_blocks < 0:
        raise ValidationError(f"Transfer list block count is invalid: {transfer}")
    if new_dat.stat().st_size <= 0:
        raise ValidationError(f"Generated new.dat is empty: {new_dat}")
    return ConverterResult(
        transfer_list=transfer,
        new_dat=new_dat,
        backend="python",
        backend_version=_CONVERTER_VERSION,
        validation={
            "valid": True,
            "transfer_version": transfer_version,
            "transfer_line_count": len(transfer_lines),
            "total_blocks": total_blocks,
            "new_dat_size_bytes": new_dat.stat().st_size,
        },
    )


def compress_brotli(
    input_file: Path,
    level: int,
    enabled: bool,
    verbose: bool,
    workers: int = 0,
    progress_callback: Callable[[int, int, int], None] | None = None,
) -> CompressionResult:
    output_file = input_file.with_suffix(input_file.suffix + ".br")
    input_size = input_file.stat().st_size
    _ = workers
    backend = "python-brotli"
    if not enabled:
        input_file.replace(output_file)
        return CompressionResult(
            output_file=output_file,
            backend=backend,
            backend_version=_BROTLI_BACKEND_VERSION,
            input_size=input_size,
            output_size=output_file.stat().st_size,
            level=level,
            enabled=False,
        )

    if verbose:
        LOGGER.info("Compressing %s with python-brotli level %d", input_file.name, level)
    _compress_brotli_in_process(input_file, output_file, level, progress_callback=progress_callback)
    if not output_file.exists():
        raise ValidationError(f"Brotli output missing: {output_file}")
    return CompressionResult(
        output_file=output_file,
        backend=backend,
        backend_version=_BROTLI_BACKEND_VERSION,
        input_size=input_size,
        output_size=output_file.stat().st_size,
        level=level,
        enabled=True,
    )


def compress_zstd(
    input_file: Path,
    level: int,
    enabled: bool,
    verbose: bool,
    workers: int = 0,
    progress_callback: Callable[[int, int, int], None] | None = None,
) -> CompressionResult:
    return compress_brotli(
        input_file,
        level,
        enabled,
        verbose,
        workers,
        progress_callback=progress_callback,
    )


def _run(cmd: list[str], verbose: bool) -> None:
    stdout = None if verbose else subprocess.DEVNULL
    stderr = subprocess.PIPE
    completed = subprocess.run(cmd, stdout=stdout, stderr=stderr, text=True, check=False)
    if completed.returncode != 0:
        stderr_text = completed.stderr.strip() if completed.stderr else ""
        detail = f": {stderr_text}" if stderr_text else ""
        raise ValidationError(f"Command failed ({completed.returncode}): {' '.join(cmd)}{detail}")


def _sorted_images(output_dir: Path) -> list[Path]:
    images = sorted(output_dir.glob("*.img"))
    if images:
        return images
    raw_files = [
        path
        for path in sorted(output_dir.iterdir())
        if path.is_file() and path.suffix == "" and path.name not in {"payload.bin"}
    ]
    renamed: list[Path] = []
    for path in raw_files:
        target = path.with_suffix(".img")
        path.rename(target)
        renamed.append(target)
    return renamed


def _convert_sparse_to_dat_subprocess(script_dir: Path, image_path: Path, output_dir: Path, partition: str) -> None:
    cmd = [
        "python3",
        str(script_dir / "img2sdat.py"),
        str(image_path),
        "-o",
        str(output_dir),
        "-v",
        "4",
        "-p",
        partition,
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "img2sdat failed"
        raise ValidationError(f"Command failed ({completed.returncode}): {' '.join(cmd)}: {message}")


def benchmark_converter(
    script_dir: Path,
    image_path: Path,
    output_dir: Path,
    partition: str,
    stage_callback: Callable[[str], None] | None = None,
    img2simg_bin: Path | None = None,
) -> tuple[ConverterResult, dict[str, float | int | str | bool]]:
    if stage_callback is not None:
        stage_callback("sparse")
    sparse_started = perf_counter()
    convert_img_to_sparse(script_dir, image_path, img2simg_bin=img2simg_bin)
    sparse_elapsed = perf_counter() - sparse_started

    if stage_callback is not None:
        stage_callback("dat")
    dat_started = perf_counter()
    result = convert_sparse_to_dat(
        script_dir,
        image_path,
        output_dir,
        partition,
    )
    dat_elapsed = perf_counter() - dat_started
    metrics: dict[str, float | int | str | bool] = {
        "partition": partition,
        "backend": result.backend,
        "backend_version": result.backend_version,
        "sparse_seconds": sparse_elapsed,
        "dat_seconds": dat_elapsed,
    }
    metrics.update(result.validation)
    return result, metrics


def _load_script_module(script_dir: Path, module_name: str) -> types.ModuleType:
    with _CONVERTER_IMPORT_LOCK:
        scripts_path = str(script_dir)
        if scripts_path not in sys.path:
            sys.path.insert(0, scripts_path)
        return importlib.import_module(module_name)


def _compress_brotli_in_process(
    input_file: Path,
    output_file: Path,
    level: int,
    progress_callback: Callable[[int, int, int], None] | None = None,
) -> None:
    compressor = brotli.Compressor(mode=brotli.MODE_GENERIC, quality=level, lgwin=24)
    total_bytes = input_file.stat().st_size
    processed_bytes = 0
    written_bytes = 0
    with input_file.open("rb") as src, output_file.open("wb") as dst:
        if progress_callback is not None:
            progress_callback(0, total_bytes, 0)
        while chunk := src.read(8 * 1024 * 1024):
            processed_bytes += len(chunk)
            compressed = compressor.process(chunk)
            if compressed:
                dst.write(compressed)
                written_bytes += len(compressed)
            if progress_callback is not None:
                progress_callback(processed_bytes, total_bytes, written_bytes)
        tail = compressor.finish()
        if tail:
            dst.write(tail)
            written_bytes += len(tail)
        if progress_callback is not None:
            progress_callback(total_bytes, total_bytes, written_bytes)
    input_file.unlink()
