"""Minimal OpenRouter client: JSON chat completions, embeddings, and audio transcription."""

import json
import os
import re
import time

import requests

BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
RETRY_STATUS = {408, 429, 500, 502, 503, 504}
TRANSCRIBE_PROMPT = (
    "Transcribe the speech in this video verbatim. Start a new line and label the speaker (A:, B:, ...) "
    "whenever the speaker changes. If on-screen text adds context the speech lacks (a sign, a caption, "
    "a title card), note it in [brackets]. Output only the transcript."
)


class OpenRouterError(RuntimeError):
    pass


class OpenRouter:
    def __init__(self, api_key: str | None = None, timeout: float = 600, retries: int = 5):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not self.api_key:
            raise OpenRouterError("Set OPENROUTER_API_KEY.")
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "X-Title": "PlaylistCreator",
        })

    def _post(self, path: str, body: dict) -> dict:
        for attempt in range(self.retries + 1):
            try:
                resp = self.session.post(f"{BASE_URL}{path}", json=body, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt == self.retries:
                    raise OpenRouterError(str(exc)) from exc
            else:
                # 402 "given your current in-flight requests" clears once running requests settle.
                in_flight = resp.status_code == 402 and "in-flight" in resp.text
                if resp.status_code not in RETRY_STATUS and not in_flight:
                    if resp.status_code >= 400:
                        raise OpenRouterError(f"{resp.status_code}: {resp.text[:500]}")
                    data = resp.json()
                    # OpenRouter can return 200 with an upstream error in the body.
                    if "error" not in data:
                        return data
                    if attempt == self.retries:
                        raise OpenRouterError(str(data["error"])[:500])
                elif attempt == self.retries:
                    raise OpenRouterError(f"{resp.status_code}: {resp.text[:500]}")
            time.sleep(2 ** (attempt + 1))
        raise AssertionError("unreachable")

    def chat(self, model: str, messages: list[dict], **params) -> str:
        data = self._post("/chat/completions", {"model": model, "messages": messages, **params})
        return data["choices"][0]["message"]["content"] or ""

    def chat_json(self, model: str, system: str, user: str | list, schema: dict | None = None, **params) -> dict:
        """Chat that must return a JSON object. Uses a strict JSON schema when given one."""
        if schema:
            params["response_format"] = {"type": "json_schema", "json_schema": {"name": "result", "strict": True, "schema": schema}}
        else:
            params["response_format"] = {"type": "json_object"}
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        last_error = None
        for _ in range(3):
            text = self.chat(model, messages, **params)
            try:
                return parse_json(text)
            except ValueError as exc:
                last_error = exc
        raise OpenRouterError(f"{model} did not return valid JSON: {last_error}")

    def embed(self, model: str, texts: list[str], batch_size: int = 64) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            data = self._post("/embeddings", {"model": model, "input": texts[start:start + batch_size]})
            vectors.extend(item["embedding"] for item in sorted(data["data"], key=lambda d: d["index"]))
        return vectors

    def transcribe_youtube(self, model: str, url: str, max_tokens: int = 32_000) -> str:
        """Have a video-capable model (Gemini) watch a YouTube URL and transcribe it."""
        content = [
            {"type": "text", "text": TRANSCRIBE_PROMPT},
            {"type": "video_url", "video_url": {"url": url}},
        ]
        return self.chat(model, [{"role": "user", "content": content}], max_tokens=max_tokens, temperature=0).strip()


def parse_json(text: str) -> dict:
    """Parse a JSON object, tolerating markdown code fences around it."""
    text = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if fenced:
        text = fenced.group(1)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError(f"no JSON object in: {text[:200]!r}")
        value = json.loads(text[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value
