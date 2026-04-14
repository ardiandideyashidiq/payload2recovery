from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from importlib.resources import as_file, files
from pathlib import Path


@dataclass(slots=True)
class ResourcePaths:
    update_binary: Path
    default_partitions: Path
    scripts_dir: Path


class ResourceManager:
    def __init__(self) -> None:
        self._stack = ExitStack()

    def open(self) -> ResourcePaths:
        payload_assets = files("payload2recovery.assets")
        port_assets = files("port2recovery.assets")
        update_binary = self._stack.enter_context(as_file(payload_assets / "bin" / "update-binary"))
        scripts_dir = self._stack.enter_context(as_file(payload_assets / "scripts"))
        default_partitions = self._stack.enter_context(
            as_file(port_assets / "config" / "port2recovery_default_partitions.txt")
        )
        return ResourcePaths(
            update_binary=Path(update_binary),
            default_partitions=Path(default_partitions),
            scripts_dir=Path(scripts_dir),
        )

    def close(self) -> None:
        self._stack.close()
