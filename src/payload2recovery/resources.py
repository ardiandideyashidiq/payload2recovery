from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from importlib.resources import as_file, files
from pathlib import Path


@dataclass(slots=True)
class ResourcePaths:
    payload_extractor: Path
    update_binary: Path
    default_partitions: Path
    scripts_dir: Path


class ResourceManager:
    def __init__(self) -> None:
        self._stack = ExitStack()

    def open(self) -> ResourcePaths:
        assets = files("payload2recovery.assets")
        payload_extractor = self._stack.enter_context(as_file(assets / "bin" / "payload-dumper-go"))
        update_binary = self._stack.enter_context(as_file(assets / "bin" / "update-binary"))
        default_partitions = self._stack.enter_context(
            as_file(assets / "config" / "default_partitions.txt")
        )
        scripts_dir = self._stack.enter_context(as_file(assets / "scripts"))
        return ResourcePaths(
            payload_extractor=Path(payload_extractor),
            update_binary=Path(update_binary),
            default_partitions=Path(default_partitions),
            scripts_dir=Path(scripts_dir),
        )

    def close(self) -> None:
        self._stack.close()
