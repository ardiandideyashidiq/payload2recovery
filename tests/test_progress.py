import io
import re

from payload2recovery.progress import LiveProgress


def test_live_progress_plain_output_lines() -> None:
    stream = io.StringIO()
    progress = LiveProgress(enabled=True, stream=stream)
    progress.update("system", "sparse")
    progress.update("system", "dat")
    progress.update("system", "waiting-brotli")
    progress.update("system", "brotli", processed_bytes=32, total_bytes=128)
    progress.update("system", "brotli", processed_bytes=64, total_bytes=128)
    progress.fail("system", "brotli", "boom")
    output = stream.getvalue()
    assert "system: sparse" in output
    assert "system: dat" in output
    assert "system: waiting  00:00" in output
    assert "system: brotli  25% 0MiB/0MiB" in output
    assert "system: brotli  50% 0MiB/0MiB" in output
    assert "system: brotli failed: boom" in output


def test_live_progress_tracks_current_stage() -> None:
    progress = LiveProgress(enabled=False, stream=io.StringIO())
    assert progress.stage("product") == "build"
    progress.update("product", "brotli")
    assert progress.stage("product") == "brotli"


class _TtyBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_live_progress_interactive_brotli_status() -> None:
    stream = _TtyBuffer()
    progress = LiveProgress(enabled=True, stream=stream)
    progress.update("system", "brotli", processed_bytes=64 * 1024 * 1024, total_bytes=128 * 1024 * 1024)
    progress.close()
    rendered = stream.getvalue()
    assert "system" in rendered
    assert "brotli" in rendered
    assert "50%" in rendered
    assert "64MiB/s" in rendered or re.search(r"\d+MiB/s", rendered)
    assert "system.new.dat.br" in rendered


def test_live_progress_interactive_keeps_done_partitions() -> None:
    stream = _TtyBuffer()
    progress = LiveProgress(enabled=True, stream=stream)
    progress.update("product", "done")
    progress.close()
    rendered = stream.getvalue()
    assert "product" in rendered
    assert "done" in rendered


def test_live_progress_interactive_zip_status() -> None:
    stream = _TtyBuffer()
    progress = LiveProgress(enabled=True, stream=stream)
    progress.update_package(
        "system.new.dat.br",
        2,
        5,
        64 * 1024 * 1024,
        128 * 1024 * 1024,
        store_entry=True,
    )
    progress.close()
    rendered = stream.getvalue()
    assert "zip" in rendered
    assert "store" in rendered
    assert "system.new.dat.br" in rendered
    assert "2/5 files" in rendered


def test_live_progress_plain_zip_output_lines() -> None:
    stream = io.StringIO()
    progress = LiveProgress(enabled=True, stream=stream)
    progress.update_package("system.new.dat.br", 0, 2, 0, 10, store_entry=True)
    progress.update_package("system.new.dat.br", 1, 2, 5, 10, store_entry=True)
    progress.update_package("vendor.transfer.list", 2, 2, 10, 10, store_entry=False)
    output = stream.getvalue()
    assert "zip 0/2 files 0MiB/0MiB store system.new.dat.br" in output
    assert "zip 1/2 files 0MiB/0MiB store system.new.dat.br" in output
    assert "zip 2/2 files 0MiB/0MiB deflate vendor.transfer.list" in output
