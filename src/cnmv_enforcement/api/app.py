"""FastAPI read-only API — every response carries coverage context.

The API serves the built dataset exactly as the coverage ledger defines
it: publicly observable CNMV enforcement, with explicit non-claims.
"""

from __future__ import annotations

import json

import duckdb
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from cnmv_enforcement.config import exports_root, runtime_root
from cnmv_enforcement.coverage.ledger import _LIMITATIONS, DATASET_SCHEMA_VERSION

app = FastAPI(
    title="cnmv-enforcement",
    description=(
        "Read-only API over the evidence-backed ledger of publicly "
        "observable CNMV enforcement. Absence from this dataset does NOT "
        "establish that no sanction was imposed."
    ),
    version=DATASET_SCHEMA_VERSION,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
)

_DB = runtime_root() / "cnmv-enforcement.duckdb"


def _con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(_DB), read_only=True)


def _one(con, sql: str, params: list | None = None):
    row = con.execute(sql, params or []).fetchone()
    return row[0] if row else None


def _rows(con, sql: str, params: list | None = None) -> list[dict]:
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def _table_exists(con, name: str) -> bool:
    return bool(
        con.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name = ?",
            [name],
        ).fetchone()[0]
    )


def _coverage_meta() -> dict:
    candidates = sorted(
        p for p in exports_root().glob("*/coverage.json") if p.exists()
    )
    if candidates:
        return json.loads(candidates[-1].read_text(encoding="utf-8"))
    return {
        "scope_statement": "publicly observable CNMV enforcement",
        "limitations": _LIMITATIONS,
    }


@app.get("/coverage")
def coverage() -> dict:
    """The honest-scope ledger: sources, windows, counts, non-claims."""
    return _coverage_meta()


@app.get("/stats")
def stats() -> dict:
    con = _con()
    try:
        # sums are emitted as canonical decimal strings — the exact value,
        # never a float. Individual amounts are integers (< 2^53) and
        # remain numeric.
        total = _one(
            con,
            "SELECT SUM(amount) FROM sanctions "
            "WHERE sanction_type = 'MONETARY_FINE'",
        )
        out = {
            "cases": _one(con, "SELECT COUNT(*) FROM cases"),
            "infringements": _one(con, "SELECT COUNT(*) FROM infringements"),
            "sanctions": _one(con, "SELECT COUNT(*) FROM sanctions"),
            "respondents": _one(con, "SELECT COUNT(*) FROM respondents"),
            "total_fine_eur": str(total) if total is not None else None,
        }
        out["by_severity"] = _rows(
            con,
            "SELECT severity, COUNT(*) n FROM infringements GROUP BY 1",
        )
        out["by_sanction_type"] = [
            {"sanction_type": r["sanction_type"], "n": r["n"],
             "total": str(r["total"]) if r["total"] is not None else None}
            for r in _rows(
                con,
                "SELECT sanction_type, COUNT(*) n, SUM(amount) total "
                "FROM sanctions GROUP BY 1",
            )
        ]
        out["by_statute"] = _rows(
            con,
            "SELECT statute_normalized, COUNT(*) n FROM infringements "
            "GROUP BY 1 ORDER BY 2 DESC",
        )
        out["coverage"] = {
            "scope": _coverage_meta().get("scope_statement"),
            "limitations": _LIMITATIONS,
        }
        return out
    finally:
        con.close()


