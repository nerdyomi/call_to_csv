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


# ---- Phase 1a: transcript in the same pass ----

def test_response_schema_puts_transcript_first_and_can_switch_off(schema):
    on = build_response_schema(schema, include_transcript=True)
    assert list(on["properties"])[0] == "transcript" and "transcript" in on["required"]
    turn = on["properties"]["transcript"]["items"]["properties"]
    assert turn["speaker"]["enum"] == ["CEX", "farmer", "other"]
    off = build_response_schema(schema, include_transcript=False)
    assert "transcript" not in off["properties"] and "transcript" not in off["required"]


def test_system_prompt_includes_transcript_section_only_when_enabled(schema):
    s = load_settings(require_key=False)
    assert "TRANSCRIPT" in build_system_prompt(s, schema)
    assert "TRANSCRIPT" not in build_system_prompt(replace(s, include_transcript=False), schema)


def test_transcript_normalization_and_ordering_warning(schema):
    raw = {"transcript": [{"speaker": "CEX", "time": "7", "text": " as salam oa alaikum. "},
                          {"speaker": "farmer", "time": "00:14", "text": "ji bujhte parsi."},
                          {"speaker": "CEX", "time": "00:00:10", "text": "loan lagbe?"},
                          {"speaker": "farmer", "time": "00:00:20", "text": "  "}],
           "fields": [{"field": "loan_amount", "value": "40000", "confidence": "high", "evidence": "q",
                       "timestamp": "01:48"}]}
    row = build_row(raw, schema)
    assert row.transcript == [{"speaker": "CEX", "time": "00:00:07", "text": "as salam oa alaikum."},
                              {"speaker": "farmer", "time": "00:00:14", "text": "ji bujhte parsi."},
                              {"speaker": "CEX", "time": "00:00:10", "text": "loan lagbe?"}]   # blank turn dropped
    assert row.evidence["loan_amount"]["timestamp"] == "00:01:48"
    assert any("goes backwards at 00:00:10" in i.detail for i in row.issues)


def test_format_transcript_matches_requested_layout():
    from call_pipeline.writer import format_transcript
    out = format_transcript([{"speaker": "CEX", "time": "00:00:07", "text": "as salam oa alaikum."},
                             {"speaker": "farmer", "time": "00:00:14", "text": "ji bujhte parsi."}])
    assert out == "CEX: as salam oa alaikum. (00:00:07)\nfarmer: ji bujhte parsi. (00:00:14)\n"


@pytest.mark.skipif(not SAMPLE.exists(), reason="reference recording missing")
def test_end_to_end_writes_transcript_txt(tmp_path):
    inp = tmp_path / "in"
    inp.mkdir()
    shutil.copy(SAMPLE, inp / SAMPLE.name)

    class WithTranscript(FakeExtractor):
        def extract(self, rec, instruction):
            res = super().extract(rec, instruction)
            res.data["transcript"] = [{"speaker": "CEX", "time": "00:00:07", "text": "as salam oa alaikum."}]
            return res

    s = replace(load_settings(require_key=False), input_dir=inp, output_dir=tmp_path / "out",
                manifest=tmp_path / "none.csv")
    pipeline.run(s, extractor=WithTranscript())
    f = tmp_path / "out" / SAMPLE.stem / "transcript.txt"
    assert f.read_text(encoding="utf-8") == "CEX: as salam oa alaikum. (00:00:07)\n"


# ---- retry behaviour ----

def test_retry_delay_parsing_and_quota_fail_fast():
    from call_pipeline.gemini_client import _retry_delay
    assert _retry_delay(Exception("Please retry in 12.5s."), 99) == 13.5
    assert _retry_delay(Exception("Please retry in 20h23m15.2s."), 99) == 20 * 3600 + 23 * 60 + 16.2
    assert _retry_delay(Exception("boom"), 99) == 99


def test_daily_quota_stops_batch_without_sleeping(tmp_path):
    from google.genai import errors
    from call_pipeline.gemini_client import GeminiExtractor, QuotaExhausted

    class Models:
        calls = 0

        def generate_content(self, **kw):
            Models.calls += 1
            raise errors.ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                                                     "message": "Quota exceeded, limit: 20. Please retry in 20h23m15.2s."}})

    class Client:
        models = Models()

    rec_file = tmp_path / "a.mp3"
    rec_file.write_bytes(b"x")
    s = replace(load_settings(require_key=False), requests_per_minute=6000, fallback_models=(), api_keys=("k-one",))
    ex = GeminiExtractor(s, "sys", {"type": "object"}, client=Client())
    rec = audio.Recording(rec_file)
    with pytest.raises(QuotaExhausted):
        ex.extract(rec, "go")
    with pytest.raises(QuotaExhausted):          # second recording: no API call at all
        ex.extract(rec, "go")
    assert Models.calls == 1


