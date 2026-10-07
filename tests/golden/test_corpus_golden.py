"""Golden corpus — all 91 register-linked BOE publication resolutions.

Each expectation was generated from a verified parse and stratified to
cover every observed grammar variant (bullets, numbering, multi-subject,
multi-sanction, lettered bullets, gerund conduct clauses, non-monetary
sanctions, missing-comma typos, guillemets, U+2212, ●).

A change here is a parser regression or an intentional format expansion —
either way it must be reviewed, never casually regenerated.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cnmv_enforcement.parsing.boe_publication import parse_publication_xml

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "corpus"
EXPECTATIONS = (
    Path(__file__).resolve().parent / "corpus_expectations.json"
)

_cases = json.loads(EXPECTATIONS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def expectations() -> dict[str, dict]:
    return {c["boe_id"]: c for c in _cases}


def test_all_fixture_files_have_expectations(expectations):
    xmls = sorted(FIXTURES.glob("BOE-A-*.xml"))
    assert len(xmls) == len(_cases) == 91
    assert {p.stem for p in xmls} == set(expectations)


@pytest.mark.parametrize("case", _cases, ids=lambda c: c["boe_id"])
def test_publication_parse(case):
    pub = parse_publication_xml(
        (FIXTURES / f"{case['boe_id']}.xml").read_bytes()
    )
    assert pub.boe_id == case["boe_id"]
    assert len(pub.blocks) == case["blocks"], (
        f"{case['boe_id']}: expected {case['blocks']} blocks, "
        f"got {len(pub.blocks)}"
    )
    n_sanc = sum(len(b.sanctions) for b in pub.blocks)
    assert n_sanc == case["sanctions"], (
        f"{case['boe_id']}: expected {case['sanctions']} sanctions, "
        f"got {n_sanc}"
    )
    assert sorted({b.severity.value for b in pub.blocks}) == case["severities"]
    assert sorted(
        {b.article_normalized for b in pub.blocks if b.article_normalized}
    ) == case["articles"]
    assert sorted(
        {b.statute_normalized for b in pub.blocks if b.statute_normalized}
    ) == case["statutes"]
    total = int(
        sum(s.amount or 0 for b in pub.blocks for s in b.sanctions)
    )
    assert total == case["total_fine_eur"]
    assert sorted(
        {s.subject_raw for b in pub.blocks for s in b.sanctions}
    ) == case["subjects"]
    assert not pub.parse_issues, pub.parse_issues


def test_corpus_grammar_coverage():
    """The frozen corpus must exercise every grammar family — deleting a
    fixture silently would weaken this guarantee."""
    assert len(_cases) >= 30  # stratification floor


def test_stratified_grammar_markers(expectations):
    """Spot-check documents that carry each distinct grammar variant."""
    # numbered 'Imponer a X, Y, Z' multi-subject blocks
    assert expectations["BOE-A-2024-20286"]["sanctions"] == 14
    # ● bullets with bare 'A X: N euros' sanctions
    assert expectations["BOE-A-2023-18206"]["sanctions"] == 15
    # restitution + fine multi-clause tail
    assert expectations["BOE-A-2024-13096"]["sanctions"] >= 2
    # 'sanción de separación del cargo … y sanción de multa' zone
    assert expectations["BOE-A-2025-18960"]["non_monetary"] == [
        "DISQUALIFICATION"
    ]
    # non-monetary public reprimand only
    assert expectations["BOE-A-2026-16752"]["non_monetary"] == [
        "PUBLIC_REPRIMAND"
    ]
    # missing comma before 'multa' (source typo, year boundary)
    assert expectations["BOE-A-2022-1771"]["total_fine_eur"] == 15000
    # 'todos ellos de la Ley 22/2014' quantifier statute coverage
    assert expectations["BOE-A-2026-16921"]["statutes"] == ["Ley 22/2014"]
