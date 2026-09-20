/*
 * Copyright (C) 2026 The Android Open Source Project / payload2recovery
 *
 * Minimal, zero-dependency C implementation to wipe/reset Android dynamic
 * partition metadata in 'super' partition.
 *
 * It reads LpMetadataGeometry from block 0 of the super partition,
 * resets the partition and extent tables to 0 entries, ensures default group
 * exists, recomputes SHA-256 checksums, and updates primary + backup metadata
 * across all slots.
 */

#define _LARGEFILE64_SOURCE
#define _GNU_SOURCE

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <inttypes.h>
#include <stdbool.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/types.h>
#include <sys/stat.h>

#if defined(__linux__)
#include <linux/fs.h>
#include <sys/ioctl.h>
#endif

#ifdef __ANDROID__
#include <sys/system_properties.h>
#endif

/* -------------------------------------------------------------------------
 * AOSP liblp definitions (metadata_format.h)
 * ------------------------------------------------------------------------- */
#define LP_METADATA_GEOMETRY_MAGIC 0x616c4467
#define LP_METADATA_GEOMETRY_SIZE 4096

#define LP_METADATA_HEADER_MAGIC 0x414C5030
#define LP_METADATA_MAJOR_VERSION 10
#define LP_METADATA_MINOR_VERSION_MIN 0
#define LP_METADATA_MINOR_VERSION_MAX 2
#define LP_METADATA_VERSION_FOR_EXPANDED_HEADER 2

#define LP_SECTOR_SIZE 512
#define LP_PARTITION_RESERVED_BYTES 4096

typedef struct LpMetadataGeometry {
    uint32_t magic;
    uint32_t struct_size;
    uint8_t checksum[32];
    uint32_t metadata_max_size;
    uint32_t metadata_slot_count;
    uint32_t logical_block_size;
} __attribute__((packed)) LpMetadataGeometry;

typedef struct LpMetadataTableDescriptor {
    uint32_t offset;
    uint32_t num_entries;
    uint32_t entry_size;
} __attribute__((packed)) LpMetadataTableDescriptor;

typedef struct LpMetadataHeader {
    uint32_t magic;
    uint16_t major_version;
    uint16_t minor_version;
    uint32_t header_size;
    uint8_t header_checksum[32];
    uint32_t tables_size;
    uint8_t tables_checksum[32];
    LpMetadataTableDescriptor partitions;
    LpMetadataTableDescriptor extents;
    LpMetadataTableDescriptor groups;
    LpMetadataTableDescriptor block_devices;
    uint32_t flags;
    uint8_t reserved[124];
} __attribute__((packed)) LpMetadataHeader;

typedef struct LpMetadataPartition {
    char name[36];
    uint32_t attributes;
    uint32_t first_extent_index;
    uint32_t num_extents;
    uint32_t group_index;
} __attribute__((packed)) LpMetadataPartition;

typedef struct LpMetadataExtent {
    uint64_t num_sectors;
    uint32_t target_type;
    uint64_t target_data;
    uint32_t target_source;
} __attribute__((packed)) LpMetadataExtent;

typedef struct LpMetadataPartitionGroup {
    char name[36];
    uint32_t flags;
    uint64_t maximum_size;
} __attribute__((packed)) LpMetadataPartitionGroup;

typedef struct LpMetadataBlockDevice {
    uint64_t first_logical_sector;
    uint32_t alignment;
    uint32_t alignment_offset;
    uint64_t size;
    char partition_name[36];
    uint32_t flags;
} __attribute__((packed)) LpMetadataBlockDevice;

/* -------------------------------------------------------------------------
 * Standalone SHA-256 implementation (Public Domain / MIT style)
 * ------------------------------------------------------------------------- */
typedef struct {
    uint32_t state[8];
    uint64_t count;
    uint8_t buffer[64];
} SHA256_CTX;

#define ROR(x, n) (((x) >> (n)) | ((x) << (32 - (n))))
#define Ch(x, y, z)  (((x) & (y)) ^ (~(x) & (z)))
#define Maj(x, y, z) (((x) & (y)) ^ ((x) & (z)) ^ ((y) & (z)))
#define S0(x) (ROR(x, 2) ^ ROR(x, 13) ^ ROR(x, 22))
#define S1(x) (ROR(x, 6) ^ ROR(x, 11) ^ ROR(x, 25))
#define s0(x) (ROR(x, 7) ^ ROR(x, 18) ^ ((x) >> 3))
#define s1(x) (ROR(x, 17) ^ ROR(x, 19) ^ ((x) >> 10))

