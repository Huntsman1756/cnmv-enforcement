"""Assemble a ParsedPublication (+ optional register row) into a CaseBundle.

Deterministic: same inputs → same ids, same order. Facts carry evidence
records pointing at the source document + paragraph locator.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from functools import lru_cache

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
    EventType,
    ExtractionMethod,
    RespondentType,
    Severity,
)
from cnmv_enforcement.domain.events import CaseEvent
from cnmv_enforcement.domain.provenance import FactEvidence
from cnmv_enforcement.legal.rules import RuleIndex, load_rules, resolve_rule_version
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
    split_subject_role,
    strip_successor_clause,
)
from cnmv_enforcement.parsing.text import normalize_key


def _strip_person_prefix(name: str) -> str:
    return re.sub(r"^(?:don|doña|d\.|dña)\s+", "", name.strip(), flags=re.IGNORECASE)


def _normalized_name(raw: str) -> str:
    return normalize_key(_strip_person_prefix(raw))


@lru_cache(maxsize=1)
def _rules() -> RuleIndex:
    return load_rules()


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

    def ev(  # noqa: PLR0917 — field-level evidence needs the full locator
        fact_type: str,
        entity_id: str,
        field_name: str,
        para_index: int,
        excerpt: str,
        method: ExtractionMethod = ExtractionMethod.DIRECT,
        raw_value: str | None = None,
    ) -> None:
        bundle.evidence.append(
            FactEvidence(
                fact_type=fact_type,
                entity_id=entity_id,
                field_name=field_name,
                document_id=document_id,
                locator=f"texto/p[{para_index + 1}]",  # XPath-true: p[1]=first
                excerpt=excerpt[:500],
                extraction_method=method,
                confidence_type=ConfidenceType(method.value),
                observed_at=observed_at,
                representation="XML",
                locator_type="PARAGRAPH",
                artifact_sha256=pub.raw_sha256,
                raw_value=raw_value,
            )
        )

    respondents: dict[str, Respondent] = {}

    def respondent_for(name_raw: str) -> Respondent:
        # successor clause is legal-identity context, not a name —
        # 'NCG Banco, S.A., como sucesor en la responsabilidad
        # declarada de Caixa Galicia' → respondent 'NCG Banco, S.A.'
        name_raw, _pred = strip_successor_clause(name_raw)
        # strip the role clause for identity — 'don X, en su condición de
        # consejero de Y' is the same respondent as 'don X'; the verbatim
        # name stays in raw_display_name, the role in role_raw
        name_part, role = split_subject_role(name_raw)
        norm = _normalized_name(name_part)
        rtype = classify_subject(name_part)
        rid = respondent_id_for(norm, rtype.value)
        if rid not in respondents:
            resp = Respondent(
                respondent_id=rid,
                raw_display_name=name_raw.strip(),
                normalized_name=_strip_person_prefix(name_part.strip()),
                respondent_type=rtype,
                source_anonymized=rtype == RespondentType.ANONYMIZED_PERSON,
                publication_policy=(
                    "SOURCE_ANONYMIZED"
                    if rtype == RespondentType.ANONYMIZED_PERSON
                    else "SOURCE_NAMED"
                ),
                role_raw=role,
            )
            respondents[rid] = resp
            bundle.case_respondents.append(
                CaseRespondent(case_id=case_id, respondent_id=rid, role=role)
            )
        return respondents[rid]

    # map a successor-sanction block onto the infringement ordinal of
    # the 'Declarar la responsabilidad de X' block it succeeds —
    # 'Imponer a <succ>, como sucesor en la responsabilidad declarada
    # de <X>' means the sanction answers for X's infringement
    declared_iid: dict[int, str] = {}
    declared_name_iid: dict[str, str] = {}

    def _emit_sanction(line, resp, sid, iid, block) -> None:
        # per-line successor link overrides the block-level one —
        # 'Bancaja, una multa…' under a succ-list binds Bancaja's
        # declared infringement, not the block's
        if line.declared_subject is not None:
            iid = declared_name_iid.get(
                line.declared_subject.lower().strip(' ,').rstrip('.'), iid
            )
        s = Sanction(
            sanction_id=sid,
            case_id=case_id,
            respondent_id=resp.respondent_id,
            infringement_id=iid,
            ordinal=line.ordinal,
            sanction_type=line.sanction_type,
            severity=block.severity,
            amount=line.amount,
            currency=line.currency,
            amount_raw=line.amount_raw,
            duration_raw=line.duration_raw,
        )
        bundle.sanctions.append(s)
        ev(
            "sanction", sid, "subject", line.paragraph_index,
            line.excerpt, raw_value=line.subject_raw,
        )
        ev(
            "sanction", sid, "sanction_text", line.paragraph_index,
            line.excerpt, raw_value=line.sanction_raw,
        )
        if line.amount is not None:
            ev(
                "sanction",
                sid,
                "amount",
                line.paragraph_index,
                line.excerpt,
                ExtractionMethod.NORMALIZED,
                raw_value=line.amount_raw or str(line.amount),
            )

    for block in pub.blocks:
        if block.declared_for is not None:
            # successor sanction — the infringement row already exists
            # from the 'Declarar' block; bind sanctions to its iid.
            # severity/article/statute live on the DECLARATION
            src = block.declared_for
            iid = declared_iid[id(src)]
            for line in block.sanctions:
                resp = respondent_for(line.subject_raw)
                sid = sanction_id_for(case_id, line.ordinal)
                _emit_sanction(line, resp, sid, iid, src)
            continue
        iid = infringement_id_for(case_id, block.ordinal)
        declared_iid[id(block)] = iid
        if block.declared:
            # 'Declarar la responsabilidad de X' — X is a case
            # respondent even when the sanction lands on a successor;
            # no sanction row exists for it
            for s in block.subjects_inline:
                respondent_for(s)
                declared_name_iid[s.lower().strip(' ,').rstrip('.')] = iid
        # a pure successor-host block ('Imponer a <succ> una multa de:'
        # + per-predecessor amount lines) creates NO infringement —
        # every sanction binds per-line to its declared block
        pure_succ_host = bool(block.sanctions) and all(
            ln.declared_subject is not None for ln in block.sanctions
        )
        if pure_succ_host:
            for line in block.sanctions:
                resp = respondent_for(line.subject_raw)
                sid = sanction_id_for(case_id, line.ordinal)
                _emit_sanction(line, resp, sid, iid, block)
            continue
        (
            rule_version_id,
            rule_status,
            conduct_code,
            _resolved_family,
        ) = resolve_rule_version(
            _rules(),
            block.statute_normalized,
            block.article_normalized,
            block.conduct_start,
            block.conduct_end,
        )
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
            conduct_start_date=block.conduct_start,
            conduct_end_date=block.conduct_end,
            conduct_code=conduct_code,
            rule_version_id=rule_version_id,
            rule_resolution_status=rule_status,
        )
        bundle.infringements.append(infr)
        ev(
            "infringement", iid, "severity", block.paragraph_index,
            block.header_text,
            # the verbatim source token — the enum is English and can
            # never satisfy VALUE_BINDING; the Spanish severity word is
            # what actually appears in the paragraph
            raw_value={
                Severity.VERY_SERIOUS: "muy grave",
                Severity.SERIOUS: "grave",
                Severity.MINOR: "leve",
            }.get(block.severity),
        )
        if block.article_raw:
            ev(
                "infringement",
                iid,
                "article",
                block.paragraph_index,
                block.header_text,
                ExtractionMethod.NORMALIZED,
                raw_value=block.article_raw,
            )
        if block.conduct_raw:
            ev(
                "infringement", iid, "conduct", block.paragraph_index,
                block.conduct_raw, raw_value=block.conduct_raw,
            )
        for line in block.sanctions:
            resp = respondent_for(line.subject_raw)
            sid = sanction_id_for(case_id, line.ordinal)
            _emit_sanction(line, resp, sid, iid, block)

    bundle.respondents = list(respondents.values())
    for rid, respo in respondents.items():
        bundle.evidence.append(
            FactEvidence(
                fact_type="respondent",
                entity_id=rid,
                field_name="name",
                document_id=document_id,
                artifact_sha256=pub.raw_sha256,
                locator=None,
                excerpt=respo.raw_display_name,
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
    if pub.administrative_appeal:
        add_event(
            EventType.ADMINISTRATIVE_APPEAL,
            None,
            {"wording": "interpuesto recurso de alzada/reposición "
             "(observed in publication)"},
        )
    if pub.renunciation_stated:
        add_event(
            EventType.ADMINISTRATIVE_FINALITY,
            None,
            {"wording": "renunciado al recurso administrativo "
             "(observed in publication)"},
        )
    if pub.publication_date:
        add_event(EventType.BOE_PUBLICATION, pub.publication_date)

    return bundle
