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
    assert "system: waiting 00:00" in output
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
    rendered = stream.getvalue()
    assert "[0/1 done]" in rendered
    assert "system:brotli  50% 64MiB/128MiB" in rendered
    assert re.search(r"\d+MiB/s 00:00", rendered)


def test_live_progress_interactive_hides_done_partitions() -> None:
    stream = _TtyBuffer()
    progress = LiveProgress(enabled=True, stream=stream)
    progress.update("product", "done")
    rendered = stream.getvalue()
    assert "[1/1 done] | all partitions done" in rendered


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
    rendered = stream.getvalue()
    assert "zip 2/5 files 64MiB/128MiB" in rendered
    assert "store system.new.dat.br" in rendered


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
