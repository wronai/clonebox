#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -d "$DIR/.venv" ]; then
    "$DIR/.venv/bin/python" -m clonebox "$@"
else
    echo "Error: Virtual environment not found. Please run make install first." >&2
    exit 1
fi