static const uint32_t K256[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
};

static void sha256_init(SHA256_CTX *ctx) {
    ctx->state[0] = 0x6a09e667;
    ctx->state[1] = 0xbb67ae85;
    ctx->state[2] = 0x3c6ef372;
    ctx->state[3] = 0xa54ff53a;
    ctx->state[4] = 0x510e527f;
    ctx->state[5] = 0x9b05688c;
    ctx->state[6] = 0x1f83d9ab;
    ctx->state[7] = 0x5be0cd19;
    ctx->count = 0;
}

static void sha256_transform(SHA256_CTX *ctx, const uint8_t *data) {
    uint32_t a, b, c, d, e, f, g, h, t1, t2, m[64];
    for (int i = 0; i < 16; i++) {
        m[i] = ((uint32_t)data[i * 4] << 24) |
               ((uint32_t)data[i * 4 + 1] << 16) |
               ((uint32_t)data[i * 4 + 2] << 8) |
               ((uint32_t)data[i * 4 + 3]);
    }
    for (int i = 16; i < 64; i++) {
        m[i] = s1(m[i - 2]) + m[i - 7] + s0(m[i - 15]) + m[i - 16];
    }
    a = ctx->state[0]; b = ctx->state[1]; c = ctx->state[2]; d = ctx->state[3];
    e = ctx->state[4]; f = ctx->state[5]; g = ctx->state[6]; h = ctx->state[7];

    for (int i = 0; i < 64; i++) {
        t1 = h + S1(e) + Ch(e, f, g) + K256[i] + m[i];
        t2 = S0(a) + Maj(a, b, c);
        h = g; g = f; f = e; e = d + t1;
        d = c; c = b; b = a; a = t1 + t2;
    }
    ctx->state[0] += a; ctx->state[1] += b; ctx->state[2] += c; ctx->state[3] += d;
    ctx->state[4] += e; ctx->state[5] += f; ctx->state[6] += g; ctx->state[7] += h;
}

static void sha256_update(SHA256_CTX *ctx, const void *in, size_t len) {
    const uint8_t *data = (const uint8_t *)in;
    size_t buffer_idx = (size_t)(ctx->count & 63);
    ctx->count += len;
    while (len > 0) {
        size_t to_copy = 64 - buffer_idx;
        if (len < to_copy) to_copy = len;
        memcpy(ctx->buffer + buffer_idx, data, to_copy);
        buffer_idx += to_copy;
        data += to_copy;
        len -= to_copy;
        if (buffer_idx == 64) {
            sha256_transform(ctx, ctx->buffer);
            buffer_idx = 0;
        }
    }
}

static void sha256_final(SHA256_CTX *ctx, uint8_t hash[32]) {
    size_t pad_len = (size_t)(ctx->count & 63);
    ctx->buffer[pad_len++] = 0x80;
    if (pad_len > 56) {
        memset(ctx->buffer + pad_len, 0, 64 - pad_len);
        sha256_transform(ctx, ctx->buffer);
        pad_len = 0;
    }
    memset(ctx->buffer + pad_len, 0, 56 - pad_len);
    uint64_t bits = ctx->count * 8;
    for (int i = 7; i >= 0; i--) {
        ctx->buffer[56 + (7 - i)] = (uint8_t)(bits >> (i * 8));
    }
    sha256_transform(ctx, ctx->buffer);
    for (int i = 0; i < 8; i++) {
        hash[i * 4]     = (uint8_t)(ctx->state[i] >> 24);
        hash[i * 4 + 1] = (uint8_t)(ctx->state[i] >> 16);
        hash[i * 4 + 2] = (uint8_t)(ctx->state[i] >> 8);
        hash[i * 4 + 3] = (uint8_t)(ctx->state[i]);
    }
}

static void compute_sha256(const void *data, size_t len, uint8_t out[32]) {
    SHA256_CTX ctx;
    sha256_init(&ctx);
    sha256_update(&ctx, data, len);
    sha256_final(&ctx, out);
}

/* -------------------------------------------------------------------------
 * Super device path candidates
 * ------------------------------------------------------------------------- */
static const char *kSuperCandidates[] = {
    "/dev/block/by-name/super",
    "/dev/block/bootdevice/by-name/super",
    "/dev/block/platform/bootdevice/by-name/super",
    "/dev/block/mapper/super",
    NULL
};