def test_bangla_script_in_transcript_is_flagged(schema):
    raw = {"transcript": [{"speaker": "CEX", "time": "00:00:01", "text": "7 jon ki ekshathe, \u09a8\u09be\u0995\u09bf alada?"}]}
    assert any("Bangla-script" in i.detail for i in build_row(raw, schema).issues)
    raw["transcript"][0]["text"] = "7 jon ki ekshathe, naki alada?"
    assert not any("Bangla-script" in i.detail for i in build_row(raw, schema).issues)


# ---- key + model failover ----

class _Resp:
    usage_metadata = None
    text = '{"fields": [], "call_assessment": {}, "notes": "", "eng_notes": "", "warnings": []}'


def _err(code, msg=""):
    from google.genai import errors
    cls = errors.ServerError if code >= 500 else errors.ClientError
    return cls(code, {"error": {"code": code, "message": msg or f"http {code}", "status": "X"}})


class FakeClient:
    """behaviour: callable(model) -> None (ok) or an exception to raise."""
    def __init__(self, behaviour):
        self.behaviour, self.calls = behaviour, []
        outer = self

        class Models:
            def generate_content(self, model, contents, config):
                outer.calls.append(model)
                err = outer.behaviour(model)
                if err:
                    raise err
                return _Resp()
        self.models = Models()


def _extractor(tmp_path, clients, models=("m1", "m2")):
    from call_pipeline.gemini_client import GeminiExtractor
    f = tmp_path / "a.mp3"
    f.write_bytes(b"x")
    s = replace(load_settings(require_key=False), requests_per_minute=60000, retry_base_seconds=0,
                max_retries=1, api_keys=tuple(f"key-{i}" for i in range(len(clients))),
                model=models[0], fallback_models=tuple(models[1:]))
    return GeminiExtractor(s, "sys", {"type": "object"}, clients=clients), audio.Recording(f)


DAILY = "Quota exceeded. Please retry in 20h23m15.2s."


def test_failover_to_second_key_when_first_is_out_of_daily_quota(tmp_path):
    c1, c2 = FakeClient(lambda m: _err(429, DAILY)), FakeClient(lambda m: None)
    ex, rec = _extractor(tmp_path, [c1, c2], models=("m1",))
    r = ex.extract(rec, "go")
    assert (r.model, r.key_tail) == ("m1", "ey-1")
    ex.extract(rec, "go")
    assert len(c1.calls) == 1 and len(c2.calls) == 2          # key 1 is skipped after it was dropped


def test_overload_503_tries_next_key_but_does_not_drop_the_first(tmp_path):
    state = {"down": True}
    c1 = FakeClient(lambda m: _err(503) if state["down"] else None)
    c2 = FakeClient(lambda m: None)
    ex, rec = _extractor(tmp_path, [c1, c2], models=("m1",))
    assert ex.extract(rec, "go").key_tail == "ey-1"
    assert len(c1.calls) == 2                                  # 1 try + 1 retry, then moved on
    state["down"] = False
    assert ex.extract(rec, "go").key_tail == "ey-0"       # key 1 was not dropped


def test_fallback_model_used_when_main_model_quota_is_gone_on_all_keys(tmp_path):
    c1 = FakeClient(lambda m: _err(429, DAILY) if m == "m1" else None)
    c2 = FakeClient(lambda m: _err(429, DAILY) if m == "m1" else None)
    ex, rec = _extractor(tmp_path, [c1, c2], models=("m1", "m2"))
    r = ex.extract(rec, "go")
    assert r.model == "m2" and r.key_tail == "ey-0"
    assert c1.calls == ["m1", "m2"] and c2.calls == ["m1"]


def test_rejected_key_is_dropped_for_every_model(tmp_path):
    c1, c2 = FakeClient(lambda m: _err(403, "free tier not available")), FakeClient(lambda m: None)
    ex, rec = _extractor(tmp_path, [c1, c2], models=("m1", "m2"))
    ex.extract(rec, "go")
    ex.extract(rec, "go")
    assert c1.calls == ["m1"]                                  # never asked again, not even for m2


def test_everything_exhausted_raises_quota_and_makes_no_more_calls(tmp_path):
    from call_pipeline.gemini_client import QuotaExhausted
    c1, c2 = FakeClient(lambda m: _err(429, DAILY)), FakeClient(lambda m: _err(403))
    ex, rec = _extractor(tmp_path, [c1, c2], models=("m1",))
    with pytest.raises(QuotaExhausted) as e:
        ex.extract(rec, "go")
    assert "no usable Gemini key" in str(e.value)
    n = len(c1.calls) + len(c2.calls)
    with pytest.raises(QuotaExhausted):
        ex.extract(rec, "go")
    assert len(c1.calls) + len(c2.calls) == n


def test_bad_request_is_not_retried_or_failed_over(tmp_path):
    c1, c2 = FakeClient(lambda m: _err(400, "invalid schema")), FakeClient(lambda m: None)
    ex, rec = _extractor(tmp_path, [c1, c2])
    from google.genai import errors
    with pytest.raises(errors.APIError):
        ex.extract(rec, "go")
    assert len(c1.calls) == 1 and c2.calls == []


