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

    # ── v0.5 evidence binding ──────────────────────────────────────
    representation: str | None = Field(
        default=None,
        description="Source representation: XML, PDF_TEXT, REGISTER_HTML…",
    )
    locator_type: str | None = Field(
        default=None,
        description="PARAGRAPH | CHAR_SPAN | XPATH | PAGE — the kind of "
        "locator the proof binds against",
    )
    artifact_sha256: str | None = Field(
        default=None,
        description="SHA-256 of the raw artifact bytes the locator "
        "resolves against — the binding belongs to these bytes, "
        "not the URL",
    )
    proof_level: str | None = Field(
        default=None,
        description=(
            "DOCUMENT_PROVEN | LOCATION_PROVEN | VALUE_BINDING_PROVEN | "
            "NORMALIZED_VALUE_DERIVED — never conflate: the document "
            "being right does not prove the field binding"
        ),
    )
    raw_value: str | None = Field(
        default=None,
        description="Verbatim source value whose presence inside the "
        "excerpt upgrades the binding to VALUE_BINDING_PROVEN",
    )


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
