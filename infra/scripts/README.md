# `infra/scripts`

Operator-facing CLI scripts. **Stdlib-only Python.** No external deps. Anyone with Python 3.13+ and network access to a running TruFindAI backend can run these — no need to install backend deps or set up a venv.

## `batch_score.py`

Batch-score a CSV of businesses against a running TruFindAI backend.

### Input format

CSV with at least `business_name` and `location` columns. Any additional columns pass through to the output unchanged.

```csv
business_name,location,notes
Joe Pizza,"Brooklyn, NY",lead from Mike
Acme Roofing,"Miami, FL",imported 2026-05
```

### Usage

```bash
# Backend running on default localhost:8000
python infra/scripts/batch_score.py \
  --input  path/to/leads.csv \
  --output path/to/scored.csv

# Against a remote backend
python infra/scripts/batch_score.py \
  --input  leads.csv \
  --output scored.csv \
  --base-url https://api.trufindai-staging.up.railway.app
```

Or set the env var once:

```bash
export BATCH_SCORE_BASE_URL=https://api.trufindai-staging.up.railway.app
python infra/scripts/batch_score.py -i leads.csv -o scored.csv
```

### Options

| Flag | Default | Notes |
|---|---|---|
| `--input` / `-i` | required | Input CSV path |
| `--output` / `-o` | required | Output CSV path |
| `--base-url` | `BATCH_SCORE_BASE_URL` env, fallback `http://127.0.0.1:8000` | Backend origin |
| `--endpoint` | `/analyze-business` | Legacy alias (preserved through Phase B per ADR-005). Phase C will switch this script to `/v1/analyses` async-poll |
| `--timeout` | `30` | Per-request timeout (seconds) |

### Output format

Input columns + appended `score`, `gaps`, `summary`. Failed rows have empty `score`/`gaps` and `summary="ERROR: <message>"` so they're easy to grep for.

### Exit codes

- `0` — all rows succeeded
- `1` — at least one row failed (output CSV still written with error markers)
- `2` — input CSV invalid (no header row, or missing required columns)

### History

Replaces the pre-A.8 `run_batch_test.py` at the repo root, which had:
- Hardcoded `C:\Users\luxco\OneDrive\Desktop\...` paths (Andrew-specific)
- Hardcoded `http://127.0.0.1:8000/analyze-business` URL
- Used the `requests` third-party library (was implicit dependency)

This rewrite is stdlib-only, environment-portable, and operator-friendly per the strategic platform direction (reduce founder dependency).
