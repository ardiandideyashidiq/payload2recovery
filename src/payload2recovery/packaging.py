from __future__ import annotations

import shutil
import zipfile
from collections.abc import Callable
from pathlib import Path

from payload2recovery.errors import UnsupportedLayoutError
from payload2recovery.models import UNSUPPORTED_PARTITIONS, DeviceAssertion, PartitionArtifact, RawImageSpec

_RECOVERY_ART = [
    "",
    "",
    "             >^..^<",
    "",
    "",
]


def discover_banner_lines(input_root: Path) -> list[str] | None:
    for name in ("banner", "banner.txt"):
        candidate = input_root / name
        if candidate.is_file():
            return candidate.read_text().splitlines()
    return None


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
    unsupported = set(UNSUPPORTED_PARTITIONS)
    overlap = unsupported.intersection(partitions)
    if overlap:
        joined = ", ".join(sorted(overlap))
        raise UnsupportedLayoutError(f"Unsupported recovery package layout for partitions: {joined}")


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
    raw_images: list[RawImageSpec] | None = None,
    device_assertion: DeviceAssertion | None = None,
    banner_lines: list[str] | None = None,
) -> None:
    raw_images = raw_images or []
    lines = _banner_ui_print_lines(_RECOVERY_ART)
    lines.append(
        'run_program("/sbin/sh", "-c", "[ -d /data/cache ] || mkdir -p /data/cache");',
    )
    lines.append("")
    if banner_lines:
        lines.extend(_banner_ui_print_lines(banner_lines))
    if device_assertion and device_assertion.enabled and device_assertion.device_names:
        lines.extend(_device_assertion_lines(device_assertion))
    lines.extend(_avbctl_disable_lines())
    lines.extend(_superwipe_lines())
    lines.extend(_raw_image_updater_lines(raw_images))
    lines.append('assert(update_dynamic_partitions(package_extract_file("dynamic_partitions_op_list")));')
    for partition in partitions:
        lines.extend(
            [
                "",
                f'ui_print("Flashing {partition.name}" || getprop("ro.boot.slot_suffix") || "...");',
                (
                    f'block_image_update(map_partition("{partition.name}"), '
                    f'package_extract_file("{partition.transfer_list.name}"), '
                    f'"{partition.new_dat_br.name}", "{partition.name}.patch.dat") ||'
                ),
                f'  abort("E1001: Failed to flash {partition.name}");',
            ]
        )
    lines.extend(
        [
            "",
            'ui_print("Flashing into slot " || getprop("ro.boot.slot_suffix") || " is finished!");',
            'ui_print("");',
            'ui_print("Don\'t forget to format data before booting!");',
            'ui_print("");',
        ]
    )
    destination.write_text("\n".join(lines) + "\n")


def _device_assertion_lines(device_assertion: DeviceAssertion) -> list[str]:
    checks = " || ".join(
        [f'getprop("ro.product.device") == "{name}"' for name in device_assertion.device_names]
        + [f'getprop("ro.build.product") == "{name}"' for name in device_assertion.device_names]
        + [f'getprop("ro.product.vendor.device") == "{name}"' for name in device_assertion.device_names]
    )
    expected = ", ".join(device_assertion.device_names)
    return [
        'ui_print("Checking target device...");',
        (
            f"assert({checks} || "
            f'abort("E1000: This package is for device(s): {expected}; this device is " '
            '|| getprop("ro.product.device") || "."));'
        ),
        "",
    ]


def _raw_image_updater_lines(raw_images: list[RawImageSpec]) -> list[str]:
    lines: list[str] = []
    active_slot_raw_images = [item for item in raw_images if item.slot_policy == "active"]
    if active_slot_raw_images:
        lines.extend(
            [
                'ui_print("Checking active slot...");',
                (
                    'assert(getprop("ro.boot.slot_suffix") == "_a" || '
                    'getprop("ro.boot.slot_suffix") == "_b" || '
                    'abort("E1002: Unsupported slot suffix: " || getprop("ro.boot.slot_suffix") || "."));'
                ),
                'ui_print("Active slot:" || getprop("ro.boot.slot_suffix") || "");',
                'ui_print("");',
                'ui_print("Flashing on" || getprop("ro.boot.slot_suffix") || " slot...");',
                "",
            ]
        )

    if raw_images:
        lines.append('ui_print("Flashing raw images...");')
        for raw_image in raw_images:
            name = raw_image.target.rsplit("/", 1)[-1]
            if raw_image.slot_policy == "active":
                lines.append(f'ui_print("Flashing {name}...");')
                lines.append(
                    f'ifelse(getprop("ro.boot.slot_suffix") == "_a", '
                    f'package_extract_file("{raw_image.file}", "{raw_image.target}_a"), '
                    f'package_extract_file("{raw_image.file}", "{raw_image.target}_b"));'
                )
            elif raw_image.slot_policy == "both":
                lines.append(f'ui_print("Flashing {name}_a...");')
                lines.append(f'package_extract_file("{raw_image.file}", "{raw_image.target}_a");')
                lines.append(f'ui_print("Flashing {name}_b...");')
                lines.append(f'package_extract_file("{raw_image.file}", "{raw_image.target}_b");')
            else:
                lines.append(f'ui_print("Flashing {name}...");')
                lines.append(f'package_extract_file("{raw_image.file}", "{raw_image.target}");')
        lines.extend(["", 'ui_print("Updating dynamic partitions...");'])
    return lines


