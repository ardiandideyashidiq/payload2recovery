import zipfile
from pathlib import Path

from payload2recovery.models import DeviceAssertion, PartitionArtifact, RawImageSpec
from payload2recovery.packaging import (
    _escape_edify_string,
    build_flashable_zip,
    calculate_group_table_size,
    discover_banner_lines,
    validate_partition_layout,
    write_dynamic_partitions_op_list,
    write_updater_script,
)


def test_calculate_group_table_size_rounds_up() -> None:
    size = calculate_group_table_size([100, 200])
    assert size >= 300
    assert size % (1024 * 1024) == 0


def test_validate_partition_layout_rejects_super() -> None:
    try:
        validate_partition_layout(["system", "super"])
    except Exception as exc:
        assert "super" in str(exc)
    else:
        raise AssertionError("Expected an unsupported layout error")


def test_write_generated_metadata(tmp_path: Path) -> None:
    artifact = PartitionArtifact(
        name="system",
        image_path=tmp_path / "system.img",
        image_size=1234,
        transfer_list=tmp_path / "system.transfer.list",
        new_dat_zst=tmp_path / "system.new.dat.zst",
        patch_dat=tmp_path / "system.patch.dat",
    )
    op_list = tmp_path / "dynamic_partitions_op_list"
    updater_script = tmp_path / "updater-script"
    write_dynamic_partitions_op_list(op_list, "main", 5678, [artifact])
    write_updater_script(updater_script, [artifact])
    assert "add_group main 5678" in op_list.read_text()
    assert 'block_image_update(map_partition("system")' in updater_script.read_text()


def test_write_updater_script_with_device_assertion(tmp_path: Path) -> None:
    artifact = PartitionArtifact(
        name="system",
        image_path=tmp_path / "system.img",
        image_size=1234,
        transfer_list=tmp_path / "system.transfer.list",
        new_dat_zst=tmp_path / "system.new.dat.zst",
        patch_dat=tmp_path / "system.patch.dat",
    )
    updater_script = tmp_path / "updater-script"
    write_updater_script(
        updater_script,
        [artifact],
        device_assertion=DeviceAssertion(
            device_names=["P661N"],
            source="META-INF/com/android/metadata",
            enabled=True,
        ),
    )
    content = updater_script.read_text()
    assert 'getprop("ro.product.device") == "P661N"' in content
    assert "This package is for device(s): P661N" in content


def test_write_updater_script_with_banner_lines(tmp_path: Path) -> None:
    artifact = PartitionArtifact(
        name="system",
        image_path=tmp_path / "system.img",
        image_size=1234,
        transfer_list=tmp_path / "system.transfer.list",
        new_dat_zst=tmp_path / "system.new.dat.zst",
        patch_dat=tmp_path / "system.patch.dat",
    )
    updater_script = tmp_path / "updater-script"
    write_updater_script(
        updater_script,
        [artifact],
        banner_lines=["Hello", "", 'Quote " and slash \\'],
    )
    content = updater_script.read_text()
    assert 'ui_print("Checking /cache...");' not in content
    assert 'run_program("/sbin/sh", "-c", "[ -d /data/cache ] || mkdir -p /data/cache");' in content
    assert content.count('ui_print(" ");') >= 5
    assert 'ui_print("Hello");' in content
    assert 'ui_print(" ");' in content
    assert 'ui_print("Quote \\" and slash \\\\");' in content
    assert 'package_extract_file("bin/avbctl", "/system/bin/avbctl");' in content
    assert 'run_program("/sbin/sh", "-c", "chmod 0755 /system/bin/avbctl");' in content
    assert 'run_program("/sbin/sh", "-c", "chown 0:0 /system/bin/avbctl");' in content
    assert 'run_program("/system/bin/avbctl", "--force", "disable-verity");' in content
    assert content.index('package_extract_file("bin/avbctl", "/system/bin/avbctl");') < content.index(
        'assert(update_dynamic_partitions(package_extract_file("dynamic_partitions_op_list")));'
    )


