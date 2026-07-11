# Plan 002: Test CLI argument parsing

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 58b33f3..HEAD -- src/payload2recovery/cli.py tests/`
> If any file listed has changed since this plan was written, treat it as a
> STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: 001 (tooling) — optional; can proceed without it but ruff/mypy will not be available to catch issues
- **Category**: test-coverage
- **Planned at**: commit `58b33f3`, 2026-07-11

## Why this matters

The CLI module (`cli.py`) is the entry point for every user interaction. `_normalize_argv`, `_options_from_args`, `_add_common_build_args`, and the parser construction have no test coverage. A regression in argument normalization — e.g., breaking `p2r ota.zip` (bare invocation → `build` subcommand) — silently breaks the whole tool. This plan adds unit tests that cover the parsing layer in isolation, without needing real OTA files or external binaries.

## Current state

- `cli.py:20-62` — `main()` orchestrates parsing, resource setup, and routing
- `cli.py:65-73` — `_normalize_argv()` turns `["ota.zip"]` into `["build", "ota.zip"]`
- `cli.py:76-105` — `_build_parser()` constructs argparse with 4 subcommands
- `cli.py:130-201` — `_add_common_build_args()` adds shared args including the mutually exclusive `--all`/`-p` group
- `cli.py:108-128` — `_add_build_output_args()` adds `--output-name`, `--keep-temp`, etc.
- `cli.py:204-229` — `_options_from_args()` maps argparse Namespace → `BuildOptions`
- The `cli` module has zero tests (`tests/test_cli.py` does not exist)
- Existing tests in `tests/test_pipeline.py` mock heavily but test pipeline logic, not parsing

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install | `uv sync --group dev` | exit 0 |
| Run tests | `uv run --group dev pytest -v tests/test_cli.py` | all pass |
| Run all tests | `uv run --group dev pytest` | 27+ tests pass |
| Lint | `uv run ruff check tests/test_cli.py` | exit 0 |
| Typecheck | `uv run mypy tests/test_cli.py` | exit 0 |

## Scope

**In scope** (the only files you should modify):
- `tests/test_cli.py` — create (new test file)

**Out of scope** (do NOT touch):
- `cli.py` — the code is not broken; we are only adding tests. Do NOT refactor `cli.py` even if you see improvements.
- `tests/test_pipeline.py` — not in scope
- Any other source file
- Resource files, config, or test data

## Git workflow

- Branch: `advisor/002-cli-tests`
- Commit message: `test CLI argument parsing`
- Single commit

## Steps

### Step 1: Create `tests/test_cli.py`

Create the file with these test functions. Model the test style on `tests/test_pipeline.py`'s simpler tests (use `tmp_path` for path arguments, plain asserts).

```python
from __future__ import annotations

from pathlib import Path

import pytest
from payload2recovery.cli import _build_parser, _normalize_argv, _options_from_args
from payload2recovery.config import Settings
```

Cover these cases:

#### `test_normalize_argv_bare_ota_zip`

`_normalize_argv(["ota.zip"])` → returns `["build", "ota.zip"]`
Also test with `["ota.zip", "-p", "system"]` → returns `["build", "ota.zip", "-p", "system"]`

#### `test_normalize_argv_passes_known_commands_unchanged`

For each known command (`"build"`, `"benchmark"`, `"inspect"`, `"list-partitions"`, `"doctor"`, `"-h"`, `"--help"`):
`_normalize_argv([cmd, ...])` → first element stays as `cmd`

#### `test_normalize_argv_empty`

`_normalize_argv([])` → returns `[]`
`_normalize_argv(None)` → should not crash (but note it reads `sys.argv` — use a partial mock or just test the None branch returns None)

For `_normalize_argv(None)`, it's hard to test deterministically since it reads `sys.argv[1:]`. Use `monkeypatch.setattr("sys.argv", ["prog", "ota.zip"])` then `assert _normalize_argv(None) == ["build", "ota.zip"]`.

#### `test_parser_build_arguments`

Use `_build_parser().parse_args(["build", "ota.zip"])` to verify:
- `args.command == "build"`
- `args.ota_zip == Path("ota.zip")`
- `args.partitions` is `None` (default, not provided)
- `args.brotli_level` is `None` (default, overrides from settings later)

#### `test_parser_mutually_exclusive_all_and_partitions`

`parse_args(["build", "ota.zip", "--all"])` → `args.all` is `True`
`parse_args(["build", "ota.zip", "-p", "system", "vendor"])` → `args.partitions == ["system", "vendor"]`
`parse_args(["build", "ota.zip", "--all", "-p", "system"])` → should raise `SystemExit` (argparse error)

Use `pytest.raises(SystemExit)` for the last case.

#### `test_parser_inspect`

`parse_args(["inspect", "ota.zip"])` → `args.command == "inspect"`

#### `test_parser_doctor`

`parse_args(["doctor"])` → `args.command == "doctor"`

#### `test_options_from_args_template_mode`

Factory method: create a `argparse.Namespace` with representative values (mode implied by `all=False, partitions=None`), call `_options_from_args(args, settings)` where `settings` is a `Settings()` with defaults, and assert `BuildOptions` fields are mapped correctly:
- `options.mode == "template"`
- `options.brotli_level` falls back to `settings.brotli_level`
- `options.zip_level` falls back to `settings.zip_level`

#### `test_options_from_args_manual_mode`

Set `args.partitions = ["system"]`, `args.all = False`, verify `options.mode == "manual"` and `options.custom_partitions == ["system"]`.

#### `test_options_from_args_all_mode`

Set `args.all = True`, verify `options.mode == "all"`.

#### `test_options_from_args_workers_alias`

Set `args.workers = 4`, `args.converter_workers = 0`, verify `options.converter_workers` is resolved to 4.

#### `test_options_from_args_group_table_size`

Set `args.group_table_size = 12345678`, verify `options.group_table_size == 12345678`.

#### `test_options_from_args_raw_partitions_default_empty`

Set `args.raw_partitions = []`, verify `options.raw_partitions == []` (not `None`).

**Verify**: `uv run --group dev pytest -v tests/test_cli.py -x` → all tests pass

### Step 2: Verify full suite and lint

**Verify**:
- `uv run --group dev pytest -v` → all tests pass (27 existing + new CLI tests)
- `uv run ruff check tests/test_cli.py` → exit 0
- `uv run mypy tests/test_cli.py` → exit 0

## Test plan

This plan IS the test plan — the new file `tests/test_cli.py` contains the tests. No other test changes needed.

## Done criteria

ALL must hold:

- [ ] `tests/test_cli.py` exists with >=10 test functions covering the cases in Step 1
- [ ] `uv run --group dev pytest -v` exits 0, including the new tests
- [ ] `uv run ruff check tests/test_cli.py` exits 0
- [ ] `uv run mypy tests/test_cli.py` exits 0
- [ ] No files outside `tests/test_cli.py` are modified (`git status`)
- [ ] `plans/README.md` status row updated to DONE

## STOP conditions

Stop and report back (do not improvise) if:

- The CLI module has been significantly refactored since this plan was written (drift check fails)
- A test reveals what looks like a real bug in `cli.py` — stop and report the evidence; a bug fix should be a separate plan
- `mypy` errors cannot be resolved with type annotations alone

## Maintenance notes

- When new CLI arguments are added, corresponding tests should be added to `test_cli.py`
- The `_normalize_argv(None)` test uses `monkeypatch` to control `sys.argv` — if the implementation of `_normalize_argv` changes, this test will need updating
- When the `BuildOptions` dataclass changes, update `test_options_from_args_*` tests to match