def test_all_503_fails_the_call_but_not_the_batch(tmp_path):
    from google.genai import errors
    c1, c2 = FakeClient(lambda m: _err(503)), FakeClient(lambda m: _err(503))
    ex, rec = _extractor(tmp_path, [c1, c2], models=("m1",))
    with pytest.raises(errors.ServerError):
        ex.extract(rec, "go")
    assert ex.quota_exhausted is None                          # nothing dropped: next call may succeed


# ---- worker (queue -> Gemini -> database) ----

class FakeDb:
    def __init__(self, calls):
        self.queue, self.updates, self.results, self.requeued = list(calls), [], [], 0

    def claim_next(self):
        return self.queue.pop(0) if self.queue else None

    def requeue_stale(self, minutes):
        self.requeued += 1
        return 0

    def download(self, path):
        return b"fake-audio-bytes"

    def update_call(self, call_id, patch):
        self.updates.append((call_id, patch))

    def save_result(self, payload):
        self.results.append(payload)

    def last_status(self, call_id):
        return [p["status"] for c, p in self.updates if c == call_id and "status" in p][-1]


class StubExtractor:
    def __init__(self, behaviour=None):
        self.behaviour, self.calls = behaviour, 0

    def extract(self, rec, instruction):
        self.calls += 1
        if self.behaviour:
            self.behaviour()
        return GeminiResult(
            {"transcript": [{"speaker": "CEX", "time": "00:00:07", "text": "as salam oa alaikum."}],
             "call_assessment": {"audio_quality": "good", "is_kyc_call": True, "respondent_is_farmer": "yes",
                                 "language_note": ""},
             "fields": [item("loan_amount", "40,000"), item("own", "16.5", "low")],
             "notes": "Farmer loan nibe.", "eng_notes": "Farmer wants a loan.", "warnings": ["w1"]},
            {"prompt_tokens": 10, "output_tokens": 5}, "m1", "ey-0")


def _call(i, name="a.mp3"):
    return {"id": f"id{i}", "file_name": name, "storage_path": f"p/{i}/{name}", "attempts": 1}


def _worker(db, extractor, schema, **over):
    from call_pipeline.worker import Worker
    s = replace(load_settings(require_key=False), workers=1, poll_seconds=0.01, quota_pause_minutes=30, **over)
    return Worker(db, lambda: extractor, schema, s)


def test_worker_saves_result_and_marks_done(schema):
    db = FakeDb([_call(1)])
    w = _worker(db, StubExtractor(), schema)
    assert w.process(db.claim_next()) == "done"
    r = db.results[0]
    assert r["call_id"] == "id1" and r["model"] == "m1" and r["usage"]["key"] == "ey-0"
    assert r["fields"] == {"loan_amount": "40000", "own": "16.5"}          # normalised; notes not in fields
    assert r["transcript_text"] == "CEX: as salam oa alaikum. (00:00:07)\n"
    assert r["notes"] == "Farmer loan nibe." and r["eng_notes"] == "Farmer wants a loan."
    assert {i["kind"] for i in r["review"]} == {"low_confidence", "warning"}
    assert r["evidence"]["own"]["confidence"] == "low"
    patch = db.updates[-1][1]
    assert patch["status"] == "done" and patch["model"] == "m1" and patch["error"] is None


def test_worker_marks_failed_with_reason(schema):
    def boom():
        raise RuntimeError("gemini exploded")
    db = FakeDb([_call(1)])
    w = _worker(db, StubExtractor(boom), schema)
    assert w.process(db.claim_next()) == "failed"
    assert db.last_status("id1") == "failed" and "gemini exploded" in db.updates[-1][1]["error"]
    assert db.results == []


def test_worker_requeues_and_pauses_when_quota_exhausted(schema):
    from call_pipeline.gemini_client import QuotaExhausted

    def quota():
        raise QuotaExhausted("no usable Gemini key/model left")
    db = FakeDb([_call(1), _call(2)])
    w = _worker(db, StubExtractor(quota), schema)
    assert w.process(db.claim_next()) == "requeued"
    assert db.last_status("id1") == "queued"
    w.run(once=True)                                  # paused: must not touch call 2
    assert [c["id"] for c in db.queue] == ["id2"]


def test_worker_once_processes_whole_queue_and_requeues_stale_first(schema):
    db = FakeDb([_call(1), _call(2), _call(3)])
    ex = StubExtractor()
    _worker(db, ex, schema).run(once=True)
    assert ex.calls == 3 and db.queue == [] and db.requeued == 1
    assert [db.last_status(f"id{i}") for i in (1, 2, 3)] == ["done"] * 3


def test_worker_marks_failed_when_saving_result_fails(schema):
    db = FakeDb([_call(1)])

    def bad_save(payload):
        raise RuntimeError("db down")
    db.save_result = bad_save
    w = _worker(db, StubExtractor(), schema)
    assert w.process(db.claim_next()) == "failed"
    assert "saving failed" in db.updates[-1][1]["error"]
