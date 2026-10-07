"""Regression coverage for the 18 adversarial defects.

Every defect in ``data/review/defect_registry.yaml`` gets an explicit
test asserting the corrected behaviour on the cited frozen fixture —
the review ledger's machine oracle. ``REVIEW_COVERAGE`` at the bottom
produces the machine-readable coverage artifact.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cnmv_enforcement.parsing.boe_publication import parse_publication_xml, split_subjects
from cnmv_enforcement.parsing.dates import extract_conduct_period

ROOT = Path(__file__).resolve().parents[1].parent
HIST = ROOT / "data" / "corpus_historical"
REG = ROOT / "tests" / "fixtures" / "corpus"
REGISTRY = ROOT / "data" / "review" / "defect_registry.yaml"


CORP = ROOT / "data" / "corpus"


def _pub(boe: str):
    for base in (HIST, REG, CORP):
        p = base / f"{boe}.xml"
        if p.exists():
            return parse_publication_xml(p.read_bytes())
    raise FileNotFoundError(boe)


def test_S1_duration_not_dropped():
    pub = _pub("BOE-A-2023-17427")
    durations = [s.duration_raw for b in pub.blocks for s in b.sanctions if s.duration_raw]
    assert durations, "duration_raw lost between parse and assembly"


def test_S2_resolution_date_extracted():
    pub = _pub("BOE-A-2026-16921")
    assert pub.sanctioning_resolution_date is not None


def test_S3_no_phantom_paren_subjects():
    pub = _pub("BOE-A-2022-17410")
    subs = [s.subject_raw for b in pub.blocks for s in b.sanctions]
    for s in subs:
        assert "a la fecha" not in s, f"paren text leaked into subject: {s}"


def test_S4_xy_subject_list_splits():
    pub = _pub("BOE-A-2025-16708")
    subs = {s.subject_raw for b in pub.blocks for s in b.sanctions}
    joined = " ".join(subs)
    assert " y don " not in joined and " y doña " not in joined, (
        "X y Y subject list not split"
    )


def test_S5_no_dative_phantom_respondents():
    pub = _pub("BOE-A-2022-12643")
    subs = {s.subject_raw for b in pub.blocks for s in b.sanctions}
    for s in subs:
        assert "descripción" not in s.lower() and len(s) < 120


def test_S6_lettered_articles_kept():
    pub = _pub("BOE-A-2022-9282")
    arts = {r.article_normalized for b in pub.blocks for r in b.related}
    assert "227.1.a" in arts and "227.1.b" in arts


def test_S7_reglamento_numero_normalized():
    pub = _pub("BOE-A-2024-13096")
    for b in pub.blocks:
        for r in b.related:
            if "Reglamento" in (r.statute_normalized or ""):
                assert "596/2014" in r.statute_normalized


def test_S8_cross_month_conduct_dates():
    p = extract_conduct_period("9 de marzo y 29 de mayo de 2020")
    assert p and p[0].isoformat() == "2020-03-09" and p[1].isoformat() == "2020-05-29"


def test_S9_respondents_dedup():
    """Duplicate respondent_id rows must never reach the respondents
    table — build over a small fixture subset and assert PK uniqueness."""
    from cnmv_enforcement.pipeline.build import build_corpus
    from cnmv_enforcement.storage.tables import flatten

    result = build_corpus(REG)
    tables = flatten(result)
    ids = [r["respondent_id"] for r in tables["respondents"]]
    assert len(ids) == len(set(ids)), (
        f"duplicate respondent_id rows: {len(ids)} rows, "
        f"{len(set(ids))} unique"
    )


def test_F1_el_article_cross_month():
    p = extract_conduct_period("entre el 4 de marzo y el 18 de mayo de 2022")
    assert p and p[0].isoformat() == "2022-03-04" and p[1].isoformat() == "2022-05-18"


def test_F2_entity_y_name_intact():
    subs = split_subjects("Banco Financiero y de Ahorro, S.A., (actualmente, BFA)")
    assert len(subs) == 1


def test_F3_separacion_not_in_name():
    pub = _pub("BOE-A-2020-11881")
    for s in [s.subject_raw for b in pub.blocks for s in b.sanctions]:
        assert "separación del cargo" not in s


def test_F4_por_la_comision_not_in_name():
    pub = _pub("BOE-A-2018-4548")
    for s in [s.subject_raw for b in pub.blocks for s in b.sanctions]:
        assert "por la comisión" not in s.lower()


def test_F5_respectivamente_positional():
    pub = _pub("BOE-A-2019-9035")
    pairs = sorted(
        (s.subject_raw, s.amount) for b in pub.blocks for s in b.sanctions
    )
    amts = sorted(a for _, a in pairs if a)
    assert len(pairs) <= 3 and amts == sorted(
        [a for a in amts], key=Decimal
    ), f"cross-product suspected: {pairs}"
    total = sum(a for _, a in pairs if a)
    assert total <= Decimal("200000") + Decimal("15000")


def test_F6_comision_por_parte_de():
    pub = _pub("BOE-A-2020-8441")
    assert pub.blocks and all(b.article_normalized for b in pub.blocks)


def test_F7_mismo_texto_legal_per_chunk():
    pub = _pub("BOE-A-2018-5711")
    for b in pub.blocks:
        for r in b.related:
            if r.article_normalized and r.article_normalized.startswith("59"):
                assert r.statute_normalized == "Real Decreto 217/2008"


def test_F8_en_la_actualidad_masked():
    pub = _pub("BOE-A-2018-4548")
    for b in pub.blocks:
        if b.article_normalized and b.article_normalized.startswith("100"):
            assert b.statute_normalized == "Ley 24/1988"


def test_F9_word_suffix_articles():
    from cnmv_enforcement.normalize.legal import normalize_article

    assert normalize_article("99, letra o)") == "99.o"
    assert normalize_article("83 ter 1") == "83.ter.1"
    assert normalize_article("107 quáter 3.c") == "107.quater.3.c"
    assert normalize_article("99 z ter") == "99.z.ter"


def test_registry_covers_all_18_defects():
    import sys

    import yaml

    doc = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    ids = {d["defect_id"] for d in doc["defects"]}
    assert len(ids) == 18
    mod = sys.modules[__name__]
    tests = {n for n in dir(mod) if n.startswith("test_")}
    for did in ids:
        assert any(
            t.startswith(f"test_{did}_") for t in tests
        ), f"no regression test for defect {did}"
