"""Settings: config/settings.yaml for defaults, .env / environment for secrets and overrides."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    root: Path
    api_key: str
    model: str
    input_dir: Path
    manifest: Path
    output_dir: Path
    schema_path: Path
    pricing_path: Path
    system_prompt_path: Path
    transcript_prompt_path: Path
    include_transcript: bool
    transcript_csv: str
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
    def usage_log(self) -> Path:
        return self.output_dir / "usage.jsonl"

    @property
    def error_log(self) -> Path:
        return self.output_dir / "errors.jsonl"


def load_settings(root: Path = PROJECT_ROOT, require_key: bool = True) -> Settings:
    load_dotenv(root / ".env")
    cfg = yaml.safe_load((root / "config" / "settings.yaml").read_text(encoding="utf-8"))
    p, a, f, m, r, o = (cfg[k] for k in ("paths", "audio", "filename", "model", "run", "output"))

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if require_key and not api_key:
        raise SystemExit("GEMINI_API_KEY is not set. Copy .env.example to .env and add your key.")

    def path(key: str) -> Path:
        return (root / p[key]).resolve()

    return Settings(
        root=root,
        api_key=api_key,
        model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip(),
        input_dir=path("input_dir"),
        manifest=path("manifest"),
        output_dir=path("output_dir"),
        schema_path=path("schema"),
        pricing_path=path("pricing"),
        system_prompt_path=path("system_prompt"),
        transcript_prompt_path=path("transcript_prompt"),
        include_transcript=bool(cfg["extraction"]["include_transcript"]),
        transcript_csv="transcript.txt",
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
