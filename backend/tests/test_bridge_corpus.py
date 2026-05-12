"""B.6A.6 corpus + replay tests against real Postgres.

The empirical validation of the mirror-phase bridge. Uses the new
B.6A.5 db_session fixture (real Postgres, nested-SAVEPOINT rollback
per test) and the migration 0020 seeded demo account + vertical +
lead-signal catalog + weights.

Per docs/phase-b6a-plan.md §6 (B.6A.6 sub-phase row, locked
narrowing 2026-05-11):
  - Corpus: 10-15 inputs covering signal-score ranges, mirror
    parity within BRIDGE_DIVERGENCE_TOLERANCE
  - Baseline: ("Joe Pizza", "Brooklyn, NY") -> legacy score == 60
    (preserved across all of B.6A) + canonical within tolerance
  - Replay: persist snapshot, re-run compute_lead_score against
    the same lead + stored weight_version_at, assert EXACT equality
    (delta == 0, no tolerance -- replay is deterministic)
  - Bridge-source grep: count(*) FROM lead WHERE source =
    BRIDGE_LEAD_SOURCE matches the number of orchestrator calls
    in the test

DEFERRED out of B.6A.6 scope (per locked decision 2026-05-11):
  - Partial-catalog mutation test (drop a weight row mid-test)
    -- adds DB-fixture complexity beyond narrowest-safe; the
    unobserved-signal code path is already unit-tested in
    test_scoring_divergence.py.

fetch_google_business is deterministic mock-style in this codebase
(backend/app/clients/google_business.py uses md5-based hashing,
not real HTTP), so no external-service mocking is required.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.lead_repo import LeadRepository
from app.db.repositories.lead_score_snapshot_repo import (
    LeadScoreSnapshotRepository,
)
from app.db.repositories.lead_signal_definition_repo import (
    LeadSignalDefinitionRepository,
)
from app.db.repositories.lead_signal_repo import LeadSignalRepository
from app.db.repositories.vertical_lead_signal_weight_repo import (
    VerticalLeadSignalWeightRepository,
)
from app.domain.leads.scoring import compute_lead_score
from app.domain.scoring_divergence import BRIDGE_DIVERGENCE_TOLERANCE
from app.domain.scoring_persistence import (
    BRIDGE_LEAD_SOURCE,
    BridgeResult,
    analyze_and_persist,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SEED_MIGRATION_PATH = (
    _REPO_ROOT
    / "backend"
    / "alembic"
    / "versions"
    / "0020_seed_demo_account_vertical_catalog.py"
)


def _load_seed_module():
    """Load migration 0020 as a module so the tests can reach its
    DEMO_ACCOUNT_ID / DEMO_VERTICAL_ID constants. Same pattern as
    test_db_fixtures.py."""
    spec = importlib.util.spec_from_file_location(
        "alembic_0020_seed_for_corpus", _SEED_MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_SEED = _load_seed_module()
DEMO_ACCOUNT_ID: UUID = _SEED.DEMO_ACCOUNT_ID
DEMO_VERTICAL_ID: UUID = _SEED.DEMO_VERTICAL_ID


# ---------------------------------------------------------------------------
# Corpus -- 10 inputs covering different deterministic-hash buckets
# ---------------------------------------------------------------------------

_CORPUS: list[tuple[str, str]] = [
    ("Joe Pizza", "Brooklyn, NY"),               # baseline (legacy = 60)
    ("Acme Plumbing", "Austin, TX"),
    ("Sunset Yoga", "Portland, OR"),
    ("Mike's Auto Repair", "Chicago, IL"),
    ("Green Leaf Cafe", "Seattle, WA"),
    ("Riverside Dental", "Denver, CO"),
    ("Bright Smile Bakery", "Miami, FL"),
    ("Stone Path Landscaping", "Boston, MA"),
    ("Blue Wave Surf Shop", "San Diego, CA"),
    ("Polar Bear Plumbing", "Anchorage, AK"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _run_bridge(
    db_session: AsyncSession,
    *,
    business_name: str,
    location: str,
) -> BridgeResult:
    """Construct the 5 repos against the live test session and
    invoke the orchestrator. Logger is a MagicMock -- the corpus
    cares about returned BridgeResult, not the log output (which
    is exercised by test_analyze_and_persist.py)."""
    return await analyze_and_persist(
        business_name=business_name,
        location=location,
        trade=None,
        account_id=DEMO_ACCOUNT_ID,
        vertical_id=DEMO_VERTICAL_ID,
        lead_repo=LeadRepository(db_session, DEMO_ACCOUNT_ID),
        lead_signal_repo=LeadSignalRepository(db_session, DEMO_ACCOUNT_ID),
        signal_definition_repo=LeadSignalDefinitionRepository(
            db_session, None
        ),
        weight_repo=VerticalLeadSignalWeightRepository(
            db_session, None
        ),
        score_repo=LeadScoreSnapshotRepository(
            db_session, DEMO_ACCOUNT_ID
        ),
        logger=MagicMock(),
    )


# ---------------------------------------------------------------------------
# Baseline -- the regression guard preserved across all of B.6A
# ---------------------------------------------------------------------------


async def test_baseline_joe_pizza_brooklyn_legacy_score_60(
    db_session: AsyncSession,
) -> None:
    """The canonical mirror-parity baseline. analyze('Joe Pizza',
    'Brooklyn, NY').score has equaled 60 in every test across every
    B.6A sub-phase. Inside the orchestrator the same legacy call
    must produce the same 60, and the canonical snapshot must agree
    within tolerance."""
    result = await _run_bridge(
        db_session,
        business_name="Joe Pizza",
        location="Brooklyn, NY",
    )
    assert result.response.score == 60
    assert result.divergence.legacy_score == 60
    assert result.divergence.within_tolerance
    assert abs(result.divergence.delta) <= BRIDGE_DIVERGENCE_TOLERANCE


async def test_baseline_bridge_result_shape(
    db_session: AsyncSession,
) -> None:
    """Full BridgeResult contract: response is legacy AnalyzeResponse;
    snapshot is persisted LeadScoreSnapshot for the demo vertical with
    a 4-signal breakdown; divergence carries lead_id + snapshot_id."""
    result = await _run_bridge(
        db_session,
        business_name="Joe Pizza",
        location="Brooklyn, NY",
    )
    # AnalyzeResponse preserved
    assert result.response.score == 60
    assert len(result.response.competitors) == 3
    # Snapshot persisted with the right vertical + lead source
    assert result.snapshot.vertical_id == DEMO_VERTICAL_ID
    assert result.snapshot.account_id == DEMO_ACCOUNT_ID
    # Breakdown has 4 signal contributions (all 4 legacy signals
    # were observed and contributed).
    contribs = result.snapshot.score_breakdown["signal_contributions"]
    assert len(contribs) == 4
    contrib_names = {c["signal_name"] for c in contribs}
    assert contrib_names == {
        "website_presence",
        "google_business_presence",
        "content_signals",
        "reviews",
    }
    # Divergence carries the persisted identities
    assert result.divergence.lead_id is not None
    assert result.divergence.snapshot_id == result.snapshot.id
    assert result.divergence.vertical_id == DEMO_VERTICAL_ID


# ---------------------------------------------------------------------------
# Corpus parity -- 10 inputs, each must agree within tolerance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("business_name,location", _CORPUS)
async def test_corpus_mirror_parity_within_tolerance(
    business_name: str,
    location: str,
    db_session: AsyncSession,
) -> None:
    """For each corpus input, the legacy and canonical scores agree
    within BRIDGE_DIVERGENCE_TOLERANCE. The mirror-phase parity
    claim is empirical -- this test is the evidence."""
    result = await _run_bridge(
        db_session,
        business_name=business_name,
        location=location,
    )
    assert result.divergence.within_tolerance, (
        f"Mirror parity violated for ({business_name!r}, {location!r}): "
        f"legacy={result.divergence.legacy_score} "
        f"canonical={result.divergence.canonical_score} "
        f"delta={result.divergence.delta} "
        f"tolerance={BRIDGE_DIVERGENCE_TOLERANCE}"
    )


async def test_corpus_covers_score_range(
    db_session: AsyncSession,
) -> None:
    """Run the full corpus once and assert the scores actually vary
    -- if all 10 inputs collapsed to the same score, the parity
    test above would be a tautology."""
    legacy_scores = []
    for business_name, location in _CORPUS:
        result = await _run_bridge(
            db_session, business_name=business_name, location=location
        )
        legacy_scores.append(result.response.score)
    distinct = set(legacy_scores)
    assert len(distinct) >= 3, (
        f"corpus scores collapsed to {sorted(distinct)}; expected "
        f"at least 3 distinct values across the 10-input range"
    )


# ---------------------------------------------------------------------------
# Replay determinism (ADR-010) -- exact, no tolerance
# ---------------------------------------------------------------------------


async def test_replay_recomputed_score_equals_snapshot_exactly(
    db_session: AsyncSession,
) -> None:
    """Foundational ADR-010 property: given the same lead + stored
    inputs + stored weight_version_at, compute_lead_score is
    DETERMINISTIC. Re-running it against the persisted state must
    produce a score IDENTICAL to the original snapshot's score (no
    tolerance, exact Decimal equality)."""
    from app.db.models import Lead

    original = await _run_bridge(
        db_session,
        business_name="Joe Pizza",
        location="Brooklyn, NY",
    )
    await db_session.flush()

    # Fetch the persisted lead row in this session.
    lead = await db_session.get(Lead, original.divergence.lead_id)
    assert lead is not None

    # Re-run compute against the persisted state. The repos read
    # from the same session; the lead_signal rows the orchestrator
    # staged are visible (autoflush'd by the ORM select() inside
    # the repo). weight_version_at is the SAME timestamp the
    # original snapshot pinned.
    replay = await compute_lead_score(
        lead=lead,
        vertical_id=DEMO_VERTICAL_ID,
        lead_signal_repo=LeadSignalRepository(
            db_session, DEMO_ACCOUNT_ID
        ),
        weight_repo=VerticalLeadSignalWeightRepository(
            db_session, None
        ),
        weight_version_at=original.snapshot.weight_version_at,
    )
    assert replay.score == original.snapshot.score


async def test_replay_breakdown_matches_snapshot(
    db_session: AsyncSession,
) -> None:
    """Replay also reproduces the per-signal breakdown bit-for-bit.
    Persisted signal_contributions in the snapshot must equal the
    breakdown recomputed at replay time -- proves the breakdown is
    a faithful frozen snapshot, not a lossy summary."""
    original = await _run_bridge(
        db_session,
        business_name="Joe Pizza",
        location="Brooklyn, NY",
    )
    await db_session.flush()
    # Fetch the lead row from this session.
    from app.db.models import Lead
    lead = await db_session.get(Lead, original.divergence.lead_id)
    assert lead is not None

    replay = await compute_lead_score(
        lead=lead,
        vertical_id=DEMO_VERTICAL_ID,
        lead_signal_repo=LeadSignalRepository(
            db_session, DEMO_ACCOUNT_ID
        ),
        weight_repo=VerticalLeadSignalWeightRepository(
            db_session, None
        ),
        weight_version_at=original.snapshot.weight_version_at,
    )
    # Compare signal_contributions list element-by-element.
    original_contribs = original.snapshot.score_breakdown[
        "signal_contributions"
    ]
    replay_contribs = replay.breakdown["signal_contributions"]
    assert len(original_contribs) == len(replay_contribs)
    by_name_original = {c["signal_name"]: c for c in original_contribs}
    by_name_replay = {c["signal_name"]: c for c in replay_contribs}
    assert by_name_original.keys() == by_name_replay.keys()
    for name in by_name_original:
        assert by_name_original[name]["value"] == by_name_replay[name]["value"]
        assert by_name_original[name]["weight"] == by_name_replay[name]["weight"]
        assert (
            by_name_original[name]["contribution"]
            == by_name_replay[name]["contribution"]
        )


# ---------------------------------------------------------------------------
# Bridge-source grep
# ---------------------------------------------------------------------------


async def test_bridge_source_grep_matches_call_count(
    db_session: AsyncSession,
) -> None:
    """After N orchestrator calls in THIS test session, exactly N
    lead rows must carry source = BRIDGE_LEAD_SOURCE. Validates
    that the source-string constant is the right grep target for
    finding bridge-originated rows in DB inspection."""
    n_calls = 3
    for i in range(n_calls):
        await _run_bridge(
            db_session,
            business_name=f"Grep Corpus Biz {i}",
            location="Grep Test City",
        )
    await db_session.flush()

    result = await db_session.execute(
        text("SELECT count(*) AS c FROM lead WHERE source = :src"),
        {"src": BRIDGE_LEAD_SOURCE},
    )
    assert result.one().c == n_calls
    # And the constant itself is the documented one.
    assert BRIDGE_LEAD_SOURCE == "bridge:legacy_analyzer:v1"


# ---------------------------------------------------------------------------
# Test isolation -- corpus runs do not leak across tests
# ---------------------------------------------------------------------------


async def test_corpus_does_not_leak_across_tests(
    db_session: AsyncSession,
) -> None:
    """Validates the B.6A.5 nested-SAVEPOINT rollback property end-
    to-end: this test runs AFTER the corpus tests (declared later
    in file order), but starts with a fresh outer transaction.
    Bridge-source rows from prior tests must NOT be visible."""
    result = await db_session.execute(
        text(
            "SELECT count(*) AS c FROM lead WHERE source = :src "
            "AND account_id = :aid"
        ),
        {
            "src": BRIDGE_LEAD_SOURCE,
            "aid": str(DEMO_ACCOUNT_ID),
        },
    )
    assert result.one().c == 0
