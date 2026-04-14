from __future__ import annotations

from pathlib import Path

from payload2recovery.models import DeviceAssertion, PartitionArtifact, RawImageSpec
from payload2recovery.packaging import write_updater_script as write_shared_updater_script


def write_updater_script(
    destination: Path,
    partitions: list[PartitionArtifact],
    raw_images: list[RawImageSpec],
    device_assertion: DeviceAssertion | None = None,
    banner_lines: list[str] | None = None,
) -> None:
    write_shared_updater_script(
        destination,
        partitions,
        raw_images=raw_images,
        device_assertion=device_assertion,
        banner_lines=banner_lines,
    )
