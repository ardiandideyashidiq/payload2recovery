from pathlib import Path
import zipfile

import port2recovery.pipeline as pipeline
from payload2recovery.models import CompressionResult, ConverterResult

from port2recovery.config import Settings
from port2recovery.models import BuildOptions
from port2recovery.resources import ResourceManager


def test_partition_support_marks_raw_images_unsupported(tmp_path: Path) -> None:
    extracted = [
        tmp_path / "system.img",
        tmp_path / "vendor.img",
        tmp_path / "vbmeta.img",
        tmp_path / "vendor_boot.img",
    ]
    supported, unsupported = pipeline._partition_support(extracted)
    assert supported == {"system", "vendor"}
    assert unsupported == {"vbmeta", "vendor_boot"}


def test_build_stages_raw_images_into_final_zip(tmp_path: Path, monkeypatch) -> None:
    rom_dir = tmp_path / "hyperos"
    rom_dir.mkdir()
    (rom_dir / "system.img").write_bytes(b"system-image")
    (rom_dir / "vendor.img").write_bytes(b"vendor-image")
    (rom_dir / "logo.bin").write_bytes(b"logo")
    (rom_dir / "lk.img").write_bytes(b"lk")
    (rom_dir / "port2recovery.toml").write_text(
        "\n".join(
            [
                "[device]",
                'assert_devices = ["P13001L-GL"]',
                "",
                "[[raw_images]]",
                'file = "logo.bin"',
                'target = "/dev/block/by-name/logo"',
                'slot_policy = "none"',
                "",
                "[[raw_images]]",
                'file = "lk.img"',
                'target = "/dev/block/by-name/lk"',
                'slot_policy = "active"',
            ]
        )
    )

    def fake_benchmark_converter(script_dir: Path, image_path: Path, output_dir: Path, partition: str, stage_callback=None):
        _ = script_dir
        if stage_callback is not None:
            stage_callback("dat")
        transfer = output_dir / f"{partition}.transfer.list"
        new_dat = output_dir / f"{partition}.new.dat"
        transfer.write_text("4\n1\n0\n")
        new_dat.write_bytes(f"{partition}-dat".encode())
        return (
            ConverterResult(
                transfer_list=transfer,
                new_dat=new_dat,
                backend="python",
                backend_version="test",
                validation={"new_dat_size_bytes": new_dat.stat().st_size, "valid": True},
            ),
            {"partition": partition, "backend": "python"},
        )

    def fake_compress_brotli(input_file: Path, level: int, enabled: bool, verbose: bool, workers: int = 0, progress_callback=None):
        _ = verbose, workers
        output_file = input_file.with_suffix(input_file.suffix + ".br")
        data = input_file.read_bytes()
        output_file.write_bytes(data)
        input_file.unlink()
        if progress_callback is not None:
            progress_callback(len(data), len(data), len(data))
        return CompressionResult(
            output_file=output_file,
            backend="python-brotli",
            backend_version="test",
            input_size=len(data),
            output_size=len(data),
            level=level,
            enabled=enabled,
        )

    monkeypatch.setattr(pipeline, "benchmark_converter", fake_benchmark_converter)
    monkeypatch.setattr(pipeline, "compress_brotli", fake_compress_brotli)

    settings = Settings(default_partitions=["system", "vendor"], verbose=False)
    options = BuildOptions(rom_dir=rom_dir, mode="template", output_dir=tmp_path / "dist")
    resources = ResourceManager()
    resource_paths = resources.open()
    try:
        result = pipeline.build(options, settings, resource_paths)
    finally:
        resources.close()

    assert result.output_path.exists()
    with zipfile.ZipFile(result.output_path) as archive:
        names = set(archive.namelist())
        assert "logo.bin" in names
        assert "lk.img" in names
        assert "system.transfer.list" in names
        assert "system.new.dat.br" in names
        assert "META-INF/com/google/android/updater-script" in names
    assert result.build_metadata["raw_images"] == [
        {
            "file": "logo.bin",
            "target": "/dev/block/by-name/logo",
            "slot_policy": "none",
            "source": "manifest",
        },
        {
            "file": "lk.img",
            "target": "/dev/block/by-name/lk",
            "slot_policy": "active",
            "source": "manifest",
        },
    ]


