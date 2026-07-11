# Plan 003: Deduplicate `_UNSUPPORTED_PARTITIONS` and remove dead `_partition_support`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 58b33f3..HEAD -- src/payload2recovery/pipeline.py src/payload2recovery/packaging.py src/payload2recovery/models.py`
> If any file listed has changed since this plan was written, treat it as a
> STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (002 is recommended but not required)
- **Category**: tech-debt
- **Planned at**: commit `58b33f3`, 2026-07-11

## Why this matters

Two independent locations define `{"super", "userdata", "metadata"}` as unsupported partitions — `pipeline.py:49` as a module constant and `packaging.py:43` as a local variable inside `validate_partition_layout`. If someone adds a partition to one list but not the other, the classification and validation functions silently disagree. Separately, `_partition_support()` at `pipeline.py:549-556` is dead code — defined but never called. Removing it eliminates confusion and a maintenance trap.

## Current state

**Duplicate constant:**

`src/payload2recovery/pipeline.py:49`:
```python
_UNSUPPORTED_PARTITIONS = {"super", "userdata", "metadata"}
```

`src/payload2recovery/packaging.py:42-44`:
```python
def validate_partition_layout(partitions: list[str]) -> None:
    unsupported = {"super", "userdata", "metadata"}
    overlap = unsupported.intersection(partitions)
```

These two sets must always be identical but have no shared definition.

**Dead code:**

`src/payload2recovery/pipeline.py:549-556`:
```python
def _partition_support(extracted: list[Path]) -> tuple[set[str], set[str]]:
    logical_supported, default_raw, explicit_raw, denied, auto_raw, skipped = _classify_extracted_partitions(extracted)
    unsupported = set(default_raw)
    unsupported.update(explicit_raw)
    unsupported.update(denied)
    unsupported.update(auto_raw)
    unsupported.update(skipped)
    return logical_supported, unsupported
```

This function has zero callers (confirmed by `grep -rn "_partition_support" src/` returning only the definition).

**Reference pattern for moving shared constants:**

`src/payload2recovery/models.py` already holds shared dataclasses. Adding a module-level constant here follows the pattern of `BuildOptions`, `PartitionArtifact`, etc. living in `models.py`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install | `uv sync --group dev` | exit 0 |
| Run tests | `uv run --group dev pytest -v` | all pass |
| Lint | `uv run ruff check src/ tests/` | exit 0 |
| Typecheck | `uv run mypy src/payload2recovery/` | exit 0 |

## Scope

**In scope**:
- `src/payload2recovery/models.py` — add the shared constant
- `src/payload2recovery/pipeline.py` — remove `_UNSUPPORTED_PARTITIONS`, import from models, remove `_partition_support`
- `src/payload2recovery/packaging.py` — import the constant instead of defining locally

**Out of scope**:
- Any changes to logic or behavior
- Test changes (existing tests cover both code paths already)
- Any other module or file

## Git workflow

- Branch: `advisor/003-dedup-unsupported`
- Commit message: `deduplicate _UNSUPPORTED_PARTITIONS and remove dead _partition_support`
- Single commit

## Steps

### Step 1: Add shared constant to models.py

Add at the end of `src/payload2recovery/models.py` (after the last dataclass, typically after `BuildResult`):

```python
UNSUPPORTED_PARTITIONS: frozenset[str] = frozenset({"super", "userdata", "metadata"})
```

Use `frozenset` to signal immutability (following the convention that module-level constants should not be modified).

**Verify**: `uv run ruff check src/payload2recovery/models.py` → exit 0

### Step 2: Update pipeline.py

- Remove the line `_UNSUPPORTED_PARTITIONS = {"super", "userdata", "metadata"}` (line 49)
- Add an import: `from payload2recovery.models import UNSUPPORTED_PARTITIONS` at the top
- Replace every reference to `_UNSUPPORTED_PARTITIONS` with `UNSUPPORTED_PARTITIONS` (there should be exactly one, at line 575: `if name in _UNSUPPORTED_PARTITIONS:`)
- Remove the entire `_partition_support` function (lines 549-556)

**Verify**:
- `grep -rn "_UNSUPPORTED_PARTITIONS" src/` → no matches (it was replaced with `UNSUPPORTED_PARTITIONS`)
- `grep -rn "_partition_support" src/` → no matches
- `uv run ruff check src/payload2recovery/pipeline.py` → exit 0

### Step 3: Update packaging.py

In `src/payload2recovery/packaging.py`:
- Add `from payload2recovery.models import UNSUPPORTED_PARTITIONS` to the existing imports (line 10)
- Replace the local `unsupported = {"super", "userdata", "metadata"}` (line 43) with `unsupported = set(UNSUPPORTED_PARTITIONS)`

**Verify**: `uv run ruff check src/payload2recovery/packaging.py` → exit 0

### Step 4: Run full test suite

**Verify**:
- `uv run --group dev pytest -v` → all tests pass (all 27 existing tests should still pass since behavior hasn't changed)
- `uv run ruff check src/ tests/` → exit 0
- `uv run mypy src/payload2recovery/` → exit 0 (if mypy is configured; skip if not yet added)

## Test plan

No new tests needed. Existing tests cover both:
- Classification of `super` as unsupported (`test_classify_extracted_partitions_separates_default_and_explicit_raw`)
- Validation rejecting `super` (`test_validate_partition_layout_rejects_super`)

Both should continue passing since the set contents are identical.

## Done criteria

ALL must hold:

- [ ] `UNSUPPORTED_PARTITIONS` is defined once in `models.py` as a `frozenset`
- [ ] `grep -rn "_UNSUPPORTED_PARTITIONS" src/` returns no matches (old private name gone)
- [ ] `grep -rn "_partition_support" src/` returns no matches (dead function removed)
- [ ] `packaging.py` uses `set(UNSUPPORTED_PARTITIONS)` instead of a literal set
- [ ] `pipeline.py` imports `UNSUPPORTED_PARTITIONS` from `models`
- [ ] `uv run --group dev pytest` exits 0
- [ ] No files outside the in-scope list are modified
- [ ] `plans/README.md` status row updated to DONE

## STOP conditions

Stop and report back if:

- Any test fails after the change (unlikely, but could indicate the constant set somehow differs)
- The packaging module uses `unsupported` in additional ways beyond `validate_partition_layout` (e.g., in the zip builder)

## Maintenance notes

- If more partitions become unsupported in the future, update `models.py:UNSUPPORTED_PARTITIONS` in one place
- The `frozenset` prevents accidental mutation — if mutation is ever needed, convert to `list`/`set` at the use site
