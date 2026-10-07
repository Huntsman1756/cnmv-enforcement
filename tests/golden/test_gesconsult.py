"""Golden test: BOE-A-2026-16921 (Gesconsult) — the mandatory cardinality case.

Observed truth (verified against the BOE XML on 2026-10-07):

- 1 publication resolution
- 2 respondents: Gesconsult, SA, SGIIC (legal person) + don Juan Lladó
  García-Lomas (natural person)
- 3 infringements: 1 very serious (93.a), 2 serious (94.ñ, 94.o)
- 6 monetary fines (2 respondents x 3 infringements):
  50 000 + 40 000 + 30 000 + 20 000 + 35 000 + 25 000 EUR
- 3 distinct dates: sanctioning 2026-04-30, publication resolution
  2026-07-17, BOE publication 2026-08-03
- administrative finality + possibility of judicial review

The parser must produce this from the general grammar — no
Gesconsult-specific branches.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from cnmv_enforcement.domain.enums import (
    RespondentType,
    RuleResolutionStatus,
    SanctionType,
    Severity,
)
from cnmv_enforcement.parsing.assemble import assemble_case
from cnmv_enforcement.parsing.boe_publication import (
    classify_subject,
    parse_publication_xml,
)

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "boe"
    / "BOE-A-2026-16921.xml"
)

pytestmark = pytest.mark.golden


@pytest.fixture(scope="module")
def pub():
    return parse_publication_xml(FIXTURE.read_bytes())


def test_document_metadata(pub):
    assert pub.boe_id == "BOE-A-2026-16921"
    assert pub.publication_date is not None and pub.publication_date.isoformat() == "2026-08-03"
    assert pub.document_date is not None and pub.document_date.isoformat() == "2026-07-17"
    assert (
        pub.sanctioning_resolution_date is not None
        and pub.sanctioning_resolution_date.isoformat() == "2026-04-30"
    )
    assert pub.administrative_finality is True
    assert pub.judicial_review_possible is True
    assert pub.parse_issues == []


def test_cardinalities(pub):
    assert len(pub.blocks) == 3
    sanctions = [s for b in pub.blocks for s in b.sanctions]
    assert len(sanctions) == 6


def test_infringement_articles(pub):
    arts = [(b.severity, b.article_normalized, b.statute_normalized) for b in pub.blocks]
    assert arts == [
        (Severity.VERY_SERIOUS, "93.a", "Ley 22/2014"),
        (Severity.SERIOUS, "94.ñ", "Ley 22/2014"),
        (Severity.SERIOUS, "94.o", "Ley 22/2014"),
    ]
    related = [[r.article_normalized for r in b.related] for b in pub.blocks]
    assert related == [["67", "70"], ["45", "47", "48"], ["13.2", "45"]]


def test_sanction_amounts(pub):
    per_block = [[(s.subject_raw, s.amount) for s in b.sanctions] for b in pub.blocks]
    amounts = sorted(s.amount for b in pub.blocks for s in b.sanctions)
    assert amounts == sorted(
        [Decimal("50000"), Decimal("40000"), Decimal("30000"),
         Decimal("20000"), Decimal("35000"), Decimal("25000")]
    )
    for lines in per_block:
        subjects = {subj for subj, _amt in lines}
        assert subjects == {"Gesconsult, SA, SGIIC", "don Juan Lladó García-Lomas"}


def test_subject_types():
    assert classify_subject("Gesconsult, SA, SGIIC") == RespondentType.LEGAL_PERSON
    assert classify_subject("don Juan Lladó García-Lomas") == RespondentType.NATURAL_PERSON


def test_bundle_assembly(pub):
    bundle = assemble_case(
        pub,
        document_id="AEBOE:boe_xml:test",
        observed_at=__import__("datetime").datetime(2026, 10, 7),
    )
    assert bundle.case.case_id == "CNMV-BOE-A-2026-16921"
    assert len(bundle.respondents) == 2
    assert len(bundle.infringements) == 3
    assert len(bundle.sanctions) == 6
    types = {r.respondent_type for r in bundle.respondents}
    assert types == {RespondentType.LEGAL_PERSON, RespondentType.NATURAL_PERSON}
    # every sanction references a real infringement + respondent
    iids = {i.infringement_id for i in bundle.infringements}
    rids = {r.respondent_id for r in bundle.respondents}
    for s in bundle.sanctions:
        assert s.infringement_id in iids
        assert s.respondent_id in rids
        assert s.currency == "EUR"
        assert s.sanction_type == SanctionType.MONETARY_FINE
    # rule versions resolve under Ley 22/2014 for every infringement
    for i in bundle.infringements:
        assert i.rule_resolution_status in (
            RuleResolutionStatus.VALID_FOR_CONDUCT,
            RuleResolutionStatus.UNRESOLVED_RULE_VERSION,
        )
        if i.rule_resolution_status == RuleResolutionStatus.VALID_FOR_CONDUCT:
            assert i.rule_version_id is not None
    # evidence exists for every sanction
    sids = {s.sanction_id for s in bundle.sanctions}
    evidenced = {e.entity_id for e in bundle.evidence if e.fact_type == "sanction"}
    assert sids <= evidenced
    # events: resolution + finality + publication
    etypes = {e.event_type.value for e in bundle.events}
    assert etypes == {"RESOLUTION", "ADMINISTRATIVE_FINALITY", "BOE_PUBLICATION"}
