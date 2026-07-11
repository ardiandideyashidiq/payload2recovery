# Plan 001: Add ruff, mypy, and pre-commit tooling

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 58b33f3..HEAD -- pyproject.toml src/ tests/`
> If any file listed has changed since this plan was written, treat it as a
> STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `58b33f3`, 2026-07-11

## Why this matters

The project has zero linting, zero typechecking, and no pre-commit hooks. This means every PR reviewer spends time on formatting nits that machines should catch, and type errors that mypy or pyright would surface immediately get shipped. Adding these tools now makes every subsequent plan cheaper and safer because ruff and mypy catch regressions automatically. The dev dependencies are cheap — `ruff`, `mypy`, and `pre-commit` are standard Python tooling.

## Current state

- `pyproject.toml` has no `[tool.ruff]` or `[tool.mypy]` sections
- Dev dependencies list only `pytest`
- No `.pre-commit-config.yaml`
- The project currently has no type-checking; some functions lack annotations (e.g. `cli.py:204` — `settings` parameter has no type)

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install dev deps | `uv sync --group dev` | exit 0 |
| Run ruff | `uv run ruff check src/ tests/` | exit 0, no errors |
| Run ruff formatter | `uv run ruff format --check src/ tests/` | exit 0 |
| Run mypy | `uv run mypy src/payload2recovery/` | exit 0 |
| Run pre-commit | `uv run pre-commit run --all-files` | exit 0 |
| Run tests | `uv run --group dev pytest` | 27 passed |
| Validate TOML | `uv run python3 -c "import tomllib; tomllib.loads(open('pyproject.toml').read())"` | exit 0 |

## Scope

**In scope** (the only files you should modify):
- `pyproject.toml` — add dev deps and tool configs
- `.pre-commit-config.yaml` — create
- `tests/` — fix any lint issues in existing tests
- `src/` — fix any lint/type issues (narrow scope: only trivial fixes like missing annotations, unused imports, etc.)

**Out of scope** (do NOT touch):
- Any functional change beyond what ruff/mypy requires
- The `assets/scripts/` directory (vendored AOSP code — not ours to reformat)
- `.gitignore` changes
- CI configuration (that's a future concern)

## Git workflow

- Branch: `advisor/001-ruff-mypy-precommit`
- Commit message style: imperative, short. Example: `add ruff, mypy, and pre-commit tooling`
- Single commit for config + auto-fixes; a second commit for manual type-annotation fixes

## Steps

### Step 1: Add dev dependencies

Edit `pyproject.toml` to add `ruff`, `mypy`, and `pre-commit` to the dev group, and add tool configuration sections for ruff and mypy.

```toml
# In [dependency-groups]
dev = [
  "pytest>=8.4",
  "ruff>=0.11",
  "mypy>=1.15",
  "pre-commit>=4.2",
]

# Add at the end of the file:
[tool.ruff]
target-version = "py311"
line-length = 120

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "SIM", "ARG"]

[tool.ruff.format]
quote-style = "double"

[tool.mypy]
python_version = "3.11"
strict = true
exclude = [
  "src/payload2recovery/assets/scripts/",
]
```

**Verify**:
- `uv sync --group dev` → exit 0
- `uv run ruff check src/ tests/` → may show errors (we'll fix in step 2)

### Step 2: Run ruff auto-fix and manual fixes

```bash
uv run ruff check --fix src/ tests/
uv run ruff check src/ tests/   # re-check
```

If any remaining errors cannot be auto-fixed, fix them by hand:
- Unused imports → remove them
- Unused function arguments prefixed with `_` → keep as is (ruff ruff/ARG handles this)
- Minor formatting → `uv run ruff format src/ tests/`

Do NOT change logic. If a lint fix would require understanding (e.g., a complex refactor), add `# noqa: <code>` with a brief comment and note it in the commit message instead.

**Verify**:
- `uv run ruff check src/ tests/` → exit 0, "All checks passed!"
- `uv run ruff format --check src/ tests/` → exit 0

### Step 3: Fix mypy errors

```bash
uv run mypy src/payload2recovery/
```

Fix all type errors. Common patterns in this repo:
- Add missing type annotations (e.g. `settings` parameter in `cli.py:_options_from_args`)
- The `_load_script_module` return type should be `types.ModuleType` or `Any`
- `dict[str, object]` values need casts or `assert isinstance()` when used with specific methods
- The `_select_partitions` internal helpers may need explicit return types

If a mypy error requires significant refactoring, you may use `# type: ignore[code]` with a brief inline comment explaining why, but prefer fixing the annotation.

**Verify**:
- `uv run mypy src/payload2recovery/` → exit 0, "Success: no issues found"

### Step 4: Create pre-commit config

Create `.pre-commit-config.yaml` in the repo root:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.11.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.15.0
    hooks:
      - id: mypy
        args: [src/payload2recovery/]
        pass_filenames: false
        additional_dependencies: []
```

**Verify**:
- `uv run pre-commit run --all-files` → exit 0

### Step 5: Run full test suite

**Verify**:
- `uv run --group dev pytest` → "27 passed" (or the same number as before, depending on any test tweaks from Step 2)
- `uv run ruff check src/ tests/` → exit 0
- `uv run mypy src/payload2recovery/` → exit 0

## Test plan

No new tests are needed — this plan adds tooling, not features. Existing tests must still pass. The presence of `ruff check` and `mypy` with zero errors IS the verification.

## Done criteria

ALL must hold:

- [ ] `uv run ruff check src/ tests/` exits 0
- [ ] `uv run ruff format --check src/ tests/` exits 0
- [ ] `uv run mypy src/payload2recovery/` exits 0
- [ ] `uv run pre-commit run --all-files` exits 0
- [ ] `uv run --group dev pytest` exits 0, 27+ tests pass
- [ ] `.pre-commit-config.yaml` exists at repo root
- [ ] `pyproject.toml` has `[tool.ruff]`, `[tool.mypy]` sections
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row updated to DONE

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations referenced in "Current state" doesn't match (codebase has drifted)
- A step's verification fails twice after a reasonable fix attempt
- A mypy error requires changing actual runtime behavior (not just annotations)
- ruff auto-fix changes logic in a way you don't understand

## Maintenance notes

- When adding new source files, ruff and mypy will check them automatically as long as they're under `src/`
- The `strict = true` mypy setting means new code needs full annotations — this is intentional
- When upgrading ruff or mypy versions, run `pre-commit autoupdate` to keep hook versions in sync
- The `assets/scripts/` vendored code is excluded from mypy because it's not ours to maintain
