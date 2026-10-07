"""Documents and their relationships.

A BOE publication resolution is *not* the full sanctioning decision
(``BOE PUBLICATION RESOLUTION != FULL SANCTIONING DECISION``). A BOE
correction never deletes the original — it links to it via ``CORRECTS``.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from .enums import Authority, DocumentRole, DocumentType, RelationshipType


class SourceDocument(BaseModel):
    """A first-class document entity backed by an immutable raw artifact."""

    document_id: str = Field(description="source_id of the backing artifact")
    authority: Authority
    document_type: DocumentType
    document_role: DocumentRole = DocumentRole.UNCLASSIFIED
    canonical_locator: str | None = None
    title: str | None = None
    publication_date: date | None = None
    document_date: date | None = Field(
        default=None,
        description="Date on the document itself (fecha_disposicion), != publication_date",
    )
    retrieved_at: datetime
    sha256: str
    content_type: str | None = None
    retrieval_url: str
    raw_path: str


class DocumentRelationship(BaseModel):
    source_document_id: str
    target_document_id: str
    relationship_type: RelationshipType
    evidence_document_id: str | None = Field(
        default=None,
        description="Document whose content establishes this relationship "
        "(defaults to source_document_id when the relationship is asserted "
        "by the source document itself)",
    )
    note: str | None = None
