from __future__ import annotations
import datetime
from google import genai
import google.genai
from . import memory
from .settings import GEMINI_API_KEY, GEMINI_MODEL, GEMINI_SEARCH_MODEL
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

def ask(text: str, realtime: bool = False) -> str | None:
    if client is None: return None
    try:
        config = None
        if realtime: config = google.genai.types.GenerateContentConfig(tools=[google.genai.types.Tool(google_search=google.genai.types.GoogleSearch())])
        prompt = f"You are Friday, a calm capable personal assistant. Be brief and helpful. Date: {datetime.date.today()}. Saved context: {memory.context()}. Use grounded data only for current facts. User: {text}"
        response = client.models.generate_content(model=GEMINI_SEARCH_MODEL if realtime else GEMINI_MODEL, contents=prompt, config=config)
        return (response.text or "").strip() or None
    except Exception as error: print(f"Gemini error: {error}"); return None
