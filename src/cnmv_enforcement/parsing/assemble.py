"""Assemble a ParsedPublication (+ optional register row) into a CaseBundle.

Deterministic: same inputs → same ids, same order. Facts carry evidence
records pointing at the source document + paragraph locator.
"""

from __future__ import annotations

from datetime import UTC, datetime

from cnmv_enforcement.domain.bundle import CaseBundle
from cnmv_enforcement.domain.case import (
    Case,
    CaseRespondent,
    Infringement,
    Respondent,
    Sanction,
)
from cnmv_enforcement.domain.enums import (
    Authority,
    ConfidenceType,
    ConductCode,
    EventType,
    ExtractionMethod,
    RespondentType,
    RuleResolutionStatus,
    Severity,
)
from cnmv_enforcement.domain.events import CaseEvent
from cnmv_enforcement.domain.provenance import FactEvidence
from cnmv_enforcement.normalize.ids import (
    case_id_for,
    event_id_for,
    infringement_id_for,
    respondent_id_for,
    sanction_id_for,
)
from cnmv_enforcement.parsing.boe_publication import (
    ParsedPublication,
    classify_subject,
)
from cnmv_enforcement.parsing.text import normalize_key


def _strip_person_prefix(name: str) -> str:
    import re

    return re.sub(r"^(?:don|doña|d\.|dña)\s+", "", name.strip(), flags=re.IGNORECASE)


def _normalized_name(raw: str) -> str:
    return normalize_key(_strip_person_prefix(raw))


def assemble_case(
    pub: ParsedPublication,
    *,
    document_id: str,
    observed_at: datetime,
    register_entry_date=None,
    fallback_key: str = "",
) -> CaseBundle:
    case_id = case_id_for(pub.boe_id, fallback_key or (pub.title or ""))
    case = Case(
        case_id=case_id,
        authority=Authority.CNMV,
        title_raw=pub.title,
        canonical_boe_id=pub.boe_id,
        sanctioning_resolution_date=pub.sanctioning_resolution_date,
        publication_resolution_date=pub.document_date,
        register_entry_date=register_entry_date,
        boe_publication_date=pub.publication_date,
        created_at=datetime.now(UTC),
    )
    bundle = CaseBundle(case=case)

    def ev(
        fact_type: str,
        entity_id: str,
        field_name: str,
        para_index: int,
        excerpt: str,
        method: ExtractionMethod = ExtractionMethod.DIRECT,
    ) -> None:
        bundle.evidence.append(
            FactEvidence(
                fact_type=fact_type,
                entity_id=entity_id,
                field_name=field_name,
                document_id=document_id,
                locator=f"texto/p[{para_index}]",
                excerpt=excerpt[:500],
                extraction_method=method,
                confidence_type=ConfidenceType(method.value),
                observed_at=observed_at,
            )
        )

    respondents: dict[str, Respondent] = {}
    respondent_ord: dict[str, int] = {}

    def respondent_for(name_raw: str) -> Respondent:
        norm = _normalized_name(name_raw)
        rtype = classify_subject(name_raw)
        rid = respondent_id_for(norm, rtype.value)
        if rid not in respondents:
            resp = Respondent(
                respondent_id=rid,
                raw_display_name=name_raw.strip(),
                normalized_name=_strip_person_prefix(name_raw.strip()),
                respondent_type=rtype,
                source_anonymized=rtype == RespondentType.ANONYMIZED_PERSON,
                publication_policy=(
                    "SOURCE_ANONYMIZED"
                    if rtype == RespondentType.ANONYMIZED_PERSON
                    else "SOURCE_NAMED"
                ),
            )
            respondents[rid] = resp
            respondent_ord[rid] = len(respondent_ord)
            bundle.case_respondents.append(
                CaseRespondent(case_id=case_id, respondent_id=rid)
            )
        return respondents[rid]

    for block in pub.blocks:
        iid = infringement_id_for(case_id, block.ordinal)
        infr = Infringement(
            infringement_id=iid,
            case_id=case_id,
            ordinal=block.ordinal,
            severity=block.severity,
            statute_raw=block.statute_raw,
            article_raw=block.article_raw,
            statute_normalized=block.statute_normalized,
            article_normalized=block.article_normalized,
            related_provisions=block.related,
            conduct_raw=block.conduct_raw,
            conduct_code=ConductCode.UNKNOWN,
            rule_version_id=None,
            rule_resolution_status=RuleResolutionStatus.UNRESOLVED_RULE_VERSION,
        )
        bundle.infringements.append(infr)
        ev("infringement", iid, "severity", block.paragraph_index, block.header_text)
        if block.article_raw:
            ev(
                "infringement",
                iid,
                "article",
                block.paragraph_index,
                block.header_text,
                ExtractionMethod.NORMALIZED,
            )
        if block.conduct_raw:
            ev(
                "infringement", iid, "conduct", block.paragraph_index,
                block.conduct_raw,
            )
        for line in block.sanctions:
            resp = respondent_for(line.subject_raw)
            sid = sanction_id_for(case_id, line.ordinal)
            sev = block.severity if block.severity != Severity.UNKNOWN else Severity.UNKNOWN
            s = Sanction(
                sanction_id=sid,
                case_id=case_id,
                respondent_id=resp.respondent_id,
                infringement_id=iid,
                ordinal=line.ordinal,
                sanction_type=line.sanction_type,
                severity=sev,
                amount=line.amount,
                currency=line.currency,
                amount_raw=line.amount_raw,
            )
            bundle.sanctions.append(s)
            ev("sanction", sid, "subject", line.paragraph_index, line.excerpt)
            ev("sanction", sid, "sanction_text", line.paragraph_index, line.excerpt)
            if line.amount is not None:
                ev(
                    "sanction",
                    sid,
                    "amount",
                    line.paragraph_index,
                    line.excerpt,
                    ExtractionMethod.NORMALIZED,
                )

    bundle.respondents = list(respondents.values())
    for rid in respondents:
        bundle.evidence.append(
            FactEvidence(
                fact_type="respondent",
                entity_id=rid,
                field_name="name",
                document_id=document_id,
                locator=None,
                excerpt=respondents[rid].raw_display_name,
                extraction_method=ExtractionMethod.DIRECT,
                confidence_type=ConfidenceType.DIRECT,
                observed_at=observed_at,
            )
        )

    event_ord = 0

    def add_event(
        etype: EventType, event_date, payload: dict | None = None
    ) -> None:
        nonlocal event_ord
        event_ord += 1
        bundle.events.append(
            CaseEvent(
                event_id=event_id_for(case_id, etype.value, event_ord, document_id),
                case_id=case_id,
                event_type=etype,
                event_date=event_date,
                observed_at=observed_at,
                source_document_id=document_id,
                event_payload=payload or {},
            )
        )

    if pub.sanctioning_resolution_date:
        add_event(EventType.RESOLUTION, pub.sanctioning_resolution_date)
    if pub.administrative_finality:
        add_event(
            EventType.ADMINISTRATIVE_FINALITY,
            None,
            {"wording": "firmes en dicha vía (observed in publication)"},
        )
    if pub.publication_date:
        add_event(EventType.BOE_PUBLICATION, pub.publication_date)

    return bundle
