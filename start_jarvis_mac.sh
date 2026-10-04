#!/usr/bin/env bash
# ==============================================================================
# JARVIS macOS Launcher
# Starts the JARVIS Desktop App using the project's Python 3.11 virtual environment.
# ==============================================================================

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"

if [ ! -x "$VENV_PYTHON" ]; then
    echo "[ERROR] Virtual environment not found at .venv"
    echo "Please run ./setup_mac.sh first to set up your environment."
    exit 1
fi

exec "$VENV_PYTHON" start_jarvis_app.py "$@"