static const char *detect_super_device(void) {
    for (int i = 0; kSuperCandidates[i] != NULL; i++) {
        if (access(kSuperCandidates[i], F_OK) == 0) {
            return kSuperCandidates[i];
        }
    }
    return NULL;
}

/* -------------------------------------------------------------------------
 * Slot detection
 * ------------------------------------------------------------------------- */
static char *detect_slot_from_cmdline(void) {
    FILE *f = fopen("/proc/cmdline", "r");
    if (!f) return NULL;
    char buf[4096];
    if (!fgets(buf, sizeof(buf), f)) {
        fclose(f);
        return NULL;
    }
    fclose(f);

    char *tok = strtok(buf, " \t\r\n");
    while (tok) {
        if (strncmp(tok, "androidboot.slot_suffix=", 24) == 0) {
            return strdup(tok + 24);
        }
        if (strncmp(tok, "androidboot.slot=", 17) == 0) {
            char *s = tok + 17;
            char *ret = malloc(4);
            if (ret) snprintf(ret, 4, "_%s", s);
            return ret;
        }
        tok = strtok(NULL, " \t\r\n");
    }
    return NULL;
}

static char *detect_slot_from_bootconfig(void) {
    FILE *f = fopen("/proc/bootconfig", "r");
    if (!f) return NULL;
    char line[256];
    char *slot = NULL;
    while (fgets(line, sizeof(line), f)) {
        char *eq = strchr(line, '=');
        if (!eq) continue;
        *eq = '\0';
        char *val = eq + 1;
        while (*val == ' ' || *val == '"') val++;
        char *end = val + strlen(val) - 1;
        while (end >= val && (*end == ' ' || *end == '"' || *end == '\n' || *end == '\r')) {
            *end = '\0';
            end--;
        }
        if (strcmp(line, "androidboot.slot_suffix") == 0) {
            slot = strdup(val);
            break;
        }
        if (strcmp(line, "androidboot.slot") == 0) {
            slot = malloc(4);
            if (slot) snprintf(slot, 4, "_%s", val);
            break;
        }
    }
    fclose(f);
    return slot;
}

static char *detect_slot(const char *arg_slot) {
    if (arg_slot && strlen(arg_slot) > 0) {
        if (arg_slot[0] == '_') return strdup(arg_slot);
        char *s = malloc(4);
        if (s) snprintf(s, 4, "_%s", arg_slot);
        return s;
    }

#ifdef __ANDROID__
    char prop[PROP_VALUE_MAX] = {0};
    if (__system_property_get("ro.boot.slot_suffix", prop) > 0 && strlen(prop) > 0) {
        return strdup(prop);
    }
    if (__system_property_get("ro.boot.slot", prop) > 0 && strlen(prop) > 0) {
        char *s = malloc(4);
        if (s) snprintf(s, 4, "_%s", prop);
        return s;
    }
#endif

    char *slot = detect_slot_from_bootconfig();
    if (slot) return slot;

    slot = detect_slot_from_cmdline();
    if (slot) return slot;

    return NULL;
}

/* -------------------------------------------------------------------------
 * Block device helpers
 * ------------------------------------------------------------------------- */
static bool read_fully(int fd, void *buf, size_t size) {
    uint8_t *p = (uint8_t *)buf;
    size_t remaining = size;
    while (remaining > 0) {
        ssize_t n = read(fd, p, remaining);
        if (n < 0) {
            if (errno == EINTR) continue;
            return false;
        }
        if (n == 0) return false;
        p += n;
        remaining -= n;
    }
    return true;
}

static bool write_fully(int fd, const void *buf, size_t size) {
    const uint8_t *p = (const uint8_t *)buf;
    size_t remaining = size;
    while (remaining > 0) {
        ssize_t n = write(fd, p, remaining);
        if (n < 0) {
            if (errno == EINTR) continue;
            return false;
        }
        p += n;
        remaining -= n;
    }
    return true;
}

static int64_t get_primary_geometry_offset(void) {
    return LP_PARTITION_RESERVED_BYTES;
}

static int64_t get_backup_geometry_offset(void) {
    return LP_PARTITION_RESERVED_BYTES + LP_METADATA_GEOMETRY_SIZE;
}

static int64_t get_primary_metadata_offset(const LpMetadataGeometry *geom, uint32_t slot) {
    return LP_PARTITION_RESERVED_BYTES + (LP_METADATA_GEOMETRY_SIZE * 2) +
           (int64_t)geom->metadata_max_size * slot;
}

