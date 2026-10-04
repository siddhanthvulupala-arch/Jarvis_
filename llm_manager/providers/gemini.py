"""Gemini API adapter preserving FRIDAY's existing request behavior."""

import datetime
import time


class GeminiProvider:
    def __init__(self, api_key, model="gemini-3.8-flash", search_model="gemini-3.8-flash"):
        self.model = model or "gemini-3.8-flash"
        self.search_model = search_model or "gemini-3.8-flash"
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
            primary_model = self.search_model if use_grounding else self.model
            fallback_models = [self.model, "gemini-3.8-flash", "gemini-flash-latest", "gemini-3.1-flash-lite"]
            candidates = []
            for m in ([primary_model] + fallback_models):
                if m and m not in candidates:
                    candidates.append(m)

            config = None
            if use_grounding and self._types is not None:
                config = self._types.GenerateContentConfig(
                    tools=[self._types.Tool(google_search=self._types.GoogleSearch())],
                )

            last_error = None
            # Step 1: Try with grounding if requested
            if use_grounding:
                try:
                    response = self.client.models.generate_content(
                        model=primary_model,
                        contents=contents,
                        config=config,
                    )
                    return (response.text or "").strip()
                except Exception as e:
                    last_error = e

            # Step 2: Try ungrounded generation across candidate models
            for cand_model in candidates:
                try:
                    response = self.client.models.generate_content(
                        model=cand_model,
                        contents=contents,
                    )
                    return (response.text or "").strip()
                except Exception as e:
                    last_error = e
                    err_str = str(e)
                    if "429" in err_str or "503" in err_str:
                        continue  # Try next available model in cascade

            if last_error:
                raise last_error
        except Exception as error:
            err_str = str(error)
            category = "Unknown error"
            if "429" in err_str or "quota" in err_str.lower() or "RESOURCE_EXHAUSTED" in err_str:
                category = "Rate limit / Quota reached (429)"
                self.locked_until = datetime.datetime.now() + datetime.timedelta(seconds=60)
                print("[GEMINI] Backing off until:", self.locked_until.strftime("%H:%M:%S"))
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

