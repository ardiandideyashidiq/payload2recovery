# Plan 007: Refactor pipeline.py into focused modules

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 58b33f3..HEAD -- src/payload2recovery/pipeline.py src/payload2recovery/`
> If `pipeline.py` has changed since this plan was written, treat it as a
> STOP condition.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MEDIUM
- **Depends on**: 001 (tooling — ruff/mypy), 002 (CLI tests), 003 (dedup), 005 (worker cleanup)
- **Category**: tech-debt
- **Planned at**: commit `58b33f3`, 2026-07-11

## Why this matters

`pipeline.py` is 787 lines and contains build orchestration, partition classification, output naming, benchmark reporting, worker resolution, and workspace management. The `build()` function alone is 222 lines (115-337), with a 50-line metadata-dict literal inline. This makes the module hard to reason about, impossible to unit-test the helpers in isolation (the classification helpers are private within the file), and risky to modify — one change in the classification logic might accidentally affect the build flow.

The refactor extracts three natural groupings into their own modules without changing any logic. This is purely a code-moving exercise.

## Current state

The module structure of `src/payload2recovery/pipeline.py`:

| Lines | Content | Role |
|-------|---------|------|
| 1-47 | Imports and constants | Module header |
| 49-63 | Partition set constants | `_UNSUPPORTED_PARTITIONS`, `_KNOWN_LOGICAL_PARTITIONS`, etc. |
| 66-78 | `doctor()` | Host dependency check |
| 81-84 | `inspect_ota()` | Basic file info |
| 87-112 | `detect_device_assertion()` | Parse OTA metadata |
| 115-337 | `build()` | Main build orchestration |
| 339-347 | `benchmark()` | Wrapper around build |
| 350-376 | `list_partitions()` | List available partitions |
| 379-417 | `_process_partitions()` | Threaded partition conversion |
| 420-498 | `_build_partition_artifact()` | Single partition pipeline |
| 501-546 | `_select_partitions()` | Choose which to include |
| 549-556 | `_partition_support()` | DEAD — will be removed |
| 559-590 | `_classify_extracted_partitions()` | Categorize by type |
| 593-595 | `_is_recovery_in_boot()` | magiskboot probe helper |
| 597-640 | `_selected_raw_images()` | Build raw image list |
| 643-652 | `_extractor_selected_partitions()` | Filter for extractor |
| 654-664 | `_is_default_raw_partition()` / `_is_explicit_raw_partition()` | Classification predicates |
| 667-681 | `_raw_image_spec_for_path()` | Create RawImageSpec |
| 684-694 | `_stage_raw_images()` | Copy raw images |
| 697-712 | `_list_partition_status()` | Status string for listing |
| 715-737 | `_workspace` | Context manager class |
| 740-765 | `_resolved_*_workers()` | Worker count resolution |
| 768-774 | `_output_name()` | Generate output filename |
| 777-787 | `_write_benchmark_report()` | Write benchmark JSON |

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install | `uv sync --group dev` | exit 0 |
| Run tests | `uv run --group dev pytest -v` | all pass |
| Lint | `uv run ruff check src/ tests/` | exit 0 |
| Typecheck | `uv run mypy src/payload2recovery/` | exit 0 |

## Scope

**In scope**:
- `src/payload2recovery/pipeline.py` — remove extracted functions, keep only the orchestrators
- `src/payload2recovery/classification.py` — CREATE with partition classification logic
- `src/payload2recovery/metadata.py` — CREATE with build metadata construction
- `src/payload2recovery/config.py` — move `_resolved_*_workers` wrappers here (thin, append to `Settings`)
- Update all imports in `pipeline.py`, `cli.py`, and tests

**Out of scope**:
- Changing any function body or behavior
- Renaming any function or class (moves only)
- Adding new functionality
- Changing the `_workspace` class (leave it in pipeline.py as it's tightly coupled to `build()`)

## Git workflow

- Branch: `advisor/007-pipeline-refactor`
- Commit per step: one extraction per commit, ending with a cleanup commit
- Message example: `extract partition classification into classification.py`

## Steps

Each step follows the same pattern: create a new module, move functions there, update `pipeline.py` to import them, then verify.

### Step 1: Extract `_resolved_*_workers` into config.py

This step depends on plan 005 having landed (the `partition_count` parameter was removed).

Move these functions from `pipeline.py` to `config.py` as methods on `Settings`:

```python
# In src/payload2recovery/config.py, append to Settings:
    def resolved_extractor_workers(self) -> int:
        return self.extractor_workers if self.extractor_workers > 0 else max(1, os.cpu_count() or 4)

    def resolved_converter_workers(self) -> int:
        return self.converter_workers if self.converter_workers > 0 else max(1, os.cpu_count() or 4)

    def resolved_brotli_workers(self) -> int:
        return self.brotli_workers if self.brotli_workers > 0 else max(1, os.cpu_count() or 4)
