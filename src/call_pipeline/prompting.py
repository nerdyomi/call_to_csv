"""System prompt assembly and the JSON response schema sent to Gemini."""
from __future__ import annotations

from .config import Settings
from .schema import Schema

USER_INSTRUCTION = (
    "Listen to the attached CEX call recording and fill in the form as instructed. "
    "Return only the JSON object described by the response schema."
)


def build_system_prompt(settings: Settings, schema: Schema) -> str:
    base = settings.system_prompt_path.read_text(encoding="utf-8").strip()
    if settings.include_transcript:
        base += "\n\n" + settings.transcript_prompt_path.read_text(encoding="utf-8").strip()
    return f"{base}\n\n# FORM FIELDS\n\nOnly use these field names in `fields`.\n\n{schema.catalog_text()}\n"


def build_response_schema(schema: Schema, include_transcript: bool = True) -> dict:
    """JSON schema for Gemini structured output. Sparse: only filled fields are returned."""
    field_names = [f.name for f in schema.audio_fields if f.name not in ("Notes", "eng_notes")]
    transcript = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "speaker": {"type": "string", "enum": ["CEX", "farmer", "other"]},
                "time": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["speaker", "time", "text"],
        },
    }
    # Property order matters: the transcript is generated first so the fields are filled from it.
    props = {"transcript": transcript} if include_transcript else {}
    props.update({
            "call_assessment": {
                "type": "object",
                "properties": {
                    "audio_quality": {"type": "string", "enum": ["good", "fair", "poor"]},
                    "is_kyc_call": {"type": "boolean"},
                    "respondent_is_farmer": {"type": "string", "enum": ["yes", "no", "unclear"]},
                    "language_note": {"type": "string"},
                },
                "required": ["audio_quality", "is_kyc_call", "respondent_is_farmer", "language_note"],
            },
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string", "enum": field_names},
                        "value": {"type": "string"},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                        "evidence": {"type": "string"},
                        "timestamp": {"type": "string"},
                    },
                    "required": ["field", "value", "confidence", "evidence", "timestamp"],
                },
            },
            "notes": {"type": "string"},
            "eng_notes": {"type": "string"},
            "warnings": {"type": "array", "items": {"type": "string"}},
    })
    required = (["transcript"] if include_transcript else []) + ["call_assessment", "fields", "notes", "eng_notes", "warnings"]
    return {"type": "object", "properties": props, "required": required}
