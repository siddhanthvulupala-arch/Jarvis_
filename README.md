# FRIDAY / JARVIS

Windows voice assistant restored around the recovered `jarvis.py` core. It uses Gemini for online responses, profile-based ElevenLabs speech with Kokoro and Windows SAPI fallbacks, Whisper for speech recognition, and keeps the existing Edge/Kokoro/robot voice modes. Piper is not used.

## Run

- Open PowerShell in the project folder and activate its environment once:

  ```powershell
  & ".\.venv\Scripts\Activate.ps1"
  ```

- Start JARVIS with `python jarvis.py`; it starts the existing voice backend, serves the UI on `http://127.0.0.1:8765/`, and opens that page in the default browser. The `--text` option keeps the existing terminal text loop and also starts the UI.
- `Start-Friday.ps1` starts the assistant and the UI together. `Start-Friday.ps1 -Background` starts the assistant hidden; its UI still opens in the default browser. The UI bridge is optional and a bind or browser-launch failure does not stop JARVIS.
- Set `GEMINI_API_KEY` in the process or Windows user environment to enable Gemini. `GEMINI_MODEL` defaults to `gemini-3.5-flash` and `GEMINI_SEARCH_MODEL` defaults to `gemini-2.5-flash`.
- Set `ELEVENLABS_API_KEY` in the process or Windows user environment to enable profile voices. In PowerShell for the current session, run `$env:ELEVENLABS_API_KEY = "your-key"`; for persistence, add it as a Windows user environment variable. The key is never stored in this repository. ElevenLabs uses the standard library HTTP client and needs no added package. Without a key or if ElevenLabs fails, speech falls back to Kokoro, then Microsoft David.
- Say `switch to Friday`, `change to Friday`, `use Friday voice`, `switch voice to Friday`, or `change voice to Friday` to select FRIDAY. Replace `Friday` with `Jarvis` for the other profile. The selection is saved in `data/voice_profile.json` and defaults to JARVIS for existing installations.
- `JARVIS_KOKORO_VOICE` defaults to `af_heart`; `JARVIS_KOKORO_LANGUAGE` defaults to `a` (American English).

Voice routing for either profile is ElevenLabs (profile-specific voice ID) → Kokoro → Microsoft David.

The UI keeps the existing Three.js core and adds a small text console plus a text/voice mode control. Text requests are sent to `jarvis.py`'s existing `handle_text` router. Voice mode enables the existing microphone loop and requests browser fullscreen; text mode pauses that loop while the UI is connected. If the browser closes, voice listening resumes after a 12-second connection timeout.

The local JSON bridge is loopback-only and uses `POST /api/message` with `{"type":"USER_TEXT","text":"..."}` or `{"type":"VOICE_INPUT","text":"..."}`, `POST /api/mode` with `{"type":"MODE_CHANGED","mode":"text|voice"}`, and `GET /api/events?since=<event-id>` for backend state and response events. Backend `speaking` state brackets the existing TTS call and drives the core's speech pulse; `listening`, `thinking`, and `error` are also emitted. No frontend AI or alternate speech pipeline is used.

## Project files

- `jarvis.py`: recovered assistant core and entry point
- `friday_core/`: supporting modules from the separate Friday implementation
- `requirements.txt`: Python 3.11 runtime dependencies, including Kokoro
- `Start-Friday.ps1`: Python 3.11 environment bootstrap and launcher
- `app_aliases.json`: local application aliases
- `data/`: assistant-generated local data

The current recovered core continuously records short microphone windows and transcribes them with Whisper. A wake-word/VAD component was not present in the recovered source or local Git history, so wake-word restoration is being handled separately.
