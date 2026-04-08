from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
import zipfile

from payload2recovery.errors import UnsupportedLayoutError
from payload2recovery.models import DeviceAssertion, PartitionArtifact


def calculate_group_table_size(sizes: list[int]) -> int:
    total = sum(sizes)
    if total <= 0:
        raise UnsupportedLayoutError("No partition sizes available for group table calculation")
    padded = total + (total // 5)
    mib = 1024 * 1024
    remainder = padded % mib
    if remainder:
        padded += mib - remainder
    return padded


def validate_partition_layout(partitions: list[str]) -> None:
    unsupported = {"super", "userdata", "metadata"}
    overlap = unsupported.intersection(partitions)
    if overlap:
        joined = ", ".join(sorted(overlap))
        raise UnsupportedLayoutError(
            f"Unsupported recovery package layout for partitions: {joined}"
        )


def write_dynamic_partitions_op_list(
    destination: Path, group_table: str, group_table_size: int, partitions: list[PartitionArtifact]
) -> None:
    lines = [
        "# Remove all existing dynamic partitions",
        "remove_all_groups",
        f"# Add group {group_table} with maximum size {group_table_size}",
        f"add_group {group_table} {group_table_size}",
    ]
    for partition in partitions:
        lines.extend(
            [
                f"# Add partition {partition.name} to group {group_table}",
                f"add {partition.name} {group_table}",
            ]
        )
    for partition in partitions:
        lines.extend(
            [
                f"# Grow partition {partition.name} from 0 to {partition.image_size}",
                f"resize {partition.name} {partition.image_size}",
            ]
        )
    destination.write_text("\n".join(lines) + "\n")


def write_updater_script(
    destination: Path,
    partitions: list[PartitionArtifact],
    device_assertion: DeviceAssertion | None = None,
) -> None:
    lines = [
        'ui_print("Checking /cache...");',
        'run_program("/sbin/sh", "-c", "[ -d /data/cache ] || mkdir -p /data/cache");',
        "",
    ]
    if device_assertion and device_assertion.enabled and device_assertion.device_names:
        checks = " || ".join(
            [
                f'getprop("ro.product.device") == "{name}"'
                for name in device_assertion.device_names
            ]
            + [
                f'getprop("ro.build.product") == "{name}"'
                for name in device_assertion.device_names
            ]
            + [
                f'getprop("ro.product.vendor.device") == "{name}"'
                for name in device_assertion.device_names
            ]
        )
        expected = ", ".join(device_assertion.device_names)
        lines.extend(
            [
                'ui_print("Checking target device...");',
                (
                    f'assert({checks} || '
                    f'abort("E1000: This package is for device(s): {expected}; this device is " '
                    '|| getprop("ro.product.device") || "."));'
                ),
                "",
            ]
        )
    lines.append('assert(update_dynamic_partitions(package_extract_file("dynamic_partitions_op_list")));')
    for partition in partitions:
        lines.extend(
            [
                "",
                f'ui_print("Flashing {partition.name}...");',
                (
                    f'block_image_update(map_partition("{partition.name}"), '
                    f'package_extract_file("{partition.transfer_list.name}"), '
                    f'"{partition.new_dat_br.name}", "{partition.name}.patch.dat") ||'
                ),
                f'  abort("E1001: Failed to flash {partition.name}");',
            ]
        )
    lines.extend(["", 'ui_print("Installation complete!");'])
    destination.write_text("\n".join(lines) + "\n")


def build_flashable_zip(
    payload_dir: Path,
    update_binary: Path,
    output_path: Path,
    zip_level: int,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    meta_dir = payload_dir / "META-INF" / "com" / "google" / "android"
    meta_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(update_binary, meta_dir / "update-binary")

    compression = zipfile.ZIP_STORED if zip_level == 0 else zipfile.ZIP_DEFLATED
    compresslevel = None if zip_level == 0 else zip_level
    with zipfile.ZipFile(output_path, "w", compression=compression, compresslevel=compresslevel) as archive:
        for file_path in sorted(payload_dir.rglob("*")):
            if file_path.is_file():
                arcname = file_path.relative_to(payload_dir)
                if file_path.suffix == ".br":
                    archive.write(file_path, arcname, compress_type=zipfile.ZIP_STORED)
                else:
                    archive.write(file_path, arcname)
    return output_path


def human_size(path: Path) -> str:
    result = subprocess.run(["du", "-h", str(path)], capture_output=True, text=True, check=False)
    if result.returncode == 0 and result.stdout:
        return result.stdout.split()[0]
    return f"{path.stat().st_size} bytes"
