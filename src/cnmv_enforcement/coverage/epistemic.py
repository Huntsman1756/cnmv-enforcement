"""Epistemic coverage states — absence is a claim, not a default.

    0 results  !=  proof of absence

A negative claim is only admissible when the *surface* of the search is
itself verifiable. HTTP errors, partial enumerations and ambiguous
terminations are never strong negatives — they are INCONCLUSIVE at best.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum


class CoverageStatus(StrEnum):
    OBSERVED = "OBSERVED"
    NOT_OBSERVED_WITHIN_VERIFIED_COVERAGE = (
        "NOT_OBSERVED_WITHIN_VERIFIED_COVERAGE"
    )
    UNAVAILABLE = "UNAVAILABLE"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class CoverageBasis:
    """Identifies *what surface* a negative claim was checked against.

    A strong negative (``NOT_OBSERVED_WITHIN_VERIFIED_COVERAGE``) is only
    admissible with a basis proving enumeration over a defined universe.
    """

    basis_id: str
    source: str                # e.g. cnmv_register | boe_sumario
    enumeration: str           # e.g. daily-sumario-dept-1040 | register-snapshot
    date_from: str | None
    date_to: str | None
    manifest_sha256: str | None = None
    item_count: int | None = None
    retrieval_status: str = "COMPLETE"  # COMPLETE | PARTIAL | FAILED


def coverage_basis_id(
    source: str,
    enumeration: str,
    date_from: str | None,
    date_to: str | None,
    manifest_sha256: str | None = None,
) -> str:
    h = hashlib.sha256(
        json.dumps(
            {
                "source": source,
                "enum": enumeration,
                "from": date_from,
                "to": date_to,
                "sha": manifest_sha256,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return f"cb-{h[:16]}"


@dataclass
class CoverageAssessment:
    """Outcome of one observation query — positive or negative."""

    entity: str                # e.g. appeal | status_note | case
    subject_id: str            # e.g. case_id | boe_id
    status: CoverageStatus
    basis: CoverageBasis | None = None
    observed_value: str | None = None
    detail: str | None = None

    def to_dict(self) -> dict:
        return {
            "entity": self.entity,
            "subject_id": self.subject_id,
            "status": str(self.status),
            "basis_id": self.basis.basis_id if self.basis else None,
            "basis": {
                "source": self.basis.source,
                "enumeration": self.basis.enumeration,
                "date_from": self.basis.date_from,
                "date_to": self.basis.date_to,
                "manifest_sha256": self.basis.manifest_sha256,
                "item_count": self.basis.item_count,
                "retrieval_status": self.basis.retrieval_status,
            }
            if self.basis
            else None,
            "observed_value": self.observed_value,
            "detail": self.detail,
        }


def assess(
    *,
    entity: str,
    subject_id: str,
    found: bool,
    observed_value: str | None = None,
    basis: CoverageBasis | None = None,
    retrieval_ok: bool = True,
    detail: str | None = None,
) -> CoverageAssessment:
    """Classify an observation result — never upgrades a weak negative."""
    if found:
        return CoverageAssessment(
            entity, subject_id, CoverageStatus.OBSERVED, basis,
            observed_value, detail,
        )
    if not retrieval_ok:
        return CoverageAssessment(
            entity, subject_id, CoverageStatus.UNAVAILABLE, basis,
            None, detail or "source not retrievable",
        )
    if basis and basis.retrieval_status == "COMPLETE":
        return CoverageAssessment(
            entity,
            subject_id,
            CoverageStatus.NOT_OBSERVED_WITHIN_VERIFIED_COVERAGE,
            basis,
            None,
            detail or f"enumerated {basis.item_count} items, none matched",
        )
    return CoverageAssessment(
        entity,
        subject_id,
        CoverageStatus.INCONCLUSIVE,
        basis,
        None,
        detail or "enumeration incomplete — cannot claim absence",
    )
