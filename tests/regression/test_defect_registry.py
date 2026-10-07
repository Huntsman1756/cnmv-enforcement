"""Regression coverage for the 18 adversarial defects.

Every defect in ``data/review/defect_registry.yaml`` gets an explicit
test asserting the corrected behaviour on the cited frozen fixture —
the review ledger's machine oracle. ``REVIEW_COVERAGE`` at the bottom
produces the machine-readable coverage artifact.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from cnmv_enforcement.domain.enums import SanctionType, Severity
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
    """Duration must survive parse → assemble → Sanction row (the defect
    was loss at ASSEMBLY, not just parse)."""
    from cnmv_enforcement.parsing.assemble import assemble_case

    for boe in ("BOE-A-2023-17427", "BOE-A-2020-11881"):
        pub = _pub(boe)
        assert any(
            s.duration_raw for b in pub.blocks for s in b.sanctions
        ), f"{boe}: no duration in parse"
        from datetime import UTC, datetime

        bundle = assemble_case(
            pub,
            document_id=f"boe-xml:{boe}",
            observed_at=datetime.now(UTC),
        )
        assert any(s.duration_raw for s in bundle.sanctions), (
            f"{boe}: duration_raw dropped between parse and assembly"
        )


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
    """Positional pairing: each subject gets ITS amount — never the
    cross-product of subjects x amounts."""
    pub = _pub("BOE-A-2019-9035")
    # within ONE block a cross-product yields subject x amount pairs;
    # positional pairing yields one sanction per subject per block
    for b in pub.blocks:
        per_sub: dict[str, set] = {}
        for s in b.sanctions:
            per_sub.setdefault(s.subject_raw, set()).add(s.amount)
        for sub, amts in per_sub.items():
            assert len(amts) == 1, (
                f"block {b.ordinal}: {sub} got {amts} — cross-product"
            )
    pairs = sorted(
        (s.subject_raw, s.amount) for b in pub.blocks for s in b.sanctions
    )
    total = sum(a for _, a in pairs if a)
    assert total <= Decimal("200000") + Decimal("15000") + Decimal("50000")


def test_F6_comision_por_parte_de():
    pub = _pub("BOE-A-2020-8441")
    assert pub.blocks and all(b.article_normalized for b in pub.blocks)


def test_F7_mismo_texto_legal_per_chunk():
    """'del mismo texto legal' must resolve per chunk — assert the
    Reglamento article exists AND carries the right statute."""
    pub = _pub("BOE-A-2018-5711")
    rd = [
        r for b in pub.blocks for r in b.related
        if r.article_normalized and r.article_normalized.startswith("59")
    ]
    assert rd, "59.* related provisions not parsed (vacuous)"
    assert all(
        r.statute_normalized == "Real Decreto 217/2008" for r in rd
    ), [(r.article_normalized, r.statute_normalized) for r in rd]


def test_F8_en_la_actualidad_masked():
    """'(en la actualidad, ... RDL)' successor mention must not replace
    the typifying statute."""
    pub = _pub("BOE-A-2018-4548")
    arts = [
        b for b in pub.blocks
        if b.article_normalized and b.article_normalized.startswith("100")
    ]
    assert arts, "no 100.* articles parsed (vacuous)"
    assert all(b.statute_normalized == "Ley 24/1988" for b in arts), (
        [(b.article_normalized, b.statute_normalized) for b in arts]
    )


def test_F9_word_suffix_articles():
    from cnmv_enforcement.normalize.legal import normalize_article

    assert normalize_article("99, letra o)") == "99.o"
    assert normalize_article("83 ter 1") == "83.ter.1"
    assert normalize_article("107 quáter 3.c") == "107.quater.3.c"
    assert normalize_article("99 z ter") == "99.z.ter"
    # 'letra z) bis' — suffix after the letter group (judge round A, F-06)
    assert normalize_article("99, letra z) bis") == "99.z.bis"
    # on the real fixture that exposed it
    pub = _pub("BOE-A-2018-5711")
    assert any(
        b.article_normalized == "99.z.bis" for b in pub.blocks
    ), [b.article_normalized for b in pub.blocks]


def test_registry_covers_all_defects():
    import sys

    import yaml

    doc = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    ids = {d["defect_id"] for d in doc["defects"]}
    assert len(ids) >= 18
    mod = sys.modules[__name__]
    tests = {n for n in dir(mod) if n.startswith("test_")}
    for did in ids:
        assert any(
            t.startswith(f"test_{did}_") for t in tests
        ), f"no regression test for defect {did}"


def test_D19_written_paren_amount():
    """'seiscientos cincuenta mil (650.000) euros' → 650000."""
    pub = _pub("BOE-A-2018-3230")
    s = [s for b in pub.blocks for s in b.sanctions if "650.000" in (s.sanction_raw or "")]
    assert s and s[0].amount == Decimal("650000"), [(x.amount, x.sanction_raw) for x in s]


def test_D20_chain_head_statute():
    """Typified article inherits the chain's first statute — 'art. 99.i,
    en relación con el art. 83 ter 1., de la Ley 24/1988' → Ley 24/1988."""
    pub = _pub("BOE-A-2018-9009")
    b = [b for b in pub.blocks if b.article_normalized == "99.i"]
    assert b and b[0].statute_normalized == "Ley 24/1988", (
        [(x.article_normalized, x.statute_normalized) for x in pub.blocks]
    )


