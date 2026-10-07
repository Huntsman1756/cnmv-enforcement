"""Release gates — the dataset must pass ALL of these to ship.

Each gate returns (ok, detail). A gate failure is a release blocker, not
a warning: the ledger must never silently degrade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from cnmv_enforcement.domain.enums import SanctionType, Severity
from cnmv_enforcement.parsing.boe_publication import parse_publication_xml
from cnmv_enforcement.pipeline.build import build_corpus


@dataclass
class GateResult:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class GateReport:
    gates: list[GateResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(g.ok for g in self.gates)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "gates": [
                {"name": g.name, "ok": g.ok, "detail": g.detail}
                for g in self.gates
            ],
        }


def _gate(name: str):
    def deco(fn):
        fn.gate_name = name
        return fn

    return deco


def run_gates(corpus_dir: Path, extra_dirs: list[Path] | None = None) -> dict:
    """Build the corpus and check every release invariant.

    ``extra_dirs``: additional corpus dirs (e.g. historical backfill) —
    gates must cover every corpus that feeds the dataset, not just the
    register snapshot.
    """
    dirs = [corpus_dir, *(extra_dirs or [])]
    result = build_corpus(dirs)
    report = GateReport()

    def gate(name: str, ok: bool, detail: str = "") -> None:
        report.gates.append(GateResult(name, ok, detail))

    # -- parsing integrity ------------------------------------------------
    failed = [i for i in result.issues if i["kind"] == "PARSE_FAILED"]
    gate(
        "all documents parsed",
        not failed,
        "; ".join(i["boe_id"] or "?" for i in failed[:10]),
    )
    sanction_pubs = [
        p for p in result.publications
        if p.document_kind == "SANCTION_PUBLICATION"
    ]
    zero_block = [p.boe_id for p in sanction_pubs if not p.blocks]
    gate(
        "every publication yields >=1 infringement block",
        not zero_block,
        ", ".join(b or "?" for b in zero_block[:10]),
    )
    zero_sanc = [
        p.boe_id
        for p in sanction_pubs
        if not any(b.sanctions for b in p.blocks)
    ]
    gate(
        "every publication yields >=1 sanction",
        not zero_sanc,
        ", ".join(b or "?" for b in zero_sanc[:10]),
    )

    # -- field completeness ------------------------------------------------
    missing_sev = [
        f"{b.case.case_id}/i{i.ordinal}"
        for b in result.bundles
        for i in b.infringements
        if i.severity == Severity.UNKNOWN
    ]
    gate("every infringement has severity", not missing_sev, ", ".join(missing_sev[:10]))
    missing_art = [
        f"{b.case.case_id}/i{i.ordinal}"
        for b in result.bundles
        for i in b.infringements
        if not i.article_normalized
    ]
    gate(
        "every infringement has a normalized article",
        not missing_art,
        str(missing_art[:10]),
    )
    missing_stat = [
        f"{b.case.case_id}/i{i.ordinal}"
        for b in result.bundles
        for i in b.infringements
        if not i.statute_normalized
    ]
    gate(
        "every infringement has a normalized statute",
        not missing_stat,
        str(missing_stat[:10]),
    )
    subjectless = [
        s.sanction_id
        for b in result.bundles
        for s in b.sanctions
        if not s.respondent_id
    ]
    gate("every sanction has a respondent", not subjectless, ", ".join(subjectless[:10]))
    fine_no_amount = [
        s.sanction_id
        for b in result.bundles
        for s in b.sanctions
        if s.sanction_type == SanctionType.MONETARY_FINE and s.amount is None
    ]
    gate(
        "every monetary fine has an amount",
        not fine_no_amount,
        str(fine_no_amount[:10]),
    )
    non_monetary_amount = [
        s.sanction_id
        for b in result.bundles
        for s in b.sanctions
        if s.sanction_type not in (SanctionType.MONETARY_FINE, SanctionType.DISGORGEMENT)
        and s.amount is not None
    ]
    gate(
        "non-monetary sanctions carry no amount",
        not non_monetary_amount,
        str(non_monetary_amount[:10]),
    )

    # -- referential integrity ----------------------------------------------
    for bundle in result.bundles:
        iids = {i.infringement_id for i in bundle.infringements}
        rids = {r.respondent_id for r in bundle.respondents}
        bad = [
            s.sanction_id
            for s in bundle.sanctions
            if (s.infringement_id and s.infringement_id not in iids)
            or s.respondent_id not in rids
        ]
        if bad:
            gate(
                f"referential integrity {bundle.case.case_id}",
                False,
                str(bad[:5]),
            )
            break
    else:
        gate("referential integrity (all cases)", True)

    # -- uniqueness ----------------------------------------------------------
    seen: set = set()
    dupes: list = []
    for b in result.bundles:
        for s in b.sanctions:
            if s.sanction_id in seen:
                dupes.append(s.sanction_id)
            seen.add(s.sanction_id)
    gate("sanction ids unique", not dupes, ", ".join(dupes[:10]))

    # -- evidence ------------------------------------------------------------
    unevidenced = [
        s.sanction_id
        for b in result.bundles
        for s in b.sanctions
        if not any(
            e.entity_id == s.sanction_id and e.fact_type == "sanction"
            for e in b.evidence
        )
    ]
    gate("every sanction has evidence", not unevidenced, ", ".join(unevidenced[:10]))

    # -- temporality ----------------------------------------------------------
    bad_temporal = [
        b.case.case_id
        for b in result.bundles
        if b.case.sanctioning_resolution_date
        and b.case.boe_publication_date
        and b.case.sanctioning_resolution_date > b.case.boe_publication_date
    ]
    gate(
        "sanctioning resolution precedes BOE publication",
        not bad_temporal,
        str(bad_temporal[:10]),
    )
    bad_conduct = [
        b.case.case_id
        for b in result.bundles
        for i in b.infringements
        if i.conduct_end_date
        and b.case.boe_publication_date
        and i.conduct_end_date > b.case.boe_publication_date
    ]
    gate(
        "conduct predates publication",
        not bad_conduct,
        str(bad_conduct[:10]),
    )

    # ── v0.5 gates ─────────────────────────────────────────────────────
    # G16 REVIEW_REGRESSION_COVERAGE — 18 defects / 18 covered

    import yaml

    reg = Path("data/review/defect_registry.yaml")
    if reg.exists():
        doc = yaml.safe_load(reg.read_text(encoding="utf-8"))
        defect_ids = {d["defect_id"] for d in doc["defects"]}
        test_names = set()
        tdir = Path("tests/regression")
        for f in tdir.glob("test_*.py"):
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.startswith("def test_"):
                    test_names.add(
                        line.split("(")[0].replace("def ", "")
                    )
        uncovered = [
            d for d in defect_ids
            if not any(n.startswith(f"test_{d}_") for n in test_names)
        ]
        # ledger must only contain registry-consistent (defect, doc) pairs
        from cnmv_enforcement.review.ledger import load_ledger

        lpath = Path("data/review/review_ledger.jsonl")
        valid = {
            (d["defect_id"], f)
            for d in doc["defects"]
            for f in d["fixtures"]
        }
        orphans = [
            r.review_id
            for r in load_ledger(lpath)
            if r.subject_type == "defect"
            and (r.subject_id, r.document_id) not in valid
        ]
        gate(
            f"G16 review regression coverage "
            f"({len(defect_ids)-len(uncovered)}/{len(defect_ids)})",
            not uncovered and not orphans,
            ",".join(uncovered)
            + (f" | {len(orphans)} ledger orphans" if orphans else ""),
        )
    else:
        gate("G16 review regression coverage", False, "registry missing")

    # G17 REVIEW_STALENESS — independent oracle: compute the expected
    # stale-set WITHOUT apply_staleness, then verify the ledger's
    # output matches it (a regression inside apply_staleness fails here)
    from cnmv_enforcement.review.ledger import load_ledger
    from cnmv_enforcement.review.model import (
        REVIEW_COMPAT_VERSION,
        ReviewStatus,
        apply_staleness,
    )

    lpath = Path("data/review/review_ledger.jsonl")
    if lpath.exists():
        raw_sha = {
            p.boe_id: p.raw_sha256 or ""
            for p in result.publications
            if p.boe_id
        }
        raw_items = load_ledger(lpath)
        expected_stale = {
            r.review_id
            for r in raw_items
            if (
                r.review_compat_version != REVIEW_COMPAT_VERSION
                or r.raw_sha256 != raw_sha.get(r.document_id, "")
            )
        }
        out = {r.review_id: r.status for r in apply_staleness(
            raw_items, REVIEW_COMPAT_VERSION, raw_sha
        )}
        wrong = [
            rid
            for rid in expected_stale
            if out.get(rid) != ReviewStatus.STALE
        ] + [
            rid
            for rid, st in out.items()
            if rid not in expected_stale and st == ReviewStatus.STALE
        ]
        gate(
            "G17 review staleness",
            not wrong,
            f"{len(wrong)} reviews in wrong staleness state",
        )
    else:
        gate("G17 review staleness", True, "no ledger yet")

    # G18 EVIDENCE_REFERENTIAL_INTEGRITY
    doc_ids = {
        f"boe-xml:{p.boe_id}" for p in result.publications if p.boe_id
    }
    broken = [
        e.entity_id
        for b in result.bundles
        for e in b.evidence
        if e.document_id.startswith("boe-xml:")
        and e.document_id not in doc_ids
    ]
    gate(
        "G18 evidence referential integrity",
        not broken,
        f"{len(broken)} broken refs",
    )

    # G19 EVIDENCE_BINDING_HONESTY — recompute proof_level on the domain
    # objects with the same function flatten() uses (proof_level is a
    # projection, never read from the table)
    from cnmv_enforcement.evidence.verify import verify_binding

    meta = {p.boe_id: p for p in result.publications}
    dishonest = []
    for b in result.bundles:
        pub = meta.get(b.case.canonical_boe_id or "")
        for e in b.evidence:
            if (
                verify_binding(e, pub) == "VALUE_BINDING_PROVEN"
                and (not e.locator or not e.artifact_sha256)
            ):
                dishonest.append(e.entity_id)
    gate(
        "G19 evidence binding honesty",
        not dishonest,
        f"{len(dishonest)} VB_PROVEN without locator/sha",
    )

    # G20 COVERAGE_NEGATIVE_CLAIMS — recompute appeal status from the
    # pdf-status manifest with the same helper flatten() uses; every
    # NOT_OBSERVED must come from a retrieval-verified entry
    import json

    pstatus_path = Path("data/runtime/cnmv_pdf_status.json")
    pstatus = (
        json.loads(pstatus_path.read_text(encoding="utf-8"))
        if pstatus_path.exists()
        else {}
    )
    from cnmv_enforcement.storage.tables import _pdf_basis_id

    basis = _pdf_basis_id(pstatus) if pstatus else None
    # independent recompute — do NOT reuse _appeal_status (a bug inside
    # it must trip this gate): a strong negative requires an entry with
    # retrieval=OK AND zero appeal note-kinds AND a basis id
    appeal_kinds = {
        "JUDICIAL_APPEAL_OBSERVED",
        "JUDGMENT_OBSERVED",
        "RENUNCIATION_TO_APPEAL",
    }
    negatives = []
    for b in result.bundles:
        obs = pstatus.get(b.case.canonical_boe_id or "") or {}
        kinds = {n.get("kind") for n in obs.get("notes", [])}
        if not obs or obs.get("retrieval") != "OK":
            expected = "INCONCLUSIVE"
        elif kinds & appeal_kinds:
            expected = "OBSERVED"
        else:
            expected = "NEGATIVE"
        if expected == "NEGATIVE":
            negatives.append((b.case.case_id, bool(obs), bool(basis)))
    gate(
        "G20 coverage negative claims",
        all(ok and basis for _, ok, basis in negatives),
        f"{len(negatives)} negatives, "
        f"{sum(1 for _, ok, bas in negatives if not (ok and bas))} "
        "without verified coverage",
    )

    # G21 AS_KNOWN_AT_NO_FUTURE_LEAKAGE — no observation timestamp may
    # postdate the build itself (evidence or PDF-derived events dated
    # into the future would be invisible to every AS_KNOWN_AT query);
    # end-to-end leakage is covered by tests/test_known_at*.py

    built = result.built_at.replace(tzinfo=None)
    future = [
        e.entity_id
        for b in result.bundles
        for e in b.evidence
        if e.observed_at
        and (e.observed_at.replace(tzinfo=None) - built).total_seconds()
        > 3600
    ]
    future_events = [
        ev.event_id
        for b in result.bundles
        for ev in b.events
        if ev.observed_at
        and (ev.observed_at.replace(tzinfo=None) - built).total_seconds()
        > 3600
    ]
    gate(
        "G21 known_at no future leakage",
        not future and not future_events,
        f"{len(future)} evidence + {len(future_events)} events "
        ">1h after the build instant",
    )

    # G22 REPRODUCIBLE_DATASET — golden fixture integrity
    sums = Path("tests/fixtures/corpus/SHA256SUMS")
    import hashlib

    if sums.exists():
        manifest = {}
        for line in sums.read_text(encoding="utf-8").splitlines():
            h, n = line.split(None, 1)
            manifest[n.lstrip("*")] = h
        mism = []
        for name, h in manifest.items():
            p = Path("tests/fixtures/corpus") / name
            if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != h:
                mism.append(name)
        gate("G22 reproducible dataset", not mism, ",".join(mism[:5]))
    else:
        gate("G22 reproducible dataset", False, "SHA256SUMS missing")

    # ── v0.6 historical gates ──────────────────────────────────────────
    # G23 HISTORICAL_ENUMERATION_REPRODUCIBLE — every non-fixture corpus
    # doc present in the dataset must trace to an enumerated manifest
    # entry; the manifests themselves are frozen JSONL.
    # committed frozen manifests are authoritative; data/runtime is
    # a working fallback for in-progress enumerations
    manifests = sorted(
        Path("coverage/history").glob("boe_history*.jsonl")
    ) or sorted(Path("data/runtime").glob("boe_history*.jsonl"))
    has_historical = any(
        p.corpus != "register_snapshot" for p in result.publications
    )
    if not manifests:
        gate(
            "G23 historical enumeration reproducible",
            not has_historical,
            "historical corpus present but no enumeration manifest",
        )
    else:
        enum_ids = set()
        for mp in manifests:
            for ln in mp.read_text(encoding="utf-8").splitlines():
                for it in json.loads(ln).get("items", []):
                    enum_ids.add(it["boe_id"])
        # publications not in the register corpus must be manifest-backed
        missing = [
            p.boe_id
            for p in result.publications
            if p.corpus != "register_snapshot" and p.boe_id not in enum_ids
        ]
        gate(
            "G23 historical enumeration reproducible",
            not missing,
            f"{len(missing)} historical docs absent from manifests: "
            f"{missing[:4]}",
        )

    # G24 HISTORICAL_DOCUMENT_RECONCILIATION — the documents↔cases
    # count must reconcile exactly per corpus (no unexplained deltas)
    from collections import Counter

    per_corpus: dict[str, Counter] = {}
    for p in result.publications:
        c = per_corpus.setdefault(p.corpus, Counter())
        c["documents"] += 1
        c[p.document_kind] += 1
    case_by_corpus: Counter = Counter(
        next(
            (p.corpus for p in result.publications
             if p.boe_id == b.case.canonical_boe_id),
            "?",
        )
        for b in result.bundles
    )
    unreconciled = [
        corpus
        for corpus, counts in per_corpus.items()
        if counts["documents"] - case_by_corpus.get(corpus, 0)
        != counts.get("SUBSEQUENT_EVENT", 0) + counts.get("OTHER", 0)
    ]
    gate(
        "G24 historical document reconciliation",
        not unreconciled,
        f"{unreconciled} corpora have unexplained doc/case deltas",
    )

    # G25 HISTORICAL_HOLDOUT — the frozen holdout corpus must parse
    # cleanly (dev-set fixes may not have degraded it)
    holdout_dir = Path("data/corpus_h1_holdout")
    if holdout_dir.exists() and any(holdout_dir.glob("BOE-A-*.xml")):
        hold_fails = []
        for xf in sorted(holdout_dir.glob("BOE-A-*.xml")):
            try:
                hp = parse_publication_xml(xf.read_bytes())
            except Exception as exc:  # noqa: BLE001 — a crash IS a fail
                hold_fails.append(f"{xf.stem}: crash {exc}")
                continue
            if not hp.blocks or not any(b.sanctions for b in hp.blocks):
                hold_fails.append(f"{xf.stem}: no sanctions")
        gate(
            "G25 historical holdout",
            not hold_fails,
            f"{len(hold_fails)} holdout docs failed: "
            f"{hold_fails[:3]}",
        )

    # G26 HISTORICAL_MONEY_EXACTNESS — every monetary fine in the
    # non-register corpus carries a Decimal amount (never None/float)
    bad_money = [
        f"{b.case.case_id}/{s.ordinal}"
        for p in result.publications
        if p.corpus != "register_snapshot"
        for b in result.bundles
        if p.boe_id == b.case.canonical_boe_id
        for s in b.sanctions
        if s.sanction_type.name == "MONETARY_FINE" and s.amount is None
    ]
    gate(
        "G26 historical money exactness",
        not bad_money,
        f"{len(bad_money)} fines w/o amount: {bad_money[:4]}",
    )

    # G27 HISTORICAL_CASE_LINK_HONESTY — no sanction may land on an
    # empty respondent (successor/dative parsing must always resolve to
    # a concrete subject — the N-finding "empty-subject phantom
    # respondent" becomes a hard failure here)
    empty_subj = [
        f"{b.case.case_id}/{s.ordinal}"
        for b in result.bundles
        for s in b.sanctions
        if not s.respondent_id or s.respondent_id.strip() == ""
    ]
    gate(
        "G27 historical case-link honesty",
        not empty_subj,
        f"{len(empty_subj)} sanctions with empty respondent",
    )

    # G28 HISTORICAL_COVERAGE_CLAIMS — coverage.json must declare the
    # historical slice explicitly (no silent exhaustivity)
    import json as _json

    cov = Path("data/exports")
    covs = sorted(cov.glob("*/coverage.json"))
    if covs:
        cdoc = _json.loads(covs[-1].read_text(encoding="utf-8"))
        hist_cov = cdoc.get("historical_backfill", {})
        note = str(hist_cov.get("note", ""))
        gate(
            "G28 historical coverage claims",
            "NOT exhaustive" in note or "not exhaustive" in note.lower(),
            "coverage.json must declare the historical slice as "
            "non-exhaustive",
        )

    # G29 HISTORICAL_EVIDENCE_INTEGRITY — every evidence row in the
    # historical cohort binds to an artifact sha (no unbound evidence)
    unbound = [
        f"{e.entity_id}/{e.field_name}"
        for b in result.bundles
        for e in b.evidence
        if not e.artifact_sha256
    ]
    gate(
        "G29 historical evidence integrity",
        not unbound,
        f"{len(unbound)} evidence rows without artifact sha",
    )

    # G30 SUMARIO_SHAPE_COVERAGE — a pre-2005 sumario (departamento→
    # item, no epigrafe) must never enumerate to zero: the frozen
    # fixtures prove both shapes parse. This is the regression gate
    # for the silent-zero-items coverage bug found in H3.
    fixture_dir = Path("tests/fixtures/sumario")
    shape_failures: list[str] = []
    for fixture, day in (("20000301.json", "2000-03-01"),
                         ("20050103.json", "2005-01-03")):
        f = fixture_dir / fixture
        if not f.exists():
            shape_failures.append(f"missing fixture {fixture}")
            continue
        from datetime import date as _date

        from cnmv_enforcement.sources.boe.sumario import parse_sumario

        y, m, d = day.split("-")
        s = parse_sumario(f.read_bytes(), _date(int(y), int(m), int(d)))
        if not s.items:
            shape_failures.append(f"{fixture}: parsed 0 items")
    gate(
        "G30 sumario shape coverage",
        not shape_failures,
        "; ".join(shape_failures) if shape_failures else "both shapes yield items",
    )

    return report.to_dict()
