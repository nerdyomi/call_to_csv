# Call → CEX CSV pipeline

Turns CEX KYC call recordings (Bangla) into a CSV with the **same 198 columns as `reference/CEX data/CEX.csv`**, using Gemini. Comparison with iCore data comes later and will be a separate module that reads `output/CEX.csv`.

## Setup

```powershell
pip install -r requirements.txt
pip install -e .
copy .env.example .env      # then put GEMINI_API_KEY in .env
```

## Use

```powershell
# put .mp3 files in input/recordings/
python -m call_pipeline run --file "C:\path	o\call.mp3"   # one specific call, from anywhere
python -m call_pipeline run --file call.mp3 --force --model gemini-3.6-flash   # redo it, other model
python -m call_pipeline run --limit 1      # first test on one call
python -m call_pipeline run                # everything new; already-done calls are skipped
python -m call_pipeline run --force --only 01745196254   # redo specific calls
python -m call_pipeline rebuild            # rewrite CSVs from cached results, no API calls
python -m call_pipeline evaluate --truth "reference/CEX data/CEX.csv" "reference/test_four_datas/CEX datas/CEX_datas.csv"
                                           # score output/ against hand-filled CEX sheets (matched by phone number)
python scripts/estimate_cost.py            # forecast tokens/cost (add --exact for API counts)
python scripts/estimate_cost.py --report   # real usage so far
pytest
```

## What you get in `output/`

Each recording gets its own folder, `output/<recording name>/`, with `CEX.csv` (one row), `evidence.csv`, `review.csv` and `raw.json`. The files below in `output/` itself combine all calls. `output/evaluation/` (summary.md, cells.csv) is written by `evaluate`.


| file | content |
|---|---|
| `CEX.csv` | one row per call, columns identical to the CEX form (+ `eng_notes` at the end) |
| `evidence.csv` | every filled value with confidence, a quote from the call, and the `mm:ss` timestamp |
| `review.csv` | what a human should look at: low-confidence values, warnings (self-contradiction, noisy audio, unit conversions, new codes…) |
| `raw/<recording>.json` | the model's raw answer + token usage (this is the resume cache) |
| `usage.jsonl`, `errors.jsonl` | token usage per call; failures |

Blank cell = not said / not clear in the call. Nothing is guessed.

## Where each column comes from

- **Audio** (167 columns): the form answers, `Notes` (romanized Bangla), `eng_notes` (English).
- **Filename** (fallback): `Started at`, `Ended at`, `Duration (seconds)`, `Phone`, parsed from names like `20261025-114133_IFARMERR__4004_01745196254-all.mp3`. Pattern is in `config/settings.yaml`.
- **`input/manifest.csv`** (optional, overrides the filename values): call-system / loan-app columns such as `Call ID, Customer ID, Customer, loan_id, Agent, Portfolio, project_sub_type, item_name_crops, call_form_version…`. First column must be `recording_file`; other columns are any CEX column names.

## Project layout

```
config/schema.yaml       the form: column order, type, meaning, known values  <- edit this as the form is finalised
config/settings.yaml     paths, filename pattern, rate limits, output encoding
config/pricing.yaml      model prices for the cost script (verify!)
prompts/system_prompt.md instructions to the model; the field catalog is appended from schema.yaml
src/call_pipeline/       audio, gemini_client, normalize, manifest, writer, pipeline, cost, cli
scripts/                 estimate_cost.py, generate_schema.py (one-off bootstrap from a CEX header)
tests/                   unit tests + end-to-end test with a fake Gemini client
```

## When the allowed values get finalised

Edit `config/schema.yaml`: put the values under `known_values` for a field. They appear in the prompt so the model uses exactly those codes. With `closed_enums: false` (current) a value outside the list is kept but listed in `review.csv` as `unknown_code`; set `closed_enums: true` to drop such values instead. Then `python -m call_pipeline run --force` (or `rebuild` if only the validation rules changed).

## Notes and assumptions

- **Free tier**: Google may use free-tier prompts/audio to improve its products. These calls contain NID/loan/personal data, so move to a paid key before using real data in production. Free quotas (requests/minute and per day) are also well below 200 calls/day; the throttle in `settings.yaml` (`requests_per_minute`, `workers`) keeps you under per-minute limits, and a quota failure is logged and retried on the next run.
- Yield is in **kg** (maund answers are converted at 40 kg). Unit price is assumed to be BDT per **maund**, and income fields yearly BDT: confirm the price unit.
- Model prices in `pricing.yaml` were typed by hand; check Google's pricing page.
- Scale path: the cache-per-recording design lets you run the same command on a schedule; moving to a queue/cloud storage would only change `audio.discover` and the writer.