```

Wait — `resolved_payload_threads()` already exists on `Settings` (line 24). The others (`resolved_extractor_workers`, `resolved_converter_workers`, `resolved_brotli_workers`) already exist too. The pipeline wrappers (`_resolved_extractor_workers`, `_resolved_converter_workers`, `_resolved_brotli_workers`) add the CLI-override layer on top.

So actually, DON'T move these to config.py — they belong in pipeline.py because they combine CLI options with Settings. The `Settings` methods are already there. Skip this step.

### Step 1 (revised): Create classification.py

Create `src/payload2recovery/classification.py`:

Move these functions from `pipeline.py` to the new module:
- `_classify_extracted_partitions`
- `_is_recovery_in_boot`
- `_is_default_raw_partition`
- `_is_explicit_raw_partition`
- `_list_partition_status`
- ALL the partition set constants: `_UNSUPPORTED_PARTITIONS` (after plan 003, this is `UNSUPPORTED_PARTITIONS` from models), `_ALWAYS_DEFAULT_RAW_PARTITIONS`, `_CONDITIONAL_DEFAULT_RAW_PARTITIONS`, `_EXPLICIT_RAW_PARTITIONS`, `_EXPLICIT_RAW_PREFIXES`, `_KNOWN_LOGICAL_PARTITIONS`, `_DEFAULT_RAW_PROBES`, `_RECOVERY_SKIP_PARTITIONS`

Imports needed in classification.py:
```python
from __future__ import annotations

from pathlib import Path

from payload2recovery.magiskboot import MagiskbootProbe
from payload2recovery.models import UNSUPPORTED_PARTITIONS
```

Move the `MagiskbootProbe` import and the `_is_recovery_in_boot` function:
```python
def is_recovery_in_boot(name: str, probes: dict[str, MagiskbootProbe]) -> bool:
    probe = probes.get(name)
    return bool(probe and probe.is_valid and probe.recovery_dtbo_size > 0)
```

Rename internal functions to remove the leading underscore (they're public in the new module):
- `_classify_extracted_partitions` → `classify_extracted_partitions`
- `_is_default_raw_partition` → `is_default_raw_partition`
- `_is_explicit_raw_partition` → `is_explicit_raw_partition`
- `_list_partition_status` → `partition_status`

Update all references inside the module to use the new names.

**Verify**:
- `uv run ruff check src/payload2recovery/classification.py` → exit 0

### Step 2: Update pipeline.py to use classification module

In `pipeline.py`:
- Remove the partition set constants (lines 49-63)
- Remove the functions moved to classification.py
- Add imports:
  ```python
  from payload2recovery.classification import (
      classify_extracted_partitions,
      is_default_raw_partition,
      is_explicit_raw_partition,
      is_recovery_in_boot,
      partition_status,
  )
  ```
- Update all call sites:
  - `_classify_extracted_partitions(...)` → `classify_extracted_partitions(...)`
  - `_is_default_raw_partition(...)` → `is_default_raw_partition(...)`
  - `_is_explicit_raw_partition(...)` → `is_explicit_raw_partition(...)`
  - `_is_recovery_in_boot(...)` → `is_recovery_in_boot(...)`
  - `_list_partition_status(...)` → `partition_status(...)`

**Verify**: `uv run pytest -v tests/test_pipeline.py -x` → all tests pass

### Step 3: Create metadata.py

Create `src/payload2recovery/metadata.py`:

Extract the build metadata dictionary construction from `pipeline.py:build()` (lines 282-333) into its own function:

```python
from __future__ import annotations

from payload2recovery.models import BuildOptions, BuildResult, PartitionArtifact, RawImageSpec