static int64_t get_backup_metadata_offset(const LpMetadataGeometry *geom, uint32_t slot) {
    int64_t start = LP_PARTITION_RESERVED_BYTES + (LP_METADATA_GEOMETRY_SIZE * 2) +
                    (int64_t)geom->metadata_max_size * geom->metadata_slot_count;
    return start + (int64_t)geom->metadata_max_size * slot;
}

static bool parse_geometry(const uint8_t *buffer, LpMetadataGeometry *geom) {
    memcpy(geom, buffer, sizeof(*geom));
    if (geom->magic != LP_METADATA_GEOMETRY_MAGIC) {
        return false;
    }
    if (geom->struct_size > sizeof(LpMetadataGeometry)) {
        return false;
    }
    LpMetadataGeometry temp = *geom;
    memset(temp.checksum, 0, sizeof(temp.checksum));
    uint8_t check[32];
    compute_sha256(&temp, temp.struct_size, check);
    if (memcmp(check, geom->checksum, 32) != 0) {
        return false;
    }
    if (geom->metadata_slot_count == 0 || geom->metadata_max_size % LP_SECTOR_SIZE != 0) {
        return false;
    }
    return true;
}

static bool read_geometry(int fd, LpMetadataGeometry *geom) {
    uint8_t buf[LP_METADATA_GEOMETRY_SIZE];
    // On physical partitions / block devices, geometry is at 4096 (primary) and 8192 (backup)
    if (lseek(fd, get_primary_geometry_offset(), SEEK_SET) >= 0) {
        if (read_fully(fd, buf, sizeof(buf)) && parse_geometry(buf, geom)) {
            return true;
        }
    }
    if (lseek(fd, get_backup_geometry_offset(), SEEK_SET) >= 0) {
        if (read_fully(fd, buf, sizeof(buf)) && parse_geometry(buf, geom)) {
            return true;
        }
    }
    // On standalone super_empty.img files, geometry is at offset 0
    if (lseek(fd, 0, SEEK_SET) >= 0) {
        if (read_fully(fd, buf, sizeof(buf)) && parse_geometry(buf, geom)) {
            return true;
        }
    }
    return false;
}

static bool read_existing_metadata_header_and_tables(int fd, const LpMetadataGeometry *geom,
                                                    LpMetadataHeader *hdr,
                                                    LpMetadataBlockDevice *blk_dev,
                                                    bool *has_blk_dev) {
    *has_blk_dev = false;
    for (uint32_t slot = 0; slot < geom->metadata_slot_count; slot++) {
        int64_t off = get_primary_metadata_offset(geom, slot);
        if (lseek(fd, off, SEEK_SET) < 0) continue;
        memset(hdr, 0, sizeof(*hdr));
        if (!read_fully(fd, hdr, 128)) continue;
        if (hdr->magic != LP_METADATA_HEADER_MAGIC) continue;
        if (hdr->header_size > 128 && hdr->header_size <= sizeof(*hdr)) {
            if (!read_fully(fd, ((uint8_t *)hdr) + 128, hdr->header_size - 128)) continue;
        }

        // Valid header magic found; try to read block device table if present
        if (hdr->block_devices.num_entries >= 1 &&
            hdr->block_devices.entry_size >= sizeof(LpMetadataBlockDevice)) {
            int64_t table_off = off + hdr->header_size + hdr->block_devices.offset;
            if (lseek(fd, table_off, SEEK_SET) >= 0) {
                if (read_fully(fd, blk_dev, sizeof(*blk_dev))) {
                    if (blk_dev->size > 0 && blk_dev->first_logical_sector > 0) {
                        *has_blk_dev = true;
                        return true;
                    }
                }
            }
        }
    }
    return false;
}

/* -------------------------------------------------------------------------
 * Main wiping / resetting logic (standalone synthesis)
 * ------------------------------------------------------------------------- */
