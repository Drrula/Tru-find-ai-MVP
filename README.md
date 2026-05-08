# Tru-find-ai-MVP

> **Status:** Pre-implementation Phase A (architecture lock). Read the architectural contract before changing code:
>
> - `docs/adr/ARCHITECTURE-LOCK.md` — schema, lifecycles, service boundaries, phase plan
> - `docs/adr/README.md` — ADR change protocol
> - `CONTRIBUTING.md` — day-to-day rules
> - `docs/phase-a-plan.md` — current phase tasks
>
> The MVP described below runs as a baseline and will be progressively restructured per the locked plan. Phase A introduces no behavior change.

---

AI Visibility Scoring — MVP. A FastAPI service that scores how visible a business is to AI assistants and local search, and lists the gaps holding it back.

## Project layout

```
app/
  main.py       # FastAPI app + /analyze-business route
  schemas.py    # Pydantic request/response models
  scoring.py    # Blends signals into a 0–100 score and writes the summary
  signals.py    # Individual signals (website, GBP, content, reviews) — currently mocked
requirements.txt
```

The scoring layer (`scoring.py`) does not know how a signal is computed — it only consumes `SignalResult`. To plug in a real data source (Google Places API, a scraper, an LLM probe, etc.), replace the body of the relevant function in `signals.py`. No other file needs to change.

To add a new signal, write a function that returns a `SignalResult` and append it to the `SIGNALS` list at the bottom of `signals.py`.

## Run locally

From the project root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The API is then served at `http://127.0.0.1:8000`. Interactive docs: `http://127.0.0.1:8000/docs`.

## Try it

```powershell
curl.exe -X POST http://127.0.0.1:8000/analyze-business `
  -H "Content-Type: application/json" `
  -d '{\"business_name\": \"Joe''s Pizza\", \"location\": \"Brooklyn, NY\"}'
```

Example response:

```json
{
  "score": 65,
  "gaps": [
    "Google Business Profile is missing or unclaimed — claim and verify it to appear on Maps and local search.",
    "Review volume is modest — ask recent customers for Google reviews to build social proof."
  ],
  "summary": "Joe's Pizza has a moderate AI visibility profile (score 65/100). 2 gap(s) identified. A few targeted fixes could meaningfully lift discoverability."
}
```

The mock signals are deterministic for a given `(business_name, location)` pair, so the same input always returns the same score — useful while wiring up a frontend.
