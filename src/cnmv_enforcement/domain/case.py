"""Case grain entities.

Case = one CNMV enforcement matter as publicly observable through a
publication resolution. A case has respondents; each infringement is
committed by respondent(s) and may produce one or more sanctions per
respondent.

Temporal fields are deliberately separate:

- ``sanctioning_resolution_date``: the underlying Consejo/Board resolution
  that *imposes* the sanctions (e.g. 2026-04-30 for Gesconsult).
- ``publication_resolution_date``: the resolution ordering *publication*
  (BOE ``fecha_disposicion``, e.g. 2026-07-17).
- ``boe_publication_date``: BOE ``fecha_publicacion`` (e.g. 2026-08-03).
- ``register_entry_date``: CNMV "Fecha de incorporación al registro".

None of these is the offence date. Conduct dates live on ``Infringement``.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from .enums import (
    Authority,
    ConductCode,
    RespondentType,
    RuleResolutionStatus,
    SanctionType,
    Severity,
)


class Case(BaseModel):
    case_id: str
    authority: Authority = Authority.CNMV
    title_raw: str | None = None
    canonical_boe_id: str | None = Field(
        default=None, description="BOE-A-* locator when resolvable"
    )
    sanctioning_resolution_date: date | None = None
    publication_resolution_date: date | None = None
    register_entry_date: date | None = None
    boe_publication_date: date | None = None
    created_at: datetime


class Respondent(BaseModel):
    respondent_id: str
    raw_display_name: str
    normalized_name: str | None = None
    respondent_type: RespondentType = RespondentType.UNKNOWN
    source_anonymized: bool = False
    publication_policy: str = Field(
        default="SOURCE_NAMED",
        description="SOURCE_NAMED | SOURCE_ANONYMIZED — reproduces only what "
        "the official source makes public; no enrichment, no reidentification",
    )
    role_raw: str | None = Field(
        default=None,
        description="Role in the sanctioned entity when the source states it "
        "(e.g. 'consejero'), verbatim",
    )
    regulatory_entity_id: str | None = Field(
        default=None,
        description="Link to an external regulatory register (finreg-es / "
        "OpenCNMV) — populated ONLY by strong-identifier evidence",
    )
    lei: str | None = None


class CaseRespondent(BaseModel):
    case_id: str
    respondent_id: str
    role: str | None = None


class LegalReference(BaseModel):
    """One statutory reference as written plus its normalization.

    ``raw`` is never destroyed; ``normalized`` is a deterministic transform.
    Letter suffixes (o, ñ, a, b, bis, ter, quater) are preserved exactly.
    """

    statute_raw: str
    article_raw: str
    statute_normalized: str | None = None
    article_normalized: str | None = None
    relation: str = Field(
        default="TYPIFYING",
        description="TYPIFYING (tipificada en) | RELATED (en relación con) | "
        "CONDUCT (conduct provision cited)",
    )


class Infringement(BaseModel):
    infringement_id: str
    case_id: str
    ordinal: int = Field(description="Document order of the impose clause")
    severity: Severity = Severity.UNKNOWN
    statute_raw: str | None = None
    article_raw: str | None = None
    statute_normalized: str | None = None
    article_normalized: str | None = None
    related_provisions: list[LegalReference] = Field(default_factory=list)
    conduct_raw: str | None = Field(
        default=None, description="Verbatim conduct clause ('por la remisión…')"
    )
    conduct_start_date: date | None = None
    conduct_end_date: date | None = None
    conduct_code: ConductCode = ConductCode.UNKNOWN
    rule_version_id: str | None = None
    rule_resolution_status: RuleResolutionStatus = (
        RuleResolutionStatus.UNRESOLVED_RULE_VERSION
    )


class Sanction(BaseModel):
    sanction_id: str
    case_id: str
    respondent_id: str
    infringement_id: str | None = Field(
        default=None,
        description="Impose clause this sanction belongs to, when determinable",
    )
    ordinal: int = Field(description="Document order")
    sanction_type: SanctionType = SanctionType.UNKNOWN
    severity: Severity = Severity.UNKNOWN
    amount: Decimal | None = None
    currency: str | None = None
    amount_raw: str | None = Field(
        default=None, description="Verbatim amount text e.g. '50.000 euros'"
    )
    duration_raw: str | None = Field(
        default=None, description="Verbatim duration for non-monetary sanctions"
    )
    relief_type: str | None = None