def test_D21_y_su_role_split():
    """'X y su consejero delegado, don Y' — the fused entity+role chunk
    must split into entity and role'd person (judge round 2, N1)."""
    subs = split_subjects(
        "Universal UP2ME, S.L. y su consejero delegado, "
        "don Jordi Busoms Julia"
    )
    assert len(subs) == 2
    assert any("don Jordi Busoms" in s for s in subs)
    assert any("Universal UP2ME" in s for s in subs)


def test_D22_related_dot_letter():
    """'81.2. a)' / '227.1. b)' — space-dot letters in related refs must
    not be dropped (judge round 2, N3)."""
    pub = _pub("BOE-A-2018-14109")
    arts = {r.article_normalized for b in pub.blocks for r in b.related}
    assert {"81.2.a", "81.2.b", "227.1.a", "227.1.b"} <= arts, arts


# ── H1 cohort: 2015–2017 historical grammar ──────────────────────────


def _h1_pub(boe_id):
    p = Path(f"data/corpus_h1_dev/{boe_id}.xml")
    if not p.exists():
        pytest.skip("h1 dev corpus absent")
    return parse_publication_xml(p.read_bytes())


def test_D23_por_comision_sin_la():
    """'por comisión de' (no 'la') must produce the third block of
    BOE-A-2022-10033 — the verified corpus silently dropped it."""
    pub = _pub("BOE-A-2022-10033")
    assert len(pub.blocks) == 3
    b3 = pub.blocks[2]
    assert b3.severity == Severity.SERIOUS
    assert b3.article_normalized == "295.5"
    assert any(
        "Arturo Sotillo" in l.subject_raw for l in b3.sanctions
    )


def test_D24_impose_inline_sucesor():
    pub = _h1_pub("BOE-A-2015-3810")
    assert len(pub.blocks) == 2
    assert pub.blocks[0].declared
    succ = pub.blocks[1]
    assert succ.declared_for is pub.blocks[0]
    assert succ.sanctions[0].amount == 80000


def test_D25_sucesor_colon_list():
    """'…como sucesor en la responsabilidad declarada de:' + bare
    'X, una multa…' lines — each predecessor's fine binds its declared
    block."""
    pub = _h1_pub("BOE-A-2015-9188")
    amts = {
        l.declared_subject: l.amount
        for b in pub.blocks
        for l in b.sanctions
        if l.declared_subject
    }
    assert amts.get("Bancaja") == 1000000
    assert amts.get("Caja Madrid") == 1000000
    assert amts.get("Caixa Laietana") == 100000


def test_D26_dash_amount_sucesor():
    pub = _h1_pub("BOE-A-2016-1297")
    pairs = {
        l.declared_subject: l.amount
        for b in pub.blocks
        for l in b.sanctions
        if l.declared_subject
    }
    assert pairs == {
        "Caja España": 250000,
        "Caja Duero": 100000,
        "CEISS": 750000,
    }


