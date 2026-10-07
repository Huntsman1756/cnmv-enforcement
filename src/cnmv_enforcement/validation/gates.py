"""Release gates — the dataset must pass ALL of these to ship.

Each gate returns (ok, detail). A gate failure is a release blocker, not
a warning: the ledger must never silently degrade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
        "; ".join(i["boe_id"] for i in failed[:10]),
    )
    zero_block = [
        p.boe_id for p in result.publications if not p.blocks
    ]
    gate(
        "every publication yields >=1 infringement block",
        not zero_block,
        ", ".join(zero_block[:10]),
    )
    zero_sanc = [
        p.boe_id
        for p in result.publications
        if not any(b.sanctions for b in p.blocks)
    ]
    gate(
        "every publication yields >=1 sanction",
        not zero_sanc,
        ", ".join(zero_sanc[:10]),
    )

    # -- field completeness ------------------------------------------------
    missing_sev = [
        f"{b.case_id}/i{i.ordinal}"
        for b in result.bundles
        for i in b.infringements
        if i.severity == Severity.UNKNOWN
    ]
    gate("every infringement has severity", not missing_sev, ", ".join(missing_sev[:10]))
    missing_art = [
        f"{b.case_id}/i{i.ordinal}"
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
        f"{b.case_id}/i{i.ordinal}"
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
    dupes = [
        s.sanction_id
        for b in result.bundles
        for s in b.sanctions
        if (s.sanction_id in seen or seen.add(s.sanction_id))
    ]
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

    return report.to_dict()
