# Plan 005: Clean up misleading `partition_count` parameter in worker resolvers

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 58b33f3..HEAD -- src/payload2recovery/config.py src/payload2recovery/pipeline.py tests/`
> If any file changed, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: 002 (CLI tests) — the test file may reference these functions indirectly
- **Category**: correctness
- **Planned at**: commit `58b33f3`, 2026-07-11

## Why this matters

`Settings.resolved_converter_workers(partition_count)` and `Settings.resolved_brotli_workers(partition_count)` accept a `partition_count` parameter but ignore it — the function body starts with `_ = partition_count` (a no-op assignment). The pipeline wrappers `_resolved_converter_workers` and `_resolved_brotli_workers` do the same. This is misleading: the API suggests the worker count adapts to the number of partitions being processed, but in reality it always returns `cpu_count()`. Either implement the adaptive behavior, or remove the parameter.

This plan removes the parameter (the simpler, honest option). Adaptive worker allocation can be added properly later if profiling shows it matters.

## Current state

`src/payload2recovery/config.py:30-36`:
```python
def resolved_converter_workers(self, partition_count: int) -> int:
    _ = partition_count
    return self.converter_workers if self.converter_workers > 0 else max(1, os.cpu_count() or 4)

def resolved_brotli_workers(self, partition_count: int) -> int:
    _ = partition_count
    return self.brotli_workers if self.brotli_workers > 0 else max(1, os.cpu_count() or 4)
```

`src/payload2recovery/pipeline.py:748-765`:
```python
def _resolved_converter_workers(
    options: BuildOptions, settings: Settings, partition_count: int
) -> int:
    _ = partition_count
    if options.converter_workers > 0:
        return max(1, options.converter_workers)
    if options.workers > 0:
        return max(1, options.workers)
    return settings.resolved_converter_workers(partition_count)

def _resolved_brotli_workers(
    options: BuildOptions, settings: Settings, partition_count: int
) -> int:
    _ = partition_count
    if options.brotli_workers > 0:
        return max(1, options.brotli_workers)
    return settings.resolved_brotli_workers(partition_count)
```

Callers (in `pipeline.py:306-307, 309-310, 386-387, 389, 455`):
```python
_resolved_converter_workers(options, settings, len(selected))
_resolved_brotli_workers(options, settings, len(selected))
```

Note: `Settings.resolved_payload_threads()` (line 24) and `Settings.resolved_extractor_workers()` (line 27) do NOT take `partition_count` — they're already clean. Only the converter and brotli resolvers have the dead parameter.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install | `uv sync --group dev` | exit 0 |
| Run tests | `uv run --group dev pytest -v` | all pass |
| Lint | `uv run ruff check src/ tests/` | exit 0 |

## Scope

**In scope**:
- `src/payload2recovery/config.py` — remove `partition_count` parameter from `resolved_converter_workers` and `resolved_brotli_workers`
- `src/payload2recovery/pipeline.py` — remove `partition_count` parameter from `_resolved_converter_workers` and `_resolved_brotli_workers`, and update all callers to drop the argument
- `tests/test_config.py` — update the test that calls the resolved methods (line 37-39 currently passes `1` and `8` — change to no arguments)

**Out of scope**:
- Changing the actual worker-counting logic (leave it as-is)
- `Settings.resolved_payload_threads` and `Settings.resolved_extractor_workers` — already clean
- Any other module or file

## Git workflow

- Branch: `advisor/005-worker-count-cleanup`
- Commit message: `remove unused partition_count param from worker resolvers`
- Single commit

## Steps

### Step 1: Fix config.py

Remove `partition_count` from both method signatures:

```python
def resolved_converter_workers(self) -> int:
    return self.converter_workers if self.converter_workers > 0 else max(1, os.cpu_count() or 4)

def resolved_brotli_workers(self) -> int:
    return self.brotli_workers if self.brotli_workers > 0 else max(1, os.cpu_count() or 4)
