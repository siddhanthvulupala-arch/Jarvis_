from __future__ import annotations
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_SEARCH_MODEL = os.getenv("GEMINI_SEARCH_MODEL", "gemini-3.8-flash")
WHISPER_MODEL = os.getenv("FRIDAY_WHISPER_MODEL", "base")
VOICE_NAME = os.getenv("FRIDAY_VOICE", "zira").lower()
VOICE_RATE = int(os.getenv("FRIDAY_RATE", "0"))
VOICE_VOLUME = int(os.getenv("FRIDAY_VOLUME", "100"))
CONFIDENCE_THRESHOLD = float(os.getenv("FRIDAY_CONFIDENCE_THRESHOLD", "0.15"))
SILENCE_THRESHOLD = float(os.getenv("FRIDAY_SILENCE_THRESHOLD", "0.01"))
USAGE_FILE = DATA_DIR / "gemini_usage.json"
MEMORY_FILE = DATA_DIR / "memory.json"
ALIASES_FILE = ROOT / "app_aliases.json"