def test_build_pads_unaligned_logical_images_in_workspace(tmp_path: Path, monkeypatch) -> None:
    rom_dir = tmp_path / "hyperos"
    rom_dir.mkdir()
    (rom_dir / "system.img").write_bytes(b"abcde")
    (rom_dir / "vendor.img").write_bytes(b"v" * 4096)
    work_dir = tmp_path / "work"
    seen_sizes: dict[str, int] = {}

    def fake_benchmark_converter(
        script_dir: Path,
        image_path: Path,
        output_dir: Path,
        partition: str,
        stage_callback=None,
    ):
        _ = script_dir
        if stage_callback is not None:
            stage_callback("dat")
        seen_sizes[partition] = image_path.stat().st_size
        transfer = output_dir / f"{partition}.transfer.list"
        new_dat = output_dir / f"{partition}.new.dat"
        transfer.write_text("4\n1\n0\n")
        new_dat.write_bytes(f"{partition}-dat".encode())
        return (
            ConverterResult(
                transfer_list=transfer,
                new_dat=new_dat,
                backend="python",
                backend_version="test",
                validation={"new_dat_size_bytes": new_dat.stat().st_size, "valid": True},
            ),
            {"partition": partition, "backend": "python"},
        )

    def fake_compress_brotli(
        input_file: Path,
        level: int,
        enabled: bool,
        verbose: bool,
        workers: int = 0,
        progress_callback=None,
    ):
        _ = verbose, workers
        output_file = input_file.with_suffix(input_file.suffix + ".br")
        data = input_file.read_bytes()
        output_file.write_bytes(data)
        input_file.unlink()
        if progress_callback is not None:
            progress_callback(len(data), len(data), len(data))
        return CompressionResult(
            output_file=output_file,
            backend="python-brotli",
            backend_version="test",
            input_size=len(data),
            output_size=len(data),
            level=level,
            enabled=enabled,
        )

    monkeypatch.setattr(pipeline, "benchmark_converter", fake_benchmark_converter)
    monkeypatch.setattr(pipeline, "compress_brotli", fake_compress_brotli)

    settings = Settings(default_partitions=["system", "vendor"], verbose=False)
    options = BuildOptions(
        rom_dir=rom_dir,
        mode="template",
        output_dir=tmp_path / "dist",
        work_dir=work_dir,
    )
    resources = ResourceManager()
    resource_paths = resources.open()
    try:
        result = pipeline.build(options, settings, resource_paths)
    finally:
        resources.close()

    assert result.output_path.exists()
    assert (rom_dir / "system.img").stat().st_size == 5
    assert seen_sizes["system"] == 4096
    assert seen_sizes["vendor"] == 4096
    assert (work_dir / "logical_images" / "system.img").stat().st_size == 4096
    assert result.build_metadata["padded_logical_images"] == [
        {
            "partition": "system",
            "original_size": 5,
            "padded_size": 4096,
            "padding_bytes": 4091,
        }
    ]


def test_inspect_rom_reports_manifest_and_raw_images(tmp_path: Path) -> None:
    rom_dir = tmp_path / "hyperos"
    rom_dir.mkdir()
    (rom_dir / "system.img").write_bytes(b"system")
    (rom_dir / "logo.bin").write_bytes(b"logo")
    (rom_dir / "port2recovery.toml").write_text(
        "\n".join(
            [
                "[[raw_images]]",
                'file = "logo.bin"',
                'target = "/dev/block/by-name/logo"',
            ]
        )
    )
    info = pipeline.inspect_rom(rom_dir, Settings(default_partitions=["system"]))
    assert info["manifest_present"] is True
    assert info["raw_images"][0]["exists"] is True
    assert info["raw_images"][0]["source"] == "manifest"
    assert "system.img" in info["logical_images"]


