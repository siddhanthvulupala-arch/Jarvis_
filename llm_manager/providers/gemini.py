"""Gemini API adapter preserving FRIDAY's existing request behavior."""

import datetime


class GeminiProvider:
    def __init__(self, api_key, model="gemini-2.5-flash", search_model="gemini-2.5-flash"):
        self.model = model or "gemini-2.5-flash"
        self.search_model = search_model or "gemini-2.5-flash"
        self.client = None
        self.locked_until = None
        self._types = None

        if not api_key:
            return

        api_key = str(api_key).strip()
        try:
            from google import genai
            from google.genai import types

            self._types = types
            self.client = genai.Client(api_key=api_key)
        except Exception as error:
            print("[GEMINI] Initialization notice:", type(error).__name__)

    def generate(self, contents, use_grounding=False):
        if self.is_locked():
            return None

        if self.client is None:
            return None

        try:
            model_name = self.search_model if use_grounding else self.model
            config = None
            if use_grounding and self._types is not None:
                config = self._types.GenerateContentConfig(
                    tools=[self._types.Tool(google_search=self._types.GoogleSearch())],
                )

            response = self.client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config,
            )
            return (response.text or "").strip()
        except Exception as error:
            err_str = str(error)
            category = "Unknown error"
            if "429" in err_str or "quota" in err_str.lower() or "RESOURCE_EXHAUSTED" in err_str:
                category = "Quota limit reached (429)"
                now = datetime.datetime.utcnow()
                pt_now = now - datetime.timedelta(hours=7)
                tomorrow = pt_now + datetime.timedelta(days=1)
                self.locked_until = tomorrow.replace(
                    hour=0,
                    minute=0,
                    second=0,
                    microsecond=0,
                )
                print("[GEMINI] Locked until:", self.locked_until)
            elif "400" in err_str or "INVALID_ARGUMENT" in err_str:
                category = "Invalid argument or model not found (400)"
            elif "403" in err_str or "PERMISSION_DENIED" in err_str or "API key not valid" in err_str:
                category = "Authentication failed (Invalid API key)"
            elif "503" in err_str or "UNAVAILABLE" in err_str:
                category = "Service unavailable (503)"
            
            print(f"[GEMINI] Request failed: {category}")
            return None

    def is_locked(self):
        if not self.locked_until:
            return False
        if datetime.datetime.now() < self.locked_until:
            print("[GEMINI] Locked until:", self.locked_until)
            return True
        self.locked_until = None
        return False

