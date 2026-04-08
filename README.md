# payload2recovery

`payload2recovery` converts Android OTA ZIP packages that contain `payload.bin` into custom-recovery flashable ZIPs.

It is built for a narrow recovery workflow on Linux. It extracts partitions from a payload-based OTA, converts selected images into `transfer.list` and `new.dat.br` artifacts, generates dynamic partition metadata, adds recovery installer scripts, and writes a final flashable ZIP.

This is not a stock OTA client and not a general A/B updater replacement. It is a repackaging tool for users who specifically want a recovery ZIP.

## Features

- Extract partitions from `payload.bin` using `payload-dumper-go`
- Select partitions from the default template, with `-p`, or with `--all`
- Generate `dynamic_partitions_op_list` and `updater-script`
- Compress `new.dat` payloads with Brotli
- Add best-effort device assertions from OTA metadata

## Requirements

- Linux
- Python 3.11+
- `zip`
- `unzip`
- `xz`

Run this after install:

```bash
payload2recovery doctor
```

## Install

From the current checkout:

```bash
uv tool install .
```

From a GitHub repository:

```bash
uv tool install git+https://github.com/<owner>/<repo>.git
```

Both installed commands are supported:

```bash
payload2recovery doctor
p2r doctor
```

For local development:

```bash
uv sync
uv run payload2recovery --help
uv run p2r --help
```

## Usage

Basic build:

```bash
payload2recovery ota.zip
```

Short alias:

```bash
p2r ota.zip
```

Other common examples:

```bash
payload2recovery build ota.zip -p system vendor product
payload2recovery build ota.zip --all
payload2recovery list-partitions ota.zip
payload2recovery inspect ota.zip
payload2recovery benchmark ota.zip --benchmark-report benchmark.json
```

Source checkouts also include these launchers:

```bash
./payload2recovery ota.zip
./p2r ota.zip
```

## Output and Workspace

Default final output:

- Output directory: `output/` next to the input OTA
- Output filename: `<ota_name>_recovery.zip`

Default temporary workspace:

- A system temp directory such as `/tmp/payload2recovery-xxxxxx`
- It is removed automatically unless you keep it

Custom paths:

```bash
payload2recovery ota.zip --output-dir ./dist
payload2recovery ota.zip --output-name rom_recovery.zip
payload2recovery ota.zip --work-dir ./work --keep-temp
```

## Important Options

- `-p, --partitions`: build only the named partitions
- `--all`: include all extracted partitions supported by the current package generator
- `--output-dir`: choose the final ZIP directory
- `--output-name`: choose the final ZIP filename
- `--work-dir`: use a fixed workspace instead of a temp directory
- `--keep-temp`: preserve the workspace after the run
- `--payload-dumper-go-binary`: override the bundled extractor
- `--payload-threads`, `--extractor-workers`, `--converter-workers`, `--brotli-workers`: worker counts; `0` means all logical CPUs
- `-b, --brotli-level`: Brotli level, default `5`
- `-z, --zip-level`: ZIP compression level
- `--no-brotli`: skip Brotli compression

## Configuration

Repo-local defaults can be set in `config/settings.toml`:

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
output_name_max_len = 60
# payload_dumper_go_binary = "/usr/local/bin/payload-dumper-go"
```

## Limitations

- Linux-only host workflow
- The generated package is still constrained by recovery support for dynamic partitions and block image update commands
- `--all` means all partitions supported by the current package generator, not literally every extracted image
- Raw-image partitions such as `boot`, `vendor_boot`, and `vbmeta*` are currently not repackaged by this flow

## Development

```bash
uv run --group dev pytest
uv run payload2recovery doctor
uv run payload2recovery build ota.zip -p system vendor
python3 -m payload2recovery --help
```

## Credits

This project depends on and bundles work from other projects.

- `payload-dumper-go`
  - Used as the payload extraction backend
  - Upstream: https://github.com/ssut/payload-dumper-go
- Android Open Source Project OTA tooling
  - Bundled Python components in `src/payload2recovery/assets/scripts/`
  - Includes `blockimgdiff.py`, `common.py`, `rangelib.py`, and `sparse_img.py`
  - Copyright: The Android Open Source Project
- `img2sdat.py`
  - Bundled conversion script by xpirt, luxi78, and howellzhu
- `img2simg.py`
  - Bundled sparse image helper used by the conversion pipeline
- Python `brotli`
  - Used for host-side Brotli compression
  - Package: https://pypi.org/project/Brotli/

