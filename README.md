# FRIDAY / JARVIS

Windows voice assistant restored around the recovered `jarvis.py` core. It uses Gemini for online responses, Kokoro for local speech, Whisper for speech recognition, and Windows SAPI as a speech fallback. Edge neural speech remains available with `JARVIS_TTS=edge`; Piper is not used.

## Run

- Open PowerShell in the project folder and activate its environment once:

  ```powershell
  & ".\.venv\Scripts\Activate.ps1"
  ```

- Start voice mode with `python jarvis.py`.
- Start typed mode with `python jarvis.py --text`.
- `Start-Friday.ps1` remains available when the environment needs bootstrapping, and `Start-Friday.ps1 -Background` starts the assistant in a hidden process without holding up the calling startup script.
- Set `GEMINI_API_KEY` in the process or Windows user environment to enable Gemini. `GEMINI_MODEL` defaults to `gemini-3.5-flash` and `GEMINI_SEARCH_MODEL` defaults to `gemini-2.5-flash`.
- `JARVIS_KOKORO_VOICE` defaults to `af_heart`; `JARVIS_KOKORO_LANGUAGE` defaults to `a` (American English).

## Project files

- `jarvis.py`: recovered assistant core and entry point
- `friday_core/`: supporting modules from the separate Friday implementation
- `requirements.txt`: Python 3.11 runtime dependencies, including Kokoro
- `Start-Friday.ps1`: Python 3.11 environment bootstrap and launcher
- `app_aliases.json`: local application aliases
- `data/`: assistant-generated local data

The current recovered core continuously records short microphone windows and transcribes them with Whisper. A wake-word/VAD component was not present in the recovered source or local Git history, so wake-word restoration is being handled separately.
