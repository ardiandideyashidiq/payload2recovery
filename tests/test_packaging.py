from pathlib import Path

from payload2recovery.models import DeviceAssertion, PartitionArtifact
from payload2recovery.packaging import (
    calculate_group_table_size,
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


def test_build_flashable_zip_creates_output_parent(tmp_path: Path) -> None:
    from payload2recovery.packaging import build_flashable_zip

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

    output_zip = tmp_path / "missing" / "nested" / "result.zip"
    build_flashable_zip(payload_dir, update_binary, output_zip, zip_level=0)

    assert output_zip.exists()
