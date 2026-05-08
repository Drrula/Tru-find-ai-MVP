# ADR-020 — Versioned prompts as DB rows

| Field | Value |
|---|---|
| Status | **Locked** |
| Class | AI mutation behavior |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
Prompts live in `vertical_prompt_version(vertical_id, probe_name, version, system_text, user_template, output_schema, model, max_tokens, status)`. Every `ai_probe` records the `prompt_version_id` it used. Editing a prompt creates a new version row, never overwrites.

## Why
Old reports must be explainable: "this score was computed with prompt v3, model X, on Y date." Without this, a tuned prompt silently changes historical results, destroying customer trust and our ability to debug. Versioning also lets us A/B test prompts.

## Tradeoffs
- More moving parts than a constant.
- Prompt edit is a DB write requiring review (a "prompt PR" pattern: SQL migration that inserts a new version, not a runtime edit).

## Future limitations
- Prompt-as-data is harder to grep through than prompt-as-code. Mitigated by exporting the active set to a checked-in YAML on every change.

## Migration cost if revisited
Going from constants to versioned-data after months means we have no version history for old runs — they get retroactively pinned to "v0," partly fictional. Doing it now is the right call.

## Scaling implications
None.

## Operational complexity
Medium. The discipline is "edits go through migrations." A prompt registry module enforces "no inline strings to LLMClient.invoke" via a small lint.

## Constraints this ADR imposes
- `vertical_prompt_version` table per ARCHITECTURE-LOCK §2.3.
- Resolution: `(vertical_id, probe_name, status='active')`.
- `ai_probe.prompt_version_id` not nullable.
- `analysis_run.prompt_version_snapshot` JSONB captures the active set at run time.
- Prompt edits via Alembic migration only; no runtime UPDATE.

## See also
- ARCHITECTURE-LOCK §3.3
- ADR-010 (immutable runs)
- ADR-021 (output schema)
- ADR-022 (cost cap)
