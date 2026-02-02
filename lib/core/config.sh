#!/bin/bash
# PayloadForge - Configuration Management

# Default configuration
DEFAULT_PARTITIONS="odm_dlkm product system system_ext vendor vendor_dlkm"
DEFAULT_BROTLI_LEVEL=6
DEFAULT_ZIP_LEVEL=6

# Global variables
SCRIPT_DIR=""
BIN_DIR=""
SCRIPTS_DIR=""
CONFIG_DIR=""
TEMP_DIR=""
OUTPUT_DIR=""
INPUT_FILE=""
INPUT_FILE_NAME=""
SELECTED_PARTITIONS=""
GENERATED_ZIP_PATH=""
GROUP_TABLE=""
GROUP_TABLE_SIZE=""
MAX_THREADS=""
BROTLI_LEVEL=""
USE_COMPRESSION="true"
ZIP_COMPRESSION_LEVEL=""
VERBOSE="false"
OUTPUT_NAME_MAX_LEN="40"

init_environment() {
    # Get the main script directory (payloadforge2 location)
    local lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    SCRIPT_DIR="$(dirname "$(dirname "$lib_dir")")"
    
    BIN_DIR="$SCRIPT_DIR/bin"
    SCRIPTS_DIR="$SCRIPT_DIR/scripts"
    CONFIG_DIR="$SCRIPT_DIR/config"
    TEMP_DIR="$SCRIPT_DIR/temp"
    OUTPUT_DIR="$SCRIPT_DIR/output"
    
    mkdir -p "$TEMP_DIR"/{partitions,output,config}
    mkdir -p "$OUTPUT_DIR"
    
    # Don't set defaults here - let load_user_config handle it
}

getvalue() {
    grep "^$1=" "$2" 2>/dev/null | tail -n1 | cut -d= -f2
}

calculate_group_table_size() {
    local sizes_file="$TEMP_DIR/partition_sizes.txt"
    
    if [ ! -f "$sizes_file" ]; then
        log_warn "Partition sizes file not found, using default"
        return 1
    fi
    
    log_info "Calculating optimal GROUP_TABLE_SIZE from partition data..."
    
    # Sum all partition sizes
    local total_size=0
    while IFS='=' read -r partition size; do
        if [ -n "$size" ]; then
            total_size=$((total_size + size))
        fi
    done < "$sizes_file"
    
    if [ "$total_size" -eq 0 ]; then
        log_warn "Total partition size is 0, using default"
        return 1
    fi
    
    # No overhead - use exact size for precise allocation
    local calculated_size="$total_size"
    
    # Round up to nearest 1MB (1048576 bytes)
    local remainder=$((calculated_size % 1048576))
    if [ "$remainder" -ne 0 ]; then
        calculated_size=$((calculated_size + 1048576 - remainder))
    fi
    
    local total_mb=$((total_size / 1024 / 1024))
    local calculated_mb=$((calculated_size / 1024 / 1024))
    
    log_info "Total partition size: ${total_mb} MB"
    log_info "Calculated GROUP_TABLE_SIZE: ${calculated_mb} MB (exact size)"
    
    GROUP_TABLE_SIZE="$calculated_size"
    return 0
}

