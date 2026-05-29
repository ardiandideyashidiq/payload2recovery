# payload2recovery

This repo ships two related tools:

- `payload2recovery`: converts an Android OTA ZIP that contains `payload.bin` into a custom-recovery flashable ZIP
- `port2recovery`: converts a directory of extracted port ROM images into the same kind of recovery ZIP

Both tools target a narrow Linux recovery workflow. They generate `dynamic_partitions_op_list`, `updater-script`, and a final flashable ZIP instead of acting like a stock OTA client or seamless A/B updater.

## Install

From the current checkout:

```bash
uv tool install .
```

From a GitHub repository:

```bash
uv tool install git+https://github.com/ardiandideyashidiq/payload2recovery.git
```

Both installed commands are supported:

```bash
payload2recovery doctor
p2r doctor
port2recovery doctor
pt2r doctor
```

For local development:

```bash
uv sync
uv run payload2recovery --help
uv run p2r --help
uv run port2recovery --help
uv run pt2r --help
```

## Features

- Extract partitions from `payload.bin` using `payload-dumper-go`
- Select partitions from the default template, with `-p`, or with `--all`
- Generate `dynamic_partitions_op_list` and `updater-script`
- Compress `new.dat` payloads with Brotli
- Add best-effort device assertions from OTA metadata
- Bundle `avbctl` and disable AVB verity/verification during install
- Flash raw images such as `logo`, `lk`, and other opt-in boot-side partitions
- Read optional `banner` / `banner.txt` files and render them through `ui_print(...)`

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

## payload2recovery Usage

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
payload2recovery build ota.zip -p system vendor --raw-partitions vendor_boot vbmeta
payload2recovery list-partitions ota.zip
payload2recovery inspect ota.zip
payload2recovery benchmark ota.zip --benchmark-report benchmark.json
```

Source checkouts also include these launchers:

```bash
./payload2recovery ota.zip
./p2r ota.zip
```

Banner support:

- Place `banner` or `banner.txt` next to the input OTA ZIP
- `banner` is preferred when both files exist
- Each line is emitted into the generated `updater-script`

Example:

```text
releases/
├── banner
└── ota_build.zip
```

Example `banner` file:

```text
HyperOS Port

Android 14
Flash at your own risk
```

## port2recovery Usage

Basic build:

```bash
port2recovery ./hyperos
```

Short alias:

```bash
pt2r ./hyperos
```

Other common examples:

```bash
port2recovery build ./hyperos -p system vendor product
port2recovery build ./hyperos --all
port2recovery inspect ./hyperos
port2recovery list-partitions ./hyperos
port2recovery benchmark ./hyperos --benchmark-report benchmark.json
```

### Input Folder Structure

Minimal autodetect flow:

```text
hyperos/
├── banner
├── system.img
├── vendor.img
├── product.img
├── system_ext.img
├── vendor_dlkm.img
├── logo.bin
└── lk.img
```

In this mode, `port2recovery` auto-detects common raw files such as `logo.bin`, `lk.img`, `vendor_boot.img`, `vbmeta.img`, `vbmeta_system.img`, and `vbmeta_vendor.img` when they exist in the input root.

Manifest-driven flow:

```text
hyperos/
├── banner.txt
├── port2recovery.toml
├── system.img
├── vendor.img
├── product.img
├── system_ext.img
├── vendor_dlkm.img
├── odm_dlkm.img
├── logo.bin
├── lk.img
├── vendor_boot.img
├── vbmeta.img
├── vbmeta_system.img
└── vbmeta_vendor.img
```

Example `port2recovery.toml`:

```toml
[device]
assert_devices = ["P13001L-GL"]

[dynamic_partitions]
group_table = "main"

[[raw_images]]
file = "logo.bin"
target = "/dev/block/by-name/logo"
slot_policy = "none"

[[raw_images]]
file = "lk.img"
target = "/dev/block/by-name/lk"
slot_policy = "active"

[[raw_images]]
file = "vendor_boot.img"
target = "/dev/block/by-name/vendor_boot"
slot_policy = "active"

[[raw_images]]
file = "vbmeta.img"
target = "/dev/block/by-name/vbmeta"
slot_policy = "active"
```

Notes:

- `banner` and `banner.txt` are read from the ROM directory root
- blank lines in the banner are preserved
- source `META-INF` content is ignored; the tool generates fresh installer metadata
- if `raw_images` is present in `port2recovery.toml`, autodetect is skipped and the manifest fully controls raw-image inclusion

## Output and Workspace

Default final output:

- Output directory: `output/` next to the input OTA
- Output filename: `<ota_name>-recovery.zip`

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
- `--raw-partitions`: for `payload2recovery`, opt in excluded-by-default raw partitions such as `vendor_boot` or `vbmeta`
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
# payload_dumper_go_binary = "/usr/local/bin/payload-dumper-go"
```

`port2recovery` can also use repo-local defaults from `config/port2recovery.toml`:

```toml
[tool.port2recovery]
brotli_level = 5
zip_level = 6
converter_workers = 0
brotli_workers = 0
compression = true
verbose = true
group_table = "main"
# group_table_size = 9663676416
```

## Limitations

- Linux-only host workflow
- The generated package is still constrained by recovery support for dynamic partitions and block image update commands
- `--all` means all partitions supported by the current package generator, not literally every extracted image
- `payload2recovery` includes `logo` and `lk` raw images by default when extracted, but keeps `boot`, `init_boot`, `vendor_boot`, `dtbo`, `recovery`, and `vbmeta*` excluded unless you opt in with `--raw-partitions`
- `port2recovery` logical partition conversion still applies only to partitions supported by the current dynamic-partition/block-image packaging flow

## Development

```bash
uv run --group dev pytest
uv run payload2recovery doctor
uv run payload2recovery build ota.zip -p system vendor
uv run port2recovery build ./hyperos -p system vendor
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