def test_inspect_rom_autodetects_common_raw_images_without_manifest(tmp_path: Path) -> None:
    rom_dir = tmp_path / "hyperos"
    rom_dir.mkdir()
    (rom_dir / "system.img").write_bytes(b"system")
    (rom_dir / "logo.bin").write_bytes(b"logo")
    (rom_dir / "lk.img").write_bytes(b"lk")
    (rom_dir / "boot.img").write_bytes(b"boot")
    (rom_dir / "vendor_boot.img").write_bytes(b"vb")
    (rom_dir / "vbmeta.img").write_bytes(b"meta")

    info = pipeline.inspect_rom(rom_dir, Settings(default_partitions=["system"]))

    assert info["manifest_present"] is False
    assert info["raw_images"] == [
        {
            "file": "logo.bin",
            "target": "/dev/block/by-name/logo",
            "slot_policy": "none",
            "source": "autodetect",
            "exists": True,
        },
        {
            "file": "lk.img",
            "target": "/dev/block/by-name/lk",
            "slot_policy": "both",
            "source": "autodetect",
            "exists": True,
        },
        {
            "file": "boot.img",
            "target": "/dev/block/by-name/boot",
            "slot_policy": "both",
            "source": "autodetect",
            "exists": True,
        },
    ]


def test_inspect_rom_does_not_autodetect_boot_without_vendor_boot(tmp_path: Path) -> None:
    rom_dir = tmp_path / "hyperos"
    rom_dir.mkdir()
    (rom_dir / "system.img").write_bytes(b"system")
    (rom_dir / "boot.img").write_bytes(b"boot")
    (rom_dir / "vbmeta.img").write_bytes(b"meta")

    info = pipeline.inspect_rom(rom_dir, Settings(default_partitions=["system"]))

    assert info["manifest_present"] is False
    assert info["raw_images"] == []


def test_build_autodetects_raw_images_when_manifest_has_no_raw_entries(tmp_path: Path, monkeypatch) -> None:
    rom_dir = tmp_path / "hyperos"
    rom_dir.mkdir()
    (rom_dir / "system.img").write_bytes(b"system-image")
    (rom_dir / "vendor.img").write_bytes(b"vendor-image")
    (rom_dir / "logo.bin").write_bytes(b"logo")
    (rom_dir / "lk.img").write_bytes(b"lk")
    (rom_dir / "boot.img").write_bytes(b"boot")
    (rom_dir / "vendor_boot.img").write_bytes(b"vb")

    def fake_benchmark_converter(script_dir: Path, image_path: Path, output_dir: Path, partition: str, stage_callback=None):
        _ = script_dir
        if stage_callback is not None:
            stage_callback("dat")
        transfer = output_dir / f"{partition}.transfer.list"
        new_dat = output_dir / f"{partition}.new.dat"
        transfer.write_text("4\n1\n0\n")
        new_dat.write_bytes(f"{partition}-dat".encode())
        return (
            ConverterResult(
                transfer_list=transfer,
                new_dat=new_dat,
                backend="python",
                backend_version="test",
                validation={"new_dat_size_bytes": new_dat.stat().st_size, "valid": True},
            ),
            {"partition": partition, "backend": "python"},
        )

    def fake_compress_brotli(input_file: Path, level: int, enabled: bool, verbose: bool, workers: int = 0, progress_callback=None):
        _ = verbose, workers
        output_file = input_file.with_suffix(input_file.suffix + ".br")
        data = input_file.read_bytes()
        output_file.write_bytes(data)
        input_file.unlink()
        if progress_callback is not None:
            progress_callback(len(data), len(data), len(data))
        return CompressionResult(
            output_file=output_file,
            backend="python-brotli",
            backend_version="test",
            input_size=len(data),
            output_size=len(data),
            level=level,
            enabled=enabled,
        )

    monkeypatch.setattr(pipeline, "benchmark_converter", fake_benchmark_converter)
    monkeypatch.setattr(pipeline, "compress_brotli", fake_compress_brotli)

    settings = Settings(default_partitions=["system", "vendor"], verbose=False)
    options = BuildOptions(rom_dir=rom_dir, mode="template", output_dir=tmp_path / "dist")
    resources = ResourceManager()
    resource_paths = resources.open()
    try:
        result = pipeline.build(options, settings, resource_paths)
    finally:
        resources.close()

    with zipfile.ZipFile(result.output_path) as archive:
        names = set(archive.namelist())
        assert "bin/avbctl" in names
        assert "boot.img" in names
        assert "logo.bin" in names
        assert "lk.img" in names

    assert result.build_metadata["raw_images"] == [
        {
            "file": "logo.bin",
            "target": "/dev/block/by-name/logo",
            "slot_policy": "none",
            "source": "autodetect",
        },
        {
            "file": "lk.img",
            "target": "/dev/block/by-name/lk",
            "slot_policy": "both",
            "source": "autodetect",
        },
        {
            "file": "boot.img",
            "target": "/dev/block/by-name/boot",
            "slot_policy": "both",
            "source": "autodetect",
        },
    ]


