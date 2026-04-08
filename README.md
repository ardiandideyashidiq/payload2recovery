# payload2recovery

`payload2recovery` converts Android OTA `payload.bin` packages into custom-recovery flashable ZIPs for TWRP-style workflows on Linux.

It is not a general A/B OTA installer. It extracts payload partitions, converts the selected images into recovery-friendly transfer lists and `new.dat.br` files, then assembles a flashable package with dynamic partition metadata and device assertions.

## Install

```bash
uv tool install .
payload2recovery doctor
```

For local development:

```bash
uv sync
uv run payload2recovery doctor
```

## Usage

```bash
payload2recovery build ota.zip
payload2recovery build ota.zip -p system vendor product
payload2recovery build ota.zip --all
payload2recovery list-partitions ota.zip
payload2recovery inspect ota.zip
payload2recovery benchmark ota.zip --benchmark-report benchmark.json
```

The root `./payload2recovery` shim also works in a source checkout.

## Key Options

- `-p/--partitions`: explicit partition list; otherwise use the configured default template
- `--all`: include all extracted partitions supported by the current package generator
- `-b/--brotli-level`: brotli level `0-11`, default `5`
- `-z/--zip-level`: ZIP level `0-9`
- `--payload-dumper-go-binary`: override path for an external `payload-dumper-go`
- `--payload-threads`, `--extractor-workers`, `--converter-workers`, `--brotli-workers`: concurrency controls; `0` means all logical CPUs
- `--no-brotli`: skip Brotli compression
- `--keep-temp`: keep the workspace for debugging

## Configuration

Set repo-local defaults in `config/settings.toml`:

```toml
[tool.payload2recovery]
brotli_level = 5
zip_level = 6
payload_threads = 0
extractor_workers = 0
converter_workers = 0
brotli_workers = 0
compression = true
verbose = true
group_table = "main"
group_table_size = 9663676416
output_name_max_len = 40
# payload_dumper_go_binary = "/usr/local/bin/payload-dumper-go"
```

## Development

```bash
uv run --group dev pytest
uv run payload2recovery doctor
uv run payload2recovery --help
python3 -m payload2recovery --help
```