def test_escape_edify_string_handles_special_characters() -> None:
    result = _escape_edify_string("normal line")
    assert result == "normal line"

    result = _escape_edify_string('quote " and backslash \\')
    assert result == 'quote \\" and backslash \\\\'

    result = _escape_edify_string("line with );")
    assert result == "line with );"

    result = _escape_edify_string("line with\nnewline")
    assert result == "line with newline"

    result = _escape_edify_string("line with\r\nCRLF")
    assert result == "line with  CRLF"

    result = _escape_edify_string("null\0byte")
    assert result == "nullbyte"


def test_write_updater_script_includes_superwipe_in_correct_order(tmp_path: Path) -> None:
    artifact = PartitionArtifact(
        name="system",
        image_path=tmp_path / "system.img",
        image_size=1234,
        transfer_list=tmp_path / "system.transfer.list",
        new_dat_zst=tmp_path / "system.new.dat.zst",
        patch_dat=tmp_path / "system.patch.dat",
    )
    updater_script = tmp_path / "updater-script"
    write_updater_script(updater_script, [artifact])
    content = updater_script.read_text()
    assert 'ui_print("Wiping super partition metadata...");' in content
    assert 'package_extract_dir("bin", "/tmp");' in content
    assert 'run_program("/sbin/sh", "-c", "chmod 0755 /tmp/superwipe");' in content
    assert 'run_program("/sbin/sh", "-c", "chown 0:0 /tmp/superwipe");' in content
    assert 'run_program("/tmp/superwipe", "/tmp/super_empty.img");' in content
    assert content.index('run_program("/system/bin/avbctl", "--force", "disable-verification");') < content.index(
        'package_extract_dir("bin", "/tmp");'
    )
    assert content.index('run_program("/tmp/superwipe", "/tmp/super_empty.img");') < content.index(
        'assert(update_dynamic_partitions(package_extract_file("dynamic_partitions_op_list")));'
    )


def test_write_updater_script_includes_raw_images_and_slot_logic(tmp_path: Path) -> None:
    artifact = PartitionArtifact(
        name="system",
        image_path=tmp_path / "system.img",
        image_size=1234,
        transfer_list=tmp_path / "system.transfer.list",
        new_dat_zst=tmp_path / "system.new.dat.zst",
        patch_dat=tmp_path / "system.patch.dat",
    )
    updater_script = tmp_path / "updater-script"
    write_updater_script(
        updater_script,
        [artifact],
        raw_images=[
            RawImageSpec(file="logo.bin", target="/dev/block/by-name/logo", slot_policy="none"),
            RawImageSpec(file="lk.img", target="/dev/block/by-name/lk", slot_policy="active"),
        ],
    )
    content = updater_script.read_text()
    assert 'package_extract_file("bin/avbctl", "/system/bin/avbctl");' in content
    assert 'run_program("/sbin/sh", "-c", "chmod 0755 /system/bin/avbctl");' in content
    assert 'run_program("/sbin/sh", "-c", "chown 0:0 /system/bin/avbctl");' in content
    assert content.index('package_extract_file("bin/avbctl", "/system/bin/avbctl");') < content.index(
        'ui_print("Flashing raw images...");'
    )
    assert 'package_extract_file("logo.bin", "/dev/block/by-name/logo");' in content
    assert 'getprop("ro.boot.slot_suffix") == "_a"' in content
    assert 'package_extract_file("lk.img", "/dev/block/by-name/lk_a")' in content
    assert 'ui_print("Updating dynamic partitions...");' in content


def test_discover_banner_lines_prefers_banner_over_banner_txt(tmp_path: Path) -> None:
    (tmp_path / "banner").write_text("top\n\nbottom\n")
    (tmp_path / "banner.txt").write_text("other\n")
    assert discover_banner_lines(tmp_path) == ["top", "", "bottom"]


