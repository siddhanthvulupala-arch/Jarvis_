from __future__ import annotations
import numpy as np
import sounddevice as sd
import whisper
from scipy.io.wavfile import write
from win32com.client import Dispatch
from .settings import ROOT, SILENCE_THRESHOLD, VOICE_NAME, VOICE_RATE, VOICE_VOLUME, WHISPER_MODEL
_model = None
_speaker = None

def setup_voice() -> None:
    global _speaker
    _speaker = Dispatch("SAPI.SpVoice"); _speaker.Rate, _speaker.Volume = VOICE_RATE, VOICE_VOLUME
    for voice in _speaker.GetVoices():
        if VOICE_NAME in voice.GetDescription().lower(): _speaker.Voice = voice; break

def speak(text: str) -> None:
    print(f"Friday: {text}")
    if _speaker is None: setup_voice()
    _speaker.Speak(str(text))

def stop() -> None:
    if _speaker is not None: _speaker.Speak("", 2)

def listen(duration: int = 5, device: int | None = None) -> tuple[str, float]:
    global _model
    try:
        audio = sd.rec(int(duration * 16000), samplerate=16000, channels=1, dtype="float32", device=device); sd.wait()
    except Exception as error: print(f"Microphone error: {error}"); return "", 0.0
    volume = float(np.sqrt(np.mean(audio ** 2)))
    if volume < SILENCE_THRESHOLD: return "", 0.0
    audio = audio.flatten(); peak = np.max(np.abs(audio))
    if peak: audio /= peak
    wav_path = ROOT / "data" / "input.wav"; write(wav_path, 16000, audio)
    try:
        _model = _model or whisper.load_model(WHISPER_MODEL)
        result = _model.transcribe(str(wav_path), fp16=False, language="en", temperature=0.0)
        segment = (result.get("segments") or [{}])[0]
        return result.get("text", "").lower().strip(), max(1-segment.get("no_speech_prob", 1), segment.get("avg_logprob", -1)+1)
    except Exception as error: print(f"Whisper error: {error}"); return "", 0.0
