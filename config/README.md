# Configuration

## settings.toml

Control defaults for compression, concurrency, and output behavior:

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
group_table_size = 9126805504
output_name_max_len = 40
# payload_dumper_go_binary = "/usr/local/bin/payload-dumper-go"
```

Set worker counts to `0` to use all logical CPUs.

## default_partitions.txt

Template partition list (one per line):

```
odm_dlkm
product
system
system_ext
vendor
vendor_dlkm
```

Edit to customize default partitions.
