from pathlib import Path
import zipfile

from payload2recovery.models import DeviceAssertion, PartitionArtifact, RawImageSpec
from payload2recovery.packaging import (
    calculate_group_table_size,
    build_flashable_zip,
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
        new_dat_br=tmp_path / "system.new.dat.br",
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
        new_dat_br=tmp_path / "system.new.dat.br",
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
        new_dat_br=tmp_path / "system.new.dat.br",
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


def test_write_updater_script_includes_raw_images_and_slot_logic(tmp_path: Path) -> None:
    artifact = PartitionArtifact(
        name="system",
        image_path=tmp_path / "system.img",
        image_size=1234,
        transfer_list=tmp_path / "system.transfer.list",
        new_dat_br=tmp_path / "system.new.dat.br",
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


def test_build_flashable_zip_creates_output_parent(tmp_path: Path) -> None:
    payload_dir = tmp_path / "payload"
    payload_dir.mkdir()
    (payload_dir / "system.transfer.list").write_text("4\n1\n0\n")
    (payload_dir / "system.new.dat.br").write_bytes(b"payload")
    (payload_dir / "system.patch.dat").write_bytes(b"")
    meta_dir = payload_dir / "META-INF" / "com" / "google" / "android"
    meta_dir.mkdir(parents=True)
    (meta_dir / "updater-script").write_text("ui_print(\"ok\");\n")

    update_binary = tmp_path / "update-binary"
    update_binary.write_bytes(b"binary")
    avbctl_binary = tmp_path / "avbctl"
    avbctl_binary.write_bytes(b"binary")

    output_zip = tmp_path / "missing" / "nested" / "result.zip"
    build_flashable_zip(payload_dir, update_binary, avbctl_binary, output_zip, zip_level=0)

    assert output_zip.exists()


def test_build_flashable_zip_reports_monotonic_progress(tmp_path: Path) -> None:
    payload_dir = tmp_path / "payload"
    payload_dir.mkdir()
    (payload_dir / "system.transfer.list").write_text("4\n1\n0\n")
    (payload_dir / "system.new.dat.br").write_bytes(b"a" * (9 * 1024 * 1024))
    (payload_dir / "system.patch.dat").write_bytes(b"")
    meta_dir = payload_dir / "META-INF" / "com" / "google" / "android"
    meta_dir.mkdir(parents=True)
    (meta_dir / "updater-script").write_text("ui_print(\"ok\");\n")

    update_binary = tmp_path / "update-binary"
    update_binary.write_bytes(b"binary")
    avbctl_binary = tmp_path / "avbctl"
    avbctl_binary.write_bytes(b"binary")
    output_zip = tmp_path / "result.zip"
    events: list[tuple[str, int, int, int, int, bool]] = []

    build_flashable_zip(
        payload_dir,
        update_binary,
        avbctl_binary,
        output_zip,
        zip_level=6,
        progress_callback=lambda current_file, files_done, total_files, bytes_done, total_bytes, store_entry: events.append(
            (current_file, files_done, total_files, bytes_done, total_bytes, store_entry)
        ),
    )

    assert output_zip.exists()
    assert events
    assert events[0][1] == 0
    assert events[-1][1] == events[-1][2]
    assert events[-1][3] == events[-1][4]
    assert [event[3] for event in events] == sorted(event[3] for event in events)


def test_build_flashable_zip_stores_brotli_entries(tmp_path: Path) -> None:
    payload_dir = tmp_path / "payload"
    payload_dir.mkdir()
    (payload_dir / "system.transfer.list").write_text("4\n1\n0\n")
    (payload_dir / "system.new.dat.br").write_bytes(b"payload")
    (payload_dir / "system.patch.dat").write_bytes(b"")
    meta_dir = payload_dir / "META-INF" / "com" / "google" / "android"
    meta_dir.mkdir(parents=True)
    (meta_dir / "updater-script").write_text("ui_print(\"ok\");\n")

    update_binary = tmp_path / "update-binary"
    update_binary.write_bytes(b"binary")
    avbctl_binary = tmp_path / "avbctl"
    avbctl_binary.write_bytes(b"binary")
    output_zip = tmp_path / "result.zip"
    build_flashable_zip(payload_dir, update_binary, avbctl_binary, output_zip, zip_level=6)

    with zipfile.ZipFile(output_zip) as archive:
        assert archive.getinfo("bin/avbctl").compress_type == zipfile.ZIP_DEFLATED
        assert archive.getinfo("system.new.dat.br").compress_type == zipfile.ZIP_STORED
        assert archive.getinfo("system.transfer.list").compress_type == zipfile.ZIP_DEFLATED
