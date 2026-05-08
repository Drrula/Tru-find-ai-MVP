# ADR-021 — LLM output validated against JSON schema

| Field | Value |
|---|---|
| Status | Locked-default |
| Class | AI mutation behavior |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
Every LLM call declares a JSON schema for its expected output. Output is parsed and validated; invalid responses trigger one repair retry, then fail the probe (recorded in `ai_probe`). No free-text output flows into business logic.

## Why
LLMs occasionally return malformed JSON, hallucinated fields, or refuse. Schema validation turns a flaky upstream into a predictable error code. It also gives us a contract that survives prompt edits, model swaps, and provider changes.

## Tradeoffs
- Schema authoring is up-front work per probe.
- Models that don't natively support structured output cost more retry budget.

## Future limitations
- Open-ended generation (user-facing prose) does not fit schemas — those need a separate "free-text probe" type with its own moderation step.

## Migration cost if revisited
Retrofitting schemas to a free-text codebase is hard because callers learn to pattern-match strings. Doing it now is the cheapest path.

## Scaling implications
Schema validation is microseconds. Repair retries roughly double cost in the rare bad case.

## Operational complexity
Low. One validator per probe. Failed validations logged; dashboards expose the rate.

## Constraints this ADR imposes
- `vertical_prompt_version.output_schema` is JSON Schema, validated at insert.
- `ai_probe.validated boolean` set true only after schema pass.
- Repair retry max 1; second failure → probe failed, signal `failed` or `skipped`.
- No LLM output reaches `domain/scoring` un-validated.

## See also
- ARCHITECTURE-LOCK §3.3
- ADR-020 (prompt versions)