static int wipe_super(const char *super_path, const char *slot_suffix, bool dry_run) {
    printf("[wipe-super] Target device: %s\n", super_path);
    if (slot_suffix) {
        printf("[wipe-super] Active slot suffix: %s\n", slot_suffix);
    } else {
        printf("[wipe-super] Active slot suffix: (none / non-AB)\n");
    }

    int flags = dry_run ? O_RDONLY : (O_RDWR | O_SYNC);
    int fd = open(super_path, flags);
    if (fd < 0) {
        fprintf(stderr, "[wipe-super] Failed to open %s: %s\n", super_path, strerror(errno));
        return 1;
    }

#if defined(__linux__)
    // On Linux block devices, clear read-only flag if writing
    if (!dry_run) {
        int ro = 0;
        ioctl(fd, BLKROSET, &ro);
    }
#endif

    LpMetadataGeometry geom;
    if (!read_geometry(fd, &geom)) {
        fprintf(stderr, "[wipe-super] Failed to read valid LpMetadataGeometry from %s\n", super_path);
        close(fd);
        return 1;
    }

    printf("[wipe-super] Found geometry: max_size=%u, slot_count=%u, block_size=%u\n",
           geom.metadata_max_size, geom.metadata_slot_count, geom.logical_block_size);

    // Read existing header to preserve block_devices table if present
    LpMetadataHeader existing_hdr;
    LpMetadataBlockDevice blk_dev;
    bool has_blk_dev = false;
    read_existing_metadata_header_and_tables(fd, &geom, &existing_hdr, &blk_dev, &has_blk_dev);

    if (!has_blk_dev) {
        printf("[wipe-super] No existing valid block_devices table found. Synthesizing default super device...\n");
        memset(&blk_dev, 0, sizeof(blk_dev));
        uint64_t total_reserved = LP_PARTITION_RESERVED_BYTES +
                                  (LP_METADATA_GEOMETRY_SIZE + (uint64_t)geom.metadata_max_size * geom.metadata_slot_count) * 2;
        uint32_t align = geom.logical_block_size ? geom.logical_block_size : 1048576;
        uint64_t first_sec = (total_reserved + align - 1) / align * (align / LP_SECTOR_SIZE);
        blk_dev.first_logical_sector = first_sec;
        blk_dev.alignment = align;
        blk_dev.alignment_offset = 0;
        strncpy(blk_dev.partition_name, "super", sizeof(blk_dev.partition_name) - 1);

        // Determine super size via ioctl or stat
        uint64_t dev_size = 0;
#if defined(__linux__)
        ioctl(fd, BLKGETSIZE64, &dev_size);
#endif
        if (dev_size == 0) {
            struct stat st;
            if (fstat(fd, &st) == 0 && st.st_size > 0) {
                dev_size = (uint64_t)st.st_size;
            }
        }
        blk_dev.size = dev_size;
    }

    printf("[wipe-super] Super block device: name=%s, first_sector=%" PRIu64 ", size=%" PRIu64 "\n",
           blk_dev.partition_name, blk_dev.first_logical_sector, blk_dev.size);

    // Prepare clean metadata
    LpMetadataPartitionGroup default_group;
    memset(&default_group, 0, sizeof(default_group));
    strncpy(default_group.name, "default", sizeof(default_group.name) - 1);
    default_group.maximum_size = 0;

    size_t tables_size = sizeof(default_group) + sizeof(blk_dev);
    uint8_t *tables = calloc(1, tables_size);
    if (!tables) {
        fprintf(stderr, "[wipe-super] Out of memory allocating tables\n");
        close(fd);
        return 1;
    }

    memcpy(tables, &default_group, sizeof(default_group));
    memcpy(tables + sizeof(default_group), &blk_dev, sizeof(blk_dev));

    LpMetadataHeader hdr;
    memset(&hdr, 0, sizeof(hdr));
    hdr.magic = LP_METADATA_HEADER_MAGIC;
    hdr.major_version = LP_METADATA_MAJOR_VERSION;
    hdr.minor_version = LP_METADATA_MINOR_VERSION_MAX;
    hdr.header_size = sizeof(hdr);
    hdr.tables_size = (uint32_t)tables_size;

    hdr.partitions.offset = 0;
    hdr.partitions.num_entries = 0;
    hdr.partitions.entry_size = sizeof(LpMetadataPartition);

    hdr.extents.offset = 0;
    hdr.extents.num_entries = 0;
    hdr.extents.entry_size = sizeof(LpMetadataExtent);

    hdr.groups.offset = 0;
    hdr.groups.num_entries = 1;
    hdr.groups.entry_size = sizeof(LpMetadataPartitionGroup);

    hdr.block_devices.offset = sizeof(default_group);
    hdr.block_devices.num_entries = 1;
    hdr.block_devices.entry_size = sizeof(LpMetadataBlockDevice);

    compute_sha256(tables, tables_size, hdr.tables_checksum);
    memset(hdr.header_checksum, 0, sizeof(hdr.header_checksum));
    compute_sha256(&hdr, hdr.header_size, hdr.header_checksum);

    size_t total_blob_size = sizeof(hdr) + tables_size;
    uint8_t *blob = malloc(total_blob_size);
    if (!blob) {
        fprintf(stderr, "[wipe-super] Out of memory allocating blob\n");
        free(tables);
        close(fd);
        return 1;
    }
    memcpy(blob, &hdr, sizeof(hdr));
    memcpy(blob + sizeof(hdr), tables, tables_size);
    free(tables);

    if (total_blob_size > geom.metadata_max_size) {
        fprintf(stderr, "[wipe-super] Error: serialized metadata (%zu) > metadata_max_size (%u)\n",
                total_blob_size, geom.metadata_max_size);
        free(blob);
        close(fd);
        return 1;
    }

    if (dry_run) {
        printf("[wipe-super] DRY-RUN: Verified valid geometry and synthesized clean metadata (%zu bytes).\n", total_blob_size);
        free(blob);
        close(fd);
        return 0;
    }

    for (uint32_t slot = 0; slot < geom.metadata_slot_count; slot++) {
        int64_t p_off = get_primary_metadata_offset(&geom, slot);
        int64_t b_off = get_backup_metadata_offset(&geom, slot);

        printf("[wipe-super] Writing slot %u primary at offset %" PRId64 "...\n", slot, p_off);
        if (lseek(fd, p_off, SEEK_SET) < 0 || !write_fully(fd, blob, total_blob_size)) {
            fprintf(stderr, "[wipe-super] Failed to write primary metadata slot %u: %s\n", slot, strerror(errno));
            free(blob);
            close(fd);
            return 1;
        }

        printf("[wipe-super] Writing slot %u backup at offset %" PRId64 "...\n", slot, b_off);
        if (lseek(fd, b_off, SEEK_SET) < 0 || !write_fully(fd, blob, total_blob_size)) {
            fprintf(stderr, "[wipe-super] Failed to write backup metadata slot %u: %s\n", slot, strerror(errno));
            free(blob);
            close(fd);
            return 1;
        }
    }

    free(blob);
    fsync(fd);
    close(fd);

    printf("[wipe-super] Successfully wiped dynamic partition metadata across all %u slots!\n",
           geom.metadata_slot_count);
    return 0;
}

