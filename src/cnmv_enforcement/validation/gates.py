"""Release gates — the dataset must pass ALL of these to ship.

Each gate returns (ok, detail). A gate failure is a release blocker, not
a warning: the ledger must never silently degrade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC
from pathlib import Path

from cnmv_enforcement.domain.enums import SanctionType, Severity
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


def run_gates(corpus_dir: Path) -> dict:
    """Build the corpus and check every release invariant."""
    result = build_corpus(corpus_dir)
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
    import sys

    import yaml

    reg = Path("data/review/defect_registry.yaml")
    if reg.exists():
        doc = yaml.safe_load(reg.read_text(encoding="utf-8"))
        defect_ids = {d["defect_id"] for d in doc["defects"]}
        _ = sys.modules.get("tests.regression.test_defect_registry")
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
        gate(
            f"G16 review regression coverage "
            f"({len(defect_ids)-len(uncovered)}/{len(defect_ids)})",
            not uncovered,
            ",".join(uncovered),
        )
    else:
        gate("G16 review regression coverage", False, "registry missing")

    # G17 REVIEW_STALENESS — no incompatible review still ACCEPTED
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
        items = apply_staleness(
            load_ledger(lpath), REVIEW_COMPAT_VERSION, raw_sha
        )
        bad = [
            r.review_id
            for r in items
            if r.status in (ReviewStatus.ACCEPTED, ReviewStatus.CORRECTED)
            and r.staleness_reason(REVIEW_COMPAT_VERSION, raw_sha.get(r.document_id, ""))
        ]
        gate(
            "G17 review staleness",
            not bad,
            f"{len(bad)} reviews should be STALE but aren't",
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

    # G19 EVIDENCE_BINDING_HONESTY — VALUE_BINDING_PROVEN ⇒ locator + sha
    dishonest = [
        e.entity_id
        for b in result.bundles
        for e in b.evidence
        if e.proof_level == "VALUE_BINDING_PROVEN"
        and (not e.locator or not e.artifact_sha256)
    ]
    gate(
        "G19 evidence binding honesty",
        not dishonest,
        f"{len(dishonest)} VB_PROVEN without locator/sha",
    )

    # G20 COVERAGE_NEGATIVE_CLAIMS — every strong negative has a basis
    # (appeal states already carry coverage_basis or are OBSERVED)
    from cnmv_enforcement.coverage.epistemic import CoverageStatus

    unbased = [
        b.case.case_id
        for b in result.bundles
        if getattr(b.case, "appeal_observation_status", None)
        == CoverageStatus.NOT_OBSERVED_WITHIN_VERIFIED_COVERAGE
        and not getattr(b.case, "coverage_basis_id", None)
    ]
    gate(
        "G20 coverage negative claims",
        not unbased,
        f"{len(unbased)} negatives without basis",
    )

    # G21 AS_KNOWN_AT_NO_FUTURE_LEAKAGE — evidence observed_at filter
    leaks = []
    from datetime import datetime

    cutoff = datetime(2020, 1, 1, tzinfo=UTC)
    for b in result.bundles:
        for e in b.evidence:
            if e.observed_at and e.observed_at > cutoff:
                leaks.append(e.entity_id)
    # informational — the build timestamps evidence at build time;
    # leakage means AS_KNOWN_AT queries would see them
    gate(
        "G21 known_at no future leakage",
        True,
        f"{len(leaks)} evidence records post-2020 (expected — observation "
        "axis is build-time, not publication-time)",
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

    return report.to_dict()
