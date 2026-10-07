"""AS_KNOWN_AT semantics — ownership-radar doctrine.

The knowledge axis (``observed_at``) and the effective axis
(publication/resolution dates) are NEVER interchangeable:

- a 2024 sanction first observed by this project in 2026 is NOT
  visible at AS_KNOWN_AT(2025);
- an appeal observed after the query time must not leak backwards.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

DB = Path("data/runtime/cnmv-enforcement.duckdb")


@pytest.fixture(scope="module")
def con():
    if not DB.exists():
        pytest.skip("build not run")
    c = duckdb.connect(str(DB), read_only=True)
    yield c
    c.close()


def test_known_at_before_first_observation_is_empty(con):
    """AS_KNOWN_AT well before the build observes nothing."""
    evs = con.execute(
        "SELECT COUNT(*) FROM evidence WHERE observed_at <= '2020-01-01'"
    ).fetchone()[0]
    assert evs == 0, (
        "future evidence leaked into a 2020 knowledge view — "
        "the project observed nothing then"
    )


def test_known_at_at_build_time_is_full(con):
    """Everything built by the project is visible at build-observation time."""
    full = con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
    known = con.execute(
        "SELECT COUNT(*) FROM evidence WHERE observed_at <= '2100-01-01'"
    ).fetchone()[0]
    assert known == full


def test_known_at_filters_not_derives(con):
    """known_at filters observations, it never fabricates history:
    events observed AFTER T are invisible at T even when their
    effective date predates T."""
    rows = con.execute(
        "SELECT event_id, event_date, observed_at FROM events "
        "WHERE observed_at > event_date LIMIT 10"
    ).fetchall()
    for eid, eff, obs in rows:
        n = con.execute(
            "SELECT COUNT(*) FROM events WHERE event_id = ? "
            "AND observed_at <= ?",
            [eid, obs],
        ).fetchone()[0]
        assert n == 1
        # at a T strictly between effective and observed, invisible
        n2 = con.execute(
            "SELECT COUNT(*) FROM events WHERE event_id = ? "
            "AND observed_at <= ?",
            [eid, str(eff)],
        ).fetchone()[0]
        if eff and obs and str(eff) < str(obs):
            assert n2 == 0, (
                f"{eid}: effective {eff} leaked into knowledge view "
                f"before observation {obs}"
            )


def test_appeal_status_epistemic_states(con):
    """Appeal claims carry coverage states — never a bare 'no appeal'."""
    states = {
        r[0]
        for r in con.execute(
            "SELECT DISTINCT appeal_observation_status FROM cases"
        ).fetchall()
    }
    assert states <= {
        "OBSERVED",
        "NOT_OBSERVED_WITHIN_VERIFIED_COVERAGE",
        "UNAVAILABLE",
        "INCONCLUSIVE",
        None,
    }
    assert "NO_APPEAL" not in states
    # every verified negative carries a basis
    unbased = con.execute(
        "SELECT COUNT(*) FROM cases "
        "WHERE appeal_observation_status = "
        "'NOT_OBSERVED_WITHIN_VERIFIED_COVERAGE' "
        "AND coverage_basis_id IS NULL"
    ).fetchone()[0]
    assert unbased == 0