/* -------------------------------------------------------------------------
 * Flashing super_empty.img template onto target super device
 * ------------------------------------------------------------------------- */
static int flash_super_empty(const char *template_path, const char *target_device, bool dry_run) {
    printf("[wipe-super] Source template image: %s\n", template_path);
    printf("[wipe-super] Target super device:   %s\n", target_device);

    int src_fd = open(template_path, O_RDONLY);
    if (src_fd < 0) {
        fprintf(stderr, "[wipe-super] Failed to open template %s: %s\n", template_path, strerror(errno));
        return 1;
    }

    uint8_t geom_buf[LP_METADATA_GEOMETRY_SIZE];
    if (!read_fully(src_fd, geom_buf, sizeof(geom_buf))) {
        fprintf(stderr, "[wipe-super] Failed to read geometry from template %s\n", template_path);
        close(src_fd);
        return 1;
    }

    LpMetadataGeometry geom;
    if (!parse_geometry(geom_buf, &geom)) {
        fprintf(stderr, "[wipe-super] Invalid geometry in template %s\n", template_path);
        close(src_fd);
        return 1;
    }

    printf("[wipe-super] Template geometry: max_size=%u, slot_count=%u, block_size=%u\n",
           geom.metadata_max_size, geom.metadata_slot_count, geom.logical_block_size);

    // Read header at 4096 in template
    if (lseek(src_fd, LP_METADATA_GEOMETRY_SIZE, SEEK_SET) < 0) {
        fprintf(stderr, "[wipe-super] Failed to seek to metadata header in template\n");
        close(src_fd);
        return 1;
    }

    LpMetadataHeader hdr;
    memset(&hdr, 0, sizeof(hdr));
    if (!read_fully(src_fd, &hdr, 128)) {
        fprintf(stderr, "[wipe-super] Failed to read metadata header in template\n");
        close(src_fd);
        return 1;
    }

    if (hdr.magic != LP_METADATA_HEADER_MAGIC) {
        fprintf(stderr, "[wipe-super] Invalid metadata header magic 0x%08x in template\n", hdr.magic);
        close(src_fd);
        return 1;
    }

    if (hdr.header_size > 128) {
        size_t extra = hdr.header_size - 128;
        if (extra > sizeof(hdr) - 128) {
            fprintf(stderr, "[wipe-super] Header size too large (%u)\n", hdr.header_size);
            close(src_fd);
            return 1;
        }
        if (!read_fully(src_fd, ((uint8_t *)&hdr) + 128, extra)) {
            fprintf(stderr, "[wipe-super] Failed to read expanded header in template\n");
            close(src_fd);
            return 1;
        }
    }

    // Read tables
    uint8_t *tables = malloc(hdr.tables_size);
    if (!tables) {
        fprintf(stderr, "[wipe-super] Out of memory allocating %u bytes for tables\n", hdr.tables_size);
        close(src_fd);
        return 1;
    }

    if (!read_fully(src_fd, tables, hdr.tables_size)) {
        fprintf(stderr, "[wipe-super] Failed to read tables from template\n");
        free(tables);
        close(src_fd);
        return 1;
    }
    close(src_fd);

    // Verify table checksum
    uint8_t chk[32];
    compute_sha256(tables, hdr.tables_size, chk);
    if (memcmp(chk, hdr.tables_checksum, 32) != 0) {
        fprintf(stderr, "[wipe-super] Tables checksum mismatch in template image\n");
        free(tables);
        return 1;
    }

    // Open target device
    int flags = dry_run ? O_RDONLY : (O_RDWR | O_SYNC);
    int dst_fd = open(target_device, flags);
    if (dst_fd < 0) {
        fprintf(stderr, "[wipe-super] Failed to open target %s: %s\n", target_device, strerror(errno));
        free(tables);
        return 1;
    }

#if defined(__linux__)
    if (!dry_run) {
        int ro = 0;
        ioctl(dst_fd, BLKROSET, &ro);
    }
#endif

    uint64_t dev_size = 0;
#if defined(__linux__)
    ioctl(dst_fd, BLKGETSIZE64, &dev_size);
#endif
    if (dev_size == 0) {
        struct stat st;
        if (fstat(dst_fd, &st) == 0 && st.st_size > 0) {
            dev_size = (uint64_t)st.st_size;
        }
    }

    // Update super block device entry in tables if target device size is detected
    if (dev_size > 0 && hdr.block_devices.num_entries >= 1 &&
        hdr.block_devices.entry_size >= sizeof(LpMetadataBlockDevice)) {
        for (uint32_t i = 0; i < hdr.block_devices.num_entries; i++) {
            LpMetadataBlockDevice *bd = (LpMetadataBlockDevice *)(tables + hdr.block_devices.offset + i * hdr.block_devices.entry_size);
            if (strcmp(bd->partition_name, "super") == 0 || hdr.block_devices.num_entries == 1) {
                if (bd->size != dev_size) {
                    printf("[wipe-super] Updating block device '%s' size: %" PRIu64 " -> target %" PRIu64 "\n",
                           bd->partition_name, bd->size, dev_size);
                    bd->size = dev_size;
                    // Recompute tables checksum
                    compute_sha256(tables, hdr.tables_size, hdr.tables_checksum);
                    // Recompute header checksum
                    memset(hdr.header_checksum, 0, sizeof(hdr.header_checksum));
                    compute_sha256(&hdr, hdr.header_size, hdr.header_checksum);
                }
                break;
            }
        }
    }

    size_t total_blob_size = hdr.header_size + hdr.tables_size;
    uint8_t *blob = malloc(total_blob_size);
    if (!blob) {
        fprintf(stderr, "[wipe-super] Out of memory allocating blob\n");
        free(tables);
        close(dst_fd);
        return 1;
    }
    memcpy(blob, &hdr, hdr.header_size);
    memcpy(blob + hdr.header_size, tables, hdr.tables_size);
    free(tables);

    if (total_blob_size > geom.metadata_max_size) {
        fprintf(stderr, "[wipe-super] Error: serialized metadata (%zu) > metadata_max_size (%u)\n",
                total_blob_size, geom.metadata_max_size);
        free(blob);
        close(dst_fd);
        return 1;
    }

    if (dry_run) {
        printf("[wipe-super] DRY-RUN: Verified template and target device successfully (%zu bytes blob).\n",
               total_blob_size);
        free(blob);
        close(dst_fd);
        return 0;
    }

    // FlashPartitionTable:
    // 1. Zero initial LP_PARTITION_RESERVED_BYTES (4096 bytes)
    uint8_t zeroes[LP_PARTITION_RESERVED_BYTES] = {0};
    lseek(dst_fd, 0, SEEK_SET);
    write_fully(dst_fd, zeroes, sizeof(zeroes));

    // 2. Write primary geometry (offset 4096) and backup geometry (offset 8192)
    lseek(dst_fd, get_primary_geometry_offset(), SEEK_SET);
    write_fully(dst_fd, geom_buf, sizeof(geom_buf));
    lseek(dst_fd, get_backup_geometry_offset(), SEEK_SET);
    write_fully(dst_fd, geom_buf, sizeof(geom_buf));

    // 3. Write metadata across all slots (primary + backup)
    for (uint32_t slot = 0; slot < geom.metadata_slot_count; slot++) {
        int64_t p_off = get_primary_metadata_offset(&geom, slot);
        int64_t b_off = get_backup_metadata_offset(&geom, slot);

        printf("[wipe-super] Writing slot %u primary at offset %" PRId64 "...\n", slot, p_off);
        if (lseek(dst_fd, p_off, SEEK_SET) < 0 || !write_fully(dst_fd, blob, total_blob_size)) {
            fprintf(stderr, "[wipe-super] Failed to write primary metadata slot %u: %s\n", slot, strerror(errno));
            free(blob);
            close(dst_fd);
            return 1;
        }

        printf("[wipe-super] Writing slot %u backup at offset %" PRId64 "...\n", slot, b_off);
        if (lseek(dst_fd, b_off, SEEK_SET) < 0 || !write_fully(dst_fd, blob, total_blob_size)) {
            fprintf(stderr, "[wipe-super] Failed to write backup metadata slot %u: %s\n", slot, strerror(errno));
            free(blob);
            close(dst_fd);
            return 1;
        }
    }

    free(blob);
    fsync(dst_fd);
    close(dst_fd);

    printf("[wipe-super] Successfully flashed super_empty template onto %s across all %u slots!\n",
           target_device, geom.metadata_slot_count);
    return 0;
}

