"""Lead signal weights for the local-business AI visibility pack.

Per ADR-036 + ADR-048 + phase-b4-plan.md §7. Maps to
`vertical_lead_signal_weight` rows once seeded; B.4.4 wires the
read path through `VerticalLeadSignalWeightRepository.find_active`.

B.4.6 ships EMPTY -- no real lead scoring activates in B.4. The
pathway exists end-to-end (pack -> seed -> DB-backed pack at
startup); future commits that activate lead scoring populate this
dict + run the seed against staging/production to write the rows.

Flat `{signal_name: weight}` shape. The seed utility uses
`'lead_quality'` as the default dimension for all entries here;
multi-dimension support extends the Protocol additively when real
packs need it.
"""

from __future__ import annotations

LEAD_SIGNAL_WEIGHTS: dict[str, float] = {}
