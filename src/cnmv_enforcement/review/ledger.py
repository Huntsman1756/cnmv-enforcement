"""Review-ledger persistence — append-only JSONL + parquet table.

The ledger is authoritative *project metadata*, never official
regulatory fact: it records what judgement was made, against which
source bytes, under which parser/schema semantics — and when it stops
being automatically usable.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from cnmv_enforcement.review.model import ReviewItem, ReviewStatus


def serialize_review(r: ReviewItem) -> dict:
    return {
        "review_id": r.review_id,
        "subject_type": r.subject_type,
        "subject_id": r.subject_id,
        "document_id": r.document_id,
        "raw_sha256": r.raw_sha256,
        "review_compat_version": r.review_compat_version,
        "parser_version": r.parser_version,
        "dataset_schema_version": r.dataset_schema_version,
        "reason_code": r.reason_code,
        "status": str(r.status),
        "expected_interpretation": r.expected_interpretation,
        "reviewed_value_json": r.reviewed_value_json,
        "reviewed_at": (
            r.reviewed_at.isoformat() if r.reviewed_at else None
        ),
        "reviewer": r.reviewer,
        "notes": r.notes,
        "supersedes_review_id": r.supersedes_review_id,
    }


def load_ledger(path: Path) -> list[ReviewItem]:
    if not path.exists():
        return []
    out: list[ReviewItem] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        out.append(
            ReviewItem(
                review_id=d["review_id"],
                subject_type=d["subject_type"],
                subject_id=d["subject_id"],
                document_id=d["document_id"],
                raw_sha256=d["raw_sha256"],
                review_compat_version=d["review_compat_version"],
                parser_version=d["parser_version"],
                dataset_schema_version=d["dataset_schema_version"],
                reason_code=d["reason_code"],
                status=ReviewStatus(d["status"]),
                expected_interpretation=d.get("expected_interpretation"),
                reviewed_value_json=d.get("reviewed_value_json"),
                reviewed_at=(
                    datetime.fromisoformat(d["reviewed_at"])
                    if d.get("reviewed_at")
                    else None
                ),
                reviewer=d.get("reviewer"),
                notes=d.get("notes"),
                supersedes_review_id=d.get("supersedes_review_id"),
            )
        )
    return out


def append_ledger(path: Path, items: list[ReviewItem]) -> int:
    """Append new review_items — existing ids are never rewritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    have = {r.review_id for r in load_ledger(path)}
    n = 0
    with path.open("a", encoding="utf-8") as fh:
        for r in items:
            if r.review_id not in have:
                fh.write(
                    json.dumps(serialize_review(r), ensure_ascii=False) + "\n"
                )
                have.add(r.review_id)
                n += 1
    return n


def ledger_table(items: list[ReviewItem]) -> list[dict]:
    return [serialize_review(r) for r in items]
