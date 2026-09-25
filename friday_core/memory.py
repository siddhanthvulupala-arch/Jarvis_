from __future__ import annotations
import json
from .settings import MEMORY_FILE

def load() -> dict[str, str]:
    try:
        data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError): return {}

def save(items: dict[str, str]) -> None:
    MEMORY_FILE.write_text(json.dumps(items, indent=2), encoding="utf-8")

def handle(text: str) -> tuple[bool, str]:
    items = load()
    if text.startswith("remember "):
        fact = text.removeprefix("remember ").strip()
        if " is " in fact: key, value = fact.split(" is ", 1)
        elif " = " in fact: key, value = fact.split(" = ", 1)
        else: return True, "Tell me what to remember using a name and a value."
        items[key.strip().lower()] = value.strip(); save(items)
        return True, f"Remembered {key.strip()}."
    if text.startswith("forget "):
        key = text.removeprefix("forget ").strip().lower()
        if items.pop(key, None) is None: return True, "I do not have that saved."
        save(items); return True, f"Forgot {key}."
    if text in {"what do you remember", "list memory", "list memories", "show memory"}:
        return True, "; ".join(f"{key} is {value}" for key, value in items.items()) or "I do not have any saved memories yet."
    return False, ""

def context() -> str:
    return "; ".join(f"{key}: {value}" for key, value in load().items()) or "No saved facts."
