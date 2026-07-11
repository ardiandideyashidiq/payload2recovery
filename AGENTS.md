# Repository Guidelines

## Project Structure & Module Organization

`src/payload2recovery/` contains the application code:
- `cli.py` — argparse entrypoint (`main()`), arg normalization, `BuildOptions` construction
- `pipeline.py` — build orchestration (extract, classify, convert, stage, package)
- `classification.py` — partition classification (`classify_extracted_partitions`, type constants)
- `backends.py` — subprocess wrappers, Brotli compression, image conversion (img2simg, img2sdat)
- `packaging.py` — `updater-script`/`dynamic_partitions_op_list` generation, ZIP assembly
- `metadata.py` — `build_metadata()` dict factory for benchmark/build reports
- `models.py` — dataclasses (`BuildOptions`, `PartitionArtifact`, `BuildMode(StrEnum)`, etc.)
- `config.py` — `Settings` dataclass, TOML loading, default partition list
- `resources.py` — `ResourceManager` for bundled assets (extractor, magiskboot, avbctl, scripts)
- `magiskboot.py` — `MagiskbootProbe` dataclass, `probe_image()` for recovery-dtbo detection
- `progress.py` — `LiveProgress` (Rich-based interactve + plain text fallback)
- `metrics.py` — `MetricsCollector` for stage-level timers
- `errors.py` — `Payload2RecoveryError`, `ValidationError`, `UnsupportedLayoutError`

Packaged runtime assets: `src/payload2recovery/assets/` (`bin/` for bundled binaries, `scripts/` for vendored AOSP conversion scripts, `config/default_partitions.txt`).

Tests: `tests/` — `test_pipeline.py`, `test_packaging.py`, `test_config.py`, `test_progress.py`, `test_cli.py`.

`config/settings.toml` — runtime defaults (`[tool.payload2recovery]`). `config/default_partitions.txt` — template partition list (one per line).

Root `payload2recovery` and `p2r` are source-checkout shims (set `PYTHONPATH` and `python3 -m payload2recovery`).

## Build, Test, and Lint Commands

```bash
uv sync --group dev              # install everything including dev
uv run --group dev pytest        # all tests (51 total)
uv run --group dev pytest -v -k "banner"   # filter by test name
uv run ruff check src/ tests/    # lint
uv run mypy src/payload2recovery/   # typecheck (note: 17 pre-existing errors)
uv run ruff format --check src/ tests/  # format check
uv run pre-commit run --all-files  # full pre-commit suite
```

Pre-commit runs `ruff check --fix`, `ruff-format`, and `mypy` on commit.
There is no `ruff --fix` auto-fix for all the selected rule sets — some items (ARG001, SIM103, N801) require manual edits.

## Coding & Testing Conventions

- Python 3.11+, 4-space indent, type hints, `dataclass(slots=True)` for structured data
- `BuildMode(StrEnum)` for mode comparisons (use `is` not `==`: `options.mode is BuildMode.MANUAL`)
- Worker-count resolver methods (`resolved_converter_workers`, `resolved_brotli_workers`) take no arguments — they always return `cpu_count()` or the configured override
- Partition unsupported set lives in `models.UNSUPPORTED_PARTITIONS` (frozenset) — import from there, do not redefine
- Bundled AOSP scripts under `assets/scripts/` are excluded from ruff/mypy — do not reformat them
- `_run()` helper in `backends.py` always captures stderr (even when not verbose) and includes it in error messages
- `_escape_edify_string()` in `packaging.py` escapes `\`, `"`, `\n`, `\r`, null bytes — newlines become spaces
- Error hierarchy: `Payload2RecoveryError` (base), `ValidationError`, `UnsupportedLayoutError`
- `human_size()` is pure Python (no `du` subprocess)
- When adding new CLI arguments, add corresponding tests in `test_cli.py`
- Default partitions list: `config/default_partitions.txt` (one name per line, no blank lines)
- Verification order before commits: `ruff check -> mypy -> pytest` (but note mypy has pre-existing errors)
