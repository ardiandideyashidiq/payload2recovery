from pathlib import Path

from payload2recovery.models import DeviceAssertion, PartitionArtifact

from port2recovery.models import RawImageSpec
from port2recovery.packaging import write_updater_script


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
        [
            RawImageSpec(file="logo.bin", target="/dev/block/by-name/logo", slot_policy="none"),
            RawImageSpec(file="lk.img", target="/dev/block/by-name/lk", slot_policy="active"),
        ],
        device_assertion=DeviceAssertion(
            device_names=["P13001L-GL"],
            source="port2recovery.toml",
            enabled=True,
        ),
    )
    content = updater_script.read_text()
    assert 'package_extract_file("logo.bin", "/dev/block/by-name/logo");' in content
    assert 'getprop("ro.boot.slot_suffix") == "_a"' in content
    assert 'package_extract_file("lk.img", "/dev/block/by-name/lk_a")' in content
    assert 'block_image_update(map_partition("system")' in content
    assert "This package is for device(s): P13001L-GL" in content


def test_write_updater_script_includes_banner_lines(tmp_path: Path) -> None:
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
        [],
        banner_lines=["Port ROM", "", "Build 2026"],
    )
    content = updater_script.read_text()
    assert 'ui_print("Checking /cache...");' not in content
    assert 'run_program("/sbin/sh", "-c", "[ -d /data/cache ] || mkdir -p /data/cache");' in content
    assert content.count('ui_print(" ");') >= 5
    assert 'ui_print("Port ROM");' in content
    assert 'ui_print(" ");' in content
    assert 'ui_print("Build 2026");' in content
