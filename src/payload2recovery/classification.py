from __future__ import annotations

from pathlib import Path

from payload2recovery.magiskboot import MagiskbootProbe
from payload2recovery.models import UNSUPPORTED_PARTITIONS

ALWAYS_DEFAULT_RAW_PARTITIONS: set[str] = {"logo", "lk"}
CONDITIONAL_DEFAULT_RAW_PARTITIONS: set[str] = {"boot"}
EXPLICIT_RAW_PARTITIONS: set[str] = {"boot", "init_boot", "vendor_boot", "dtbo", "recovery"}
EXPLICIT_RAW_PREFIXES: tuple[str, ...] = ("vbmeta",)
KNOWN_LOGICAL_PARTITIONS: set[str] = {
    "system",
    "system_ext",
    "product",
    "vendor",
    "odm",
    "odm_dlkm",
    "vendor_dlkm",
    "system_dlkm",
}
DEFAULT_RAW_PROBES: set[str] = {"boot", "vendor_boot"}
RECOVERY_SKIP_PARTITIONS: set[str] = {"recovery", "vendor_boot"}


def classify_extracted_partitions(
    extracted: list[Path],
    magiskboot_probes: dict[str, MagiskbootProbe] | None = None,
) -> tuple[set[str], set[str], set[str], set[str], set[str], set[str]]:
    extracted_names = {path.stem for path in extracted}
    logical_supported: set[str] = set()
    default_raw: set[str] = set()
    explicit_raw: set[str] = set()
    unsupported: set[str] = set()
    auto_raw: set[str] = set()
    skipped: set[str] = set()

    probes = magiskboot_probes or {}

    for path in extracted:
        name = path.stem
        if name in UNSUPPORTED_PARTITIONS:
            unsupported.add(name)
        elif name in RECOVERY_SKIP_PARTITIONS:
            skipped.add(name)
        elif is_default_raw_partition(name, extracted_names):
            if name == "boot" and is_recovery_in_boot(name, probes):
                skipped.add(name)
            else:
                default_raw.add(name)
        elif is_explicit_raw_partition(name):
            explicit_raw.add(name)
        elif name in KNOWN_LOGICAL_PARTITIONS:
            logical_supported.add(name)
        else:
            auto_raw.add(name)
    return logical_supported, default_raw, explicit_raw, unsupported, auto_raw, skipped


def is_recovery_in_boot(name: str, probes: dict[str, MagiskbootProbe]) -> bool:
    probe = probes.get(name)
    return bool(probe and probe.is_valid and probe.recovery_dtbo_size > 0)


def is_default_raw_partition(name: str, extracted_names: set[str]) -> bool:
    return name in ALWAYS_DEFAULT_RAW_PARTITIONS or (
        name in CONDITIONAL_DEFAULT_RAW_PARTITIONS and "vendor_boot" in extracted_names
    )


def is_explicit_raw_partition(name: str) -> bool:
    return name in EXPLICIT_RAW_PARTITIONS or name.startswith(EXPLICIT_RAW_PREFIXES)


def partition_status(
    name: str,
    supported: set[str],
    default_raw: set[str],
    excluded_raw: set[str],
    _unsupported: set[str],
    auto_raw: set[str] | None = None,
    skipped: set[str] | None = None,
) -> str:
    if name in skipped:
        return "skipped-recovery"
    if name in supported or name in default_raw or (auto_raw and name in auto_raw):
        return "supported"
    if name in excluded_raw:
        return "excluded-by-default"
    return "unsupported"
