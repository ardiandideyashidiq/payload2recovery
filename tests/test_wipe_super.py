from __future__ import annotations

import hashlib
import struct
import subprocess
from pathlib import Path


def _make_dummy_super_image(target_path: Path, size_mb: int = 16) -> None:
    data = bytearray(size_mb * 1024 * 1024)
    # LpMetadataGeometry (52 bytes)
    # magic=0x616c4467, struct_size=52, checksum=[32], metadata_max_size=65536
    # metadata_slot_count=2, logical_block_size=4096
    geom = bytearray(52)
    struct.pack_into("<II", geom, 0, 0x616C4467, 52)
    struct.pack_into("<III", geom, 40, 65536, 2, 4096)
    chk = hashlib.sha256(geom).digest()
    geom[8:40] = chk

    # Write geometry to primary (4096) and backup (8192)
    data[4096 : 4096 + 52] = geom
    data[8192 : 8192 + 52] = geom
    target_path.write_bytes(data)


def test_wipe_super_host_execution(tmp_path: Path) -> None:
    binary = Path("tools/wipe-super/wipe-super-host")
    if not binary.is_file():
        # Compile host binary if not yet built
        subprocess.run(["make", "-C", "tools/wipe-super", "host"], check=True)

    test_img = tmp_path / "super.img"
    _make_dummy_super_image(test_img)

    # Run dry-run
    res_dry = subprocess.run([str(binary), "-n", str(test_img)], capture_output=True, text=True, check=True)
    assert "[wipe-super] DRY-RUN:" in res_dry.stdout
    assert "Found geometry: max_size=65536, slot_count=2" in res_dry.stdout

    # Run actual wipe
    res = subprocess.run([str(binary), "-s", "_a", str(test_img)], capture_output=True, text=True, check=True)
    assert "[wipe-super] Successfully wiped dynamic partition metadata across all 2 slots!" in res.stdout

    # Verify output metadata
    buf = test_img.read_bytes()
    # Slot 0 primary metadata is at offset 12288
    hdr_bytes = bytearray(buf[12288 : 12288 + 256])
    magic, maj, minv, hdr_size = struct.unpack_from("<IHHI", hdr_bytes, 0)
    assert magic == 0x414C5030  # LP_METADATA_HEADER_MAGIC
    assert maj == 10
    assert minv == 2

    orig_hdr_chk = bytes(hdr_bytes[12:44])
    hdr_bytes[12:44] = b"\x00" * 32
    assert orig_hdr_chk == hashlib.sha256(hdr_bytes[:hdr_size]).digest()

    (tables_size,) = struct.unpack_from("<I", hdr_bytes, 44)
    tables_chk = bytes(hdr_bytes[48:80])
    tables_data = buf[12288 + hdr_size : 12288 + hdr_size + tables_size]
    assert tables_chk == hashlib.sha256(tables_data).digest()


def test_wipe_super_template_flash(tmp_path: Path) -> None:
    binary = Path("tools/wipe-super/wipe-super-host")
    if not binary.is_file():
        subprocess.run(["make", "-C", "tools/wipe-super", "host"], check=True)

    template = Path("src/payload2recovery/assets/tools/super_empty.img")
    assert template.is_file()

    disk_img = tmp_path / "target_super.img"
    # Create empty 16MB image
    disk_img.write_bytes(b"\x00" * (16 * 1024 * 1024))

    # Flash template onto target disk image
    res = subprocess.run([str(binary), "-d", str(disk_img), str(template)], capture_output=True, text=True, check=True)
    assert "[wipe-super] Successfully flashed super_empty template onto" in res.stdout

    # Verify geometry on target disk
    buf = disk_img.read_bytes()
    geom_bytes = buf[4096 : 4096 + 52]
    magic, struct_size = struct.unpack_from("<II", geom_bytes, 0)
    assert magic == 0x616C4467  # LP_METADATA_GEOMETRY_MAGIC
    assert struct_size == 52

    # Verify header and block device size adjustment
    hdr_bytes = buf[12288 : 12288 + 128]
    hmagic, major, minor, hdr_size, _, tbl_size = struct.unpack_from("<IHHI32sI", hdr_bytes, 0)
    assert hmagic == 0x414C5030
    assert major == 10
    assert minor == 0

    # Verify table checksum
    tbls = buf[12288 + hdr_size : 12288 + hdr_size + tbl_size]
    tbl_chk = bytes(hdr_bytes[48:80])
    assert tbl_chk == hashlib.sha256(tbls).digest()

    # Verify block device table size was updated to target disk size (16MB)
    b_off, b_num, b_sz = struct.unpack_from("<III", hdr_bytes[116:128])
    bd_bytes = tbls[b_off : b_off + b_sz]
    first_sec, align, aoff, bsize, bname, bflags = struct.unpack_from("<QIIQ36sI", bd_bytes, 0)
    assert bsize == 16 * 1024 * 1024
