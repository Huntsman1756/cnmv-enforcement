"""Coverage ledger — the honest-scope metadata layer.

Generated per build and shipped with every export. It records exactly
WHAT the dataset covers, from WHERE, at WHICH observation time — and,
critically, what it does NOT claim:

- register absence does not establish that no sanction existed;
- the register keeps entries for five years, so the live snapshot is
  not a complete historical archive;
- minor infringements are not guaranteed to be in scope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from cnmv_enforcement import __version__

DATASET_SCHEMA_VERSION = "0.1.0"

_SCOPE_STATEMENT = (
    "Publicly observable CNMV enforcement reconstructed from the CNMV "
    "public sanctions register, BOE publications and subsequent official "
    "documents. This is NOT a complete database of all CNMV sanctions."
)

_LIMITATIONS = [
    "The CNMV public register retains entries for five years; the live "
    "register is an observed snapshot, not a complete historical archive.",
    "Register absence does not establish that no sanction was imposed.",
    "Removal from the register does not establish legal erasure.",
    "Minor infringements are not guaranteed to be included in register "
    "scope (register severity scope: very serious + serious).",
    "A BOE publication resolution is not necessarily the complete "
    "underlying sanctioning decision.",
    "Historical backfill beyond the register window is a separate, "
    "explicitly-versioned extension.",
    "No appeal was observed is NOT equivalent to no appeal exists.",
]


@dataclass
class SourceCoverage:
    source: str  # cnmv_register | boe_sumario | boe_document | cnmv_document
    role: str
    observed_from: date | None = None
    observed_to: date | None = None
    count: int = 0
    snapshot_id: str | None = None


@dataclass
class CoverageLedger:
    dataset_schema_version: str = DATASET_SCHEMA_VERSION
    package_version: str = __version__
    generated_at: str = ""
    scope_statement: str = _SCOPE_STATEMENT
    register_severity_scope: list[str] = field(
        default_factory=lambda: ["VERY_SERIOUS", "SERIOUS"]
    )
    minor_infringement_coverage: str = "NOT_GUARANTEED"
    sources: list[SourceCoverage] = field(default_factory=list)
    case_count: int = 0
    infringement_count: int = 0
    sanction_count: int = 0
    respondent_count: int = 0
    register_snapshot: dict = field(default_factory=dict)
    boe_date_range: dict = field(default_factory=dict)
    historical_backfill: dict = field(default_factory=dict)
    known_gaps: list[str] = field(default_factory=list)
    unresolved_or_ambiguous: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=lambda: list(_LIMITATIONS))

    def to_dict(self) -> dict:
        return {
            "dataset_schema_version": self.dataset_schema_version,
            "package_version": self.package_version,
            "generated_at": self.generated_at,
            "scope_statement": self.scope_statement,
            "register_severity_scope": self.register_severity_scope,
            "minor_infringement_coverage": self.minor_infringement_coverage,
            "sources": [
                {
                    "source": s.source,
                    "role": s.role,
                    "observed_from": (
                        s.observed_from.isoformat() if s.observed_from else None
                    ),
                    "observed_to": (
                        s.observed_to.isoformat() if s.observed_to else None
                    ),
                    "count": s.count,
                    "snapshot_id": s.snapshot_id,
                }
                for s in self.sources
            ],
            "counts": {
                "cases": self.case_count,
                "infringements": self.infringement_count,
                "sanctions": self.sanction_count,
                "respondents": self.respondent_count,
            },
            "register_snapshot": self.register_snapshot,
            "boe_date_range": self.boe_date_range,
            "historical_backfill": self.historical_backfill,
            "known_gaps": self.known_gaps,
            "unresolved_or_ambiguous": self.unresolved_or_ambiguous,
            "limitations": self.limitations,
            "non_claims": [
                "absence_from_dataset_does_not_imply_no_sanction",
                "register_absence_does_not_imply_no_sanction",
                "removed_from_register_does_not_imply_legal_erasure",
            ],
        }
