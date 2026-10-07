"""Per-case observed-state projection.

Combines what the BOE publication resolution itself states (administrative
finality, judicial-review possibility, appeal observations) with status
notes observed in CNMV-hosted PDFs. Output is per-case, per-observation —
never a blanket 'the sanction is final' claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from cnmv_enforcement.parsing.boe_publication import ParsedPublication
from cnmv_enforcement.parsing.cnmv_pdf import PdfStatusNote


class FirmnessStatus:
    FIRM_STATED = "FIRM_STATED"
    RENUNCIATION_OBSERVED = "RENUNCIATION_OBSERVED"
    APPEAL_POSSIBLE = "APPEAL_POSSIBLE"
    APPEAL_OBSERVED = "APPEAL_OBSERVED"
    JUDGMENT_OBSERVED = "JUDGMENT_OBSERVED"
    UNKNOWN = "UNKNOWN"


@dataclass
class CaseStatusObservation:
    case_id: str
    firmness_status: str
    basis: list[str] = field(default_factory=list)
    cnmv_notes: list[dict] = field(default_factory=list)
    observed_at: datetime | None = None
    # epistemic claim on the appeal axis specifically — never
    # "no appeal", only what the verified surface showed
    appeal_observation_status: str = "INCONCLUSIVE"
    coverage_basis_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "firmness_status": self.firmness_status,
            "appeal_observation_status": self.appeal_observation_status,
            "coverage_basis_id": self.coverage_basis_id,
            "basis": self.basis,
            "cnmv_notes": self.cnmv_notes,
            "observed_at": self.observed_at.isoformat()
            if self.observed_at
            else None,
        }


def project_case_status(
    case_id: str,
    pub: ParsedPublication | None = None,
    pdf_notes: list[PdfStatusNote] | None = None,
    observed_at: datetime | None = None,
    *,
    pdf_covered: bool = False,
    coverage_basis_id: str | None = None,
) -> CaseStatusObservation:
    """Project the observed firmness status for one case.

    Ordering of precedence for the headline status (most informative wins):
    judgment observed > appeal observed > firm stated / renunciation >
    appeal possible > unknown.

    ``pdf_covered`` = the CNMV-PDF status run verified this case's PDF —
    without it a missing appeal note is INCONCLUSIVE, never a negative
    claim.
    """
    basis: list[str] = []
    status = FirmnessStatus.UNKNOWN
    rank = {
        FirmnessStatus.UNKNOWN: 0,
        FirmnessStatus.APPEAL_POSSIBLE: 1,
        FirmnessStatus.FIRM_STATED: 2,
        FirmnessStatus.RENUNCIATION_OBSERVED: 2,
        FirmnessStatus.APPEAL_OBSERVED: 3,
        FirmnessStatus.JUDGMENT_OBSERVED: 4,
    }

    def bump(new: str, why: str) -> None:
        nonlocal status
        basis.append(why)
        if rank[new] > rank[status]:
            status = new

    if pub is not None:
        if pub.administrative_finality:
            bump(
                FirmnessStatus.FIRM_STATED,
                "publication states administrative finality",
            )
        if pub.administrative_appeal:
            bump(
                FirmnessStatus.APPEAL_OBSERVED,
                "publication states an administrative appeal was filed",
            )
        if pub.renunciation_stated:
            bump(
                FirmnessStatus.RENUNCIATION_OBSERVED,
                "publication states renunciation of administrative appeals",
            )
        if pub.judicial_review_possible:
            bump(
                FirmnessStatus.APPEAL_POSSIBLE,
                "publication states judicial review is possible",
            )
    note_map = {
        "RENUNCIATION_TO_APPEAL": FirmnessStatus.RENUNCIATION_OBSERVED,
        "ADMINISTRATIVE_FINALITY": FirmnessStatus.FIRM_STATED,
        "JUDICIAL_REVIEW_POSSIBLE": FirmnessStatus.APPEAL_POSSIBLE,
        "JUDICIAL_APPEAL_OBSERVED": FirmnessStatus.APPEAL_OBSERVED,
        "JUDGMENT_OBSERVED": FirmnessStatus.JUDGMENT_OBSERVED,
    }
    for note in pdf_notes or []:
        bump(
            note_map.get(note.kind, FirmnessStatus.UNKNOWN),
            f"cnmv pdf p{note.page}: {note.verbatim[:80]}",
        )
    # appeal axis epistemic state
    if status in (
        FirmnessStatus.APPEAL_OBSERVED,
        FirmnessStatus.JUDGMENT_OBSERVED,
        FirmnessStatus.RENUNCIATION_OBSERVED,
    ):
        appeal_status = "OBSERVED"
    elif pdf_covered:
        appeal_status = "NOT_OBSERVED_WITHIN_VERIFIED_COVERAGE"
    else:
        appeal_status = "INCONCLUSIVE"
    return CaseStatusObservation(
        case_id=case_id,
        firmness_status=status,
        appeal_observation_status=appeal_status,
        coverage_basis_id=(
            coverage_basis_id
            if appeal_status != "INCONCLUSIVE"
            else None
        ),
        basis=basis,
        cnmv_notes=[
            {"kind": n.kind, "page": n.page, "verbatim": n.verbatim}
            for n in pdf_notes or []
        ],
        observed_at=observed_at,
    )
