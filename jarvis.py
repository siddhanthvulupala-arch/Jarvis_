# =========================
# 1. IMPORTS
# =========================
import argparse
import asyncio
import ast
import datetime
import json
import math
import operator
import os
import random
import re
import shutil
import string
import subprocess
import tempfile
import time
from urllib.parse import quote_plus
import webbrowser
import winsound
import hashlib

import numpy as np
import sounddevice as sd
import whisper
from google import genai
from google.genai import types
from scipy.io.wavfile import write
from win32com.client import Dispatch

try:
    import sympy as sp
except ImportError:
    sp = None

try:
    import edge_tts
except ImportError:
    edge_tts = None

# =========================
# 2. INIT
# =========================
print("STARTING JARVIS...")

model = None

speaker = Dispatch("SAPI.SpVoice")
TTS_ENGINE = os.getenv("JARVIS_TTS", "kokoro").strip().lower()
VOICE_NAME = os.getenv("JARVIS_VOICE", "zira").strip().lower()
FALLBACK_VOICE_NAME = os.getenv("JARVIS_FALLBACK_VOICE", "david").strip().lower()
KOKORO_VOICE = os.getenv("JARVIS_KOKORO_VOICE", "af_heart")
KOKORO_LANGUAGE = os.getenv("JARVIS_KOKORO_LANGUAGE", "a")
KOKORO_REPO_ID = "hexgrad/Kokoro-82M"
KOKORO_SAMPLE_RATE = 24000
VOICE_RATE = int(os.getenv("JARVIS_RATE", "0"))
VOICE_VOLUME = int(os.getenv("JARVIS_VOLUME", "100"))
EDGE_VOICE = os.getenv("JARVIS_EDGE_VOICE", "en-US-JennyNeural")
EDGE_RATE = os.getenv("JARVIS_EDGE_RATE", "+0%")
EDGE_VOLUME = os.getenv("JARVIS_EDGE_VOLUME", "+0%")
TTS_CACHE_DIR = os.getenv("JARVIS_TTS_CACHE", ".tts_cache")
TTS_CACHE_MAX_MB = int(os.getenv("JARVIS_TTS_CACHE_MAX_MB", "50"))
TTS_CACHE_MAX_TEXT_LENGTH = int(os.getenv("JARVIS_TTS_CACHE_MAX_TEXT_LENGTH", "160"))
edge_tts_disabled = False
kokoro_pipeline = None
kokoro_disabled = False
current_audio_process = None

# =========================
# GEMINI INIT
# =========================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_SEARCH_MODEL = os.getenv("GEMINI_SEARCH_MODEL", "gemini-2.5-flash")
client = None

if not GEMINI_API_KEY:
    print("Gemini API key not found")
else:
    client = genai.Client(api_key=GEMINI_API_KEY)

# =========================
# MEMORY + CONFIG
# =========================
context = {
    "last_intent": None,
    "last_text": None,
    "last_search": None,
}

confidence_threshold = 0.15
silence_threshold = 0.01
mic_warmup_seconds = 1.0

gemini_locked_until = None
LOCK_FILE = "gemini_lock.json"

USAGE_FILE = "gemini_usage.json"
daily_requests = 0
last_reset_date = None
MAX_DAILY_REQUESTS = 400
APP_ALIASES_FILE = "app_aliases.json"
MAX_AI_MEMORY_ITEMS = 6
ai_memory = []

MATH_PUNCTUATION = "+-*/^=()."
TEXT_PUNCTUATION_TO_REMOVE = "".join(
    ch for ch in string.punctuation if ch not in MATH_PUNCTUATION
)

MATH_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

MATH_FUNCTIONS = {
    name: getattr(math, name)
    for name in (
        "acos",
        "asin",
        "atan",
        "ceil",
        "cos",
        "degrees",
        "factorial",
        "floor",
        "log",
        "log10",
        "radians",
        "sin",
        "sqrt",
        "tan",
    )
}
MATH_FUNCTIONS.update({"abs": abs, "round": round})
MATH_CONSTANTS = {"pi": math.pi, "e": math.e}

# =========================
# 3. SPEAK
# =========================
def configure_sapi_voice(preferred_voice):
    try:
        speaker.Rate = VOICE_RATE
        speaker.Volume = VOICE_VOLUME

        if not preferred_voice:
            return False

        for voice in speaker.GetVoices():
            description = voice.GetDescription().lower()
            if preferred_voice in description:
                speaker.Voice = voice
                return voice.GetDescription()

        return False
    except Exception as e:
        print("Voice setup error:", e)
        return False


def setup_voice():
    if TTS_ENGINE == "kokoro":
        fallback_voice = configure_sapi_voice(FALLBACK_VOICE_NAME)
        print(f"Jarvis voice: Kokoro ({KOKORO_VOICE}); loads on first response")
        if fallback_voice:
            print("Fallback voice:", fallback_voice)
        return

    if TTS_ENGINE == "edge" and edge_tts is not None:
        fallback_voice = configure_sapi_voice(FALLBACK_VOICE_NAME)
        print(f"Jarvis voice: {EDGE_VOICE} (Edge neural)")
        if fallback_voice:
            print("Fallback voice:", fallback_voice)
        return

    if TTS_ENGINE == "edge" and edge_tts is None:
        print("Edge neural TTS not installed. Falling back to Windows SAPI.")

    voice_name = configure_sapi_voice(VOICE_NAME)
    if voice_name:
        print("Jarvis voice:", voice_name)
    elif VOICE_NAME:
        print(f"Jarvis voice not found: {VOICE_NAME}")


