#!/bin/bash

###############################################################################
# PayloadForge - Installation Script
###############################################################################

set -e

INSTALL_DIR="$HOME/.local/share/payloadforge"
BIN_DIR="$HOME/.local/bin"

echo "╔════════════════════════════════════════╗"
echo "║      PayloadForge Installer v1.2      ║"
echo "╚════════════════════════════════════════╝"
echo ""

# Check dependencies
echo "[1/5] Checking dependencies..."
MISSING=()

command -v python3 >/dev/null 2>&1 || MISSING+=("python3")
command -v brotli >/dev/null 2>&1 || MISSING+=("brotli")
command -v zip >/dev/null 2>&1 || MISSING+=("zip")
command -v unzip >/dev/null 2>&1 || MISSING+=("unzip")

if [ ${#MISSING[@]} -ne 0 ]; then
    echo "❌ Missing dependencies: ${MISSING[*]}"
    echo ""
    echo "Please install them using your package manager:"
    echo ""
    echo "  Debian/Ubuntu:  sudo apt install ${MISSING[*]}"
    echo "  Arch Linux:     sudo pacman -S ${MISSING[*]}"
    echo "  Fedora/RHEL:    sudo dnf install ${MISSING[*]}"
    echo "  OpenSUSE:       sudo zypper install ${MISSING[*]}"
    echo ""
    exit 1
else
    echo "All dependencies found"
fi

# Create directories
echo "[2/5] Creating directories..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$BIN_DIR"
echo "Directories created"

# Copy files
echo "[3/5] Copying files..."
cp -r bin scripts lib config "$INSTALL_DIR/"
cp payloadforge "$INSTALL_DIR/"
cp README.md "$INSTALL_DIR/"

# Create directories in install location
mkdir -p "$INSTALL_DIR"/{input,output,temp}
echo "Files copied to $INSTALL_DIR"

# Create symlink
echo "[4/5] Creating symlink..."
ln -sf "$INSTALL_DIR/payloadforge" "$BIN_DIR/payloadforge"
echo "Symlink created at $BIN_DIR/payloadforge"

# Shell configuration functions
detect_shell() {
    # Primary method: Check SHELL environment variable
    if [ -n "$SHELL" ]; then
        echo "$(basename "$SHELL")"
        return 0
    fi
    
    # Fallback: Check current process
    if command -v ps >/dev/null 2>&1; then
        local current_shell=$(ps -hp $$ | awk '{print $5}' | xargs basename 2>/dev/null)
        if [ -n "$current_shell" ]; then
            echo "$current_shell"
            return 0
        fi
    fi
    
    # Ultimate fallback: Use bash
    echo "bash"
}

get_shell_config_file() {
    local shell="$1"
    local config_file=""
    
    case "$shell" in
        "bash")
            # Check macOS vs Linux for bash
            if [[ "$(uname)" == "Darwin" ]]; then
                config_file="$HOME/.bash_profile"
            else
                config_file="$HOME/.bashrc"
            fi
            ;;
        "zsh")
            config_file="$HOME/.zshrc"
            ;;
        "fish")
            config_file="$HOME/.config/fish/config.fish"
            ;;
        *)
            # Fallback to .bashrc as requested
            config_file="$HOME/.bashrc"
            ;;
    esac
    
    echo "$config_file"
}

add_path_safely() {
    local config_file="$1"
    local path_to_add="$2"
    
    # Check if PATH already contains the directory
    if [[ ":$PATH:" == *":$path_to_add:"* ]]; then
        echo "PATH already contains $path_to_add"
        return 0
    fi
    
    # Create config file directory if it doesn't exist
    local config_dir
    config_dir=$(dirname "$config_file")
    if [ ! -d "$config_dir" ]; then
        mkdir -p "$config_dir"
    fi
    
    # Create config file if it doesn't exist
    if [ ! -f "$config_file" ]; then
        touch "$config_file"
    fi
    
    # Add PATH export to config file
    local export_line="export PATH=\"\$PATH:$path_to_add\""
    echo "$export_line" >> "$config_file"
    echo "Added PATH to $config_file"
}

# Update PATH configuration
echo "[5/5] Configuring PATH..."
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    # Detect current shell
    detected_shell=$(detect_shell)
    echo "Detected shell: $detected_shell"
    
    # Get appropriate config file
    config_file=$(get_shell_config_file "$detected_shell")
    echo "Using config file: $config_file"
    
    # Add PATH safely
    add_path_safely "$config_file" "$BIN_DIR"
    
    # Source the config file for current session
    if [ -f "$config_file" ]; then
        # Export for current session
        export PATH="$PATH:$BIN_DIR"
        echo "PATH updated for current session"
        
        # Try to source the config file (with error handling)
        if source "$config_file" 2>/dev/null; then
            echo "Configuration sourced successfully"
        else
            echo "Note: You may need to restart your shell or run: source $config_file"
        fi
    fi
else
    echo "PATH is already configured correctly"
fi

echo ""
echo "╔════════════════════════════════════════╗"
echo "║      Installation Complete! 🎉        ║"
echo "╚════════════════════════════════════════╝"
echo ""
echo "Usage: payloadforge --help"
echo "Example: payloadforge your_ota.zip"
echo ""
echo "Installation location: $INSTALL_DIR"
echo ""
