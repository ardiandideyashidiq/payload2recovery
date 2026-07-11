from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class MagiskbootProbe:
    """Result of probing a partition image with magiskboot."""
    is_boot: bool
    is_vendor_boot: bool
    is_valid: bool
    header_version: int
    kernel_size: int
    recovery_dtbo_size: int
    has_vendor_ramdisk_recovery: bool


_HEADER_RE = re.compile(r"^(\w+)\s+\[(.+)\]$")
_VND_RAMDISK_RE = re.compile(r"^VND_RAMDISK.*type=\[(\w+)\]")


def probe_image(path: Path, magiskboot_bin: Path) -> MagiskbootProbe:
    header_version = 0
    kernel_size = 0
    recovery_dtbo_size = 0
    has_vendor_ramdisk_recovery = False

    with tempfile.TemporaryDirectory(prefix="p2r-magisk-") as tmpdir:
        result = subprocess.run(
            [str(magiskboot_bin), "unpack", "-h", str(path)],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            check=False,
        )
        ret = result.returncode

        header_file = Path(tmpdir) / "header"
        if header_file.is_file():
            for line in header_file.read_text().splitlines():
                m = _HEADER_RE.match(line)
                if m:
                    key, val = m.group(1), m.group(2)
                    if key == "HEADER_VER":
                        header_version = int(val)
                    elif key == "KERNEL_SZ":
                        kernel_size = int(val)
                    elif key == "RECOV_DTBO_SZ":
                        recovery_dtbo_size = int(val)

            for line in result.stdout.splitlines():
                m = _VND_RAMDISK_RE.match(line)
                if m and m.group(1) == "recovery":
                    has_vendor_ramdisk_recovery = True

    return MagiskbootProbe(
        is_boot=ret == 0,
        is_vendor_boot=ret == 3,
        is_valid=ret != 1,
        header_version=header_version,
        kernel_size=kernel_size,
        recovery_dtbo_size=recovery_dtbo_size,
        has_vendor_ramdisk_recovery=has_vendor_ramdisk_recovery,
    )
