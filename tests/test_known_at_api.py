"""API-level AS_KNOWN_AT tests — the query path itself, not the data.

These exercise the actual `?known_at=` endpoint: entity filtering,
epistemic-field scrubbing, date normalization and malformed input —
the paths where leakage bugs live.
"""

from __future__ import annotations

from pathlib import Path

import pytest

DB = Path("data/runtime/cnmv-enforcement.duckdb")


@pytest.fixture(scope="module")
def client():
    if not DB.exists():
        pytest.skip("build not run")
    from fastapi.testclient import TestClient

    from cnmv_enforcement.api.app import app

    return TestClient(app)


def test_known_at_far_past_is_empty(client):
    r = client.get("/cases/CNMV-BOE-A-2026-16921?known_at=2020-01-01")
    assert r.status_code == 200
    d = r.json()
    assert d["history_mode"] == "AS_KNOWN_AT"
    assert d["observation_note"] == "NO_OBSERVATION_HISTORY"
    assert d["sanctions"] == []
    assert d["events"] == []
    # derived counts must reflect the T-view, not current knowledge
    assert d["n_sanctions"] == 0
    assert d["n_infringements"] == 0


def test_known_at_future_is_full(client):
    r = client.get("/cases/CNMV-BOE-A-2026-16921?known_at=2100-01-01")
    d = r.json()
    assert d["history_mode"] == "AS_KNOWN_AT"
    assert len(d["sanctions"]) == 6
    assert len(d["respondents"]) == 2
    assert d["n_sanctions"] == 6


def test_known_at_scrubs_epistemic_fields(client):
    """A T-view before the pdf-status run must not leak later-observed
    appeal state — the case row's derived fields are knowledge too."""
    r = client.get("/cases/CNMV-BOE-A-2026-16921?known_at=2020-01-01")
    d = r.json()
    # nothing observed → no epistemic claim may surface
    assert d.get("appeal_observation_status") in (None, "INCONCLUSIVE")


def test_known_at_date_only_includes_that_day(client):
    """date-only T means 'by that date' — observations ON the day are
    included (end-of-day semantics)."""
    import duckdb

    con = duckdb.connect(str(DB), read_only=True)
    day = con.execute(
        "SELECT MAX(CAST(observed_at AS DATE)) FROM evidence"
    ).fetchone()[0]
    con.close()
    r = client.get(f"/cases/CNMV-BOE-A-2026-16921?known_at={day}")
    d = r.json()
    assert len(d["sanctions"]) == 6, (
        "same-day observations were excluded — date-only known_at must "
        "mean end-of-day"
    )


def test_known_at_malformed_is_400(client):
    r = client.get("/cases/CNMV-BOE-A-2026-16921?known_at=zzz")
    assert r.status_code == 400


def test_current_mode_declared(client):
    r = client.get("/cases/CNMV-BOE-A-2026-16921")
    d = r.json()
    assert d["history_mode"] == "CURRENT_KNOWLEDGE_RECONSTRUCTED"
