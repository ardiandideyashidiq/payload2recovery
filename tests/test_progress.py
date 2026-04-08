import io

from payload2recovery.progress import LiveProgress


def test_live_progress_plain_output_lines() -> None:
    stream = io.StringIO()
    progress = LiveProgress(enabled=True, stream=stream)
    progress.update("system", "sparse")
    progress.update("system", "dat")
    progress.fail("system", "brotli", "boom")
    output = stream.getvalue()
    assert "system: sparse" in output
    assert "system: dat" in output
    assert "system: brotli failed: boom" in output


def test_live_progress_tracks_current_stage() -> None:
    progress = LiveProgress(enabled=False, stream=io.StringIO())
    assert progress.stage("product") == "build"
    progress.update("product", "brotli")
    assert progress.stage("product") == "brotli"
