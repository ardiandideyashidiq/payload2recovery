# Plan 009: Fix incomplete banner string escaping

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 58b33f3..HEAD -- src/payload2recovery/packaging.py tests/test_packaging.py`
> If either file has changed since this plan was written, treat it as a
> STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `58b33f3`, 2026-07-11

## Why this matters

The `_escape_edify_string` function only escapes backslashes (`\`) and double-quotes (`"`). It does NOT escape newlines, semicolons, parentheses, or other Edify-sensitive characters. A banner file containing `");\nassert(something);\nui_print("` would inject arbitrary Edify commands into the generated `updater-script`. While the banner file is user-provided (local file next to the OTA), the principle of least astonishment says that a banner containing special characters should display literally, not alter the script's control flow.

## Current state

`src/payload2recovery/packaging.py:199-200`:
```python
def _escape_edify_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
```

Called at line 194:
```python
lines.append(f'ui_print("{_escape_edify_string(display_line)}");')
```

This means:
- A line containing `");` would close the `ui_print` string and inject a new statement
- A line with `\n` (actual newline, not the literal `\n`) would break the script
- Parentheses, semicolons, `#` (comments in Edify) are all unescaped

The fix is to also escape Edify-significant characters. Unlike shell escaping which is complex, Edify strings inside `ui_print()` just need to be well-formed string literals. The safe approach is to escape `\`, `"`, newlines, and optionally semicolons/parentheses. The simplest correct fix: replace newlines with spaces and escape the characters that would break the Edify string context.

However, the banner file is supposed to display as text. The most robust approach is to:
1. Replace literal newlines in the value with `" "` string concatenation (since Edify doesn't support multiline string literals), OR
2. Reject banner lines that contain control characters

Option 1 is the least surprising (the text displays). Option 2 is safer but might frustrate users.

This plan implements a balanced approach: escape `\`, `"`, and strip/replace non-printable characters. Newlines in a single banner line are rare and can be handled by collapsing them.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install | `uv sync --group dev` | exit 0 |
| Run tests | `uv run --group dev pytest -v -k "banner"` | all banner tests pass |
| Run all tests | `uv run --group dev pytest` | all pass |
| Lint | `uv run ruff check src/ tests/` | exit 0 |

## Scope

**In scope**:
- `src/payload2recovery/packaging.py` — fix `_escape_edify_string`
- `tests/test_packaging.py` — add a test for the escaping fix

**Out of scope**:
- The `write_updater_script` function signature or behavior
- Any other file
- The `discover_banner_lines` function (it reads the file correctly)

## Git workflow

- Branch: `advisor/009-banner-escaping`
- Commit message: `fix incomplete banner string escaping for Edify script`
- Single commit

## Steps

### Step 1: Fix `_escape_edify_string`

Replace the function body in `src/payload2recovery/packaging.py`:

```python
def _escape_edify_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", " ").replace("\r", " ")
    escaped = escaped.replace("\0", "")
    return escaped
```

Changes:
1. Escape `\` and `"` (existing behavior, preserved)
2. Replace newlines (`\n`) and carriage returns (`\r`) with spaces — these would break the Edify string literal
3. Strip null bytes — they're dangerous in any context

This is NOT a full Edify injection prevention (e.g., a banner containing `${...}` could still be an issue depending on the recovery's Edify implementation), but it prevents trivial script breakage from embedded newlines and quotes.

**Verify**: `uv run ruff check src/payload2recovery/packaging.py` → exit 0

### Step 2: Add escaping test

In `tests/test_packaging.py`, add a new test after the existing banner test:

```python
def test_escape_edify_string_handles_special_characters(tmp_path: Path) -> None:
    artifact = PartitionArtifact(
        name="system",
        image_path=tmp_path / "system.img",
        image_size=1234,
        transfer_list=tmp_path / "system.transfer.list",
        new_dat_br=tmp_path / "system.new.dat.br",
        patch_dat=tmp_path / "system.patch.dat",
    )
    updater_script = tmp_path / "updater-script"
    write_updater_script(
        updater_script,
        [artifact],
        banner_lines=[
            'normal line',
            'quote " and backslash \\',
            'line with );',           # Edify statement terminator
            "line with\nnewline",     # embedded newline
            "line with\r\nCRLF",
        ],
    )
    content = updater_script.read_text()
    # The banner should be rendered as ui_print calls
    assert 'ui_print("normal line");' in content
    assert 'ui_print("quote \\" and backslash \\\\");' in content
    assert 'ui_print("line with );");' in content  # parentheses and semicolon preserved literally
    assert 'ui_print("line with newline");' in content  # \n replaced with space
    assert 'ui_print("line with CRLF");' in content  # \r\n replaced with spaces
    # No broken statements
    assert ");\nassert(" not in content  # no injected commands
```

**Verify**: `uv run pytest -v -k "escape_edify" tests/test_packaging.py -x` → passes

### Step 3: Verify existing banner tests still pass

**Verify**:
- `uv run pytest -v -k "banner" tests/test_packaging.py` → all banner-related tests pass
- `uv run --group dev pytest -v` → all tests pass

## Test plan

Existing `test_write_updater_script_with_banner_lines` tests normal escaping (quotes and backslashes) and `test_discover_banner_lines_prefers_banner_over_banner_txt` tests file discovery. The new test in Step 2 covers the injection edge cases.

## Done criteria

ALL must hold:

- [ ] `_escape_edify_string` replaces `\n` and `\r` with spaces
- [ ] `_escape_edify_string` strips null bytes
- [ ] Existing banner escaping (quotes, backslashes) still works
- [ ] New test `test_escape_edify_string_handles_special_characters` exists and passes
- [ ] `uv run --group dev pytest` exits 0
- [ ] `uv run ruff check src/ tests/` exits 0
- [ ] No files outside the in-scope list are modified
- [ ] `plans/README.md` status row updated to DONE

## STOP conditions

Stop and report back if:

- The `_escape_edify_string` function has been renamed or moved since this plan was written
- A test fails because the escaping behavior changes
- You discover that Edify treats `$` or `${}` specially inside string literals (if so, add `$` escaping too)

## Maintenance notes

- If Edify's string escaping rules are ever fully understood, consider replacing this ad-hoc escaping with a proper Edify string builder
- The `write_updater_script` function uses `_escape_edify_string` ONLY for banner lines. The partition names and device assertions are not escaped through this function — they come from known-safe sources (partition image filenames and OTA metadata). If those sources become user-controllable, they need their own escaping.
