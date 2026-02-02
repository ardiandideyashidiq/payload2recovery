#!/bin/bash
# PayloadForge - Flashable Package Creation

create_update_binary() {
    local meta_dir="$TEMP_DIR/output/META-INF/com/google/android"
    local binary_source="$BIN_DIR/update-binary"
    
    if [ ! -f "$binary_source" ]; then
        log_error "update-binary not found in $BIN_DIR"
        return 1
    fi
    
    cp "$binary_source" "$meta_dir/update-binary"
    chmod +x "$meta_dir/update-binary"
    
    return 0
}



package_flashable_zip() {
    local base_name=""
    local timestamp=$(date +%H%M)
    
    if [ -n "$INPUT_FILE_NAME" ]; then
        base_name=$(basename "$INPUT_FILE_NAME" .zip)
        base_name=$(basename "$base_name" .img)
        base_name=$(echo "$base_name" | sed 's/_ota$//' | sed 's/_OTA$//' | sed 's/^ota_//')
    else
        base_name="rom"
    fi
    
    local output_zip="$OUTPUT_DIR/${base_name}_${timestamp}.zip"

    GENERATED_ZIP_PATH="$output_zip"
    
    log_info "Creating flashable ZIP..."
    
    local meta_dir="$TEMP_DIR/output/META-INF/com/google/android"
    mkdir -p "$meta_dir"
    
    mv "$TEMP_DIR/output/updater-script" "$meta_dir/"
    create_update_binary || return 1
    
    cd "$TEMP_DIR/output" || return 1
    
    local zip_opts="-r -q"
    if [ "${VERBOSE:-false}" = "true" ]; then
        zip_opts="-r -v"
    fi
    if [ "$ZIP_COMPRESSION_LEVEL" = "0" ]; then
        zip_opts="-0 $zip_opts"
        log_info "Using store mode (no ZIP compression)..."
    else
        zip_opts="-${ZIP_COMPRESSION_LEVEL} $zip_opts"
        log_info "Using ZIP compression level $ZIP_COMPRESSION_LEVEL..."
    fi
    
    if ! zip $zip_opts "$output_zip" .; then
        log_error "Failed to create ZIP"
        return 1
    fi
    
    cd - > /dev/null
    
    log_success "Flashable ZIP created: $(basename "$output_zip")"
    log_info "Output size: $(du -h "$output_zip" | cut -f1)"
    
    return 0
}
