import csv
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from call_pipeline import audio, pipeline
from call_pipeline.config import PROJECT_ROOT, load_settings
from call_pipeline.gemini_client import GeminiResult
from call_pipeline.normalize import build_row, parse_number
from call_pipeline.prompting import build_response_schema, build_system_prompt
from call_pipeline.schema import load_schema

SAMPLE = PROJECT_ROOT / "reference" / "call record" / "20261025-114133_IFARMERR__4004_01745196254-all.mp3"
REF_HEADER = PROJECT_ROOT / "reference" / "CEX data" / "CEX.csv"


@pytest.fixture(scope="module")
def schema():
    return load_schema(PROJECT_ROOT / "config" / "schema.yaml")


def test_schema_columns_match_reference_cex(schema):
    ref = next(csv.reader(REF_HEADER.open(encoding="utf-8-sig")))
    assert schema.columns[:len(ref)] == ref
    assert schema.columns[len(ref):] == ["eng_notes"]


def test_response_schema_lists_only_audio_fields(schema):
    enum = build_response_schema(schema)["properties"]["fields"]["items"]["properties"]["field"]["enum"]
    assert "current_landsize" in enum and "Call ID" not in enum and "Notes" not in enum


def test_system_prompt_contains_catalog(schema):
    p = build_system_prompt(load_settings(require_key=False), schema)
    assert "| farmland | multi | own, lease_mortgage |" in p


@pytest.mark.parametrize("text,expected", [("40,000", "40000"), ("৫০,০০০", "50000"), ("16.50", "16.5"),
                                           ("40 hajar", None), ("", None)])
def test_parse_number(text, expected):
    assert parse_number(text) == expected


def item(field, value, conf="high"):
    return {"field": field, "value": value, "confidence": conf, "evidence": "q", "timestamp": "00:01"}


def test_build_row_normalizes_and_flags(schema):
    raw = {
        "call_assessment": {"audio_quality": "poor", "is_kyc_call": True, "respondent_is_farmer": "yes",
                            "language_note": ""},
        "fields": [item("loan_amount", "40,000"), item("farmland", "Own, lease_mortgage"),
                   item("own", "16.5", "low"), item("yield", "lots"), item("farmer_assets", "tv, bike"),
                   item("loan_amount", "45000"), item("Call ID", "x")],
        "notes": " n ", "eng_notes": "e", "warnings": ["land in bigha"],
    }
    row = build_row(raw, schema)
    assert row.values["loan_amount"] == "45000"
    assert row.values["farmland"] == "own, lease_mortgage"
    assert "yield" not in row.values
    assert row.values["farmer_assets"] == "tv, bike"
    assert row.values["Notes"] == "n"
    kinds = {(i.field, i.kind) for i in row.issues}
    assert ("loan_amount", "duplicate") in kinds and ("own", "low_confidence") in kinds
    assert ("yield", "invalid_value") in kinds and ("farmer_assets", "unknown_code") in kinds
    assert ("Call ID", "not_in_schema") in kinds
    assert any(i.detail == "poor audio quality" for i in row.issues)


@pytest.mark.skipif(not SAMPLE.exists(), reason="reference recording missing")
def test_metadata_from_filename():
    s = load_settings(require_key=False)
    meta = audio.metadata_from_filename(SAMPLE.name, s.filename_regex, s.timezone_offset,
                                        s.phone_country_prefix, 720)
    assert meta["Phone"] == "8801745196254"
    assert meta["Started at"] == "2026-10-25 11:41:33 +0600"
    assert meta["Ended at"] == "2026-10-25 11:53:33 +0600"
    assert meta["Duration (seconds)"] == "720"


class FakeExtractor:
    def __init__(self):
        self.calls = 0

    def extract(self, rec, instruction):
        self.calls += 1
        return GeminiResult(
            {"call_assessment": {"audio_quality": "good", "is_kyc_call": True, "respondent_is_farmer": "yes",
                                 "language_note": ""},
             "fields": [item("loan_amount", "40000"), item("own", "16.5"), item("lease_mortgage", "132")],
             "notes": "Farmer loan nibe 40 hajar.", "eng_notes": "Farmer wants 40k.", "warnings": []},
            {"prompt_tokens": 100, "audio_prompt_tokens": 80, "output_tokens": 50, "thought_tokens": 0,
             "total_tokens": 150}, "fake-model")


@pytest.mark.skipif(not SAMPLE.exists(), reason="reference recording missing")
def test_end_to_end_with_fake_gemini(tmp_path, schema):
    inp = tmp_path / "in"
    inp.mkdir()
    shutil.copy(SAMPLE, inp / SAMPLE.name)
    (tmp_path / "manifest.csv").write_text(
        f"recording_file,Call ID,loan_id,Agent,Notes\n{SAMPLE.stem},int_X,75482,Agent One,ignored\n", encoding="utf-8")
    s = replace(load_settings(require_key=False), input_dir=inp, output_dir=tmp_path / "out",
                manifest=tmp_path / "manifest.csv")

    fake = FakeExtractor()
    res = pipeline.run(s, extractor=fake)
    assert (res["ok"], res["failed"], res["rows"]) == (1, 0, 1)

    rows = list(csv.DictReader((tmp_path / "out" / "CEX.csv").open(encoding="utf-8-sig")))
    assert len(rows) == 1
    r = rows[0]
    assert list(r.keys()) == schema.columns
    assert (r["Call ID"], r["loan_id"], r["Agent"]) == ("int_X", "75482", "Agent One")
    assert r["Phone"] == "8801745196254" and r["loan_amount"] == "40000"
    assert r["Notes"] == "Farmer loan nibe 40 hajar."      # manifest cannot overwrite audio fields
    assert r["eng_notes"] == "Farmer wants 40k."

    # second run is resumable: cached, no new API call
    res2 = pipeline.run(s, extractor=fake)
    assert fake.calls == 1 and res2["skipped"] == 1
    assert json.loads((tmp_path / "out" / "usage.jsonl").read_text().splitlines()[0])["model"] == "fake-model"


def test_evaluate_statuses_and_phone_matching(schema):
    from call_pipeline.evaluate import compare, phone_key, summarize
    assert phone_key("+8801727641576") == phone_key("01727641576") == "1727641576"
    truth = {"1727641576": {"loan_amount": "20000", "own": "65", "yield": "80", "farmland": "own, lease_mortgage",
                            "number_of_cows": "2", "business_type": "shop"}}
    pred = [{"Phone": "8801727641576", "Started at": "2026-11-01 18:31:00", "_stem": "x",
             "loan_amount": "20000", "own": "66", "yield": "3200", "farmland": "lease_mortgage, own",
             "number_of_goats": "3", "business_type": "kachamal"}]
    cells = {c["field"]: c for c in compare(pred, truth, schema)}
    assert cells["loan_amount"]["status"] == "match"
    assert cells["own"]["status"] == "mismatch"
    assert cells["yield"]["status"] == "mismatch" and cells["yield"]["note"].startswith("x40")
    assert cells["farmland"]["status"] == "match"           # order-insensitive
    assert "number_of_goats" not in cells                   # column absent from that sheet's form version
    assert "number_of_cows" in cells and cells["number_of_cows"]["status"] == "missed"
    assert "recall" in summarize(list(cells.values()), 1)