load_user_config() {
    local settings_conf="$CONFIG_DIR/settings.conf"
    local dp_conf="$CONFIG_DIR/dynamic_partitions.conf"
    
    if [ ! -f "$settings_conf" ]; then
        return 0
    fi
    
    log_info "Loading user configuration from settings.conf..."
    
    # Load settings
    local config_threads=$(getvalue "THREADS" "$settings_conf")
    local config_brotli=$(getvalue "BROTLI_LEVEL" "$settings_conf")
    local config_use_compression=$(getvalue "USE_COMPRESSION" "$settings_conf")
    local config_zip_level=$(getvalue "ZIP_COMPRESSION_LEVEL" "$settings_conf")
    local config_log_level=$(getvalue "LOG_LEVEL" "$settings_conf")
    local config_log_file=$(getvalue "LOG_FILE" "$settings_conf")
    local config_log_color=$(getvalue "LOG_COLOR" "$settings_conf")
    local config_log_time_format=$(getvalue "LOG_TIME_FORMAT" "$settings_conf")
    local config_log_context=$(getvalue "LOG_CONTEXT" "$settings_conf")
    local config_verbose=$(getvalue "VERBOSE" "$settings_conf")
    local config_output_name_max_len=$(getvalue "OUTPUT_NAME_MAX_LEN" "$settings_conf")
    
    # Apply thread settings if not overridden by CLI
    if [ -z "$MAX_THREADS" ] || [ "$MAX_THREADS" = "0" ]; then
        if [ -n "$config_threads" ] && [ "$config_threads" != "0" ]; then
            MAX_THREADS="$config_threads"
        else
            MAX_THREADS=$(nproc 2>/dev/null || echo 4)
        fi
    fi

    # Apply logging settings if not overridden by CLI
    if [ "${LOG_LEVEL_SOURCE-}" != "cli" ]; then
        if [ -n "$config_log_level" ]; then
            LOG_LEVEL="$config_log_level"
        fi
    fi

    if [ -n "$config_log_file" ]; then
        LOG_FILE="$config_log_file"
    fi

    if [ -n "$config_log_color" ]; then
        LOG_COLOR="$config_log_color"
    fi

    if [ -n "$config_log_time_format" ]; then
        LOG_TIME_FORMAT="$config_log_time_format"
    fi

    if [ "${LOG_CONTEXT_SOURCE-}" != "cli" ] && [ -n "$config_log_context" ]; then
        LOG_CONTEXT="$config_log_context"
        LOG_CONTEXT_SOURCE="config"
    fi

    if [ "${VERBOSE_SOURCE-}" != "cli" ] && [ -n "$config_verbose" ]; then
        case "${config_verbose,,}" in
            1|true|yes|y|on)
                VERBOSE="true"
                ;;
            0|false|no|n|off)
                VERBOSE="false"
                ;;
        esac
    fi

    if [ "$VERBOSE" = "true" ] && [ "${LOG_LEVEL_SOURCE-}" != "cli" ] && [ -z "$config_log_level" ]; then
        LOG_LEVEL="DEBUG"
    fi

    if command -v log_set_level >/dev/null 2>&1; then
        log_set_level "${LOG_LEVEL:-INFO}"
    fi

    if [ -n "$config_output_name_max_len" ]; then
        if [[ "$config_output_name_max_len" =~ ^[0-9]+$ ]] && [ "$config_output_name_max_len" -ge 8 ]; then
            OUTPUT_NAME_MAX_LEN="$config_output_name_max_len"
        else
            log_warn "Invalid OUTPUT_NAME_MAX_LEN in settings.conf (must be integer >= 8)"
        fi
    fi
    
    # Apply compression settings if not overridden by CLI
    if [ -z "$BROTLI_LEVEL" ]; then
        BROTLI_LEVEL="${config_brotli:-$DEFAULT_BROTLI_LEVEL}"
    fi
    
    if [ -z "$USE_COMPRESSION" ]; then
        USE_COMPRESSION="${config_use_compression:-yes}"
    fi
    
    if [ -z "$ZIP_COMPRESSION_LEVEL" ]; then
        ZIP_COMPRESSION_LEVEL="${config_zip_level:-$DEFAULT_ZIP_LEVEL}"
    fi
    
    # Convert "yes"/"no" to "true"/"false" for USE_COMPRESSION
    if [ "$USE_COMPRESSION" = "yes" ]; then
        USE_COMPRESSION="true"
    elif [ "$USE_COMPRESSION" = "no" ]; then
        USE_COMPRESSION="false"
    fi
    
    # Load dynamic partitions config if it exists
    if [ -f "$dp_conf" ]; then
        GROUP_TABLE=$(getvalue "GROUP_TABLE" "$dp_conf")
        GROUP_TABLE_SIZE=$(getvalue "GROUP_TABLE_SIZE" "$dp_conf")
    fi
}

cleanup() {
    if [ -d "$TEMP_DIR" ]; then
        log_info "Cleaning up temporary files..."
        rm -rf "$TEMP_DIR"
    fi
}