def build_metadata(
    options: BuildOptions,
    result: BuildResult,
    extractor_binary: Path,
    selected: list[Path],
    artifacts: list[PartitionArtifact],
    staged_raw_images: list[RawImageSpec],
    logical_partitions: set[str],
    default_raw_images: set[str],
    explicit_raw_images: set[str],
    unsupported_partitions: set[str],
    partition_metrics: list[dict],
    device_assertion_enabled: bool,
    device_assertion_names: list[str],
    device_assertion_source: str,
) -> dict[str, object]:
    return {
        "extractor": "payload-dumper-go",
        "extractor_binary": str(extractor_binary),
        # ... move the entire dict body here, replacing local refs with parameters
    }
```

The function takes all the variables that the dict references from `build()`'s scope, and returns the dict. Call it as:

```python
build_metadata = build_metadata(
    options=options,
    result=result,
    extractor_binary=extractor_binary,
    selected=selected,
    artifacts=artifacts,
    staged_raw_images=staged_raw_images,
    logical_partitions=logical_partitions,
    ...
)
```

Place the dict literal under the function body exactly as it appears in `build()`, with the variable substitutions noted.

**Verify**: `uv run ruff check src/payload2recovery/metadata.py` → exit 0

### Step 4: Update build() in pipeline.py

Replace the inline dict literal (lines 282-333) with a call to `build_metadata(...)`:

```python
result = BuildResult(
    output_path=final_output,
    stage_timings=metrics.stage_timings,
    build_metadata=build_metadata(
        options=options,
        extractor_binary=extractor_binary,
        selected=selected,
        artifacts=artifacts,
        staged_raw_images=staged_raw_images,
        logical_partitions=logical_partitions,
        default_raw_images=default_raw_images,
        explicit_raw_images=explicit_raw_images,
        unsupported_partitions=unsupported_partitions,
        partition_metrics=partition_metrics,
        device_assertion_enabled=device_assertion.enabled,
        device_assertion_names=device_assertion.device_names,
        device_assertion_source=device_assertion.source,
    ),
)
```

**Verify**:
- `uv run pytest -v tests/test_pipeline.py -x` → all tests pass (the build metadata tests check specific fields)
- `uv run pytest -v -x` → all tests pass

### Step 5: Final cleanup and verification

**Verify**:
- `uv run --group dev pytest -v` → all 27+ tests pass
- `uv run ruff check src/ tests/` → exit 0
- `uv run mypy src/payload2recovery/` → exit 0
- `git diff --stat` shows the expected files changed

## Test plan

Existing tests cover:
- `test_build_stages_default_and_explicit_raw_images` — exercises the full build pipeline with mocks, checks metadata
- `test_list_partitions_reports_supported_excluded_and_unsupported` — uses classification
- `test_partition_support_marks_raw_boot_artifacts_unsupported` — classification
- `test_classify_extracted_partitions_*` — classification unit tests

These tests already exercise the code being moved. No new tests needed — the refactor should preserve behavior exactly.

## Done criteria

ALL must hold:

- [ ] All functions moved to `classification.py` and `metadata.py` work identically (same outputs for same inputs)
- [ ] `grep -n "_classify_extracted_partitions\|_is_default_raw\|_is_explicit_raw\|_is_recovery_in_boot\|_list_partition_status\|_partition_support" src/payload2recovery/pipeline.py` → no matches for old private names
- [ ] `uv run --group dev pytest -v` exits 0, all tests pass
- [ ] `uv run ruff check src/ tests/` exits 0
- [ ] `uv run mypy src/payload2recovery/` exits 0
- [ ] No files outside the in-scope list are modified
- [ ] `plans/README.md` status row updated to DONE

## STOP conditions

Stop and report back (do not improvise) if:

- Any test fails — this is a logic-preserving move, so a failure means something was missed
- The drift check finds significant changes to pipeline.py since this plan was written
- You discover circular imports (the new modules should NOT import from pipeline.py)
- You need to change function behavior to make the extraction work — stop; this plan is about moving, not rewriting

## Maintenance notes

- The `classification.py` module is the authority on partition type logic. Any new partition types or classification rules go there.
- `metadata.py` owns the build result dictionary. If new metrics are added to builds, add them there.
- `pipeline.py` should remain as thin as possible — it orchestrates but does not contain business logic details.
- When reviewing a PR touching pipeline.py, check whether the change could live in a more specific module.
