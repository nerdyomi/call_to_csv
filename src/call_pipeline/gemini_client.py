"""Thin wrapper around google-genai: upload/inline audio, throttle, retry, parse JSON.

Failover: every (model, API key) pair is tried in order - first the main model on each key,
then each fallback model on each key. A pair is dropped for the rest of the run when its daily
quota is used up, its key is rejected, or the model is unavailable. Overload errors (503) are
retried briefly and then the next pair is tried, without dropping anything.
"""
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

MAX_RETRY_WAIT = 120  # seconds; a longer server-side wait means a daily quota, which retrying cannot fix


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
    key_tail: str = ""   # last 4 characters of the API key that served the call (never the whole key)


class QuotaExhausted(RuntimeError):
    """Every key/model combination is unusable for now (daily quota, rejected key, model gone)."""


def _retry_delay(exc: Exception, default: float) -> float:
    """Honour 'retry in 12.3s' hints from 429 responses ('1h2m3.4s' forms are converted too)."""
    m = re.search(r"retry in\s+((?:\d+(?:\.\d+)?[hms])+)", str(exc), re.I)
    if not m:
        m = re.search(r"retryDelay\D{0,6}((?:\d+(?:\.\d+)?[hms])+)", str(exc), re.I)
    if not m:
        return default
    secs = sum(float(n) * {"h": 3600, "m": 60, "s": 1}[u.lower()] for n, u in re.findall(r"(\d+(?:\.\d+)?)([hms])", m.group(1)))
    return secs + 1


