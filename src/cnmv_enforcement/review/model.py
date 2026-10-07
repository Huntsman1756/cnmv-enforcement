"""Review ledger — version-bound human/probatory judgements.

A review is a decision recorded against a *specific* combination of
source bytes, parser semantics and schema. When any of those change
incompatibly, the review goes STALE — it does NOT silently remain
accepted (a past human review ≠ valid review forever).

Compat rule: reviews bind to ``review_compat_version`` (semantic,
minor-level — patch bumps of the parser never invalidate a review).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ReviewStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    CORRECTED = "CORRECTED"
    ABSTAINED = "ABSTAINED"
    STALE = "STALE"


class DefectClass(StrEnum):
    PHANTOM_RESPONDENT = "PHANTOM_RESPONDENT"
    RESPONDENT_MERGE_LOSS = "RESPONDENT_MERGE_LOSS"
    ENTITY_NAME_SPLIT_ERROR = "ENTITY_NAME_SPLIT_ERROR"
    SUBJECT_TEXT_CONTAMINATION = "SUBJECT_TEXT_CONTAMINATION"
    RESPECTIVAMENTE_ALIGNMENT_ERROR = "RESPECTIVAMENTE_ALIGNMENT_ERROR"
    COMISION_VARIANT_DROP = "COMISION_VARIANT_DROP"
    STATUTE_MISATTRIBUTION = "STATUTE_MISATTRIBUTION"
    ARTICLE_SUFFIX_LOSS = "ARTICLE_SUFFIX_LOSS"
    CONDUCT_DATE_LOSS = "CONDUCT_DATE_LOSS"
    RESOLUTION_DATE_LOSS = "RESOLUTION_DATE_LOSS"
    DURATION_FIELD_LOSS = "DURATION_FIELD_LOSS"
    DUPLICATE_KEY_CORRUPTION = "DUPLICATE_KEY_CORRUPTION"


# the semantic band a review stays valid under — patch bumps don't
# invalidate; a parser normalisation grammar change bumps this
REVIEW_COMPAT_VERSION = "0.5"


def review_id_for(
    subject_type: str,
    subject_id: str,
    document_id: str,
    raw_sha256: str,
    compat_version: str,
) -> str:
    """Deterministic review id — same judgement target = same id."""
    h = hashlib.sha256(
        "|".join(
            [subject_type, subject_id, document_id, raw_sha256,
             compat_version]
        ).encode("utf-8")
    ).hexdigest()
    return f"RV-{h[:16]}"


@dataclass(frozen=True)
class ReviewItem:
    review_id: str
    subject_type: str          # defect | sanction | respondent | …
    subject_id: str
    document_id: str
    raw_sha256: str
    review_compat_version: str
    parser_version: str
    dataset_schema_version: str
    reason_code: str           # defect class or review reason
    status: ReviewStatus
    expected_interpretation: str | None = None
    reviewed_value_json: str | None = None
    reviewed_at: datetime | None = None
    reviewer: str | None = None
    notes: str | None = None
    supersedes_review_id: str | None = None

    def staleness_reason(self, now_compat: str, now_raw_sha: str) -> str | None:
        """Deterministic invalidation — returns a reason or None."""
        if now_compat != self.review_compat_version:
            return (
                f"review_compat_version {self.review_compat_version} "
                f"!= current {now_compat}"
            )
        if now_raw_sha != self.raw_sha256:
            return "raw_sha256 changed — source bytes differ"
        return None


def apply_staleness(
    items: list[ReviewItem], now_compat: str, raw_sha_by_doc: dict[str, str]
) -> list[ReviewItem]:
    """Mark every non-valid review STALE — never silently accepts."""
    out: list[ReviewItem] = []
    for r in items:
        reason = r.staleness_reason(
            now_compat, raw_sha_by_doc.get(r.document_id, "")
        )
        if reason and r.status is not ReviewStatus.STALE:
            out.append(
                ReviewItem(
                    **{
                        **r.__dict__,
                        "status": ReviewStatus.STALE,
                        "notes": (r.notes or "")
                        + f" [STALE: {reason}]",
                    }
                )
            )
        else:
            out.append(r)
    return out


# ------------------------------------------------------------------ seeding
def seed_from_defect_registry(
    registry_path: str,
    raw_sha_by_boe: dict[str, str],
    parser_version: str,
    schema_version: str,
    reviewer: str = "adversarial-review",
) -> list[ReviewItem]:
    """Seed CORRECTED review_items from the permanent defect registry —
    the 18 adversarial defects become structural review history."""
    from pathlib import Path

    import yaml

    doc = yaml.safe_load(Path(registry_path).read_text(encoding="utf-8"))
    items: list[ReviewItem] = []
    for d in doc["defects"]:
        for boe in d["fixtures"]:
            sha = raw_sha_by_boe.get(boe, "")
            rid = review_id_for(
                "defect", d["defect_id"], boe, sha, REVIEW_COMPAT_VERSION
            )
            items.append(
                ReviewItem(
                    review_id=rid,
                    subject_type="defect",
                    subject_id=d["defect_id"],
                    document_id=boe,
                    raw_sha256=sha,
                    review_compat_version=REVIEW_COMPAT_VERSION,
                    parser_version=parser_version,
                    dataset_schema_version=schema_version,
                    reason_code=d["defect_class"],
                    status=ReviewStatus.CORRECTED,
                    expected_interpretation=d["description"],
                    reviewed_at=datetime.fromisoformat("2026-10-08T00:00:00"),
                    reviewer=reviewer,
                    notes=f"fix_commit {d['fix_commit']} (round {d['round']})",
                )
            )
    return items
