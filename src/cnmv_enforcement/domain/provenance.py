"""Provenance model. See docs/provenance-contract.md."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .enums import ConfidenceType, ExtractionMethod


class FactEvidence(BaseModel):
    """Field-level evidence record.

    Lets a reviewer answer: "where exactly does this value come from?"
    """

    model_config = ConfigDict(frozen=True)

    fact_type: str = Field(description="Entity type the fact belongs to, e.g. sanction")
    entity_id: str = Field(description="Id of the entity carrying the fact")
    field_name: str = Field(description="Field the evidence supports, e.g. amount")
    document_id: str = Field(description="source_id of the supporting document")
    locator: str | None = Field(
        default=None,
        description="Paragraph index, XPath, page, or span inside the document",
    )
    excerpt: str | None = Field(
        default=None, description="Verbatim text fragment backing the fact"
    )
    extraction_method: ExtractionMethod
    confidence_type: ConfidenceType
    observed_at: datetime = Field(description="UTC instant the evidence was observed")


class ArtifactRef(BaseModel):
    """Reference to an immutable raw artifact (manifest row)."""

    model_config = ConfigDict(frozen=True)

    source_id: str
    authority: str
    canonical_locator: str | None
    retrieval_url: str
    retrieved_at: datetime
    sha256: str
    content_type: str | None
    http_status: int
    document_type: str
    raw_path: str
