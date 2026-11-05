"""Thin wrapper around google-genai: upload/inline audio, throttle, retry, parse JSON."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field

from google import genai
from google.genai import errors, types

from .audio import Recording
from .config import Settings

log = logging.getLogger(__name__)


class RateLimiter:
    """Spaces calls so that at most `rpm` start per minute, across all threads."""

    def __init__(self, rpm: int):
        self.interval = 60.0 / max(rpm, 1)
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next)
            self._next = start + self.interval
        if start > now:
            time.sleep(start - now)


@dataclass
class GeminiResult:
    data: dict
    usage: dict = field(default_factory=dict)
    model: str = ""


def _retry_delay(exc: Exception, default: float) -> float:
    """Honour 'retry in 12.3s' hints from 429 responses."""
    m = re.search(r"retry(?:Delay)?\D{0,12}(\d+(?:\.\d+)?)\s*s", str(exc), re.I)
    return float(m.group(1)) + 1 if m else default


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, errors.APIError):
        return exc.code in (408, 429, 500, 502, 503, 504)
    return isinstance(exc, (ConnectionError, TimeoutError, json.JSONDecodeError))


def _usage_dict(resp) -> dict:
    """Token counts for cost tracking. Field names differ between SDK versions, so be defensive:
    a usage-parsing problem must never lose an extraction."""
    try:
        u = resp.usage_metadata
        if u is None:
            return {}
        g = lambda *names: next((getattr(u, n) for n in names if getattr(u, n, None) is not None), 0)
        audio = 0
        for d in getattr(u, "prompt_tokens_details", None) or []:
            if str(getattr(d, "modality", "")).upper().endswith("AUDIO"):
                audio += d.token_count or 0
        return {
            "prompt_tokens": g("prompt_token_count"),
            "audio_prompt_tokens": audio,
            "output_tokens": g("response_token_count", "candidates_token_count"),
            "thought_tokens": g("thoughts_token_count"),
            "total_tokens": g("total_token_count"),
        }
    except Exception:
        log.warning("could not read usage metadata", exc_info=True)
        return {}


class GeminiExtractor:
    def __init__(self, settings: Settings, system_prompt: str, response_schema: dict, client=None):
        self.s = settings
        self.system_prompt = system_prompt
        self.response_schema = response_schema
        self.client = client or genai.Client(api_key=settings.api_key)
        self.limiter = RateLimiter(settings.requests_per_minute)

    def _config(self) -> types.GenerateContentConfig:
        kwargs = dict(
            system_instruction=self.system_prompt,
            temperature=self.s.temperature,
            response_mime_type="application/json",
            response_json_schema=self.response_schema,
        )
        if self.s.thinking_budget is not None:
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=int(self.s.thinking_budget))
        return types.GenerateContentConfig(**kwargs)

    def _audio_part(self, rec: Recording):
        """Returns (part, uploaded_file_or_None)."""
        if rec.size <= self.s.inline_limit_bytes:
            return types.Part.from_bytes(data=rec.path.read_bytes(), mime_type=rec.mime_type), None
        up = self.client.files.upload(file=str(rec.path), config=types.UploadFileConfig(mime_type=rec.mime_type))
        while up.state and up.state.name == "PROCESSING":
            time.sleep(2)
            up = self.client.files.get(name=up.name)
        if up.state and up.state.name == "FAILED":
            raise RuntimeError(f"Gemini failed to process uploaded audio {rec.name}")
        return types.Part.from_uri(file_uri=up.uri, mime_type=rec.mime_type), up

    def extract(self, rec: Recording, instruction: str) -> GeminiResult:
        part, uploaded = self._audio_part(rec)
        try:
            return self._generate_with_retry(part, instruction, rec.name)
        finally:
            if uploaded is not None:
                try:
                    self.client.files.delete(name=uploaded.name)
                except Exception:  # best effort; files expire on their own after 48h
                    log.warning("could not delete uploaded file for %s", rec.name)

    def _generate_with_retry(self, part, instruction: str, label: str) -> GeminiResult:
        last: Exception | None = None
        for attempt in range(self.s.max_retries + 1):
            self.limiter.wait()
            try:
                resp = self.client.models.generate_content(
                    model=self.s.model, contents=[part, instruction], config=self._config())
                text = resp.text
                if not text:
                    raise json.JSONDecodeError("empty response (blocked or truncated)", "", 0)
                return GeminiResult(json.loads(text), _usage_dict(resp), self.s.model)
            except Exception as exc:
                last = exc
                if not _is_retryable(exc) or attempt == self.s.max_retries:
                    break
                delay = _retry_delay(exc, self.s.retry_base_seconds * 2 ** attempt)
                log.warning("%s: attempt %d failed (%s); retrying in %.0fs", label, attempt + 1,
                            str(exc)[:120], delay)
                time.sleep(delay)
        raise last  # type: ignore[misc]