def _make_zstd_binary(tmp_path: Path) -> Path:
    zstd = tmp_path / "zstd"
    zstd.write_bytes(b"zstd-binary")
    return zstd


def test_build_flashable_zip_creates_output_parent(tmp_path: Path) -> None:
    payload_dir = tmp_path / "payload"
    payload_dir.mkdir()
    (payload_dir / "system.transfer.list").write_text("4\n1\n0\n")
    (payload_dir / "system.new.dat.zst").write_bytes(b"payload")
    (payload_dir / "system.patch.dat").write_bytes(b"")
    meta_dir = payload_dir / "META-INF" / "com" / "google" / "android"
    meta_dir.mkdir(parents=True)
    (meta_dir / "updater-script").write_text('ui_print("ok");\n')

    update_binary = tmp_path / "update-binary"
    update_binary.write_bytes(b"binary")
    avbctl_binary = tmp_path / "avbctl"
    avbctl_binary.write_bytes(b"binary")
    superwipe_binary = tmp_path / "superwipe"
    superwipe_binary.write_bytes(b"sw")
    super_empty_img = tmp_path / "super_empty.img"
    super_empty_img.write_bytes(b"img")

    output_zip = tmp_path / "missing" / "nested" / "result.zip"
    build_flashable_zip(
        payload_dir,
        update_binary,
        avbctl_binary,
        output_zip,
        zip_level=0,
        superwipe_binary=superwipe_binary,
        super_empty_img=super_empty_img,
        zstd_binary=_make_zstd_binary(tmp_path),
    )

    assert output_zip.exists()


def test_build_flashable_zip_reports_monotonic_progress(tmp_path: Path) -> None:
    payload_dir = tmp_path / "payload"
    payload_dir.mkdir()
    (payload_dir / "system.transfer.list").write_text("4\n1\n0\n")
    (payload_dir / "system.new.dat.zst").write_bytes(b"a" * (9 * 1024 * 1024))
    (payload_dir / "system.patch.dat").write_bytes(b"")
    meta_dir = payload_dir / "META-INF" / "com" / "google" / "android"
    meta_dir.mkdir(parents=True)
    (meta_dir / "updater-script").write_text('ui_print("ok");\n')

    update_binary = tmp_path / "update-binary"
    update_binary.write_bytes(b"binary")
    avbctl_binary = tmp_path / "avbctl"
    avbctl_binary.write_bytes(b"binary")
    superwipe_binary = tmp_path / "superwipe"
    superwipe_binary.write_bytes(b"sw")
    super_empty_img = tmp_path / "super_empty.img"
    super_empty_img.write_bytes(b"img")
    output_zip = tmp_path / "result.zip"
    events: list[tuple[str, int, int, int, int, bool]] = []

    build_flashable_zip(
        payload_dir,
        update_binary,
        avbctl_binary,
        output_zip,
        zip_level=6,
        superwipe_binary=superwipe_binary,
        super_empty_img=super_empty_img,
        zstd_binary=_make_zstd_binary(tmp_path),
        progress_callback=lambda cur, done, total, bdone, btotal, store: events.append(
            (cur, done, total, bdone, btotal, store)
        ),
    )

    assert output_zip.exists()
    assert events
    assert events[0][1] == 0
    assert events[-1][1] == events[-1][2]
    assert events[-1][3] == events[-1][4]
    assert [event[3] for event in events] == sorted(event[3] for event in events)


