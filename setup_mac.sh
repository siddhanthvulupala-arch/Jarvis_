#!/usr/bin/env bash
# ==============================================================================
# JARVIS macOS Setup Script
# Configures a clean Python 3.11 virtual environment and installs dependencies.
# ==============================================================================

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

echo "=========================================="
echo "  JARVIS macOS Environment Setup"
echo "=========================================="

# 1. Locate Python 3.11
PYTHON_BIN=""
if command -v python3.11 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3.11)"
elif [ -x "/opt/homebrew/bin/python3.11" ]; then
    PYTHON_BIN="/opt/homebrew/bin/python3.11"
elif [ -x "/usr/local/bin/python3.11" ]; then
    PYTHON_BIN="/usr/local/bin/python3.11"
fi

if [ -z "$PYTHON_BIN" ]; then
    echo "[ERROR] Python 3.11 was not found on your system."
    echo "Please install Python 3.11 using Homebrew:"
    echo "    brew install python@3.11"
    exit 1
fi

PY_VERSION="$("$PYTHON_BIN" --version 2>&1)"
echo "[FOUND] $PY_VERSION at $PYTHON_BIN"

# 2. Virtual Environment (.venv)
VENV_DIR="$PROJECT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"

if [ ! -d "$VENV_DIR" ] || [ ! -x "$VENV_PYTHON" ]; then
    echo "[SETUP] Creating virtual environment at .venv..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
else
    echo "[OK] Existing virtual environment found at .venv"
fi

# 3. Upgrade Pip & Tooling
echo "[SETUP] Upgrading packaging tools (pip, setuptools, wheel)..."
"$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel --quiet

# 4. Install Project Requirements
if [ -f "requirements.txt" ]; then
    echo "[SETUP] Installing dependencies from requirements.txt..."
    "$VENV_PYTHON" -m pip install -r requirements.txt
else
    echo "[WARN] requirements.txt not found."
fi

# 5. Hand Tracking Model Asset
if [ ! -f "data/hand_landmarker.task" ] || [ $(wc -c < "data/hand_landmarker.task") -lt 1000 ]; then
    echo "[SETUP] Downloading MediaPipe hand landmarker model..."
    mkdir -p data
    curl -L -s -o data/hand_landmarker.task "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
fi

# 6. Core Import Verification
echo "[TEST] Verifying core dependencies..."
"$VENV_PYTHON" -c "
import sys
mods = ['numpy', 'sounddevice', 'whisper', 'scipy', 'sympy', 'edge_tts', 'kokoro', 'google.genai', 'webview', 'cv2', 'mediapipe', 'psutil', 'soundfile']
failed = []
for m in mods:
    try:
        __import__(m)
    except Exception as e:
        failed.append(f'{m}: {e}')
if failed:
    print('[FAIL] Missing imports:\n  ' + '\n  '.join(failed))
    sys.exit(1)
else:
    print('[OK] All core dependencies verified successfully.')
"

# 6. Configuration / Environment Variables Notice
echo "------------------------------------------"
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo "[CONFIG] No .env file found. To configure API keys:"
        echo "    cp .env.example .env"
    fi
    echo "[CONFIG] Notice: GEMINI_API_KEY is not set."
    echo "         JARVIS will run with its local offline rule engine."
    echo "         Set GEMINI_API_KEY in .env for full AI capabilities."
else
    echo "[CONFIG] .env configuration file detected."
fi

echo "=========================================="
echo "  Setup Complete! Launch with:"
echo "    ./start_jarvis_mac.sh"
echo "  Or for console text mode:"
echo "    ./start_jarvis_mac.sh --text"
echo "=========================================="
