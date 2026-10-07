"""DuckDB build — tables from the parquet export, typed explicitly.

Parquet files are the canonical export; the DuckDB file is a queryable
projection of the same rows (rebuild is deterministic from parquet).
"""

from __future__ import annotations

from pathlib import Path

import duckdb

_TABLES = [
    "cases",
    "respondents",
    "case_respondents",
    "infringements",
    "related_provisions",
    "sanctions",
    "events",
    "evidence",
    "documents",
    "parse_issues",
    "case_status",
    "status_notes",
    "review_items",
]


def build_duckdb(parquet_dir: Path, db_path: Path) -> dict[str, int]:
    """Load all parquet tables into a fresh DuckDB database file."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = duckdb.connect(str(db_path))
    counts: dict[str, int] = {}
    try:
        for name in _TABLES:
            pq = parquet_dir / f"{name}.parquet"
            if not pq.exists():
                continue
            con.execute(
                f'CREATE TABLE "{name}" AS SELECT * FROM read_parquet(?)',
                [str(pq)],
            )
            row = con.execute(
                f'SELECT COUNT(*) FROM "{name}"'
            ).fetchone()
            counts[name] = row[0] if row else 0
        con.execute(
            "CREATE TABLE meta AS SELECT "
            "current_timestamp AS built_at_utc, "
            f"'{duckdb.__version__}' AS duckdb_version"
        )
    finally:
        con.close()
    return counts
