"""Shared measurement helpers for the isolated JARVIS voice-engine benchmarks.

Only needs numpy, soundfile and psutil, so every per-engine virtual environment
can import it without sharing any other packages with the others.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path

import numpy as np

EVAL_DIR = Path(__file__).resolve().parent
REPO_DIR = EVAL_DIR.parent

PRIMARY_SENTENCE = "Hello. This is a short local voice cloning test."
# Length ladder for latency-vs-length analysis (typical JARVIS reply sizes).
SENTENCE_SUITE = {
    "short": "Good evening, sir.",
    "primary": PRIMARY_SENTENCE,
    "medium": "All systems are online. I have finished indexing your project and found three files that need attention.",
    "long": ("I have reviewed the schedule for today. You have a meeting at ten, a code review at noon, "
             "and a reminder to call your family this evening. Shall I prepare a summary of each?"),
}

# Audio the benchmark must never accept as a "reference voice": synthetic JARVIS output.
SYNTHETIC_AUDIO_DIRS = [REPO_DIR / "voice_assets", REPO_DIR / ".tts_cache"]
SYNTHETIC_AUDIO_FILES = [REPO_DIR / "input.wav", REPO_DIR / "test_voice.mp3",
                         REPO_DIR / "cinematic_soundtrack.wav"]


class ResourceSampler:
    """Sample this process' RSS and CPU while a stage runs (context manager)."""

    def __init__(self, interval: float = 0.1) -> None:
        import psutil

        self.process = psutil.Process(os.getpid())
        self.interval = interval
        self.peak_rss = 0
        self.cpu_samples: list[float] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.cores = os.cpu_count() or 1

    def _run(self) -> None:
        self.process.cpu_percent(None)
        while not self._stop.is_set():
            try:
                self.peak_rss = max(self.peak_rss, self.process.memory_info().rss)
            except Exception:
                pass
            self._stop.wait(self.interval)
            try:
                self.cpu_samples.append(self.process.cpu_percent(None))
            except Exception:
                pass

    def __enter__(self) -> "ResourceSampler":
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join()

    def summary(self) -> dict:
        avg = sum(self.cpu_samples) / len(self.cpu_samples) if self.cpu_samples else 0.0
        peak = max(self.cpu_samples, default=0.0)
        return {
            "peak_rss_gib": round(self.peak_rss / 1024**3, 3),
            "cpu_avg_pct_of_one_core": round(avg, 1),
            "cpu_peak_pct_of_one_core": round(peak, 1),
            "cpu_avg_pct_of_machine": round(avg / self.cores, 1),
            "logical_cores": self.cores,
        }


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _forbidden_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for d in SYNTHETIC_AUDIO_DIRS:
        if d.is_dir():
            for p in d.rglob("*"):
                if p.is_file():
                    hashes[sha256(p)] = str(p)
    for p in SYNTHETIC_AUDIO_FILES:
        if p.is_file():
            hashes[sha256(p)] = str(p)
    return hashes