def test_build_flashable_zip_stores_zstd_entries(tmp_path: Path) -> None:
    payload_dir = tmp_path / "payload"
    payload_dir.mkdir()
    (payload_dir / "system.transfer.list").write_text("4\n1\n0\n")
    (payload_dir / "system.new.dat.zst").write_bytes(b"payload")
    (payload_dir / "system.patch.dat").write_bytes(b"")
    meta_dir = payload_dir / "META-INF" / "com" / "google" / "android"
    meta_dir.mkdir(parents=True)
    (meta_dir / "updater-script").write_text('ui_print("ok");\n')

    update_binary = tmp_path / "update-binary"
    update_binary.write_bytes(b"binary")
    avbctl_binary = tmp_path / "avbctl"
    avbctl_binary.write_bytes(b"binary")
    superwipe_binary = tmp_path / "superwipe"
    superwipe_binary.write_bytes(b"sw")
    super_empty_img = tmp_path / "super_empty.img"
    super_empty_img.write_bytes(b"img")
    output_zip = tmp_path / "result.zip"
    build_flashable_zip(
        payload_dir,
        update_binary,
        avbctl_binary,
        output_zip,
        zip_level=6,
        superwipe_binary=superwipe_binary,
        super_empty_img=super_empty_img,
        zstd_binary=_make_zstd_binary(tmp_path),
    )

    with zipfile.ZipFile(output_zip) as archive:
        assert archive.getinfo("bin/avbctl").compress_type == zipfile.ZIP_DEFLATED
        assert archive.getinfo("system.new.dat.zst").compress_type == zipfile.ZIP_STORED
        assert archive.getinfo("system.transfer.list").compress_type == zipfile.ZIP_DEFLATED


def test_build_flashable_zip_includes_superwipe_and_zstd_bin(tmp_path: Path) -> None:
    payload_dir = tmp_path / "payload"
    payload_dir.mkdir()
    (payload_dir / "system.transfer.list").write_text("4\n1\n0\n")
    (payload_dir / "system.new.dat.zst").write_bytes(b"payload")
    (payload_dir / "system.patch.dat").write_bytes(b"")
    meta_dir = payload_dir / "META-INF" / "com" / "google" / "android"
    meta_dir.mkdir(parents=True)
    (meta_dir / "updater-script").write_text('ui_print("ok");\n')

    update_binary = tmp_path / "update-binary"
    update_binary.write_bytes(b"binary")
    avbctl_binary = tmp_path / "avbctl"
    avbctl_binary.write_bytes(b"binary")
    superwipe_binary = tmp_path / "superwipe"
    superwipe_binary.write_bytes(b"superwipe-bin")
    super_empty_img = tmp_path / "super_empty.img"
    super_empty_img.write_bytes(b"img-data")
    zstd_binary = tmp_path / "zstd"
    zstd_binary.write_bytes(b"zstd-bin")

    output_zip = tmp_path / "result.zip"
    build_flashable_zip(
        payload_dir,
        update_binary,
        avbctl_binary,
        output_zip,
        zip_level=0,
        superwipe_binary=superwipe_binary,
        super_empty_img=super_empty_img,
        zstd_binary=zstd_binary,
    )

    with zipfile.ZipFile(output_zip) as archive:
        assert archive.getinfo("bin/superwipe")
        assert archive.getinfo("bin/super_empty.img")
        assert archive.getinfo("bin/zstd")
        assert archive.read("bin/superwipe") == b"superwipe-bin"
        assert archive.read("bin/super_empty.img") == b"img-data"
        assert archive.read("bin/zstd") == b"zstd-bin"


def test_write_updater_script_includes_zstd_decompress(tmp_path: Path) -> None:
    artifact = PartitionArtifact(
        name="system",
        image_path=tmp_path / "system.img",
        image_size=1234,
        transfer_list=tmp_path / "system.transfer.list",
        new_dat_zst=tmp_path / "system.new.dat.zst",
        patch_dat=tmp_path / "system.patch.dat",
    )
    updater_script = tmp_path / "updater-script"
    write_updater_script(updater_script, [artifact])
    content = updater_script.read_text()
    assert "chmod 0755 /tmp/zstd" in content
    assert 'run_program("/tmp/zstd", "-d", "system.new.dat.zst")' in content
    assert '"system.new.dat"' in content