def classify(exc: Exception, default_delay: float) -> tuple[str, float]:
    """What to do after an error.

    retry  - temporary; try the same key+model again after the returned delay
    quota  - this key+model has no allowance left for hours: drop the pair
    key    - this API key is rejected / not allowed: drop the key (all models)
    model  - model not available to this key: drop the pair
    fatal  - our request is wrong: do not retry anywhere
    """
    if isinstance(exc, errors.APIError):
        code, text = exc.code, str(exc)
        if code == 429:
            delay = _retry_delay(exc, default_delay)
            return ("quota", delay) if delay > MAX_RETRY_WAIT else ("retry", delay)
        if code in (408, 500, 502, 503, 504):
            return "retry", default_delay
        if code in (401, 403) or (code == 400 and re.search(r"API[_ ]KEY", text, re.I)):
            return "key", 0
        if code == 404:
            return "model", 0
        return "fatal", 0
    if isinstance(exc, (ConnectionError, TimeoutError, json.JSONDecodeError)):
        return "retry", default_delay
    return "fatal", 0


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
    def __init__(self, settings: Settings, system_prompt: str, response_schema: dict,
                 clients: list | None = None, client=None):
        """`clients` (one per API key, same order) lets tests inject fakes; normally built from settings."""
        self.s = settings
        self.system_prompt = system_prompt
        self.response_schema = response_schema
        provided = clients if clients is not None else ([client] if client is not None else None)
        if provided is not None:
            self.clients = list(provided)
            keys = list(settings.api_keys)
            self.tails = [keys[i][-4:] if i < len(keys) else f"fake{i}" for i in range(len(provided))]
        else:
            self.clients = [genai.Client(api_key=k) for k in settings.api_keys]
            self.tails = [k[-4:] for k in settings.api_keys]
        self.limiters = [RateLimiter(settings.requests_per_minute) for _ in self.clients]
        self.models = list(settings.models)
        self._dead_pairs: dict[tuple[str, int], str] = {}
        self._dead_keys: dict[int, str] = {}
        self._lock = threading.Lock()
        self._uploads: dict = {}

    # ---- availability bookkeeping ------------------------------------------------------------
    def _available(self) -> list[tuple[str, int]]:
        with self._lock:
            return [(m, k) for m in self.models for k in range(len(self.clients))
                    if k not in self._dead_keys and (m, k) not in self._dead_pairs]

    @property
    def quota_exhausted(self) -> str | None:
        """Non-empty text once nothing is usable any more (stops the rest of the batch)."""
        if self._available():
            return None
        with self._lock:
            why = [f"key ...{self.tails[k]}: {r}" for k, r in self._dead_keys.items()]
            why += [f"{m} on key ...{self.tails[k]}: {r}" for (m, k), r in self._dead_pairs.items()]
        return "no usable Gemini key/model left - " + "; ".join(why)

    def _drop(self, kind: str, model: str, k: int, exc: Exception) -> None:
        reason = f"{kind} ({str(exc)[:110].strip()})"
        with self._lock:
            if kind == "key":
                self._dead_keys[k] = reason
            else:
                self._dead_pairs[(model, k)] = reason
        log.warning("dropping %s on key ...%s for this run: %s",
                    "key" if kind == "key" else model, self.tails[k], reason)

    # ---- request building --------------------------------------------------------------------
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

    def _audio_part(self, rec: Recording, k: int, uploads: dict):
        """Inline bytes for normal files; big files are uploaded once per key (uploads belong to one key)."""
        if rec.size <= self.s.inline_limit_bytes:
            return types.Part.from_bytes(data=rec.path.read_bytes(), mime_type=rec.mime_type)
        if k not in uploads:
            client = self.clients[k]
            up = client.files.upload(file=str(rec.path), config=types.UploadFileConfig(mime_type=rec.mime_type))
            while up.state and up.state.name == "PROCESSING":
                time.sleep(2)
                up = client.files.get(name=up.name)
            if up.state and up.state.name == "FAILED":
                raise RuntimeError(f"Gemini failed to process uploaded audio {rec.name}")
            uploads[k] = up
        up = uploads[k]
        return types.Part.from_uri(file_uri=up.uri, mime_type=rec.mime_type)

    # ---- the call ----------------------------------------------------------------------------
    def extract(self, rec: Recording, instruction: str) -> GeminiResult:
        uploads: dict[int, object] = {}
        last: Exception | None = None
        try:
            for model, k in self._available():
                if k in self._dead_keys or (model, k) in self._dead_pairs:
                    continue  # another thread dropped it meanwhile
                try:
                    part = self._audio_part(rec, k, uploads)
                except Exception as exc:
                    kind, _ = classify(exc, 0)
                    if kind == "fatal":
                        raise
                    last = exc
                    if kind != "retry":
                        self._drop(kind, model, k, exc)
                    continue
                for attempt in range(self.s.max_retries + 1):
                    self.limiters[k].wait()
                    try:
                        resp = self.clients[k].models.generate_content(
                            model=model, contents=[part, instruction], config=self._config())
                        text = resp.text
                        if not text:
                            raise json.JSONDecodeError("empty response (blocked or truncated)", "", 0)
                        return GeminiResult(json.loads(text), _usage_dict(resp), model, self.tails[k])
                    except Exception as exc:
                        last = exc
                        kind, delay = classify(exc, self.s.retry_base_seconds * 2 ** attempt)
                        if kind == "fatal":
                            raise
                        if kind != "retry":
                            self._drop(kind, model, k, exc)
                            break
                        if attempt == self.s.max_retries:
                            log.warning("%s: %s on key ...%s still failing (%s); trying next",
                                        rec.name, model, self.tails[k], str(exc)[:100])
                            break
                        log.warning("%s: %s key ...%s attempt %d failed (%s); retrying in %.0fs",
                                    rec.name, model, self.tails[k], attempt + 1, str(exc)[:100], delay)
                        time.sleep(delay)
        finally:
            for k, up in uploads.items():
                try:
                    self.clients[k].files.delete(name=up.name)
                except Exception:  # best effort; files expire on their own after 48h
                    log.warning("could not delete uploaded file for %s", rec.name)
        stop = self.quota_exhausted
        if stop:
            raise QuotaExhausted(stop)
        raise last if last else RuntimeError("no Gemini key configured")