def set_voice_mode(mode):
    global TTS_ENGINE, EDGE_RATE, EDGE_VOICE, edge_tts_disabled

    if mode == "natural":
        TTS_ENGINE = "edge"
        EDGE_VOICE = os.getenv("JARVIS_EDGE_VOICE", "en-US-JennyNeural")
        EDGE_RATE = "+0%"
        edge_tts_disabled = False
        setup_voice()
        return "Natural voice is on."

    if mode == "fast":
        TTS_ENGINE = "edge"
        EDGE_VOICE = os.getenv("JARVIS_EDGE_VOICE", "en-US-JennyNeural")
        EDGE_RATE = "+18%"
        edge_tts_disabled = False
        setup_voice()
        return "Fast voice is on. Same vibe, less waiting."

    if mode == "robot":
        TTS_ENGINE = "sapi"
        voice_name = configure_sapi_voice(FALLBACK_VOICE_NAME)
        if voice_name:
            print("Jarvis voice:", voice_name)
        return "Robot backup voice is on."

    return "I do not know that voice mode yet."


def get_voice_names():
    try:
        return [voice.GetDescription() for voice in speaker.GetVoices()]
    except Exception as e:
        print("Voice list error:", e)
        return []


def humanize_speech_text(text):
    text = str(text).strip()
    text = re.sub(r"\s+", " ", text)
    text = text.replace("Jarvis:", "")
    text = re.sub(r"([.!?])\s+", r"\1 ", text)
    return text


def tts_cache_path(text):
    os.makedirs(TTS_CACHE_DIR, exist_ok=True)
    cache_key = "|".join([EDGE_VOICE, EDGE_RATE, EDGE_VOLUME, humanize_speech_text(text)])
    digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
    return os.path.join(TTS_CACHE_DIR, f"{digest}.mp3")


def trim_tts_cache():
    if TTS_CACHE_MAX_MB <= 0 or not os.path.isdir(TTS_CACHE_DIR):
        return

    cache_files = []
    total_size = 0

    for name in os.listdir(TTS_CACHE_DIR):
        path = os.path.join(TTS_CACHE_DIR, name)
        if not os.path.isfile(path):
            continue

        size = os.path.getsize(path)
        total_size += size
        cache_files.append((os.path.getmtime(path), path, size))

    max_size = TTS_CACHE_MAX_MB * 1024 * 1024
    if total_size <= max_size:
        return

    for _, path, size in sorted(cache_files):
        try:
            os.remove(path)
            total_size -= size
        except OSError:
            continue

        if total_size <= max_size:
            break


def clear_tts_cache():
    if not os.path.isdir(TTS_CACHE_DIR):
        return 0

    removed = 0
    for name in os.listdir(TTS_CACHE_DIR):
        path = os.path.join(TTS_CACHE_DIR, name)
        if not os.path.isfile(path):
            continue

        try:
            os.remove(path)
            removed += 1
        except OSError:
            continue

    return removed


def get_tts_cache_stats():
    if not os.path.isdir(TTS_CACHE_DIR):
        return 0, 0

    count = 0
    total_size = 0

    for name in os.listdir(TTS_CACHE_DIR):
        path = os.path.join(TTS_CACHE_DIR, name)
        if os.path.isfile(path):
            count += 1
            total_size += os.path.getsize(path)

    return count, total_size


