from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from importlib.resources import as_file, files
from pathlib import Path


@dataclass(slots=True)
class ResourcePaths:
    avbctl: Path
    magiskboot: Path
    payload_extractor: Path
    update_binary: Path
    default_partitions: Path
    scripts_dir: Path


class ResourceManager:
    def __init__(self) -> None:
        self._stack = ExitStack()

    def open(self) -> ResourcePaths:
        assets = files("payload2recovery.assets")
        avbctl = self._stack.enter_context(as_file(assets / "bin" / "avbctl"))
        magiskboot = self._stack.enter_context(as_file(assets / "bin" / "magiskboot"))
        payload_extractor = self._stack.enter_context(as_file(assets / "bin" / "payload-dumper-go"))
        update_binary = self._stack.enter_context(as_file(assets / "bin" / "update-binary"))
        default_partitions = self._stack.enter_context(
            as_file(assets / "config" / "default_partitions.txt")
        )
        scripts_dir = self._stack.enter_context(as_file(assets / "scripts"))
        return ResourcePaths(
            avbctl=Path(avbctl),
            magiskboot=Path(magiskboot),
            payload_extractor=Path(payload_extractor),
            update_binary=Path(update_binary),
            default_partitions=Path(default_partitions),
            scripts_dir=Path(scripts_dir),
        )

    def close(self) -> None:
        self._stack.close()