def _superwipe_lines() -> list[str]:
    return [
        'ui_print("Wiping super partition metadata...");',
        'package_extract_dir("bin", "/tmp");',
        'run_program("/sbin/sh", "-c", "chmod 0755 /tmp/superwipe");',
        'run_program("/sbin/sh", "-c", "chown 0:0 /tmp/superwipe");',
        'run_program("/tmp/superwipe", "/tmp/super_empty.img");',
        'ui_print("");',
        "",
    ]


def _avbctl_disable_lines() -> list[str]:
    return [
        'ui_print("Disabling AVB vbmeta...");',
        'package_extract_file("bin/avbctl", "/system/bin/avbctl");',
        'run_program("/sbin/sh", "-c", "chmod 0755 /system/bin/avbctl");',
        'run_program("/sbin/sh", "-c", "chown 0:0 /system/bin/avbctl");',
        'run_program("/system/bin/avbctl", "--force", "disable-verity");',
        'run_program("/system/bin/avbctl", "--force", "disable-verification");',
        "",
    ]


def _banner_ui_print_lines(banner_lines: list[str]) -> list[str]:
    lines: list[str] = ['ui_print(" ");', 'ui_print(" ");']
    for banner_line in banner_lines:
        display_line = banner_line if banner_line else " "
        lines.append(f'ui_print("{_escape_edify_string(display_line)}");')
    lines.extend(['ui_print(" ");', 'ui_print(" ");', ""])
    return lines


def _escape_edify_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", " ").replace("\r", " ")
    escaped = escaped.replace("\0", "")
    return escaped


def build_flashable_zip(
    payload_dir: Path,
    update_binary: Path,
    avbctl_binary: Path,
    output_path: Path,
    zip_level: int,
    superwipe_binary: Path,
    super_empty_img: Path,
    progress_callback: Callable[[str, int, int, int, int, bool], None] | None = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    meta_dir = payload_dir / "META-INF" / "com" / "google" / "android"
    meta_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(update_binary, meta_dir / "update-binary")
    avbctl_destination = payload_dir / "bin" / "avbctl"
    avbctl_destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(avbctl_binary, avbctl_destination)
    bin_dir = payload_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(superwipe_binary, bin_dir / "superwipe")
    shutil.copy2(super_empty_img, bin_dir / "super_empty.img")

    file_entries = [path for path in sorted(payload_dir.rglob("*")) if path.is_file()]
    total_files = len(file_entries)
    total_bytes = sum(path.stat().st_size for path in file_entries)
    compression = zipfile.ZIP_STORED if zip_level == 0 else zipfile.ZIP_DEFLATED
    compresslevel = None if zip_level == 0 else zip_level
    with zipfile.ZipFile(output_path, "w", compression=compression, compresslevel=compresslevel) as archive:
        bytes_done = 0
        for index, file_path in enumerate(file_entries, start=1):
            arcname = file_path.relative_to(payload_dir)
            store_entry = file_path.suffix == ".br"
            if progress_callback is not None:
                progress_callback(
                    arcname.as_posix(),
                    index - 1,
                    total_files,
                    bytes_done,
                    total_bytes,
                    store_entry,
                )
            bytes_done = _write_zip_entry(
                archive,
                file_path,
                arcname,
                zip_level,
                bytes_done,
                total_bytes,
                total_files,
                index,
                store_entry,
                progress_callback,
            )
    return output_path


def human_size(path: Path) -> str:
    size: float = path.stat().st_size
    for unit in ("B", "K", "M", "G", "T"):
        if size < 1024:
            return f"{int(size)}{unit}"
        size /= 1024
    return f"{int(size)}P"


def _write_zip_entry(
    archive: zipfile.ZipFile,
    file_path: Path,
    arcname: Path,
    zip_level: int,
    bytes_done: int,
    total_bytes: int,
    total_files: int,
    file_index: int,
    store_entry: bool,
    progress_callback: Callable[[str, int, int, int, int, bool], None] | None,
) -> int:
    zip_info = zipfile.ZipInfo.from_file(file_path, arcname.as_posix())
    zip_info.compress_type = zipfile.ZIP_STORED if store_entry or zip_level == 0 else zipfile.ZIP_DEFLATED
    if zip_info.compress_type == zipfile.ZIP_DEFLATED:
        zip_info._compresslevel = zip_level  # type: ignore[attr-defined]

    with file_path.open("rb") as src, archive.open(zip_info, "w", force_zip64=True) as dst:
        while chunk := src.read(8 * 1024 * 1024):
            dst.write(chunk)
            bytes_done += len(chunk)
            if progress_callback is not None:
                progress_callback(
                    arcname.as_posix(),
                    file_index,
                    total_files,
                    bytes_done,
                    total_bytes,
                    store_entry,
                )
    return bytes_done