def test_D27_declarar_que_ha_incurrido():
    pub = _h1_pub("BOE-A-2015-4880")
    decl = [b for b in pub.blocks if b.declared]
    assert decl, "no Declarar-que block"
    # the successor sanction on Santander links the Banif declaration
    succ = [
        b
        for b in pub.blocks
        if b.declared_for or any(l.declared_subject for l in b.sanctions)
    ]
    assert succ and any(
        l.amount == 50000 for b in succ for l in b.sanctions
    )


def test_D28_por_comision_quoted():
    pub = _h1_pub("BOE-A-2017-15708")
    assert len(pub.blocks) == 1
    b = pub.blocks[0]
    assert b.severity == Severity.VERY_SERIOUS
    assert b.sanctions[0].amount == 500000
    assert "Renta 4 Banco" in b.sanctions[0].subject_raw


def test_D29_lettered_conduct_items():
    pub = _h1_pub("BOE-A-2015-4242")
    assert not pub.parse_issues, pub.parse_issues
    # lettered items merged into conduct windows
    b = pub.blocks[0]
    assert b.conduct_start is not None


def test_D30_dashed_conduct_items():
    pub = _h1_pub("BOE-A-2015-9187")
    assert not pub.parse_issues, pub.parse_issues


def test_D31_resolution_listed_a_subject():
    """'A X, por la comisión…' items under 'N. Resolución… acordó
    imponer las siguientes sanciones:' — no Imponer header."""
    p = Path("data/corpus_h1_dev/BOE-A-2015-12924.xml")
    src = p if p.exists() else Path("data/corpus_h1_holdout/BOE-A-2015-12924.xml")
    if not src.exists():
        pytest.skip("h1 corpus absent")
    pub = parse_publication_xml(src.read_bytes())
    assert len(pub.blocks) == 5
    amts = sorted(l.amount for b in pub.blocks for l in b.sanctions)
    assert amts == [20000, 75000, 150000, 150000, 300000]


def test_D32_sanction_kind_wrappers():
    """'sanción, a cada uno de ellos, de multa' and 'sanción
    consistente en multa' → MONETARY_FINE, never UNKNOWN."""
    from cnmv_enforcement.domain.enums import SanctionType

    for bid, expect in (
        ("BOE-A-2015-3206", 100000),
        ("BOE-A-2015-3207", 500000),
    ):
        pub = _h1_pub(bid)
        for b in pub.blocks:
            for l in b.sanctions:
                assert l.sanction_type == SanctionType.MONETARY_FINE
        assert any(l.amount == expect for b in pub.blocks for l in b.sanctions)


# ── H2 cohort: 2010–2014 historical grammar ──────────────────────────


def _h2_pub(boe_id):
    for base in (
        "data/corpus_h2_dev",
        "data/corpus_h2_holdout",
        "data/corpus_h1_dev",
        "data/corpus_h1_holdout",
    ):
        p = Path(f"{base}/{boe_id}.xml")
        if p.exists():
            return parse_publication_xml(p.read_bytes())
    pytest.skip("corpus absent")


def test_D33_curly_quote_wrappers():
    """'‘‘…’' and '«…»' quoted entity names parse atomically."""
    pub = _h2_pub("BOE-A-2010-466")
    assert len(pub.blocks) == 1
    subj = pub.blocks[0].sanctions[0].subject_raw
    assert "Banesto Bolsa" in subj and "’’" not in subj


def test_D33b_guillemet_atomic_entity():
    """'Construcciones y Auxiliar de Ferrocarriles, S.A.' — the ' y '
    and ',' inside «…» must not split the entity."""
    pub = _h2_pub("BOE-A-2016-9688")
    subs = [l.subject_raw for b in pub.blocks for l in b.sanctions]
    assert any("Ferrocarriles, S.A." in s for s in subs)
    assert not any(s == "Auxiliar de Ferrocarriles" for s in subs)


def test_D34_numbered_operative_items():
    pub = _h2_pub("BOE-A-2011-11421")
    assert len(pub.blocks) >= 3
    assert any(
        "Guinovart" in l.subject_raw
        for b in pub.blocks for l in b.sanctions
    )


def test_D35_sanction_before_comision():
    pub = _h2_pub("BOE-A-2010-7244")
    assert len(pub.blocks) == 1
    s = pub.blocks[0].sanctions[0]
    assert s.amount == 150000
    assert "Enrique Bañuelos" in s.subject_raw
    assert "multa" not in s.subject_raw