```

Remove the `_ = partition_count` lines.

**Verify**: `uv run ruff check src/payload2recovery/config.py` → exit 0

### Step 2: Fix pipeline.py

Remove `partition_count` from `_resolved_converter_workers` and `_resolved_brotli_workers`:

```python
def _resolved_converter_workers(
    options: BuildOptions, settings: Settings
) -> int:
    if options.converter_workers > 0:
        return max(1, options.converter_workers)
    if options.workers > 0:
        return max(1, options.workers)
    return settings.resolved_converter_workers()

def _resolved_brotli_workers(
    options: BuildOptions, settings: Settings
) -> int:
    if options.brotli_workers > 0:
        return max(1, options.brotli_workers)
    return settings.resolved_brotli_workers()
```

Remove the `_ = partition_count` lines.

Update ALL callers to drop the `partition_count` argument:

1. **pipeline.py:306-307**: `_resolved_converter_workers(options, settings, len(selected))` → `_resolved_converter_workers(options, settings)`
2. **pipeline.py:309-310**: `_resolved_brotli_workers(options, settings, len(selected))` → `_resolved_brotli_workers(options, settings)`
3. **pipeline.py:386-387**: `_resolved_converter_workers(options, settings, len(selected))` → `_resolved_converter_workers(options, settings)`
4. **pipeline.py:388-389**: `_resolved_brotli_workers(options, settings, len(selected))` → `_resolved_brotli_workers(options, settings)`
5. **pipeline.py:455**: `_resolved_brotli_workers(options, settings, 1)` → `_resolved_brotli_workers(options, settings)`

Search with `grep -n "_resolved_converter_workers\|_resolved_brotli_workers" src/payload2recovery/pipeline.py` to confirm all callers are updated.

**Verify**:
- `grep -n "_resolved_converter_workers\|_resolved_brotli_workers" src/payload2recovery/pipeline.py` — no argument after `settings)` should have a second positional arg
- `uv run ruff check src/payload2recovery/pipeline.py` → exit 0

### Step 3: Fix test_config.py

In `tests/test_config.py:37-38`, update the calls:

```python
assert settings.resolved_converter_workers(1) == expected  # before
assert settings.resolved_converter_workers() == expected   # after
assert settings.resolved_brotli_workers(1) == expected      # before
assert settings.resolved_brotli_workers() == expected       # after
assert settings.resolved_brotli_workers(8) == expected      # before → remove this line
```

Remove the `(8)` variant — behavior is identical regardless of input now.

**Verify**: `uv run ruff check tests/test_config.py` → exit 0

### Step 4: Run full test suite

**Verify**:
- `uv run --group dev pytest -v` → all tests pass
- `uv run ruff check src/ tests/` → exit 0

## Test plan

Existing `test_default_runtime_uses_all_logical_cpus` in `test_config.py` will be updated in Step 3. No other test changes needed.

## Done criteria

ALL must hold:

- [ ] `config.py:resolved_converter_workers()` has no `partition_count` parameter
- [ ] `config.py:resolved_brotli_workers()` has no `partition_count` parameter
- [ ] `pipeline.py:_resolved_converter_workers()` has no `partition_count` parameter
- [ ] `pipeline.py:_resolved_brotli_workers()` has no `partition_count` parameter
- [ ] No `_ = partition_count` or `_ = workers` patterns remain in the worker resolver functions
- [ ] `uv run --group dev pytest` exits 0
- [ ] No files outside the in-scope list are modified
- [ ] `plans/README.md` status row updated to DONE

## STOP conditions

Stop and report back if:

- Any caller was missed — if a test fails with a TypeError about unexpected argument, that's a missed caller
- The function signature is used by something outside the in-scope files (e.g., a test file we didn't update)

## Maintenance notes

- If adaptive worker allocation is ever implemented, add the parameter back with a different name that reflects what it actually controls (e.g., `partition_count: int` with a docstring)
- The `_ = partition_count` pattern is a code smell in general; discourage it in review
