"""Profile-based voice routing for the FRIDAY/JARVIS assistant."""
from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable


VOICE_IDS = {
    "jarvis": "3mVBiP4gitRSZBme0mNC",
    "friday": "DXFkLCBUTmvXpp2QwZjA",
}


class VoiceManager:
    def __init__(
        self,
        kokoro_speak: Callable[[str], None],
        sapi_speak: Callable[[str], None],
        play_audio: Callable[[str], None],
        state_path: Path,
        api_key: str | None = None,
        legacy_speak: Callable[[str], None] | None = None,
    ) -> None:
        self.kokoro_speak = kokoro_speak
        self.sapi_speak = sapi_speak
        self.play_audio = play_audio
        self.state_path = Path(state_path)
        self.api_key = api_key if api_key is not None else os.getenv("ELEVENLABS_API_KEY")
        self.legacy_speak = legacy_speak
        self.legacy_mode: str | None = None
        self.profile = self._load_profile()
        self._logged_failures: set[str] = set()

    def _load_profile(self) -> str:
        try:
            profile = json.loads(self.state_path.read_text(encoding="utf-8")).get("profile", "jarvis")
            return profile if profile in VOICE_IDS else "jarvis"
        except (OSError, ValueError, AttributeError):
            return "jarvis"

    def switch_profile(self, profile: str) -> str:
        profile = profile.lower()
        if profile not in VOICE_IDS:
            raise ValueError(f"Unknown voice profile: {profile}")
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.state_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps({"profile": profile}, indent=2) + "\n", encoding="utf-8")
        temp_path.replace(self.state_path)
        self.profile = profile
        self.legacy_mode = None
        return profile

    def speak(self, text: str, cache_tts: bool = False) -> None:
        text = str(text)
        if self.legacy_mode and self.legacy_speak:
            self.legacy_speak(text, cache_tts)
            return

        try:
            self._elevenlabs_speak(text)
            return
        except Exception as error:
            if self._log_failure("ElevenLabs", error):
                print("[VOICE] ElevenLabs failed; falling back to Kokoro")
        try:
            self.kokoro_speak(text)
            return
        except Exception as error:
            if self._log_failure("Kokoro", error):
                print("[VOICE] Kokoro failed; falling back to Microsoft David")
        try:
            self.sapi_speak(text)
        except Exception as error:
            self._log_failure("Microsoft David", error)

    def _log_failure(self, provider: str, error: Exception) -> bool:
        if provider not in self._logged_failures:
            print(f"[VOICE] {provider} unavailable: {self._diagnostic(error)}")
            self._logged_failures.add(provider)
            return True
        return False

    def _diagnostic(self, error: Exception) -> str:
        if isinstance(error, urllib.error.HTTPError):
            try:
                response_body = error.read().decode("utf-8", errors="replace")
            except Exception:
                response_body = "<response body unavailable>"
            response_body = self._redact_secrets(response_body)
            if len(response_body) > 2000:
                response_body = response_body[:2000] + "... [truncated]"
            reason = self._redact_secrets(str(error.reason))
            status = f"HTTP {error.code} {reason}"
            return f"{status}; response: {response_body or '<empty response body>'}"
        message = self._redact_secrets(str(error))
        return f"{type(error).__name__}: {message}"

    def _redact_secrets(self, message: str) -> str:
        if self.api_key:
            message = message.replace(self.api_key, "[REDACTED]")
        # Also protect a key if a server echoes it in a JSON or text diagnostic.
        return re.sub(
            r'(?i)(["\']?(?:xi-api-key|api[_-]?key|authorization)["\']?\s*[:=]\s*["\']?)[^"\'\s,}]+',
            r"\1[REDACTED]",
            message,
        )

    def _elevenlabs_speak(self, text: str) -> None:
        if not self.api_key:
            raise RuntimeError("ELEVENLABS_API_KEY is not configured")
        voice_id = VOICE_IDS[self.profile]
        request = urllib.request.Request(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128",
            data=json.dumps({
                "text": text,
                "model_id": "eleven_multilingual_v2",
            }).encode("utf-8"),
            headers={
                "xi-api-key": self.api_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            audio = response.read()
        if not audio:
            raise RuntimeError("ElevenLabs returned empty audio")
        temp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as audio_file:
                temp_path = audio_file.name
                audio_file.write(audio)
            self.play_audio(temp_path)
        finally:
            if temp_path:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass


def match_voice_switch(text: str) -> str | None:
    """Match the supported voice-switch phrasings without broad substring rules."""
    normalized = " ".join(text.lower().strip().rstrip(".!?,").split())
    patterns = (
        r"(?:switch|change) to (jarvis|friday)",
        r"use (jarvis|friday) voice",
        r"(?:switch|change) voice to (jarvis|friday)",
    )
    import re
    for pattern in patterns:
        match = re.fullmatch(pattern, normalized)
        if match:
            return match.group(1)
    return None
