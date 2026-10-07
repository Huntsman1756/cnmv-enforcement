"""Dataset release manifest — the auditable identity of a frozen build.

For every table: row count, physical SHA-256 of the Parquet file, a
logical row-content hash (canonical JSON over rows — Decimal → string,
dates → ISO) and a schema fingerprint. The corpus-level
``corpus_logical_sha256`` orders table logical hashes so a logical diff
between two builds is one comparison away.

DuckDB is a query surface; Parquet + this manifest are authoritative.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from cnmv_enforcement import __version__
from cnmv_enforcement.config import PARSER_VERSION, SCHEMA_VERSION

_CANONICAL_SPEC = "CNMV_ENFORCEMENT_CANONICAL_V1"


def _canon(v: Any) -> Any:
    """Canonical JSON-safe form — Decimal → string, never float."""
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, bool) or v is None or isinstance(v, (int, str)):
        return v
    if isinstance(v, float):
        # floats must never enter the canonical chain
        raise TypeError(f"float in canonical serialization: {v!r}")
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _canon(v[k]) for k in sorted(v)}
    if isinstance(v, (list, tuple)):
        return [_canon(x) for x in v]
    return str(v)


def canonical_json(obj: Any) -> str:
    """Deterministic serialization — sorted keys, no whitespace,
    Decimal-as-string. Spec: CNMV_ENFORCEMENT_CANONICAL_V1."""
    return json.dumps(
        _canon(obj), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def logical_sha256(path: Path) -> str:
    """Hash of the table's logical rows — insensitive to Parquet encoding."""
    t = pq.read_table(path)
    h = hashlib.sha256()
    for row in sorted(t.to_pylist(), key=canonical_json):
        h.update(canonical_json(row).encode("utf-8") + b"\n")
    return h.hexdigest()


def schema_fingerprint(path: Path) -> str:
    s = pq.read_schema(path)
    desc = ";".join(f"{f.name}:{s.field(f.name).type}" for f in s)
    return hashlib.sha256(desc.encode("utf-8")).hexdigest()[:16]


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        return None


def _release_tag(path: Path) -> str | None:
    # the parquet subdir lives inside the release dir — check both levels
    for name in (path.name, path.parent.name):
        m = re.fullmatch(r"v?\d+\.\d+\.\d+(?:-rc\d+)?", name)
        if m:
            return m.group(0)
    return None


def build_manifest(
    parquet_dir: Path,
    *,
    coverage_path: Path | None = None,
    inputs: dict[str, Any] | None = None,
    built_at: datetime | None = None,
) -> dict:
    tables: dict[str, dict] = {}
    table_hashes: list[str] = []
    for pq_path in sorted(parquet_dir.glob("*.parquet")):
        entry = {
            "rows": pq.read_table(pq_path).num_rows,
            "sha256": file_sha256(pq_path),
            "logical_sha256": logical_sha256(pq_path),
            "schema_fingerprint": schema_fingerprint(pq_path),
        }
        tables[pq_path.stem] = entry
        table_hashes.append(entry["logical_sha256"])
    corpus_hash = hashlib.sha256(
        canonical_json({"order": "sorted-stem", "tables": table_hashes}).encode()
    ).hexdigest()
    manifest: dict[str, Any] = {
        "dataset_schema_version": SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "generator_version": __version__,
        "canonical_serialization": _CANONICAL_SPEC,
        "code_commit": _git_commit(),
        "built_at": (built_at or datetime.now(UTC)).isoformat(),
        "release": _release_tag(parquet_dir),
        "inputs": inputs or {},
        "tables": tables,
        "corpus_logical_sha256": corpus_hash,
        "authoritative_artifacts": [
            "parquet/*.parquet",
            "coverage.json",
            "dataset_manifest.json",
            "SHA256SUMS",
        ],
        "query_surfaces_nonauthoritative": ["cnmv-enforcement.duckdb"],
    }
    if coverage_path and coverage_path.exists():
        manifest["coverage_sha256"] = file_sha256(coverage_path)
    return manifest


def write_release(
    parquet_dir: Path,
    *,
    coverage_path: Path | None = None,
    inputs: dict[str, Any] | None = None,
) -> Path:
    """Write dataset_manifest.json + SHA256SUMS next to the Parquet set."""
    manifest = build_manifest(
        parquet_dir, coverage_path=coverage_path, inputs=inputs
    )
    mpath = parquet_dir.parent / "dataset_manifest.json"
    mpath.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    sums_path = parquet_dir.parent / "SHA256SUMS"
    lines = []
    for name, entry in sorted(manifest["tables"].items()):
        lines.append(
            f"{entry['sha256']}  parquet/{name}.parquet"
        )
    if coverage_path and coverage_path.exists():
        lines.append(f"{manifest['coverage_sha256']}  coverage.json")
    pdfm = parquet_dir.parent / "pdf_status_manifest.json"
    if pdfm.exists():
        # the coverage basis for negative appeal claims is a release
        # artifact — it must be hash-pinned like the tables
        lines.append(f"{file_sha256(pdfm)}  pdf_status_manifest.json")
    dbq = parquet_dir.parent / "cnmv-enforcement.duckdb"
    if dbq.exists():
        # non-authoritative query surface, still hash-pinned for
        # reproducible verification of the shipped bytes
        lines.append(f"{file_sha256(dbq)}  cnmv-enforcement.duckdb")
    lines.append(f"{file_sha256(mpath)}  dataset_manifest.json")
    sums_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return mpath
