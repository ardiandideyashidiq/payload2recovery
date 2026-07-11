# payload2recovery

Converts Android OTA ZIPs with `payload.bin` into custom-recovery flashable ZIPs.
Generates `dynamic_partitions_op_list`, `updater-script`, and final ZIP.

## Install

```bash
uv tool install .                          # from checkout
uv tool install git+https://github.com/ardiandideyashidiq/payload2recovery.git
payload2recovery doctor                    # verify host deps
```

## Development

```bash
uv sync --group dev
uv run --group dev pytest                  # 51 tests
uv run payload2recovery build ota.zip -p system vendor
```

## Usage

```bash
payload2recovery ota.zip                   # build with default partitions
p2r ota.zip                                # same thing, shorter
payload2recovery ota.zip -p system vendor product
payload2recovery ota.zip --all
payload2recovery ota.zip --raw-partitions vendor_boot vbmeta
payload2recovery list-partitions ota.zip
payload2recovery inspect ota.zip
payload2recovery benchmark ota.zip --benchmark-report benchmark.json
```

Place `banner` or `banner.txt` next to the OTA ZIP for custom `ui_print` lines.

## Configuration

`config/settings.toml` — defaults for compression, concurrency, output:
```toml
[tool.payload2recovery]
brotli_level = 5
zip_level = 6
# worker counts: 0 = all logical CPUs
extractor_workers = 0
converter_workers = 0
brotli_workers = 0
compression = true
group_table = "main"
group_table_size = 9663676416
```

`config/default_partitions.txt` — one partition name per line, used when no `-p` given.

## Requirements

Linux, Python 3.11+, `zip`, `unzip`, `xz`.

## Key Options

| Flag | What |
|------|------|
| `-p system vendor` | select specific partitions |
| `--all` | all supported partitions |
| `--raw-partitions vendor_boot` | opt in boot-side raw images |
| `--output-dir`, `--output-name` | output path control |
| `--work-dir`, `--keep-temp` | workspace control |
| `-b`, `-z`, `--no-brotli` | compression settings |
| `--payload-threads`, `--*-workers` | concurrency; `0` = all CPUs |

## Limitations

Linux only. `--all` means all partitions the generator supports, not every image in the OTA.
`logo` and `lk` are included by default; `boot`, `init_boot`, `vendor_boot`, `dtbo`, `recovery`, `vbmeta*` require `--raw-partitions`.

## Credits

- [payload-dumper-go](https://github.com/ssut/payload-dumper-go) — extraction backend
- AOSP OTA tooling (`blockimgdiff.py`, `common.py`, `rangelib.py`, `sparse_img.py`)
- xpirt/luxi78/howellzhu — `img2sdat.py`
- Python `brotli` — host-side compression
