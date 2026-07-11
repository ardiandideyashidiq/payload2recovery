# Plan 008: Replace `human_size` subprocess with pure Python

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 58b33f3..HEAD -- src/payload2recovery/packaging.py`
> If `packaging.py` has changed since this plan was written, treat it as a
> STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: performance
- **Planned at**: commit `58b33f3`, 2026-07-11

## Why this matters

`human_size` spawns a `du -h` subprocess to format a file size for a log message. This is wasteful (the caller already has `path.stat().st_size` available) and fragile (no timeout, could hang on a network filesystem). The function is called exactly once, at the end of `build()`, to log the output ZIP size. A simple Python implementation is faster, safer, and removes a host dependency on `du`.

## Current state

`src/payload2recovery/packaging.py:253-257`:
```python
def human_size(path: Path) -> str:
    result = subprocess.run(["du", "-h", str(path)], capture_output=True, text=True, check=False)
    if result.returncode == 0 and result.stdout:
        return result.stdout.split()[0]
    return f"{path.stat().st_size} bytes"
```

Called at `pipeline.py:281`:
```python
LOGGER.info("Created %s (%s)", final_output, human_size(final_output))
```

The function:
1. Spawns a `du -h` subprocess with no timeout
2. Parses `du`'s output (first whitespace-separated token)
3. Falls back to raw bytes if `du` fails

The same info is already available as `final_output.stat().st_size` in the caller's scope. The purpose is human-readable formatting (e.g., "123M" instead of "128974848 bytes").

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install | `uv sync --group dev` | exit 0 |
| Run tests | `uv run --group dev pytest -v` | all pass |
| Lint | `uv run ruff check src/ tests/` | exit 0 |

## Scope

**In scope**:
- `src/payload2recovery/packaging.py` — rewrite `human_size` to use pure Python

**Out of scope**:
- `pipeline.py` — the caller doesn't need to change (same function signature)
- Any other file
- The `subprocess` import — it may still be needed by other functions in `packaging.py` (check: it's also used in `build_flashable_zip` indirectly, but actually no, `subprocess` is used by `human_size` only in `packaging.py`). If `human_size` is the only `subprocess` user in `packaging.py`, remove the `import subprocess` line.

## Git workflow

- Branch: `advisor/008-human-size-python`
- Commit message: `replace du subprocess in human_size with pure Python`
- Single commit

## Steps

### Step 1: Rewrite `human_size`

Replace the function body with a pure Python implementation:

```python
def human_size(path: Path) -> str:
    size = path.stat().st_size
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024:
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}PiB"
```

This produces output like `"256.0MiB"` instead of `du -h`'s `"256M"`. The format is slightly different (includes decimal, uses KiB/MiB/GiB instead of K/M/G) but is equally readable and more standard (binary prefixes).

If you prefer to match `du`'s format exactly (one digit, no decimal, K/M/G suffixes), use:

```python
def human_size(path: Path) -> str:
    size = path.stat().st_size
    for unit in ("B", "K", "M", "G", "T"):
        if size < 1024:
            return f"{int(size)}{unit}"
        size /= 1024
    return f"{int(size)}P"
```

Either version is acceptable. Pick the binary-prefix version (KiB/MiB) for clarity.

**Verify**: `uv run ruff check src/payload2recovery/packaging.py` → exit 0

### Step 2: Clean up unused import

Check if `subprocess` is used elsewhere in `packaging.py`:
```bash
grep -n "subprocess" src/payload2recovery/packaging.py
```

If the only `subprocess` reference was inside `human_size`, remove `import subprocess` from the imports at the top of `packaging.py`.

**Verify**: `uv run ruff check src/payload2recovery/packaging.py` → exit 0 (no unused import warning)

### Step 3: Run full test suite

**Verify**:
- `uv run --group dev pytest -v` → all tests pass
- `uv run ruff check src/ tests/` → exit 0

## Test plan

No test exists for `human_size` directly. The function is called in `build()` which is tested through `test_build_stages_default_and_explicit_raw_images`. That test mocks the conversion pipeline but not the final log line, so it doesn't cover `human_size`. Adding a test is optional for this plan (low leverage), but if you want to add one, put it in `tests/test_packaging.py`:

```python
def test_human_size_uses_python(tmp_path: Path) -> None:
    f = tmp_path / "test.bin"
    f.write_bytes(b"x" * (2 * 1024 * 1024 + 512 * 1024))  # ~2.5 MiB
    result = human_size(f)
    assert isinstance(result, str)
    assert "MiB" in result or "M" in result
```

## Done criteria

ALL must hold:

- [ ] `human_size` no longer calls `subprocess`
- [ ] `human_size` produces a human-readable string (e.g., `"256.0MiB"` or `"256M"`)
- [ ] `uv run --group dev pytest` exits 0
- [ ] `uv run ruff check src/ tests/` exits 0
- [ ] No files outside `src/payload2recovery/packaging.py` are modified
- [ ] `plans/README.md` status row updated to DONE

## STOP conditions

Stop and report back if:

- `subprocess` is used elsewhere in `packaging.py` (don't remove the import in that case)
- A test fails — this is a pure refactor and tests should pass without changes

## Maintenance notes

- The old behavior used `du -h` which gave OS-specific output. The new behavior is deterministic.
- If anyone relied on the exact `du` output format (unlikely — it was used only in a log message), they'll see a slightly different string now.