def test_manifest_raw_images_disable_autodetect(tmp_path: Path) -> None:
    rom_dir = tmp_path / "hyperos"
    rom_dir.mkdir()
    (rom_dir / "system.img").write_bytes(b"system")
    (rom_dir / "logo.bin").write_bytes(b"logo")
    (rom_dir / "vendor_boot.img").write_bytes(b"vb")
    (rom_dir / "port2recovery.toml").write_text(
        "\n".join(
            [
                "[[raw_images]]",
                'file = "logo.bin"',
                'target = "/dev/block/by-name/logo"',
                'slot_policy = "none"',
            ]
        )
    )

    info = pipeline.inspect_rom(rom_dir, Settings(default_partitions=["system"]))

    assert info["raw_images"] == [
        {
            "file": "logo.bin",
            "target": "/dev/block/by-name/logo",
            "slot_policy": "none",
            "source": "manifest",
            "exists": True,
        }
    ]


def test_build_includes_banner_text_in_generated_updater_script(tmp_path: Path, monkeypatch) -> None:
    rom_dir = tmp_path / "hyperos"
    rom_dir.mkdir()
    (rom_dir / "system.img").write_bytes(b"system-image")
    (rom_dir / "vendor.img").write_bytes(b"vendor-image")
    (rom_dir / "banner").write_text('Port Banner\n\nQuote " \\\n')

    def fake_benchmark_converter(script_dir: Path, image_path: Path, output_dir: Path, partition: str, stage_callback=None):
        _ = script_dir
        if stage_callback is not None:
            stage_callback("dat")
        transfer = output_dir / f"{partition}.transfer.list"
        new_dat = output_dir / f"{partition}.new.dat"
        transfer.write_text("4\n1\n0\n")
        new_dat.write_bytes(f"{partition}-dat".encode())
        return (
            ConverterResult(
                transfer_list=transfer,
                new_dat=new_dat,
                backend="python",
                backend_version="test",
                validation={"new_dat_size_bytes": new_dat.stat().st_size, "valid": True},
            ),
            {"partition": partition, "backend": "python"},
        )

    def fake_compress_brotli(input_file: Path, level: int, enabled: bool, verbose: bool, workers: int = 0, progress_callback=None):
        _ = verbose, workers
        output_file = input_file.with_suffix(input_file.suffix + ".br")
        data = input_file.read_bytes()
        output_file.write_bytes(data)
        input_file.unlink()
        if progress_callback is not None:
            progress_callback(len(data), len(data), len(data))
        return CompressionResult(
            output_file=output_file,
            backend="python-brotli",
            backend_version="test",
            input_size=len(data),
            output_size=len(data),
            level=level,
            enabled=enabled,
        )

    monkeypatch.setattr(pipeline, "benchmark_converter", fake_benchmark_converter)
    monkeypatch.setattr(pipeline, "compress_brotli", fake_compress_brotli)

    settings = Settings(default_partitions=["system", "vendor"], verbose=False)
    options = BuildOptions(rom_dir=rom_dir, mode="template", output_dir=tmp_path / "dist")
    resources = ResourceManager()
    resource_paths = resources.open()
    try:
        result = pipeline.build(options, settings, resource_paths)
    finally:
        resources.close()

    with zipfile.ZipFile(result.output_path) as archive:
        content = archive.read("META-INF/com/google/android/updater-script").decode()
    assert 'ui_print("Port Banner");' in content
    assert 'ui_print(" ");' in content
    assert 'ui_print("Quote \\" \\\\");' in content