def test_D36_organ_members_enumeration():
    """'los miembros del Consejo…: don A, don B…' — every member is a
    subject; the role header never becomes a respondent."""
    pub = _h2_pub("BOE-A-2015-3206")
    subs = [l.subject_raw for b in pub.blocks for l in b.sanctions]
    assert len(subs) >= 5  # Codere + 4 members incl. first
    assert any("Vela Sastre" in s for s in subs)  # first member kept
    pub2 = _h2_pub("BOE-A-2016-9688")
    subs2 = [l.subject_raw for b in pub2.blocks for l in b.sanctions]
    assert any("Legarda" in s for s in subs2)


def test_D37_letra_articulo_reversal():
    pub = _h2_pub("BOE-A-2012-10687")
    assert all(b.article_normalized for b in pub.blocks)
    assert any(b.article_normalized == "99.o" for b in pub.blocks)
    assert all(b.statute_normalized == "Ley 24/1988" for b in pub.blocks)


def test_D38_colon_header_no_phantom():
    pub = _h2_pub("BOE-A-2013-13220")
    assert all(b.severity != Severity.UNKNOWN for b in pub.blocks)
    pub2 = _h2_pub("BOE-A-2013-13221")
    assert all(
        l.sanction_type == SanctionType.MONETARY_FINE or l.amount is None
        for b in pub2.blocks for l in b.sanctions
    )


def test_D39_por_importe_colon_header():
    pub = _h2_pub("BOE-A-2012-9548")
    sancs = [l for b in pub.blocks for l in b.sanctions]
    assert all(l.amount is not None for l in sancs)
    assert {l.amount for l in sancs} == {75000, 19000, 2000, 4000}


def test_D40_succ_scope_per_item_binding():
    """'Declarar…por:' + numbered succ items — each 'La Comisión…'
    block binds ITS declared infringement, not the last one."""
    pub = _h1_pub("BOE-A-2015-4242")
    b5 = next(b for b in pub.blocks if b.ordinal == 5)
    b6 = next(b for b in pub.blocks if b.ordinal == 6)
    assert b5.declared_for is pub.blocks[0]
    assert b6.declared_for is pub.blocks[1]
    assert [l.amount for l in b5.sanctions] == [Decimal("1000000")]
    assert [l.amount for l in b6.sanctions] == [Decimal("800000")]
    assert not pub.parse_issues


def test_D41_compound_surname_y():
    """'don Jaime Botín-Sanz de Sautuola y García de los Ríos' — ONE
    person; the 'y' inside the surname must never split."""
    pub = _h2_pub("BOE-A-2014-1732")
    subs = [l.subject_raw for b in pub.blocks for l in b.sanctions]
    assert any("García de los Ríos" in s for s in subs)
    assert not any(s.strip() == "García de los Ríos" for s in subs)


def test_D42_de_su_consejo_and_al_miembro():
    pub = _h2_pub("BOE-A-2010-7246")
    subs = [l.subject_raw for b in pub.blocks for l in b.sanctions]
    assert not any(
        s.strip().lower().startswith("los miembros") and "don" not in s
        for s in subs
    )
    pub2 = _h2_pub("BOE-A-2014-3117")
    assert all(
        l.subject_raw.strip() for b in pub2.blocks for l in b.sanctions
    )
    assert any(
        "Salama Millet" in l.subject_raw
        for b in pub2.blocks for l in b.sanctions
    )


def test_D43_las_sanciones_compound():
    """'las sanciones de amonestación pública … y de multa por importe
    de N' — two sanctions: PUBLIC_REPRIMAND + MONETARY_FINE."""
    from pathlib import Path
    from cnmv_enforcement.parsing.boe_publication import (
        parse_publication_xml,
    )
    p = Path("data/corpus_h3_sample/BOE-A-2004-10461.xml")
    if not p.exists():
        pytest.skip("h3 sample absent")
    pub = parse_publication_xml(p.read_bytes())
    kinds = {
        l.sanction_type for b in pub.blocks for l in b.sanctions
    }
    assert SanctionType.PUBLIC_REPRIMAND in kinds
    assert SanctionType.MONETARY_FINE in kinds
    assert sum(
        l.amount for b in pub.blocks for l in b.sanctions
        if l.amount
    ) == Decimal("250000")