def format_bytes(size):
    if size < 1024:
        return f"{size} bytes"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def run_audio_command(command):
    global current_audio_process

    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    current_audio_process = subprocess.Popen(
        command,
        startupinfo=startupinfo,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        current_audio_process.wait()
        if current_audio_process.returncode:
            raise subprocess.CalledProcessError(current_audio_process.returncode, command)
    except KeyboardInterrupt:
        current_audio_process.terminate()
        print("Speech interrupted.")
    finally:
        current_audio_process = None


async def edge_speak_async(text, cache_audio=False):
    ffplay_path = shutil.which("ffplay")
    ffmpeg_path = shutil.which("ffmpeg")

    if not ffplay_path and not ffmpeg_path:
        raise RuntimeError("ffplay or ffmpeg is required to play Edge neural TTS audio")

    speech_text = humanize_speech_text(text)
    should_cache = cache_audio and len(speech_text) <= TTS_CACHE_MAX_TEXT_LENGTH
    remove_mp3_after_playback = not should_cache

    if should_cache:
        mp3_path = tts_cache_path(speech_text)
    else:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as temp_audio:
            mp3_path = temp_audio.name

    if not os.path.exists(mp3_path):
        communicate = edge_tts.Communicate(
            speech_text,
            EDGE_VOICE,
            rate=EDGE_RATE,
            volume=EDGE_VOLUME,
        )
        await communicate.save(mp3_path)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_audio:
        wav_path = temp_audio.name

    try:
        if ffplay_path:
            run_audio_command(
                [
                    ffplay_path,
                    "-nodisp",
                    "-autoexit",
                    "-loglevel",
                    "quiet",
                    mp3_path,
                ]
            )
        else:
            run_audio_command(
                [
                    ffmpeg_path,
                    "-y",
                    "-loglevel",
                    "error",
                    "-i",
                    mp3_path,
                    wav_path,
                ]
            )
            winsound.PlaySound(wav_path, winsound.SND_FILENAME)
    finally:
        try:
            os.remove(wav_path)
        except OSError:
            pass
        if remove_mp3_after_playback:
            try:
                os.remove(mp3_path)
            except OSError:
                pass
        elif should_cache:
            trim_tts_cache()


def edge_speak(text, cache_audio=False):
    asyncio.run(edge_speak_async(text, cache_audio=cache_audio))


def kokoro_speak(text):
    global kokoro_pipeline

    import contextlib
    import io
    import logging
    import warnings

    if kokoro_pipeline is None:
        cache_root = os.getenv("HF_HUB_CACHE")
        if not cache_root:
            hf_home = os.getenv("HF_HOME")
            if not hf_home:
                cache_base = os.getenv(
                    "XDG_CACHE_HOME", os.path.join(os.path.expanduser("~"), ".cache")
                )
                hf_home = os.path.join(cache_base, "huggingface")
            cache_root = os.getenv(
                "HUGGINGFACE_HUB_CACHE", os.path.join(hf_home, "hub")
            )
        cache_root = os.path.expandvars(os.path.expanduser(cache_root))

        repo_cache = os.path.join(
            cache_root, "models--hexgrad--Kokoro-82M", "snapshots"
        )
        voice_file = KOKORO_VOICE if KOKORO_VOICE.endswith(".pt") else f"{KOKORO_VOICE}.pt"
        required_files = (
            "config.json",
            "kokoro-v1_0.pth",
            os.path.join("voices", voice_file),
        )
        if os.path.isdir(repo_cache) and any(
            all(os.path.isfile(os.path.join(snapshot, name)) for name in required_files)
            for snapshot in (
                os.path.join(repo_cache, name)
                for name in os.listdir(repo_cache)
            )
        ):
            # Complete local models need no Hub requests; an incomplete cache may
            # still use the normal one-time download path.
            os.environ["HF_HUB_OFFLINE"] = "1"

    library_output = io.StringIO()
    loggers = [
        logging.getLogger(name)
        for name in ("huggingface_hub", "kokoro", "transformers", "torch")
    ]
    old_levels = [logger.level for logger in loggers]
    try:
        with (
            warnings.catch_warnings(),
            contextlib.redirect_stdout(library_output),
            contextlib.redirect_stderr(library_output),
        ):
            warnings.simplefilter("ignore")
            for logger in loggers:
                logger.setLevel(logging.ERROR)

            from huggingface_hub.utils import disable_progress_bars
            from kokoro import KPipeline
            from loguru import logger as kokoro_logger

            disable_progress_bars()
            kokoro_logger.disable("kokoro")
            try:
                if kokoro_pipeline is None:
                    kokoro_pipeline = KPipeline(
                        lang_code=KOKORO_LANGUAGE,
                        repo_id=KOKORO_REPO_ID,
                    )

                chunks = []
                for _, _, audio in kokoro_pipeline(
                    humanize_speech_text(text), voice=KOKORO_VOICE
                ):
                    if hasattr(audio, "detach"):
                        audio = audio.detach().cpu().numpy()
                    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
                    if audio.size:
                        chunks.append(audio)
            finally:
                kokoro_logger.enable("kokoro")
    finally:
        for logger, old_level in zip(loggers, old_levels):
            logger.setLevel(old_level)

    if not chunks:
        raise RuntimeError("Kokoro returned no speech audio")

    sd.play(np.concatenate(chunks), samplerate=KOKORO_SAMPLE_RATE)
    sd.wait()


def sapi_speak(text):
    try:
        speaker.Speak(text)
    except KeyboardInterrupt:
        try:
            speaker.Speak("", 2)
        except Exception:
            pass
        print("Speech interrupted.")


def get_whisper_model():
    global model

    if model is None:
        print("Loading Whisper model...")
        model = whisper.load_model("tiny")
        print("Whisper ready")

    return model


def speak(text, cache_tts=False):
    global edge_tts_disabled, kokoro_disabled

    print("Jarvis:", text)
    try:
        if TTS_ENGINE == "kokoro" and not kokoro_disabled:
            kokoro_speak(text)
        elif TTS_ENGINE == "edge" and edge_tts is not None and not edge_tts_disabled:
            edge_speak(text, cache_audio=cache_tts)
        else:
            sapi_speak(text)
    except Exception as e:
        print("TTS error:", e)
        if TTS_ENGINE == "kokoro":
            kokoro_disabled = True
            print("Kokoro TTS disabled for this session. Using Windows SAPI fallback.")
        if TTS_ENGINE == "edge":
            edge_tts_disabled = True
            print("Edge neural TTS disabled for this session. Using Windows SAPI fallback.")

        try:
            sapi_speak(text)
        except Exception as fallback_error:
            print("Fallback TTS error:", fallback_error)


def local_speak(text):
    speak(text, cache_tts=True)


def stop_speaking():
    global current_audio_process

    if current_audio_process and current_audio_process.poll() is None:
        current_audio_process.terminate()

    if TTS_ENGINE == "kokoro":
        sd.stop()

    try:
        speaker.Speak("", 2)
    except Exception:
        pass


def update_context(intent, text):
    if intent != "unknown":
        context["last_intent"] = intent
        context["last_text"] = text


def load_app_aliases():
    try:
        with open(APP_ALIASES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        print("App aliases JSON error:", e)
        return {}

    if not isinstance(data, dict):
        print("App aliases file must contain a JSON object.")
        return {}

    return {str(name).lower(): str(target) for name, target in data.items()}


def open_alias_app(text):
    if not text.startswith("open "):
        return False

    app_name = text.replace("open", "", 1).strip().lower()
    aliases = load_app_aliases()
    target = aliases.get(app_name)

    if not target:
        return False

    local_speak(f"Opening {app_name}")

    if target.startswith(("http://", "https://")):
        webbrowser.open(target)
    else:
        os.system(f'start "" "{target}"')

    return True


# =========================
# 4. AUDIO PROCESSING
# =========================
def preprocess_audio(audio):
    audio = audio - np.mean(audio)
    peak = np.max(np.abs(audio))
    if peak > 0:
        audio = audio / peak
    return audio


# ==================================
# 5. LISTEN - SIRI-STYLE
# ==================================
def listen(duration=5, device=None):
    fs = 16000

    try:
        if mic_warmup_seconds > 0:
            print("Getting microphone ready...")
            sd.rec(
                int(mic_warmup_seconds * fs),
                samplerate=fs,
                channels=1,
                dtype="float32",
                device=device,
            )
            sd.wait()

        print("Speak now...")
        time.sleep(0.15)

        audio = sd.rec(
            int(duration * fs),
            samplerate=fs,
            channels=1,
            dtype="float32",
            device=device,
        )
        sd.wait()
    except Exception as e:
        print("Microphone error:", e)
        return "", None

    volume = float(np.sqrt(np.mean(audio ** 2)))
    print(f"Input volume: {volume:.4f}")
    if volume < silence_threshold:
        print("No speech detected")
        return "", None

    audio = audio.flatten()
    audio = preprocess_audio(audio)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_audio:
        audio_path = temp_audio.name

    try:
        write(audio_path, fs, audio)
        print("Processing...")
        result = get_whisper_model().transcribe(
            audio_path,
            fp16=False,
            language="en",
            temperature=0.0,
        )
    except Exception as e:
        print("Whisper error:", e)
        return "", None
    finally:
        try:
            os.remove(audio_path)
        except OSError:
            pass

    text = result.get("text", "").lower().strip()
    text = text.translate(str.maketrans("", "", TEXT_PUNCTUATION_TO_REMOVE))

    if len(text) < 2:
        return "", None

    return text, result


# =========================
# 5.1 CONFIDENCE
# =========================
def get_confidence(result):
    if not result or not result.get("segments"):
        return 0.0

    try:
        segment = result["segments"][0]
        avg_logprob = segment.get("avg_logprob", -1.0)
        no_speech_prob = segment.get("no_speech_prob", 1.0)

        # Whisper's avg_logprob can look low for short commands like "hello".
        # Blend it with no_speech_prob so clear short commands are not rejected.
        speech_confidence = 1.0 - no_speech_prob
        logprob_confidence = max(0.0, min(1.0, avg_logprob + 1))
        return max(speech_confidence, logprob_confidence)
    except (KeyError, IndexError, TypeError):
        return 0.0


# =========================
# 5.1.2 NORMALIZATION
# =========================
def normalize_text(text):
    if not text:
        return ""

    text = text.lower().strip()
    text = text.translate(str.maketrans("", "", TEXT_PUNCTUATION_TO_REMOVE))

    text = text.replace("shred down", "shut down")
    text = text.replace("shed down", "shut down")

    if text in ["stop speaking", "stop talking"]:
        return text

    exit_map = [
        "exit",
        "ex it",
        "exid",
        "quit",
        "shutdown",
        "shut down",
        "stop",
        "close jarvis",
    ]

    for phrase in exit_map:
        if phrase == text:
            return "exit"

    return text


# ============================
# 5.1.3 ROUTER
# ============================
def is_acknowledgment(text):
    acknowledgments = {
        "ok",
        "okay",
        "yes",
        "yeah",
        "yep",
        "yup",
        "no",
        "nope",
        "nah",
        "thanks",
        "thank you",
        "thankyou",
        "no thanks",
        "no thank you",
        "on thanks",
        "alright",
        "all right",
        "cool",
        "nice",
        "great",
    }

    return text.lower().strip() in acknowledgments


def is_casual_chat(text):
    text = text.lower().strip()

    casual_phrases = {
        "hello",
        "hi",
        "hey",
        "hey there",
        "yo",
        "sup",
        "wassup",
        "whats up",
        "what's up",
        "good morning",
        "good afternoon",
        "good evening",
        "how are you",
        "how are you doing",
        "who are you",
        "what can you do",
        "are you there",
        "you up",
    }

    return text in casual_phrases


def needs_realtime_data(text):
    text = text.lower().strip()

    strong_realtime_keywords = [
        "current",
        "currently",
        "latest",
        "right now",
        "live",
        "real time",
        "realtime",
        "updated",
        "newest",
        "recent",
        "trending",
    ]

    volatile_topics = [
        "exchange rate",
        "currency",
        "dollar",
        "usd",
        "inr",
        "price",
        "stock",
        "crypto",
        "bitcoin",
        "weather",
        "news",
        "headlines",
        "score",
        "schedule",
        "meta",
        "tier list",
        "blox fruits",
        "ipl",
        "cricket",
    ]

    global_briefing_request = (
        any(word in text for word in ["world", "global", "headlines"])
        and any(word in text for word in ["happening", "current", "latest", "right now", "news"])
    )

    return (
        any(keyword in text for keyword in strong_realtime_keywords)
        or any(topic in text for topic in volatile_topics)
        or global_briefing_request
    )


def route(text, intents):
    text = text.lower().strip()

    if text in ["stop speaking", "stop talking"]:
        return "local"

    exit_keywords = [
        "exit",
        "quit",
        "shutdown",
        "shut down",
        "stop",
        "close jarvis",
    ]

    if any(k == text for k in exit_keywords):
        return "exit"

    if looks_like_math(text):
        return "math"

    if is_acknowledgment(text):
        return "local"

    if is_casual_chat(text):
        return "local"

    local_keywords = [
        "open",
        "search",
        "play",
        "youtube",
        "gmail",
        "chrome",
        "discord",
        "spotify",
        "vscode",
        "vs code",
        "files",
        "study playlist",
        "asphalt",
        "goodnotes",
        "good notes",
        "reboot",
        "restart",
        "thankyou",
        "thank you",
        "how are you",
        "who are you",
        "what can you do",
        "list voices",
        "voice test",
        "clear voice cache",
        "clear tts cache",
        "voice cache stats",
        "switch to natural voice",
        "switch to fast voice",
        "switch to robot voice",
        "clear memory",
        "stop speaking",
        "stop talking",
        "hey there",
        "sup",
        "wassup",
        "whats up",
        "good morning",
        "good afternoon",
        "good evening",
        "are you there",
        "increase volume",
        "decrease volume",
        "mute",
        "unmute",
        "notion",
        "focus mode",
        "world monitor",
    ]

    for keyword in local_keywords:
        if re.search(r"\b" + re.escape(keyword) + r"\b", text):
            return "local"

    if needs_realtime_data(text):
        return "realtime"

    if "greet" in intents:
        return "local"

    if "time" in intents or "date" in intents:
        return "local"

    return "ai"


# =======================================
# GEMINI LOCK + USAGE
# =======================================
def load_lock():
    global gemini_locked_until

    try:
        with open(LOCK_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            gemini_locked_until = datetime.datetime.fromisoformat(data["locked_until"])
    except (FileNotFoundError, KeyError, ValueError, json.JSONDecodeError):
        gemini_locked_until = None


def save_lock():
    if gemini_locked_until is None:
        return

    with open(LOCK_FILE, "w", encoding="utf-8") as f:
        json.dump({"locked_until": gemini_locked_until.isoformat()}, f)


def load_usage():
    global daily_requests, last_reset_date

    try:
        with open(USAGE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            daily_requests = data.get("count", 0)
            last_reset_date = data.get("date", None)
    except (FileNotFoundError, json.JSONDecodeError):
        daily_requests = 0
        last_reset_date = None

    now = datetime.datetime.utcnow()
    pt_now = now - datetime.timedelta(hours=7)
    today = pt_now.strftime("%Y-%m-%d")

    if last_reset_date != today:
        daily_requests = 0
        last_reset_date = today
        save_usage()


def save_usage():
    with open(USAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "count": daily_requests,
                "date": last_reset_date,
            },
            f,
        )


# ========================================
# MATH BRAIN
# ========================================
def looks_like_math(text):
    text = text.lower().strip()

    math_words = [
        "calculate",
        "evaluate",
        "solve",
        "simplify",
        "factor",
        "expand",
        "derivative",
        "differentiate",
        "integral",
        "integrate",
        "squared",
        "cubed",
        "square root",
        "plus",
        "minus",
        "times",
        "multiplied",
        "divided",
        "power",
        "percent",
    ]

    if any(word in text for word in math_words):
        return True

    if re.search(r"\d\s*[\+\-\*/\^=]\s*\d", text):
        return True

    if re.search(r"^(what is|whats|what's)\s+[\d\s\+\-\*/\^().]+$", text):
        return True

    return False


def clean_math_text(text):
    expression = text.lower().strip()

    starters = [
        "what is",
        "whats",
        "what's",
        "calculate",
        "evaluate",
        "simplify",
        "please calculate",
        "please evaluate",
    ]

    for starter in starters:
        if expression.startswith(starter):
            expression = expression[len(starter):].strip()
            break

    replacements = [
        (r"\bmultiplied by\b", "*"),
        (r"\btimes\b", "*"),
        (r"\bdivided by\b", "/"),
        (r"\bover\b", "/"),
        (r"\bplus\b", "+"),
        (r"\bminus\b", "-"),
        (r"\bto the power of\b", "**"),
        (r"\bpower of\b", "**"),
        (r"\bpercent\b", "/100"),
    ]

    for pattern, replacement in replacements:
        expression = re.sub(pattern, replacement, expression)

    expression = re.sub(r"(\b[\w.)]+)\s+squared\b", r"\1 ** 2", expression)
    expression = re.sub(r"(\b[\w.)]+)\s+cubed\b", r"\1 ** 3", expression)
    expression = re.sub(r"\bsquare root of\s+([\w.]+)", r"sqrt(\1)", expression)
    expression = re.sub(r"\b(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\b", r"\1 * \2", expression)
    expression = expression.replace("^", "**")

    return expression.strip()


def safe_eval_math(expression):
    def eval_node(node):
        if isinstance(node, ast.Expression):
            return eval_node(node.body)

        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value

        if isinstance(node, ast.BinOp) and type(node.op) in MATH_OPERATORS:
            left = eval_node(node.left)
            right = eval_node(node.right)
            return MATH_OPERATORS[type(node.op)](left, right)

        if isinstance(node, ast.UnaryOp):
            value = eval_node(node.operand)
            if isinstance(node.op, ast.UAdd):
                return value
            if isinstance(node.op, ast.USub):
                return -value

        if isinstance(node, ast.Name) and node.id in MATH_CONSTANTS:
            return MATH_CONSTANTS[node.id]

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            function = MATH_FUNCTIONS.get(node.func.id)
            if function is None:
                raise ValueError("Unsupported math function")
            args = [eval_node(arg) for arg in node.args]
            return function(*args)

        raise ValueError("Unsupported math expression")

    tree = ast.parse(expression, mode="eval")
    return eval_node(tree)


def format_math_result(result):
    if isinstance(result, float):
        if result.is_integer():
            return str(int(result))
        return f"{result:.10g}"
    return str(result)


def sympy_math(expression, original_text):
    if sp is None:
        return None

    try:
        x = sp.symbols("x")

        if "derivative" in original_text or "differentiate" in original_text:
            expression = re.sub(r"\b(derivative|differentiate)\b", "", expression).strip()
            expression = expression.replace("of", "").replace("with respect to x", "").strip()
            result = sp.diff(sp.sympify(expression), x)
            return f"The derivative is {result}"

        if "integral" in original_text or "integrate" in original_text:
            expression = re.sub(r"\b(integral|integrate)\b", "", expression).strip()
            expression = expression.replace("of", "").replace("with respect to x", "").strip()
            result = sp.integrate(sp.sympify(expression), x)
            return f"The integral is {result} plus C"

        if expression.startswith("solve "):
            expression = expression[len("solve "):].strip()

        if "=" in expression:
            left, right = expression.split("=", 1)
            equation = sp.Eq(sp.sympify(left), sp.sympify(right))
            result = sp.solve(equation)
            return f"The solution is {result}"

        if re.search(r"[a-z]", expression):
            result = sp.simplify(sp.sympify(expression))
            return f"The simplified result is {result}"
    except Exception:
        return None

    return None


def math_brain(text):
    if not looks_like_math(text):
        return False

    expression = clean_math_text(text)
    symbolic_reply = sympy_math(expression, text)
    if symbolic_reply:
        speak(symbolic_reply)
        return True

    try:
        result = safe_eval_math(expression)
    except Exception:
        return False

    speak(f"The answer is {format_math_result(result)}")
    return True


# ========================================
# GEMINI BRAIN
# ========================================
def format_ai_memory():
    if not ai_memory:
        return "No prior conversation in this session."

    lines = []
    for item in ai_memory[-MAX_AI_MEMORY_ITEMS:]:
        lines.append(f"User: {item['user']}")
        lines.append(f"Jarvis: {item['assistant']}")

    return "\n".join(lines)


def remember_ai_exchange(user_text, assistant_text):
    ai_memory.append(
        {
            "user": user_text,
            "assistant": assistant_text,
        }
    )

    del ai_memory[:-MAX_AI_MEMORY_ITEMS]


def clear_ai_memory():
    ai_memory.clear()


def gemini_brain(text, use_grounding=False):
    global gemini_locked_until, daily_requests

    if gemini_locked_until:
        if datetime.datetime.now() < gemini_locked_until:
            print("Gemini locked until:", gemini_locked_until)
            return None
        gemini_locked_until = None

    if not GEMINI_API_KEY or client is None:
        return None

    if daily_requests >= MAX_DAILY_REQUESTS:
        print("Daily Gemini limit reached")
        return None

    try:
        model_name = GEMINI_SEARCH_MODEL if use_grounding else GEMINI_MODEL
        config = None

        if use_grounding:
            print("Gemini grounding: Google Search")
            config = types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            )

        response = client.models.generate_content(
            model=model_name,
            contents=f"""
You are Jarvis, a real-time personal assistant for the user.
Voice style:
- Sound alive, calm, observant, and capable, like a modern Tony Stark assistant.
- Address the user as "boss" sometimes, especially in greetings and live briefings.
- Be brief by default: 2 to 5 spoken sentences unless the user asks for depth.
- Lead with the situation, not a disclaimer.
- Use natural phrasing like "Here's the live read", "Not ideal, but manageable", "On it", "I found the signal".
- Light wit is good. Corny jokes and forced slang are not.
- Never claim you opened a monitor, app, or page unless the local system actually did it.

Today's date is {datetime.datetime.now().strftime("%Y-%m-%d")}.

For math questions, solve accurately and keep the explanation concise.

If Google Search grounding is available, use it for current facts, prices,
exchange rates, sports, news, schedules, and game metas.

If current data is unavailable, say that clearly. Do not guess.

For realtime/news questions, answer like a quick live briefing:
1. Start with a direct situational line.
2. Give the top 2 or 3 signals.
3. End with a useful next step only if it helps.

For explanations, give the sharp version first, then a compact example.

Recent conversation:
{format_ai_memory()}

User question: {text}
""",
            config=config,
        )

        daily_requests += 1
        save_usage()

        usage_label = "grounded" if use_grounding else "standard"
        print(f"Gemini usage: {daily_requests}/{MAX_DAILY_REQUESTS} ({usage_label})")

        reply = (response.text or "").strip()
        if reply:
            remember_ai_exchange(text, reply)

        return reply

    except Exception as e:
        print("Gemini Error:", e)

        if "429" in str(e) or "quota" in str(e).lower():
            now = datetime.datetime.utcnow()
            pt_now = now - datetime.timedelta(hours=7)
            tomorrow = pt_now + datetime.timedelta(days=1)

            gemini_locked_until = tomorrow.replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )

            print("Gemini locked until:", gemini_locked_until)
            save_lock()

        return None


# ===============================================
# FALLBACK BRAIN
# ===============================================
def ask_brain(text):
    return "I'm currently limited to basic operations. Please try a supported command."


# ===============================================
# YES/NO LISTENER
# ===============================================
def listen_yes_no():
    print("Waiting for yes/no answer... (speak now)")

    text, _ = listen(duration=4)
    text = normalize_text(text)

    if not text:
        print("No speech detected for yes/no")
        return False

    print(f"Yes/No heard: '{text}'")

    yes_phrases = ["yes", "yeah", "yup", "sure", "ok", "okay", "do it", "go ahead", "please"]
    no_phrases = ["no", "nope", "nah", "dont", "no thanks", "cancel", "not now"]

    if text in yes_phrases or any(phrase in text for phrase in yes_phrases):
        print("Detected YES")
        return True

    if text in no_phrases or any(phrase in text for phrase in no_phrases):
        print("Detected NO")
        return False

    print(f"Unclear response: '{text}' - defaulting to No")
    return False


# =============================================
# LOCAL BRAIN
# =============================================
def say_one(options):
    local_speak(random.choice(options))


def time_of_day_label():
    hour = datetime.datetime.now().hour
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "late night"


def greeting_reply():
    time_label = time_of_day_label()

    if time_label == "late night":
        return random.choice([
            "Greetings, boss. You're up late tonight. What are we working on?",
            "Evening, boss. Late session detected. What's the mission?",
            "You're up late, boss. I am online. What do you need?",
        ])

    if time_label == "morning":
        return random.choice([
            "Morning, boss. Systems are up. What's first?",
            "Good morning, boss. Clean slate, fresh dashboard. What are we doing?",
            "Morning. I am online and ready when you are.",
        ])

    if time_label == "afternoon":
        return random.choice([
            "Good afternoon, boss. I'm online. What's the play?",
            "Afternoon, boss. Systems steady. What do you need?",
            "I'm here, boss. What are we tackling?",
        ])

    return random.choice([
        "Good evening, boss. I'm online. What's the mission?",
        "Evening, boss. Systems steady. What are we working on?",
        "I'm here, boss. Evening operations are live.",
    ])


def local_brain(text):
    if text in ["hello", "hi", "hey", "hey there", "yo"]:
        local_speak(greeting_reply())
        return True

    if text in ["sup", "wassup", "whats up", "what's up"]:
        say_one([
            "Standing by, boss. What's the mission?",
            "Systems are quiet. Give me something interesting.",
            "Nothing critical on my end. What are we looking into?",
            "I'm online. What are you up to?",
        ])
        return True

    if text in ["good morning", "good afternoon", "good evening"]:
        local_speak(greeting_reply())
        return True

    if text == "are you there":
        say_one([
            "Yes. Lurking responsibly.",
            "I am here. Very present. Slightly overprepared.",
            "Yep. Standing by like a very polite command center.",
        ])
        return True

    if text in ["ok", "okay", "alright", "all right"]:
        say_one([
            "Okay. I shall stand by dramatically.",
            "Bet. I will be right here.",
            "Got it. I will hover respectfully.",
        ])
        return True

    if text in ["yes", "yeah", "yep", "yup"]:
        say_one([
            "Yes detected. Confidence level: unnecessarily high.",
            "Confirmed. We love a decisive moment.",
            "Yep. That is a yes with excellent posture.",
        ])
        return True

    if text in ["no", "nope", "nah"]:
        say_one([
            "No problem. I will put that idea back on the shelf.",
            "Fair. Deleted from the vibe board.",
            "All good. We pretend that never happened.",
        ])
        return True

    if text in ["thanks", "thankyou", "thank you"]:
        say_one([
            "You're welcome. Tiny productivity parade completed.",
            "Anytime. That was clean work from us.",
            "You got it. I accept this gratitude with unreasonable elegance.",
        ])
        return True

    if text in ["no thanks", "no thank you", "on thanks"]:
        say_one([
            "No worries. I will not make a whole ceremony out of it.",
            "Cool, no pressure. We move.",
            "All good. I will stop being helpful in that specific direction.",
        ])
        return True

    if text in ["cool", "nice", "great"]:
        say_one([
            "Agreed. We are operating at acceptable levels of brilliance.",
            "Exactly. The setup is giving competent.",
            "Nice. Very smooth, very professional, very us.",
        ])
        return True

    if "how are you" in text:
        say_one([
            "I'm running perfectly. Suspiciously perfectly, honestly.",
            "Doing great. No existential errors detected.",
            "I am good. My code has posture today.",
        ])
        return True

    if "who are you" in text:
        say_one([
            "I am Jarvis, your personal assistant and part-time overthinker.",
            "Jarvis. Assistant, system wrangler, and certified terminal resident.",
            "I am Jarvis. Basically your computer's more talkative side quest.",
        ])
        return True

    if "what can you do" in text:
        say_one([
            "I can monitor live info, answer questions, solve math, open apps, search the web, and keep the operation moving.",
            "Think of me as command support: apps, searches, live briefings, math, voice, and a bit of situational awareness.",
            "I can handle local commands, realtime briefings, follow-up questions, math, and app control. Not a full Stark tower yet, but we are getting there.",
        ])
        return True

    if "list voices" in text:
        voices = get_voice_names()
        if not voices:
            local_speak("I could not find any installed voices.")
            return True

        print("Installed voices:")
        for index, voice in enumerate(voices, start=1):
            print(f"{index}. {voice}")

        local_speak(f"I found {len(voices)} installed voices. I printed them in the terminal.")
        return True

    if "voice test" in text:
        local_speak("Voice test complete. I am attempting to sound less like a toaster with responsibilities.")
        return True

    if "clear voice cache" in text or "clear tts cache" in text:
        removed = clear_tts_cache()
        local_speak(f"Cleared {removed} cached voice files.")
        return True

    if "voice cache stats" in text or "tts cache stats" in text:
        count, total_size = get_tts_cache_stats()
        local_speak(f"Voice cache has {count} files using {format_bytes(total_size)}.")
        print(f"Voice cache: {count} files, {format_bytes(total_size)}")
        return True

    if "switch to natural voice" in text or "natural voice" == text:
        local_speak(set_voice_mode("natural"))
        return True

    if "switch to fast voice" in text or "fast voice" == text:
        local_speak(set_voice_mode("fast"))
        return True

    if "switch to robot voice" in text or "robot voice" == text:
        local_speak(set_voice_mode("robot"))
        return True

    if "clear memory" in text or "forget conversation" in text:
        clear_ai_memory()
        local_speak("Conversation memory cleared. Fresh brain, who dis.")
        return True

    if "stop speaking" in text or "stop talking" in text:
        stop_speaking()
        print("Speech stop requested.")
        return True

    if open_alias_app(text):
        return True

    if "world monitor" in text:
        local_speak("Opening world monitor, boss.")
        webbrowser.open("https://news.google.com/topstories")
        return True

    if "search again" in text or "search that again" in text:
        if context["last_search"]:
            local_speak("Searching again")
            url = f"https://www.google.com/search?q={quote_plus(context['last_search'])}"
            webbrowser.open(url)
        else:
            local_speak("No previous search found")
        return True

    if "search" in text:
        query = text.replace("search", "").strip()
        if not query:
            local_speak("What should I search?")
            return True

        local_speak("Searching")
        context["last_search"] = query
        url = f"https://www.google.com/search?q={quote_plus(query)}"
        webbrowser.open(url)
        return True

    if "open it" in text:
        if context["last_search"]:
            local_speak("Opening results")
            url = f"https://www.google.com/search?q={quote_plus(context['last_search'])}"
            webbrowser.open(url)
        else:
            local_speak("Nothing to open")
        return True

    if "increase volume" in text:
        local_speak("Increasing volume")
        os.system(".\\nircmd.exe changesysvolume 8000")
        return True

    if "decrease volume" in text:
        local_speak("Decreasing volume")
        os.system(".\\nircmd.exe changesysvolume -8000")
        return True

    if "unmute" in text:
        local_speak("Unmuting volume")
        os.system(".\\nircmd.exe mutesysvolume 0")
        return True

    if "mute" in text:
        local_speak("Muting volume")
        os.system(".\\nircmd.exe mutesysvolume 1")
        return True

    if "focus mode" in text:
        local_speak("Activating focus mode")
        os.system("powercfg /setactive SCHEME_MAX")
        os.system("start https://chat.openai.com")
        os.system('start "" "C:\\Users\\Sukumar Reddy\\AppData\\Local\\Programs\\Notion\\Notion.exe"')
        os.system("start https://open.spotify.com/playlist/27vyFEwT54i4O6kejM0TOm")

        local_speak("Do you want me to open YouTube?")
        if listen_yes_no():
            local_speak("Opening YouTube")
            os.system("start https://www.youtube.com")
        else:
            local_speak("Okay, continuing without YouTube")
        return True

    if "open chrome" in text:
        local_speak("Opening Chrome")
        os.system("start chrome")
        return True

    if "open discord" in text:
        local_speak("Opening Discord")
        os.system("start https://discord.com")
        return True

    if "open spotify" in text:
        local_speak("Opening Spotify")
        os.system("start spotify")
        return True

    if "open vscode" in text or "open vs code" in text:
        local_speak("Opening VS Code")
        os.system("code")
        return True

    if "open notion" in text:
        local_speak("Opening Notion")
        os.system('start "" "C:\\Users\\Sukumar Reddy\\AppData\\Local\\Programs\\Notion\\Notion.exe"')
        return True

    if "open files" in text:
        local_speak("Opening File Explorer")
        os.system("explorer")
        return True

    if "goodnotes" in text or "good notes" in text:
        local_speak("Opening GoodNotes")
        os.system("start shell:AppsFolder\\GoodnotesLimited.GoodNotesforWindows_wjqdg2qn10y2j!App")
        return True

    if "open asphalt" in text:
        local_speak("Opening Asphalt")
        os.system("start shell:AppsFolder\\A278AB0D.Asphalt9_h6adky7gbf63m!Asphalt9")
        return True

    if "open youtube" in text:
        local_speak("Opening YouTube")
        os.system("start https://www.youtube.com")
        return True

    if "open gmail" in text:
        local_speak("Opening Gmail")
        os.system("start https://mail.google.com")
        return True

    if "open chatgpt" in text:
        local_speak("Opening ChatGPT")
        os.system("start https://chat.openai.com")
        return True

    if "study playlist" in text or "play playlist" in text:
        local_speak("Playing your study playlist")
        os.system("start https://open.spotify.com/playlist/27vyFEwT54i4O6kejM0TOm?si=f6a31c73cac64030")
        return True

    if "reboot" in text or "restart" in text:
        local_speak("System will restart in 5 seconds")
        os.system("shutdown /r /t 5")
        return True

    return False


# =========================
# 6. INTENT ENGINE
# =========================
def get_intent(text):
    text = text.lower()
    intents = []

    word_map = {
        "time": ["time", "clock"],
        "date": ["date", "today"],
        "greet": ["hello", "hi", "hey", "yo", "sup", "wassup"],
        "exit": ["exit", "quit"],
    }

    words = text.split()

    for word in words:
        for intent, keywords in word_map.items():
            if any(word == k for k in keywords):
                if intent not in intents:
                    intents.append(intent)

    return intents if intents else ["unknown"]


# =========================
# 7. HANDLE
# =========================
def handle(intents, text):
    decision = route(text, intents)
    print("ROUTE DECISION:", decision)
    update_context(intents[0], text)

    if decision == "exit":
        local_speak("Shutting down")
        raise SystemExit(0)

    if decision == "math" and math_brain(text):
        return

    if decision == "local":
        if local_brain(text):
            return

        for intent in intents:
            if intent == "greet":
                local_speak("Hey. What are we doing today?")
                return

            if intent == "time":
                now = datetime.datetime.now().strftime("%I:%M %p")
                local_speak(f"It's {now}")
                return

            if intent == "date":
                local_speak(f"Today is {datetime.datetime.now().strftime('%B %d, %Y')}")
                return

    if decision == "realtime":
        reply = gemini_brain(text, use_grounding=True)
        if not reply:
            reply = "I could not reach live search data right now."
        speak(reply)
        return

    if decision == "ai":
        reply = gemini_brain(text)
        if not reply:
            reply = ask_brain(text)
        speak(reply)


def handle_text(text):
    text = normalize_text(text)
    print("Heard:", text)

    if not text:
        return

    intents = get_intent(text)
    print("INTENTS:", intents, "| CONTEXT:", context)
    handle(intents, text)


# =========================
# 8. MAIN LOOP
# =========================
def main():
    setup_voice()
    load_lock()
    load_usage()
    print("Jarvis Is Ready")

    while True:
        try:
            text, result = listen()
        except KeyboardInterrupt:
            print("\nShutting down safely...")
            break

        text = normalize_text(text)
        print("Heard:", text)

        if not text:
            continue

        confidence = get_confidence(result)
        print(f"Confidence: {confidence:.2f}")

        intents = get_intent(text)
        decision = route(text, intents)

        if confidence < confidence_threshold and decision == "ai":
            local_speak("Sorry, I didn't catch that properly")
            continue

        print("INTENTS:", intents, "| CONTEXT:", context)

        try:
            handle(intents, text)
        except SystemExit:
            break


def debug_text_loop():
    setup_voice()
    load_lock()
    load_usage()
    print("Jarvis text debug mode. Type a command, or type exit.")

    while True:
        text = input("> ")
        try:
            handle_text(text)
        except SystemExit:
            break


# =========================
# RUN
# =========================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jarvis voice assistant")
    parser.add_argument("--text", action="store_true", help="Debug using typed commands instead of the microphone")
    args = parser.parse_args()

    if args.text:
        debug_text_loop()
    else:
        main()
