# Plan 006: Use StrEnum for build mode instead of bare string

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 58b33f3..HEAD -- src/payload2recovery/`
> If any source file changed, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: 002 (CLI tests) — tests cover the `_options_from_args` that produces the `mode` value
- **Category**: tech-debt
- **Planned at**: commit `58b33f3`, 2026-07-11

## Why this matters

`BuildOptions.mode` is typed as `str` and compared with string literals `"template"`, `"manual"`, and `"all"` throughout the codebase. A typo (e.g., `"templat"` vs `"template"`) silently falls through to the wrong branch at runtime. A `StrEnum` gives compile-time safety, IDE autocompletion, and makes the valid values discoverable.

## Current state

`src/payload2recovery/models.py:32`:
```python
class BuildOptions:
    ...
    mode: str
```

Usage sites in `pipeline.py`:
- Line 513: `if options.mode == "manual":`
- Line 517: `elif options.mode == "all":`
- Line 524: `else:` (template — implicit)
- Line 533: `if options.mode == "manual":`
- Line 535: `elif options.mode == "template":`

Usage in `cli.py`:
- Lines 207-208:
```python
mode = "all" if getattr(args, "all", False) else "manual" if partitions else "template"
```

Usage in test files:
- `tests/test_cli.py` (if plan 002 landed): `options.mode == "template"` etc.
- `tests/test_pipeline.py`: multiple `mode="template"`, `mode="manual"` in `BuildOptions(...)` construction

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install | `uv sync --group dev` | exit 0 |
| Run tests | `uv run --group dev pytest -v` | all pass |
| Lint | `uv run ruff check src/ tests/` | exit 0 |

## Scope

**In scope**:
- `src/payload2recovery/models.py` — add `BuildMode` enum
- `src/payload2recovery/cli.py` — use enum values instead of string literals
- `src/payload2recovery/pipeline.py` — use enum comparisons instead of string comparisons
- `tests/test_cli.py` — update string comparisons to enum comparisons
- `tests/test_pipeline.py` — update string comparisons to enum comparisons

**Out of scope**:
- The `list_partitions` function signature or any other API change
- JSON serialization of `mode` in benchmark reports (it's serialized as `build_metadata["selection_mode"]` — the enum's `.value` will be the string)
- Any other module

## Git workflow

- Branch: `advisor/006-mode-enum`
- Commit message: `use StrEnum for BuildOptions.mode instead of bare string`
- Single commit

## Steps

### Step 1: Add BuildMode enum to models.py

Add after existing imports and before the first dataclass:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class BuildMode(StrEnum):
    TEMPLATE = "template"
    MANUAL = "manual"
    ALL = "all"
```

Then update `BuildOptions`:
```python
mode: BuildMode
```

**Note**: The `from __future__ import annotations` is already the first line of the file. The `StrEnum` import goes with the other standard library imports.

**Verify**: `uv run ruff check src/payload2recovery/models.py` → exit 0

### Step 2: Update cli.py

In `_options_from_args` (line 207-208):
```python
# Before:
mode = "all" if getattr(args, "all", False) else "manual" if partitions else "template"
# After:
from payload2recovery.models import BuildMode
mode = BuildMode.ALL if getattr(args, "all", False) else BuildMode.MANUAL if partitions else BuildMode.TEMPLATE
```

**Verify**: `uv run ruff check src/payload2recovery/cli.py` → exit 0

### Step 3: Update pipeline.py

Replace all string comparisons:

| Location | Before | After |
|----------|--------|-------|
| Line 513 | `if options.mode == "manual":` | `if options.mode is BuildMode.MANUAL:` |
| Line 517 | `elif options.mode == "all":` | `elif options.mode is BuildMode.ALL:` |
| Line 524 | `else:` (template branch) | `else:` (unchanged — it's the fallback) |
| Line 533 | `if options.mode == "manual":` | `if options.mode is BuildMode.MANUAL:` |
| Line 535 | `elif options.mode == "template":` | `elif options.mode is BuildMode.TEMPLATE:` |

Add the import: `from payload2recovery.models import BuildMode` (or add `BuildMode` to the existing imports from `models`).

**Verify**:
- `grep -n '"manual"\|"template"\|"all"' src/payload2recovery/pipeline.py | grep -v "#"` — ensure no string comparisons remain
- `uv run ruff check src/payload2recovery/pipeline.py` → exit 0

### Step 4: Update tests

In `tests/test_cli.py` and `tests/test_pipeline.py`:

- Change `mode="template"` to `mode=BuildMode.TEMPLATE`
- Change `mode="manual"` to `mode=BuildMode.MANUAL`
- Change `mode="all"` to `mode=BuildMode.ALL`
- Change test assertions that compare `options.mode` to strings to compare to enum values

Add `from payload2recovery.models import BuildMode` to the imports in each file.

**Verify**:
- `grep -rn 'mode="' tests/` → no matches (all should use `BuildMode.X`)
- `uv run ruff check tests/` → exit 0

### Step 5: Run full test suite

**Verify**:
- `uv run --group dev pytest -v` → all tests pass
- `uv run ruff check src/ tests/` → exit 0

## Test plan

Existing tests cover the mode comparisons; they just need the string→enum update. No new tests needed.

## Done criteria

ALL must hold:

- [ ] `BuildMode(StrEnum)` exists in `models.py` with `TEMPLATE`, `MANUAL`, `ALL`
- [ ] `BuildOptions.mode` is typed as `BuildMode`, not `str`
- [ ] No string literal comparisons (`== "manual"`, `== "template"`, `== "all"`) remain in `pipeline.py` or `cli.py`
- [ ] No `mode="..."` string values remain in test code
- [ ] `uv run --group dev pytest` exits 0
- [ ] No files outside the in-scope list are modified
- [ ] `plans/README.md` status row updated to DONE

## STOP conditions

Stop and report back if:

- The `build_metadata` JSON output uses `options.mode` directly as a string (it will now be an enum, serialized as its `.value` — which is the same string, so JSON is fine)
- Any string comparison was missed and a test fails
- `StrEnum` is not available (requires Python 3.11+, which this project already requires)

## Maintenance notes

- New build modes should be added as `BuildMode` members, not string constants
- When comparing, always use `is` (identity, not equality) since `StrEnum` members are singletons
- The `.value` attribute gives the string for serialization (e.g., `{"selection_mode": options.mode.value}`)
