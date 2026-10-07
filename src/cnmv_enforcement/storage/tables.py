"""Flatten CaseBundles into column-oriented table dicts.

The flat schema is the analytical interface — every field is a plain
Python scalar ready for PyArrow. Lists of nested objects fan out to
their own tables (related_provisions, evidence, events).
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from cnmv_enforcement.parsing.boe_publication import ParsedPublication
from cnmv_enforcement.pipeline.build import BuildResult


def _d(v: Any) -> Any:
    # Decimal passes through untouched — PyArrow maps it to a DECIMAL
    # logical type, keeping exact amounts in the canonical export.
    if isinstance(v, Decimal):
        return v
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if hasattr(v, "value"):  # StrEnum
        return v.value
    return v


def _verify_proof(ev: Any, pub: Any) -> str:
    from cnmv_enforcement.evidence.verify import verify_binding

    return verify_binding(ev, pub)


def _appeal_status(obs: dict | None) -> str:
    """Epistemic appeal state from a pdf-status observation entry.

    A strong negative (NOT_OBSERVED_WITHIN_VERIFIED_COVERAGE) requires a
    VERIFIED enumeration of the PDF content — a failed fetch or empty
    extraction is INCONCLUSIVE, never a negative claim.
    """
    if not obs:
        return "INCONCLUSIVE"
    # snapshots without 'retrieval' (pre-v0.5) cannot prove the PDF was
    # enumerated — a missing field is INCONCLUSIVE, not a negative claim
    retrieval = obs.get("retrieval")
    if retrieval != "OK":
        return "INCONCLUSIVE"
    kinds = {n.get("kind") for n in obs.get("notes", [])}
    if kinds & {
        "JUDICIAL_APPEAL_OBSERVED",
        "JUDGMENT_OBSERVED",
        "RENUNCIATION_TO_APPEAL",
    }:
        return "OBSERVED"
    return "NOT_OBSERVED_WITHIN_VERIFIED_COVERAGE"


def _pdf_basis_id(pdf_status: dict[str, dict] | None) -> str | None:
    """Coverage basis for the CNMV-PDF status run — identifies the
    verified surface (manifest hash + observed bounds)."""
    if not pdf_status:
        return None
    from cnmv_enforcement.coverage.epistemic import coverage_basis_id

    dates = sorted(
        str(o.get("observed_at") or "") for o in pdf_status.values()
    )
    import hashlib
    import json

    manifest_sha = hashlib.sha256(
        json.dumps(pdf_status, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return coverage_basis_id(
        "cnmv_verdocumento",
        "pdf-status-run",
        dates[0][:10] if dates else None,
        dates[-1][:10] if dates else None,
        manifest_sha,
    )


def flatten(
    result: BuildResult,
    pdf_status: dict[str, dict] | None = None,
    review_items: list | None = None,
) -> dict[str, list[dict]]:
    """→ table_name → rows.

    ``pdf_status``: ``{boe_id: {sha256, notes, status}}`` observations from
    the CNMV-PDF status run — folded into ``case_status`` rows when given.
    ``review_items``: review-ledger rows (authoritative project metadata).
    """
    tables: dict[str, list[dict]] = {
        "cases": [],
        "respondents": [],
        "case_respondents": [],
        "infringements": [],
        "related_provisions": [],
        "sanctions": [],
        "events": [],
        "evidence": [],
        "documents": [],
        "parse_issues": [],
        "case_status": [],
        "status_notes": [],
        "review_items": [],
    }
    meta: dict[str, ParsedPublication] = {
        p.boe_id or "": p for p in result.publications
    }
    seen_respondents: set[str] = set()
    basis_id = _pdf_basis_id(pdf_status) if pdf_status else None
    for bundle in result.bundles:
        c = bundle.case
        pub = meta.get(c.canonical_boe_id or "")
        obs = (pdf_status or {}).get(c.canonical_boe_id or "")
        appeal_status = _appeal_status(obs)
        tables["cases"].append(
            {
                "case_id": c.case_id,
                "authority": _d(c.authority),
                "title_raw": c.title_raw,
                "canonical_boe_id": c.canonical_boe_id,
                "sanctioning_resolution_date": _d(c.sanctioning_resolution_date),
                "publication_resolution_date": _d(c.publication_resolution_date),
                "register_entry_date": _d(c.register_entry_date),
                "boe_publication_date": _d(c.boe_publication_date),
                "administrative_finality_observed": (
                    pub.administrative_finality if pub else None
                ),
                "judicial_review_mentioned": (
                    pub.judicial_review_possible if pub else None
                ),
                "administrative_appeal_observed": (
                    pub.administrative_appeal if pub else None
                ),
                "n_infringements": len(bundle.infringements),
                "n_sanctions": len(bundle.sanctions),
                "n_respondents": len(bundle.respondents),
                "appeal_observation_status": appeal_status,
                "coverage_basis_id": (
                    basis_id
                    if appeal_status
                    != "INCONCLUSIVE"
                    else None
                ),
            }
        )
        if obs:
            tables["case_status"].append(
                {
                    "case_id": c.case_id,
                    "firmness_status": obs.get("status"),
                    "n_cnmv_notes": len(obs.get("notes", [])),
                    "pdf_sha256": obs.get("sha256"),
                    "first_observed_at": obs.get("first_observed_at")
                    or obs.get("observed_at"),
                    "observed_at": obs.get("observed_at"),
                }
            )
            for note in obs.get("notes", []):
                tables["status_notes"].append(
                    {
                        "case_id": c.case_id,
                        "kind": note.get("kind"),
                        "page": note.get("page"),
                        "verbatim": note.get("verbatim"),
                    }
                )
                if note.get("kind") in {
                    "JUDICIAL_APPEAL_OBSERVED",
                    "JUDGMENT_OBSERVED",
                }:
                    from cnmv_enforcement.normalize.ids import content_hash

                    tables["events"].append(
                        {
                            "event_id": (
                                f"{c.case_id}/PDF-"
                                f"{content_hash(
                                    note.get('kind'),
                                    str(note.get('page')),
                                    (note.get('verbatim') or '')[:120],
                                )[:12]}"
                            ),
                            "case_id": c.case_id,
                            "event_type": (
                                "JUDICIAL_APPEAL_FILED"
                                if note["kind"] == "JUDICIAL_APPEAL_OBSERVED"
                                else "JUDGMENT"
                            ),
                            "event_date": None,
                            "observed_at": obs.get("observed_at"),
                            "source_document_id": (
                                f"cnmv-pdf:{c.canonical_boe_id}"
                            ),
                            "event_payload": json.dumps(
                                {
                                    "verbatim": note.get("verbatim"),
                                    "page": note.get("page"),
                                    "note": "filing date not stated in note",
                                },
                                ensure_ascii=False,
                            ),
                        }
                    )
        if pub:
            tables["documents"].append(
                {
                    "document_id": f"boe-xml:{pub.boe_id}",
                    "boe_id": pub.boe_id,
                    "source": "BOE",
                    "corpus": pub.corpus,
                    "format": "xml",
                    "title": pub.title,
                    "publication_date": _d(pub.publication_date),
                    "document_date": _d(pub.document_date),
                }
            )
        for r in bundle.respondents:
            if r.respondent_id in seen_respondents:
                continue
            seen_respondents.add(r.respondent_id)
            tables["respondents"].append(
                {
                    "respondent_id": r.respondent_id,
                    "raw_display_name": r.raw_display_name,
                    "normalized_name": r.normalized_name,
                    "respondent_type": _d(r.respondent_type),
                    "source_anonymized": r.source_anonymized,
                    "publication_policy": r.publication_policy,
                    "role_raw": r.role_raw,
                }
            )
        for cr in bundle.case_respondents:
            tables["case_respondents"].append(
                {
                    "case_id": cr.case_id,
                    "respondent_id": cr.respondent_id,
                    "role": cr.role,
                }
            )
        for i in bundle.infringements:
            tables["infringements"].append(
                {
                    "infringement_id": i.infringement_id,
                    "case_id": i.case_id,
                    "ordinal": i.ordinal,
                    "severity": _d(i.severity),
                    "statute_raw": i.statute_raw,
                    "article_raw": i.article_raw,
                    "statute_normalized": i.statute_normalized,
                    "article_normalized": i.article_normalized,
                    "conduct_raw": i.conduct_raw,
                    "conduct_start_date": _d(i.conduct_start_date),
                    "conduct_end_date": _d(i.conduct_end_date),
                    "conduct_code": _d(i.conduct_code),
                    "rule_version_id": i.rule_version_id,
                    "rule_resolution_status": _d(i.rule_resolution_status),
                    "n_related_provisions": len(i.related_provisions),
                }
            )
            for ref in i.related_provisions:
                tables["related_provisions"].append(
                    {
                        "infringement_id": i.infringement_id,
                        "case_id": i.case_id,
                        "statute_raw": ref.statute_raw,
                        "article_raw": ref.article_raw,
                        "statute_normalized": ref.statute_normalized,
                        "article_normalized": ref.article_normalized,
                        "relation": ref.relation,
                    }
                )
        for s in bundle.sanctions:
            tables["sanctions"].append(
                {
                    "sanction_id": s.sanction_id,
                    "case_id": s.case_id,
                    "respondent_id": s.respondent_id,
                    "infringement_id": s.infringement_id,
                    "ordinal": s.ordinal,
                    "sanction_type": _d(s.sanction_type),
                    "severity": _d(s.severity),
                    "amount": _d(s.amount),
                    "currency": s.currency,
                    "amount_raw": s.amount_raw,
                    "duration_raw": s.duration_raw,
                }
            )
        for e in bundle.events:
            tables["events"].append(
                {
                    "event_id": e.event_id,
                    "case_id": e.case_id,
                    "event_type": _d(e.event_type),
                    "event_date": _d(e.event_date),
                    "observed_at": _d(e.observed_at),
                    "source_document_id": e.source_document_id,
                    "event_payload": json.dumps(e.event_payload, ensure_ascii=False)
                    if e.event_payload
                    else None,
                }
            )
        for ev in bundle.evidence:
            tables["evidence"].append(
                {
                    "fact_type": ev.fact_type,
                    "entity_id": ev.entity_id,
                    "field_name": ev.field_name,
                    "document_id": ev.document_id,
                    "locator": ev.locator,
                    "excerpt": ev.excerpt,
                    "extraction_method": _d(ev.extraction_method),
                    "confidence_type": _d(ev.confidence_type),
                    "observed_at": _d(ev.observed_at),
                    "representation": ev.representation,
                    "locator_type": ev.locator_type,
                    "artifact_sha256": ev.artifact_sha256,
                    "proof_level": _verify_proof(ev, pub),
                    "raw_value": ev.raw_value,
                }
            )
    for issue in result.issues:
        tables["parse_issues"].append(dict(issue))
    if review_items:
        from cnmv_enforcement.review.ledger import ledger_table

        tables["review_items"] = ledger_table(review_items)
    return tables
