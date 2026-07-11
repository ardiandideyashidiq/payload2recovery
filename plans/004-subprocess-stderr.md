# Plan 004: Show subprocess stderr on failure in `_run`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 58b33f3..HEAD -- src/payload2recovery/backends.py`
> If `backends.py` has changed since this plan was written, treat it as a
> STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: correctness
- **Planned at**: commit `58b33f3`, 2026-07-11

## Why this matters

When a subprocess command fails (e.g., `payload-dumper-go` crashes, or `zip` runs out of disk space), the `_run` helper discards stderr in non-verbose mode and produces only `"Command failed (N): cmd"`. The user has zero diagnostic information about WHY it failed. For a CLI tool that users run without `--verbose` (the subprocess stdout/stderr is set to DEVNULL when `verbose=False`), this makes every subprocess failure a debugging dead end.

## Current state

`src/payload2recovery/backends.py:135-140`:
```python
def _run(cmd: list[str], verbose: bool) -> None:
    stdout = None if verbose else subprocess.DEVNULL
    stderr = None if verbose else subprocess.DEVNULL
    completed = subprocess.run(cmd, stdout=stdout, stderr=stderr, check=False)
    if completed.returncode != 0:
        raise ValidationError(f"Command failed ({completed.returncode}): {' '.join(cmd)}")
```

Both stdout and stderr go to `DEVNULL` when `verbose=False`. The error message contains only the return code and the command string.

Note: `_run` is called from `run_payload_extractor` (line 63) which is on the main build path. It is also the gateway for any future subprocess calls in `backends.py`.

The sibling function `_convert_sparse_to_dat_subprocess` (line 172) already captures stderr correctly:
```python
completed = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
if completed.returncode != 0:
    message = completed.stderr.strip() or completed.stdout.strip() or "img2sdat failed"
    raise ValidationError(f"Command failed ({completed.returncode}): {' '.join(cmd)}: {message}")
```

The fix is to make `_run` capture stderr the same way.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install | `uv sync --group dev` | exit 0 |
| Run tests | `uv run --group dev pytest -v` | all pass |
| Lint | `uv run ruff check src/ tests/` | exit 0 |

## Scope

**In scope**:
- `src/payload2recovery/backends.py` — modify `_run` to capture stderr and include it in the error message

**Out of scope**:
- `_convert_sparse_to_dat_subprocess` — already correct, leave it alone
- Any other function or file
- Test changes (existing tests mock `_run` indirectly through `run_payload_extractor`)

## Git workflow

- Branch: `advisor/004-subprocess-stderr`
- Commit message: `show subprocess stderr on failure in _run`
- Single commit

## Steps

### Step 1: Modify `_run`

Change the function to always capture stderr (even in non-verbose mode), and include it in the error message on failure:

```python
def _run(cmd: list[str], verbose: bool) -> None:
    stdout = None if verbose else subprocess.DEVNULL
    stderr = subprocess.PIPE
    completed = subprocess.run(cmd, stdout=stdout, stderr=stderr, text=True, check=False)
    if completed.returncode != 0:
        stderr_text = completed.stderr.strip() if completed.stderr else ""
        detail = f": {stderr_text}" if stderr_text else ""
        raise ValidationError(f"Command failed ({completed.returncode}): {' '.join(cmd)}{detail}")
```

Key changes:
1. `stderr` is always `subprocess.PIPE` (never `DEVNULL`)
2. Added `text=True` to get string output
3. On failure, append the stripped stderr text after the command

**Verify**: `uv run ruff check src/payload2recovery/backends.py` → exit 0

### Step 2: Run full test suite

**Verify**:
- `uv run --group dev pytest -v` → all tests pass
- `uv run ruff check src/ tests/` → exit 0

## Test plan

The existing tests mock `run_payload_extractor` which calls `_run`, so they don't exercise the real subprocess path. No test changes needed — the fix is straightforward and the behavior change (capturing stderr that was previously discarded) cannot break any existing passing test. A future improvement could add a subprocess test, but it's out of scope here.

## Done criteria

ALL must hold:

- [ ] `_run` captures stderr via `subprocess.PIPE` (never `DEVNULL`)
- [ ] On failure, the error message includes stderr content
- [ ] `uv run --group dev pytest` exits 0
- [ ] `uv run ruff check src/ tests/` exits 0
- [ ] No files outside `src/payload2recovery/backends.py` are modified
- [ ] `plans/README.md` status row updated to DONE

## STOP conditions

Stop and report back if:

- The signature of `_run` has changed (unlikely for a private helper)
- A test fails — the change is additive (capturing more data) and should not break anything
- You discover `_run` is called in a hot loop where the PIPE overhead matters (it's called once per build, so it doesn't)

## Maintenance notes

- If `_run` is ever used for a subprocess with large stderr output, the full stderr might bloat the error message. For `payload-dumper-go` and CLI tools in this project, stderr is typically brief (error messages only).
- The stdout remains `DEVNULL` in non-verbose mode — that's intentional (the user didn't ask to see it, and it could be binary output).
