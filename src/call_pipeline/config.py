"""Settings: config/settings.yaml for defaults, .env / environment for secrets and overrides."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    root: Path
    api_keys: tuple[str, ...]          # GEMINI_API_KEY, GEMINI_API_KEY_2, ... in that order
    model: str
    fallback_models: tuple[str, ...]   # tried after `model`, per key, when a model's quota is used up
    input_dir: Path
    manifest: Path
    output_dir: Path
    schema_path: Path
    pricing_path: Path
    system_prompt_path: Path
    transcript_prompt_path: Path
    include_transcript: bool
    transcript_csv: str
    supabase_url: str
    supabase_service_key: str
    poll_seconds: float
    stale_minutes: int
    quota_pause_minutes: float
    audio_extensions: tuple[str, ...]
    inline_limit_bytes: int
    filename_regex: str
    timezone_offset: str
    phone_country_prefix: str
    temperature: float
    thinking_budget: int | None
    workers: int
    requests_per_minute: int
    max_retries: int
    retry_base_seconds: float
    csv_encoding: str
    main_csv: str
    review_csv: str
    evidence_csv: str

    def call_dir(self, stem: str) -> Path:
        """output/<recording name>/ holds everything about one call."""
        return self.output_dir / stem

    def raw_file(self, stem: str) -> Path:
        return self.call_dir(stem) / "raw.json"

    @property
    def api_key(self) -> str:
        """First key; kept for scripts that only need one."""
        return self.api_keys[0] if self.api_keys else ""

    @property
    def models(self) -> tuple[str, ...]:
        return (self.model,) + tuple(m for m in self.fallback_models if m != self.model)

    @property
    def usage_log(self) -> Path:
        return self.output_dir / "usage.jsonl"

    @property
    def error_log(self) -> Path:
        return self.output_dir / "errors.jsonl"


def _collect_api_keys() -> tuple[str, ...]:
    """GEMINI_API_KEY, GEMINI_API_KEY_2, GEMINI_API_KEY_3 ... (blank and duplicate values are skipped)."""
    found = []
    for name, value in os.environ.items():
        m = re.fullmatch(r"GEMINI_API_KEY(?:_(\d+))?", name)
        if m and value.strip():
            found.append((int(m.group(1) or 1), value.strip()))
    keys: list[str] = []
    for _, value in sorted(found):
        if value not in keys:
            keys.append(value)
    return tuple(keys)


def load_settings(root: Path = PROJECT_ROOT, require_key: bool = True) -> Settings:
    load_dotenv(root / ".env")
    cfg = yaml.safe_load((root / "config" / "settings.yaml").read_text(encoding="utf-8"))
    p, a, f, m, r, o = (cfg[k] for k in ("paths", "audio", "filename", "model", "run", "output"))
    w = cfg.get("worker", {})

    api_keys = _collect_api_keys()
    if require_key and not api_keys:
        raise SystemExit("GEMINI_API_KEY is not set. Copy .env.example to .env and add your key.")
    fallback_env = os.getenv("GEMINI_FALLBACK_MODELS")
    fallbacks = tuple(x.strip() for x in (fallback_env.split(",") if fallback_env is not None
                                          else m.get("fallbacks") or []) if x.strip())

    def path(key: str) -> Path:
        return (root / p[key]).resolve()

    return Settings(
        root=root,
        api_keys=api_keys,
        model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip(),
        fallback_models=fallbacks,
        input_dir=path("input_dir"),
        manifest=path("manifest"),
        output_dir=path("output_dir"),
        schema_path=path("schema"),
        pricing_path=path("pricing"),
        system_prompt_path=path("system_prompt"),
        transcript_prompt_path=path("transcript_prompt"),
        include_transcript=bool(cfg["extraction"]["include_transcript"]),
        transcript_csv="transcript.txt",
        supabase_url=os.getenv("SUPABASE_URL", "").strip().rstrip("/"),
        supabase_service_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip(),
        poll_seconds=float(w.get("poll_seconds", 5)),
        stale_minutes=int(w.get("stale_minutes", 30)),
        quota_pause_minutes=float(w.get("quota_pause_minutes", 30)),
        audio_extensions=tuple(e.lower() for e in a["extensions"]),
        inline_limit_bytes=int(a["inline_limit_mb"] * 1024 * 1024),
        filename_regex=f["regex"],
        timezone_offset=str(f["timezone_offset"]),
        phone_country_prefix=str(f["phone_country_prefix"]),
        temperature=float(m["temperature"]),
        thinking_budget=m["thinking_budget"],
        workers=int(os.getenv("PIPELINE_WORKERS", r["workers"])),
        requests_per_minute=int(os.getenv("PIPELINE_RPM", r["requests_per_minute"])),
        max_retries=int(r["max_retries"]),
        retry_base_seconds=float(r["retry_base_seconds"]),
        csv_encoding=o["csv_encoding"],
        main_csv=o["main_csv"],
        review_csv=o["review_csv"],
        evidence_csv=o["evidence_csv"],
    )
