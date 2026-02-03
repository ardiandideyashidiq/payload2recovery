# Repository Guidelines

## Project Structure & Module Organization

- `payloadforge` is the main Bash entrypoint; it sources modules from `lib/`.
- `lib/` contains Bash modules grouped by responsibility (`core/`, `conversion/`, `generation/`, `utils/`).
- `scripts/` holds Python helpers used by the conversion pipeline.
- `config/` stores user-editable defaults (for example `config/settings.conf`).
- `input/` is a staging area for OTA ZIPs; `output/` holds generated flashable ZIPs.
- `temp/` is used for intermediate build artifacts and is safe to delete.

## Build, Test, and Development Commands

- `./install.sh` installs runtime dependencies (brotli, zip, python3).
- `payloadforge ota.zip` runs the full conversion using template partitions.
- `payloadforge ota.zip -i` runs in interactive mode for partition selection.
- `payloadforge ota.zip -b 11 -z 0` customizes brotli and ZIP compression levels.

## Coding Style & Naming Conventions

- Bash scripts use `set -euo pipefail`; keep new scripts consistent.
- Indentation is 4 spaces in Bash and Python files.
- Bash functions use `snake_case`; constants/config use `UPPER_SNAKE_CASE`.
- Keep log output routed through `lib/utils/logging.sh` helpers.

## Testing Guidelines

- No formal test suite is included.
- Validate changes by running a known OTA through `payloadforge` and verifying
  the created ZIP in `output/`.
- If you touch Python helpers, add small, local sanity checks in the script
  you modified and remove any debug output before committing.

## Commit & Pull Request Guidelines

- Git history is minimal; no strict convention is enforced.
- Use concise, imperative subjects (for example `Add dynamic partition guard`).
- PRs should describe the OTA used for validation and attach any relevant logs
  or screenshots of the terminal output.

## Security & Configuration Tips

- Do not commit OTA images or generated ZIPs; use `input/` and `output/` locally.
- Keep secrets or device-specific settings in `config/` only.
