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
    superwipe: Path
    super_empty_img: Path
    default_partitions: Path
    scripts_dir: Path
    img2simg: Path | None = None
    simg2img: Path | None = None
    lpunpack: Path | None = None
    lpmake: Path | None = None


class ResourceManager:
    def __init__(self) -> None:
        self._stack = ExitStack()

    def open(self) -> ResourcePaths:
        assets = files("payload2recovery.assets")
        avbctl = self._stack.enter_context(as_file(assets / "bin" / "avbctl"))
        magiskboot = self._stack.enter_context(as_file(assets / "bin" / "magiskboot"))
        payload_extractor = self._stack.enter_context(as_file(assets / "bin" / "payload-dumper-go"))
        update_binary = self._stack.enter_context(as_file(assets / "bin" / "update-binary"))
        superwipe = self._stack.enter_context(as_file(assets / "tools" / "superwipe"))
        super_empty_img = self._stack.enter_context(as_file(assets / "tools" / "super_empty.img"))
        default_partitions = self._stack.enter_context(as_file(assets / "config" / "default_partitions.txt"))
        scripts_dir = self._stack.enter_context(as_file(assets / "scripts"))
        img2simg = self._stack.enter_context(as_file(assets / "bin" / "img2simg"))
        simg2img = self._stack.enter_context(as_file(assets / "bin" / "simg2img"))
        lpunpack = self._stack.enter_context(as_file(assets / "bin" / "lpunpack"))
        lpmake = self._stack.enter_context(as_file(assets / "bin" / "lpmake"))
        return ResourcePaths(
            avbctl=Path(avbctl),
            magiskboot=Path(magiskboot),
            payload_extractor=Path(payload_extractor),
            update_binary=Path(update_binary),
            superwipe=Path(superwipe),
            super_empty_img=Path(super_empty_img),
            default_partitions=Path(default_partitions),
            scripts_dir=Path(scripts_dir),
            img2simg=Path(img2simg),
            simg2img=Path(simg2img),
            lpunpack=Path(lpunpack),
            lpmake=Path(lpmake),
        )

    def close(self) -> None:
        self._stack.close()
