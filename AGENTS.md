# Repository Guidelines

## Project Structure & Module Organization
`src/payload2recovery/` contains the application code. `cli.py` defines commands, `pipeline.py` orchestrates builds, `backends.py` wraps extraction and conversion helpers, and `packaging.py` writes recovery metadata and the final ZIP. Packaged runtime assets live under `src/payload2recovery/assets/`. Repo-local defaults live in `config/`, tests live in `tests/`, and the root `payload2recovery` script is a source-checkout shim.

## Build, Test, and Development Commands
Install with `./install.sh` or `uv tool install .`. Use `uv sync` for local development. Common checks:

```bash
uv run --group dev pytest
uv run payload2recovery doctor
uv run payload2recovery build ota.zip -p system vendor
```

`pytest` covers unit-level behavior, `doctor` validates host dependencies, and a real `build` run is the main smoke test.

## Coding Style & Naming Conventions
Use Python 3.11+ with 4-space indentation, type hints, dataclasses for structured data, and lowercase module filenames. Keep user-facing errors explicit and concise. Prefer clear names over abbreviations, and keep configuration keys under `[tool.payload2recovery]`. Default partition templates stay one-per-line in `config/default_partitions.txt`.

## Testing Guidelines
Add or update pytest coverage for CLI parsing, config loading, packaging, and pipeline behavior whenever logic changes. Before opening a PR, run `uv run --group dev pytest` and at least one end-to-end conversion against a known OTA ZIP. When partition selection changes, verify template mode, `-p`, and `--all`.

## Commit & Pull Request Guidelines
Recent history uses short imperative subjects (`refactor`, `enable compression`), but quality is inconsistent. Prefer clear, imperative commit messages under 72 characters, for example `fix group table size rounding`. Keep commits scoped to one change. PRs should include a concise summary, manual test commands/results, linked issues when relevant, and screenshots only if terminal output or generated packaging behavior needs visual proof.