def validate_reference(wav_path: Path, transcript: str) -> dict:
    """Validate a reference recording + transcript. Never guesses or repairs.

    Returns {"ok": bool, "errors": [...], "warnings": [...], "info": {...}}.
    """
    import soundfile as sf

    errors: list[str] = []
    warnings: list[str] = []
    info: dict = {"path": str(wav_path)}

    if not wav_path.is_file():
        return {"ok": False, "errors": [f"reference WAV not found: {wav_path}"], "warnings": [], "info": info}

    digest = sha256(wav_path)
    info["sha256"] = digest
    info["size_kib"] = round(wav_path.stat().st_size / 1024, 1)
    clash = _forbidden_hashes().get(digest)
    if clash:
        errors.append(f"reference is identical to existing synthetic/unrelated JARVIS audio: {clash}")

    try:
        meta = sf.info(str(wav_path))
        data, sr = sf.read(str(wav_path), dtype="float32", always_2d=True)
    except Exception as exc:  # unreadable / not a real WAV
        errors.append(f"reference cannot be decoded as audio: {exc}")
        return {"ok": False, "errors": errors, "warnings": warnings, "info": info}

    mono = data.mean(axis=1)
    duration = len(mono) / sr
    rms = float(np.sqrt(np.mean(mono**2))) if len(mono) else 0.0
    peak = float(np.max(np.abs(mono))) if len(mono) else 0.0
    clipped = float(np.mean(np.abs(mono) >= 0.999)) if len(mono) else 0.0
    frame = max(int(sr * 0.02), 1)
    n = len(mono) // frame
    if n:
        frames_rms = np.sqrt(np.mean(mono[: n * frame].reshape(n, frame) ** 2, axis=1))
        silent_ratio = float(np.mean(frames_rms < 0.005))
    else:
        silent_ratio = 1.0
    info.update(duration_s=round(duration, 2), sample_rate=sr, channels=meta.channels, subtype=meta.subtype,
                rms=round(rms, 4), peak=round(peak, 3), clipped_ratio=round(clipped, 5),
                silent_frame_ratio=round(silent_ratio, 3))

    if duration < 2.0:
        errors.append(f"reference too short ({duration:.1f}s); need at least ~3s of clean speech")
    elif duration < 3.0:
        warnings.append(f"reference is short ({duration:.1f}s); 5-15s of speech clones best")
    if duration > 30.0:
        errors.append(f"reference too long ({duration:.1f}s); trim to 5-15s (cost scales with length)")
    elif duration > 20.0:
        warnings.append(f"reference is long ({duration:.1f}s); 5-15s is enough and is faster")
    if rms < 0.003 or peak < 0.02:
        errors.append("reference is essentially silent")
    if clipped > 0.005:
        warnings.append(f"reference clips on {clipped * 100:.2f}% of samples (distorted source hurts cloning)")
    if silent_ratio > 0.6:
        warnings.append(f"{silent_ratio * 100:.0f}% of the reference is silence")
    if sr < 16000:
        warnings.append(f"low sample rate {sr} Hz")

    words = len(transcript.split())
    info["transcript_words"] = words
    if not transcript.strip():
        errors.append("transcript is empty")
    else:
        speech_s = max(duration * (1 - silent_ratio), 0.1)
        wps = words / speech_s
        info["transcript_words_per_speech_second"] = round(wps, 2)
        # Natural speech is ~2-4 words/s. Far outside this means the transcript
        # is almost certainly not what is spoken in the file.
        if wps > 6.5 or words / max(duration, 0.1) < 0.6:
            errors.append(f"transcript length ({words} words) does not plausibly match a {duration:.1f}s recording")
        elif wps > 5.0 or words / max(duration, 0.1) < 1.0:
            warnings.append(f"transcript/speech rate looks unusual ({wps:.1f} words/s) - verify the transcript is exact")

    return {"ok": not errors, "errors": errors, "warnings": warnings, "info": info}


def audio_integrity(wav: np.ndarray, sr: int, written_path: Path | None = None) -> dict:
    """Objective sanity checks on generated audio (not a quality score)."""
    import soundfile as sf

    wav = np.asarray(wav, dtype=np.float32).reshape(-1)
    issues: list[str] = []
    duration = len(wav) / sr if sr else 0.0
    finite = bool(np.isfinite(wav).all())
    rms = float(np.sqrt(np.mean(wav**2))) if len(wav) else 0.0
    peak = float(np.max(np.abs(wav))) if len(wav) else 0.0
    clipped = float(np.mean(np.abs(wav) >= 0.999)) if len(wav) else 0.0
    frame = max(int(sr * 0.02), 1)
    n = len(wav) // frame
    silent = float(np.mean(np.sqrt(np.mean(wav[: n * frame].reshape(n, frame) ** 2, axis=1)) < 0.005)) if n else 1.0
    if not finite:
        issues.append("contains NaN/Inf")
    if duration < 0.5:
        issues.append("output shorter than 0.5s")
    if rms < 0.005:
        issues.append("output is near-silent")
    if clipped > 0.01:
        issues.append("output clips heavily")
    if duration > 20:
        issues.append("output suspiciously long (possible runaway generation)")
    result = {"duration_s": round(duration, 3), "sample_rate": sr, "rms": round(rms, 4), "peak": round(peak, 3),
              "clipped_ratio": round(clipped, 5), "silent_frame_ratio": round(silent, 3), "finite": finite}
    if written_path is not None:
        try:
            back, back_sr = sf.read(str(written_path), dtype="float32")
            result["readback_ok"] = bool(back_sr == sr and abs(len(back) - len(wav)) <= 1)
            if not result["readback_ok"]:
                issues.append("written WAV does not match generated audio")
        except Exception as exc:
            result["readback_ok"] = False
            issues.append(f"written WAV unreadable: {exc}")
    result["issues"] = issues
    result["ok"] = not issues
    return result


def rtf(synthesis_s: float, audio_s: float) -> float:
    return synthesis_s / audio_s if audio_s else float("inf")


def write_json(path: Path, payload: dict) -> None:
    payload = dict(payload)
    payload.setdefault("written_at", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
