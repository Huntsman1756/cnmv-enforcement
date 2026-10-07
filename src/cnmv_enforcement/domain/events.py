"""Event log — the only source of truth for legal-state claims.

``case_observed_state``/``respondent_observed_state``/``sanction_observed_state``
are *projections* derived from this log and may be rebuilt at any time. A
judgment may affect one respondent or one sanction without touching the
others — hence projections are per-entity, never a single case column.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from .enums import EventType, ObservedState


class CaseEvent(BaseModel):
    event_id: str
    case_id: str
    respondent_id: str | None = None
    sanction_id: str | None = None
    infringement_id: str | None = None
    event_type: EventType
    event_date: date | None = Field(
        default=None, description="Legal/effective date if supported by source"
    )
    observed_at: datetime
    source_document_id: str
    event_payload: dict[str, Any] = Field(default_factory=dict)


class StateProjection(BaseModel):
    """Derived view. Rebuildable; never a second source of truth."""

    entity_kind: str = Field(description="case | respondent | sanction")
    entity_id: str
    observed_state: ObservedState = ObservedState.UNKNOWN
    derived_from_event_ids: list[str] = Field(default_factory=list)
    computed_at: datetime
    note: str | None = None