@app.get("/cases")
def list_cases(
    severity: str | None = Query(default=None),
    statute: str | None = Query(default=None),
    respondent: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = 0,
) -> dict:
    con = _con()
    try:
        where, params = ["1=1"], []
        if severity:
            where.append(
                "EXISTS (SELECT 1 FROM infringements i WHERE i.case_id = "
                "c.case_id AND i.severity = ?)"
            )
            params.append(severity)
        if statute:
            where.append(
                "EXISTS (SELECT 1 FROM infringements i WHERE i.case_id = "
                "c.case_id AND i.statute_normalized ILIKE ?)"
            )
            params.append(f"%{statute}%")
        if respondent:
            where.append(
                "EXISTS (SELECT 1 FROM case_respondents cr JOIN respondents r "
                "USING(respondent_id) WHERE cr.case_id = c.case_id AND "
                "r.normalized_name ILIKE ?)"
            )
            params.append(f"%{respondent}%")
        params_t: list = list(params)
        has_status = _table_exists(con, "case_status")
        sql = (
            f"SELECT c.*{', cs.firmness_status' if has_status else ''} "
            "FROM cases c "
            + ("LEFT JOIN case_status cs USING(case_id) " if has_status else "")
            + "WHERE "
            + " AND ".join(where)
            + " ORDER BY boe_publication_date DESC NULLS LAST "
            "LIMIT ? OFFSET ?"
        )
        params_t += [limit, offset]
        return {
            "cases": _rows(con, sql, params_t),
            "limit": limit,
            "offset": offset,
            "coverage_note": (
                "Only cases publicly observable through the CNMV register "
                "snapshot are listed; absence does not imply no sanction."
            ),
        }
    finally:
        con.close()


# ── temporal semantics (ownership-radar doctrine) ─────────────────────
# known_at answers "what had the project OBSERVED by T?" — it gates on
# evidence/observation axes (observed_at), never on effective dates.
# A case is visible at T only if some observation of it existed by then.

@app.get("/cases/{case_id}")
def get_case(case_id: str, known_at: str | None = None) -> dict:
    con = _con()
    try:
        c = _rows(
            con,
            "SELECT * FROM cases WHERE case_id = ? OR canonical_boe_id = ?",
            [case_id, case_id],
        )
        if not c:
            raise HTTPException(404, "case not found")
        cid = c[0]["case_id"]
        out = dict(c[0])
        if known_at:
            ts = known_at
            # AS_KNOWN_AT — only observations with observed_at <= T
            evs = _rows(
                con,
                "SELECT fact_type, entity_id, field_name, locator, excerpt, "
                "proof_level, artifact_sha256, observed_at FROM evidence "
                "WHERE entity_id LIKE ? AND observed_at <= ? "
                "ORDER BY entity_id",
                [f"{cid}%", ts],
            )
            evs_ids = {e["entity_id"] for e in evs}
            out["events"] = _rows(
                con,
                "SELECT * FROM events WHERE case_id = ? "
                "AND observed_at <= ? ORDER BY event_date",
                [cid, ts],
            )
            out["status_notes"] = (
                _rows(
                    con,
                    "SELECT sn.* FROM status_notes sn "
                    "JOIN case_status cs ON sn.case_id = cs.case_id "
                    "WHERE sn.case_id = ? AND cs.observed_at <= ?",
                    [cid, ts],
                )
                if _table_exists(con, "status_notes")
                else []
            )
            out["evidence"] = evs
            # entities only where at least one observation existed by T
            out["sanctions"] = [
                s for s in _rows(
                    con,
                    "SELECT s.*, r.normalized_name respondent_name "
                    "FROM sanctions s LEFT JOIN respondents r "
                    "USING(respondent_id) WHERE s.case_id = ? "
                    "ORDER BY s.ordinal",
                    [cid],
                )
                if s["sanction_id"] in evs_ids
            ]
            out["infringements"] = [
                i for i in _rows(
                    con,
                    "SELECT * FROM infringements WHERE case_id = ? "
                    "ORDER BY ordinal",
                    [cid],
                )
                if i["infringement_id"] in evs_ids
            ]
            out["respondents"] = [
                r for r in _rows(
                    con,
                    "SELECT r.*, cr.role case_role FROM respondents r "
                    "JOIN case_respondents cr USING(respondent_id) "
                    "WHERE cr.case_id = ?",
                    [cid],
                )
                if r["respondent_id"] in evs_ids
            ]
            out["history_mode"] = "AS_KNOWN_AT"
            out["known_at"] = ts
            if not evs:
                out["observation_note"] = "NO_OBSERVATION_HISTORY"
            return out
        out["history_mode"] = "CURRENT_KNOWLEDGE_RECONSTRUCTED"
        out["infringements"] = _rows(
            con,
            "SELECT * FROM infringements WHERE case_id = ? ORDER BY ordinal",
            [cid],
        )
        out["sanctions"] = _rows(
            con,
            "SELECT s.*, r.normalized_name respondent_name FROM sanctions s "
            "LEFT JOIN respondents r USING(respondent_id) "
            "WHERE s.case_id = ? ORDER BY s.ordinal",
            [cid],
        )
        out["respondents"] = _rows(
            con,
            "SELECT r.*, cr.role case_role FROM respondents r "
            "JOIN case_respondents cr USING(respondent_id) "
            "WHERE cr.case_id = ?",
            [cid],
        )
        out["evidence"] = _rows(
            con,
            "SELECT fact_type, entity_id, field_name, locator, excerpt, "
            "proof_level, artifact_sha256, observed_at "
            "FROM evidence WHERE entity_id LIKE ? ORDER BY entity_id",
            [f"{cid}%"],
        )
        out["status_notes"] = (
            _rows(con, "SELECT * FROM status_notes WHERE case_id = ?", [cid])
            if _table_exists(con, "status_notes")
            else []
        )
        out["events"] = _rows(
            con,
            "SELECT * FROM events WHERE case_id = ? ORDER BY event_date",
            [cid],
        )
        return out
    finally:
        con.close()


