"""Parquet export — one file per table, deterministic content order."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

_EMPTY_SCHEMAS: dict[str, list[tuple[str, pa.DataType]]] = {
    "parse_issues": [
        ("boe_id", pa.string()),
        ("kind", pa.string()),
        ("detail", pa.string()),
    ],
}


def write_parquet(tables: dict[str, list[dict]], out_dir: Path) -> dict[str, Path]:
    """Write each table as ``<table>.parquet`` in out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for name, rows in tables.items():
        path = out_dir / f"{name}.parquet"
        if rows:
            table = pa.Table.from_pylist(rows)
        elif name in _EMPTY_SCHEMAS:
            table = pa.Table.from_pylist(
                [], schema=pa.schema(_EMPTY_SCHEMAS[name])
            )
        else:
            continue  # empty table with no declared schema — skip file
        pq.write_table(table, path, compression="zstd")
        written[name] = path
    return written
