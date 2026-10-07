"""Parsed/aggregate bundles — what the pipeline produces and persists."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .case import Case, CaseRespondent, Infringement, Respondent, Sanction
from .documents import DocumentRelationship, SourceDocument
from .events import CaseEvent
from .provenance import FactEvidence


class CaseBundle(BaseModel):
    """All entities of one parsed case, ready for persistence."""

    case: Case
    respondents: list[Respondent] = Field(default_factory=list)
    case_respondents: list[CaseRespondent] = Field(default_factory=list)
    infringements: list[Infringement] = Field(default_factory=list)
    sanctions: list[Sanction] = Field(default_factory=list)
    events: list[CaseEvent] = Field(default_factory=list)
    evidence: list[FactEvidence] = Field(default_factory=list)
    documents: list[SourceDocument] = Field(default_factory=list)
    relationships: list[DocumentRelationship] = Field(default_factory=list)


class Dataset(BaseModel):
    """The whole normalized dataset."""

    schema_version: int
    generated_at: datetime
    cases: list[Case] = Field(default_factory=list)
    respondents: list[Respondent] = Field(default_factory=list)
    case_respondents: list[CaseRespondent] = Field(default_factory=list)
    infringements: list[Infringement] = Field(default_factory=list)
    sanctions: list[Sanction] = Field(default_factory=list)
    documents: list[SourceDocument] = Field(default_factory=list)
    relationships: list[DocumentRelationship] = Field(default_factory=list)
    events: list[CaseEvent] = Field(default_factory=list)
    evidence: list[FactEvidence] = Field(default_factory=list)
