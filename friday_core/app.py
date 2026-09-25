from __future__ import annotations
import argparse
from .ai import ask
from .commands import local, needs_realtime, normalize
from .maths import calculate, looks_like_math
from .settings import CONFIDENCE_THRESHOLD
from .speech import listen, setup_voice, speak, stop

def handle(text: str) -> bool:
    text = normalize(text)
    if not text: return True
    if text in {"exit", "quit", "shutdown", "shut down"}: speak("Shutting down."); return False
    reply = local(text)
    if reply == "__STOP__": stop(); return True
    if reply is None and looks_like_math(text): reply = calculate(text)
    if reply is None: reply = ask(text, realtime=needs_realtime(text))
    speak(reply or "I could not reach the AI service. Check your Gemini API key or try a local command.")
    return True

def main() -> None:
    parser = argparse.ArgumentParser(description="Friday voice assistant"); parser.add_argument("--text", action="store_true", help="use typed commands")
    args = parser.parse_args(); setup_voice(); print("Friday is online.")
    if args.text:
        while handle(input("> ")): pass
        return
    while True:
        text, confidence = listen()
        if not text: continue
        if confidence < CONFIDENCE_THRESHOLD: speak("Sorry, I did not catch that properly."); continue
        if not handle(text): break
