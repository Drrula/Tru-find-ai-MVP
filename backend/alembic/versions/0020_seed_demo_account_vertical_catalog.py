"""Seed demo account + vertical + lead-signal catalog + weights.

Per docs/phase-b6a-plan.md §5.1 (audit-corrected 2026-05-11).

This is the FIRST seed-data migration in the codebase. Up to B.5.3,
every migration was schema-only; runtime tables stayed empty until
operator-driven population. B.6A.1 introduces a seed that primes the
canonical persistence stack with the rows the bridge needs:

  1. demo account       -- tenancy root for B.6A's lead-per-call writes
  2. demo vertical      -- linked via `pack_id` to the legacy pack
  3. 4 lead_signal_definition rows -- platform catalog for the legacy
                                       signals (FK target for weights)
  4. 4 vertical_lead_signal_weight rows -- per-vertical lead-scoring
                                            weights matching the legacy
                                            pack values

APPEND-ONLY + IDEMPOTENT. Every INSERT uses ON CONFLICT DO NOTHING on
the natural key so re-running the migration is a no-op. Deterministic
UUID5 ids for account + vertical so the seed is reproducible across
environments and the downgrade can target rows unambiguously.

Treat this migration as a FROZEN HISTORICAL BOOTSTRAP ARTIFACT per
phase-b6a-plan.md §2 decision #4. Do not auto-sync values at runtime;
if pack weights change before B.6B convergence, re-run this seed OR
document the divergence explicitly.

ADR refs: ADR-008 (tenancy), ADR-011 (signal probes), ADR-033 (UUIDv7
PK -- this migration uses UUID5 for deterministic seed ids), ADR-036
(lead signals + dimensions), ADR-047 (account/vertical ownership),
ADR-048 (vertical pack lifecycle).

-- Weights mirror the legacy pack-level WEIGHTS dict at seed time.
-- Source: backend/app/vertical/packs/local_business_ai_visibility/weights.py
-- (B.6A authored 2026-05-11; pack_id = "local_business_ai_visibility").
--
-- NOTE: LEAD_SIGNAL_WEIGHTS in the pack is intentionally empty
-- (B.4.6 deferred). This migration is the SOLE B.6A source of truth
-- for canonical lead-scoring weights. Per phase-b6a-plan.md §2
-- decision #4 + §3 out-of-scope.
--
-- DO NOT auto-sync at runtime -- treat this migration as a frozen
-- historical bootstrap artifact. If pack weights change before
-- B.6B convergence, re-run this seed OR document the divergence.
--
-- Source values at seed time (sum = 1.000):
--   website_presence:           0.300
--   google_business_presence:   0.300
--   content_signals:            0.200
--   reviews:                    0.200
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0020_seed_demo_account_vertical_catalog"
down_revision: Union[str, None] = "0019_lead_score_snapshot"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Deterministic seed identities
# ---------------------------------------------------------------------------
# UUID5 derivation: stable across environments and re-runs. Namespace
# is uuid.NAMESPACE_DNS so the seed name reads like a DNS label and
# the derived UUID is reproducible by anyone with the namespace + name.
#
# These two UUIDs are the IDENTITY OF THE B.6A SEED. The downgrade
# targets rows by these exact UUIDs -- it will NOT touch any other
# account or vertical row that happens to share a display_name.

_SEED_NAMESPACE = uuid.NAMESPACE_DNS
DEMO_ACCOUNT_ID: uuid.UUID = uuid.uuid5(
    _SEED_NAMESPACE, "trufindai.demo.account"
)
DEMO_VERTICAL_ID: uuid.UUID = uuid.uuid5(
    _SEED_NAMESPACE,
    "trufindai.demo.vertical.local_business_ai_visibility",
)
DEMO_PACK_ID: str = "local_business_ai_visibility"

EFFECTIVE_FROM: datetime = datetime(
    2026, 5, 11, 0, 0, 0, tzinfo=timezone.utc
)
FRESHNESS_TTL_SECONDS_DAILY: int = 86400  # 24h


# ---------------------------------------------------------------------------
# Catalog: 4 legacy signals with provenance
# ---------------------------------------------------------------------------
# Tuple shape: (name, description, default_weight_as_float)
# Weights mirror WEIGHTS in app/vertical/packs/local_business_ai_visibility/
# weights.py at seed time -- see module docstring for provenance.

_SIGNAL_CATALOG: list[tuple[str, str, float]] = [
    (
        "website_presence",
        "Legacy probe: deterministic-hash gate for whether the "
        "business has a discoverable website.",
        0.300,
    ),
    (
        "google_business_presence",
        "Legacy probe: real-shaped Google Business listing presence "
        "(listing exists, rating, review count).",
        0.300,
    ),
    (
        "content_signals",
        "Legacy probe: deterministic-hash content audit proxy "
        "(blog presence, schema.org markup proxy).",
        0.200,
    ),
    (
        "reviews",
        "Legacy probe: deterministic-hash review-aggregation proxy.",
        0.200,
    ),
]


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Demo account. ON CONFLICT (id) DO NOTHING -- deterministic
    #    UUID5 means re-running is a no-op.
    conn.execute(
        sa.text(
            "INSERT INTO account "
            "  (id, display_name, status, region) "
            "VALUES "
            "  (:id, :display_name, 'active', 'us') "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {
            "id": str(DEMO_ACCOUNT_ID),
            "display_name": "demo",
        },
    )

    # 2. Demo vertical, linked via pack_id to the legacy pack module.
    #    ON CONFLICT (pack_id) DO NOTHING uses the UNIQUE constraint
    #    `uq_vertical_pack_id` introduced in migration 0007.
    conn.execute(
        sa.text(
            "INSERT INTO vertical "
            "  (id, pack_id, display_name, schema_version) "
            "VALUES "
            "  (:id, :pack_id, :display_name, :schema_version) "
            "ON CONFLICT (pack_id) DO NOTHING"
        ),
        {
            "id": str(DEMO_VERTICAL_ID),
            "pack_id": DEMO_PACK_ID,
            "display_name": "Local Business AI Visibility",
            "schema_version": 1,
        },
    )

    # 3. lead_signal_definition rows (PK = name). FK target for the
    #    vertical_lead_signal_weight rows below -- MUST land first.
    #    contributes_to = ARRAY['lead_quality'] matches the codebase
    #    convention in app/vertical/seed.py:60
    #    (LEAD_SIGNAL_WEIGHT_DEFAULT_DIMENSION).
    for name, description, default_weight in _SIGNAL_CATALOG:
        conn.execute(
            sa.text(
                "INSERT INTO lead_signal_definition "
                "  (name, description, contributes_to, "
                "   freshness_ttl_seconds, source_kind, "
                "   default_weight, default_enabled) "
                "VALUES "
                "  (:name, :description, "
                "   ARRAY['lead_quality']::text[], "
                "   :freshness_ttl_seconds, 'computed', "
                "   :default_weight, TRUE) "
                "ON CONFLICT (name) DO NOTHING"
            ),
            {
                "name": name,
                "description": description,
                "freshness_ttl_seconds": FRESHNESS_TTL_SECONDS_DAILY,
                "default_weight": default_weight,
            },
        )

    # 4. vertical_lead_signal_weight rows. ONE per signal.
    #    dimension = 'lead_quality' matches the codebase convention.
    #    effective_from = 2026-05-11 00:00:00+00; effective_to NULL
    #    (active). UUID5-derived id per signal so each weight row is
    #    deterministically addressable.
    for name, _description, weight in _SIGNAL_CATALOG:
        weight_id = uuid.uuid5(
            _SEED_NAMESPACE,
            f"trufindai.demo.vertical_lead_signal_weight.{name}",
        )
        conn.execute(
            sa.text(
                "INSERT INTO vertical_lead_signal_weight "
                "  (id, vertical_id, signal_name, dimension, "
                "   weight, enabled, effective_from) "
                "VALUES "
                "  (:id, :vertical_id, :signal_name, 'lead_quality', "
                "   :weight, TRUE, :effective_from) "
                "ON CONFLICT "
                "  (vertical_id, signal_name, dimension, effective_from) "
                "DO NOTHING"
            ),
            {
                "id": str(weight_id),
                "vertical_id": str(DEMO_VERTICAL_ID),
                "signal_name": name,
                "weight": weight,
                "effective_from": EFFECTIVE_FROM,
            },
        )


def downgrade() -> None:
    conn = op.get_bind()

    # Reverse insert order to satisfy FK constraints:
    #   weights -> signal defs -> vertical -> account
    #
    # Each DELETE targets the SPECIFIC seeded rows by deterministic
    # identity. We do NOT mass-delete by predicate that could match
    # rows seeded by future migrations or operators.

    # Weights: target by (vertical_id, dimension, effective_from)
    # since those three together pin this seed's rows uniquely.
    conn.execute(
        sa.text(
            "DELETE FROM vertical_lead_signal_weight "
            "WHERE vertical_id = :vertical_id "
            "  AND dimension = 'lead_quality' "
            "  AND effective_from = :effective_from"
        ),
        {
            "vertical_id": str(DEMO_VERTICAL_ID),
            "effective_from": EFFECTIVE_FROM,
        },
    )

    # lead_signal_definition: delete the 4 seeded names. If any other
    # rows reference these via FK (e.g. lead_signal observations
    # created after seeding), the FK will block the DELETE -- this is
    # appropriate fail-loud behavior; operator must clean up
    # downstream data first.
    for name, _description, _weight in _SIGNAL_CATALOG:
        conn.execute(
            sa.text(
                "DELETE FROM lead_signal_definition WHERE name = :name"
            ),
            {"name": name},
        )

    # Vertical: target by id AND pack_id together so we cannot
    # accidentally drop someone else's vertical row that happens to
    # have an overlapping pack_id from a different seed.
    conn.execute(
        sa.text(
            "DELETE FROM vertical "
            "WHERE id = :id AND pack_id = :pack_id"
        ),
        {
            "id": str(DEMO_VERTICAL_ID),
            "pack_id": DEMO_PACK_ID,
        },
    )

    # Account: target by id alone. Deterministic UUID5 makes this
    # unambiguous. If leads or other owned data reference this
    # account, the FK will block (fail-loud).
    conn.execute(
        sa.text("DELETE FROM account WHERE id = :id"),
        {"id": str(DEMO_ACCOUNT_ID)},
    )