@app.get("/respondents")
def list_respondents(
    q: str | None = Query(default=None), limit: int = Query(default=200, le=1000)
) -> dict:
    con = _con()
    try:
        sql = (
            "SELECT r.respondent_id, r.normalized_name, r.respondent_type, "
            "COUNT(s.sanction_id) sanctions, SUM(s.amount) total_amount, "
            "COUNT(DISTINCT s.case_id) cases "
            "FROM respondents r "
            "LEFT JOIN sanctions s USING(respondent_id) "
        )
        params: list = []
        if q:
            sql += "WHERE r.normalized_name ILIKE ? "
            params.append(f"%{q}%")
        sql += (
            "GROUP BY 1,2,3 ORDER BY total_amount DESC NULLS LAST LIMIT ?"
        )
        params.append(limit)
        return {"respondents": _rows(con, sql, params)}
    finally:
        con.close()


@app.get("/respondents/{respondent_id}")
def get_respondent(respondent_id: str) -> dict:
    con = _con()
    try:
        r = _rows(
            con, "SELECT * FROM respondents WHERE respondent_id = ?", [respondent_id]
        )
        if not r:
            raise HTTPException(404, "respondent not found")
        out = dict(r[0])
        out["sanctions"] = _rows(
            con,
            "SELECT * FROM sanctions WHERE respondent_id = ?",
            [respondent_id],
        )
        out["cases"] = _rows(
            con,
            "SELECT c.* FROM cases c JOIN case_respondents cr USING(case_id) "
            "WHERE cr.respondent_id = ?",
            [respondent_id],
        )
        return out
    finally:
        con.close()


@app.get("/laws")
def laws() -> dict:
    con = _con()
    try:
        return {
            "statutes": _rows(
                con,
                "SELECT statute_normalized statute, "
                "COUNT(*) infringements, COUNT(DISTINCT case_id) cases "
                "FROM infringements GROUP BY 1 ORDER BY 2 DESC",
            )
        }
    finally:
        con.close()


@app.get("/laws/{statute}/articles/{article}")
def article_infringements(statute: str, article: str) -> dict:
    con = _con()
    try:
        return {
            "infringements": _rows(
                con,
                "SELECT * FROM infringements WHERE statute_normalized ILIKE ? "
                "AND article_normalized = ?",
                [f"%{statute}%", article],
            )
        }
    finally:
        con.close()


@app.get("/status")
def status_observations() -> dict:
    con = _con()
    try:
        has_status = _table_exists(con, "case_status")
        return {
            "firmness_statuses": (
                _rows(
                    con,
                    "SELECT c.case_id, c.canonical_boe_id, cs.firmness_status "
                    "FROM cases c LEFT JOIN case_status cs USING(case_id)",
                )
                if has_status
                else _rows(
                    con,
                    "SELECT case_id, canonical_boe_id FROM cases",
                )
            ),
            "note": (
                "Statuses are observed-only: no appeal observed does NOT "
                "mean no appeal exists."
            ),
        }
    finally:
        con.close()


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