int main(int argc, char **argv) {
    const char *template_path = NULL;
    const char *target_device = NULL;
    const char *slot_arg = NULL;
    bool dry_run = false;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "--help") == 0) {
            printf("Usage: %s [OPTIONS] [TEMPLATE_IMAGE_OR_DEVICE]\n", argv[0]);
            printf("Reset/wipe logical partition metadata in Android super partition.\n\n");
            printf("Options:\n");
            printf("  -d, --device <dev>    Target super device (e.g. /dev/block/by-name/super)\n");
            printf("  -s, --slot <slot>     Target slot (a, b, _a, _b)\n");
            printf("  -n, --dry-run         Validate without writing\n");
            printf("  -h, --help            Show this help message\n");
            return 0;
        } else if ((strcmp(argv[i], "-s") == 0 || strcmp(argv[i], "--slot") == 0) && i + 1 < argc) {
            slot_arg = argv[++i];
        } else if ((strcmp(argv[i], "-d") == 0 || strcmp(argv[i], "--device") == 0) && i + 1 < argc) {
            target_device = argv[++i];
        } else if (strcmp(argv[i], "-n") == 0 || strcmp(argv[i], "--dry-run") == 0) {
            dry_run = true;
        } else if (argv[i][0] != '-') {
            // Positional argument: either template image (.img or regular file) or target device
            size_t len = strlen(argv[i]);
            struct stat st;
            if (stat(argv[i], &st) == 0 && S_ISREG(st.st_mode)) {
                // If it ends in .img or contains geometry at offset 0, it's a template image
                if ((len > 4 && strcmp(argv[i] + len - 4, ".img") == 0) || !target_device) {
                    int test_fd = open(argv[i], O_RDONLY);
                    bool is_geom_at_0 = false;
                    if (test_fd >= 0) {
                        uint8_t gbuf[LP_METADATA_GEOMETRY_SIZE];
                        if (read_fully(test_fd, gbuf, sizeof(gbuf))) {
                            LpMetadataGeometry g;
                            is_geom_at_0 = parse_geometry(gbuf, &g);
                        }
                        close(test_fd);
                    }
                    if (is_geom_at_0) {
                        template_path = argv[i];
                    } else if (!target_device) {
                        target_device = argv[i];
                    }
                } else {
                    target_device = argv[i];
                }
            } else {
                target_device = argv[i];
            }
        }
    }

    if (!target_device) {
        target_device = detect_super_device();
    }

    if (!target_device) {
        fprintf(stderr, "[wipe-super] Error: Could not locate super partition. Specify path via -d or as argument.\n");
        return 1;
    }

    if (template_path) {
        return flash_super_empty(template_path, target_device, dry_run);
    }

    char *detected_slot = detect_slot(slot_arg);
    int rc = wipe_super(target_device, detected_slot, dry_run);
    if (detected_slot) free(detected_slot);
    return rc;
}
