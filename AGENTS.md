# Repository Guidelines

## Project Structure & Module Organization

- `payloadforge` is the main Bash entrypoint; it sources modules from `lib/`.
- `lib/` contains Bash modules grouped by responsibility:
  - `core/` - Core functionality (config, partitions)
  - `conversion/` - OTA processing (dat, sparse, brotli, processor)
  - `generation/` - Output creation (op_list, updater_script, package)
  - `extraction/` - Input handling (ota)
  - `utils/` - Utilities (logging, validation)
- `scripts/` holds Python helpers for the conversion pipeline.
- `config/` stores user-editable defaults (`settings.conf`, `dynamic_partitions.conf`).
- `input/` is a staging area for OTA ZIPs; `output/` holds generated flashable ZIPs.
- `temp/` is used for intermediate build artifacts and is safe to delete.

## Build, Test, and Development Commands

### Installation & Setup
- `./install.sh` - Install runtime dependencies and create symlink
- Requires: `brotli`, `zip`, `unzip`, `python3`

### Running PayloadForge
- `payloadforge ota.zip` - Run full conversion with template partitions
- `payloadforge ota.zip -i` - Interactive mode for partition selection
- `payloadforge ota.zip -p "system vendor"` - Custom partitions
- `payloadforge ota.zip -b 11 -z 0` - Custom compression (brotli level 11, no ZIP compression)
- `payloadforge ota.zip -t 4` - Use 4 threads
- `payloadforge ota.zip -v` - Verbose output with DEBUG logs
- `payloadforge ota.zip --log-level INFO --log-context fileline` - Custom logging

### Validation Commands
- No formal test suite exists. Validate changes by:
  1. Running a known OTA file through `payloadforge`
  2. Verifying the generated ZIP in `output/` is flashable
  3. Checking that partition sizes and GROUP_TABLE_SIZE are calculated correctly

### Debugging & Development
- `payloadforge ota.zip -d` - Debug mode (equivalent to `--log-level DEBUG --log-context full`)
- Set `LOG_FILE=/tmp/payloadforge.log` to write logs to file
- Use `LOG_CONTEXT=func` or `LOG_CONTEXT=full` to trace function execution

## Coding Style & Guidelines

### Bash Scripts
- **Headers**: Start with `#!/bin/bash` and `set -euo pipefail`
- **Indentation**: 4 spaces (no tabs)
- **Functions**: Use `snake_case` naming
- **Constants**: Use `UPPER_SNAKE_CASE`
- **Logging**: Route all log output through `lib/utils/logging.sh` helpers:
  - `log_debug()`, `log_info()`, `log_success()`, `log_warn()`, `log_error()`
  - Use `log_emit_with_logger()` for custom logger names
- **Error Handling**: Use `trap 'log_error "Script failed at line $LINENO"; cleanup; exit 1' ERR`
- **Module Loading**: Source modules with error handling:
  ```bash
  source "$module" || {
      echo "ERROR: Failed to load $module"
      exit 1
  }
  ```
- **Variable Scoping**: Use `local` for function variables
- **Configuration**: Load via `getvalue()` helper from config files

### Python Scripts
- **Style**: Follow existing patterns in `scripts/common.py`
- **Compatibility**: Python 2/3 compatible using `from __future__ import print_function`
- **Error Handling**: Use try/except blocks with meaningful error messages
- **Imports**: Group imports: standard library, third-party, local modules
- **Functions**: Use `snake_case` for function names, `CamelCase` for classes
- **Documentation**: Add docstrings for complex functions

### File Organization
- **Module Headers**: Include brief description and purpose
- **Function Order**: Group related functions, maintain logical flow
- **Constants**: Define at top of files, use descriptive names
- **Helper Functions**: Keep utility functions focused and reusable

## Error Handling & Validation

### Input Validation
- Use `lib/utils/validation.sh` helpers for file checks
- Validate file existence, format, and size before processing
- Check for required dependencies early

### Resource Management
- Always cleanup temporary files using `cleanup()` function
- Use traps to ensure cleanup on script failure
- Handle insufficient disk space gracefully

### Logging Best Practices
- Use appropriate log levels: DEBUG for development, INFO for users, ERROR for failures
- Include context in error messages (file name, operation, expected vs actual)
- Use structured logging for complex operations
- Log important state changes and decisions

## Configuration Management

### Settings Format
- Use `KEY=VALUE` format in config files
- Support boolean values as `yes/no` or `true/false`
- Allow override via command line arguments
- Document all configuration options

### Dynamic Configuration
- Load user config via `load_user_config()`
- Respect CLI overrides vs config file defaults
- Validate configuration values (range checks, type validation)
- Provide sensible defaults for all options

## Performance & Optimization

### Threading
- Use `MAX_THREADS` for parallel processing
- Default to `nproc` (auto-detect) if not specified
- Balance CPU usage vs I/O bottlenecks

### Memory Management
- Process large files in chunks when possible
- Clean up temporary resources promptly
- Monitor memory usage during batch operations

## Security Considerations

### File Handling
- Validate file paths to prevent directory traversal
- Check file permissions before processing
- Never hardcode sensitive paths or credentials

### Input Sanitization
- Sanitize user input from CLI arguments
- Validate partition names against allowed patterns
- Escape shell variables properly when constructing commands

## Common Patterns

### Argument Parsing
Use the pattern from `payloadforge` main script:
```bash
while [ $# -gt 0 ]; do
    case "$1" in
        -f|--flag)
            FLAG="true"
            shift
            ;;
        --option)
            OPTION="$2"
            shift 2
            ;;
        *)
            # Handle positional arguments
            ;;
    esac
done
```

### Directory Setup
Use `init_environment()` pattern:
```bash
init_environment() {
    local lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    SCRIPT_DIR="$(dirname "$(dirname "$lib_dir")")"
    
    # Set up directory paths
    mkdir -p "$TEMP_DIR"/{partitions,output,config}
}
```

### Module Dependencies
Load modules in dependency order:
1. utils (logging, validation)
2. core (config, partitions)
3. extraction/conversion/generation (in logical workflow order)

## Troubleshooting

### Common Issues
- **Permission Denied**: Check file permissions and script executability
- **Missing Dependencies**: Run `./install.sh` to install required tools
- **Insufficient Space**: Ensure adequate space in `temp/` and `output/` directories
- **Invalid OTA**: Verify input file is a valid Android OTA package

### Debug Tips
- Use `-d` flag for maximum debug information
- Check `LOG_FILE` output for detailed trace
- Verify intermediate files in `temp/` directory before cleanup
- Test with small OTA files first when making changes
