from __future__ import annotations
import datetime, json, random, re, subprocess, webbrowser
from urllib.parse import quote_plus
from . import memory
from .settings import ALIASES_FILE
context = {"last_search": None}

def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip().translate(str.maketrans("", "", "!?.,")))

def needs_realtime(text: str) -> bool:
    return any(word in text for word in ("weather", "news", "latest", "current", "price", "stock", "crypto", "score", "schedule"))

def _open(target: str) -> None:
    if target.startswith(("http://", "https://")): webbrowser.open(target)
    else: subprocess.Popen(["cmd", "/c", "start", "", target], shell=False)

def local(text: str) -> str | None:
    handled, reply = memory.handle(text)
    if handled: return reply
    if text in {"hello", "hi", "hey", "good morning", "good evening"}: return random.choice(["Friday online. What is the mission?", "I'm here, boss. What do you need?"])
    if text in {"time", "what time is it"}: return datetime.datetime.now().strftime("It is %I:%M %p.")
    if text in {"date", "what is the date", "today"}: return datetime.datetime.now().strftime("Today is %B %d, %Y.")
    if text in {"stop speaking", "stop talking"}: return "__STOP__"
    if text.startswith("search "):
        query = text.removeprefix("search ").strip(); context["last_search"] = query
        if query: webbrowser.open(f"https://www.google.com/search?q={quote_plus(query)}"); return f"Searching for {query}."
    if text in {"search again", "open it"} and context["last_search"]:
        webbrowser.open(f"https://www.google.com/search?q={quote_plus(context['last_search'])}"); return "Opening the search results."
    if text.startswith("open "):
        name = text.removeprefix("open ").strip()
        try: aliases = json.loads(ALIASES_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError): aliases = {}
        if target := aliases.get(name): _open(target); return f"Opening {name}."
    return None
