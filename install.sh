#!/usr/bin/env bash

set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required. Install it from https://docs.astral.sh/uv/"
    exit 1
fi

uv tool install .

echo
echo "payload2recovery installed."
echo "Run: payload2recovery doctor"
