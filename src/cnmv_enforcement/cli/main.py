"""cnmv-enforcement CLI.

Commands follow the pipeline: probe -> enumerate -> fetch -> parse ->
build -> validate -> coverage. Query commands (case / respondent /
article / law / stats) read the built dataset.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import typer

from cnmv_enforcement.config import (
    BOE_XML_URL,
    data_root,
    exports_root,
    runtime_root,
)

app = typer.Typer(
    name="cnmv-enforcement",
    help=(
        "Evidence-backed historical ledger of publicly observable CNMV "
        "enforcement. Register absence does not imply no sanction."
    ),
    no_args_is_help=True,
)


def _corpus() -> Path:
    return data_root() / "corpus"


# ---------------------------------------------------------------- sources
@app.command()
def probe() -> None:
    """Probe live source structure (register pages, BOE API reach)."""
    from cnmv_enforcement.sources.cnmv.register import (
        collect_register,
    )
    from cnmv_enforcement.sources.http import HttpClient

    client = HttpClient()
    snap = collect_register(client)
    first = snap.rows[0]
    dates = [r.register_entry_date for r in snap.rows if r.register_entry_date]
    typer.echo(
        json.dumps(
            {
                "declared_pages": snap.declared_pages,
                "rows": len(snap.rows),
                "first_row": {
                    "title": first.title[:120],
                    "register_entry_date": str(first.register_entry_date),
                },
                "date_range": [str(min(dates)), str(max(dates))],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command()
def enumerate(out: Path | None = None) -> None:
    """Resolve every register row to its BOE-A id (no download)."""
    import re
    from collections import defaultdict

    from cnmv_enforcement.sources.boe.resolve import resolve_row
    from cnmv_enforcement.sources.boe.sumario import fetch_sumario
    from cnmv_enforcement.sources.cnmv.register import collect_register
    from cnmv_enforcement.sources.http import HttpClient

    client = HttpClient()
    snap = collect_register(client)
    day_cache: dict = defaultdict(list)
    results = []
    for row in snap.rows:
        m = re.search(r"\(BOE de (\d+ de \w+ de \d{4})\)", row.title)
        if not m:
            results.append({"row": row.title, "boe_id": None, "method": "NO_DATE"})
            continue
        from cnmv_enforcement.parsing.dates import parse_long_es

        day = parse_long_es(m.group(1))
        if day is None:
            continue
        if day not in day_cache:
            day_cache[day] = fetch_sumario(client, day)
        res = resolve_row(row, day_cache[day][0].items)
        results.append(
            {
                "row": row.title,
                "boe_id": res.boe_id,
                "method": res.method,
                "score": str(res.score),
            }
        )
    unresolved = [r for r in results if not r["boe_id"]]
    typer.echo(
        f"{len(results) - len(unresolved)}/{len(results)} resolved; "
        f"{len(unresolved)} unresolved"
    )
    for r in unresolved:
        typer.echo(f"  UNRESOLVED: {str(r.get('row'))[:110]}")
    if out:
        out.write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        typer.echo(f"written: {out}")


@app.command()
def enumerate_history(
    start: str,
    end: str,
    manifest: Path | None = None,
) -> None:
    """Resumable enumeration of CNMV items in BOE Sección III, dept 1040.

    Writes a JSONL manifest — one line per day — so a multi-day backfill
    run can stop and resume exactly where it left off.
    """
    from cnmv_enforcement.sources.boe.historical import enumerate_range
    from cnmv_enforcement.sources.http import HttpClient

    manifest = manifest or runtime_root() / "boe_history.jsonl"
    client = HttpClient()
    stats = enumerate_range(
        client,
        date.fromisoformat(start),
        date.fromisoformat(end),
        manifest,
    )
    typer.echo(json.dumps(stats))
    typer.echo(f"manifest -> {manifest}")


@app.command()
def backfill_fetch(
    manifest: Path | None = None,
    corpus_dir: Path | None = None,
    sanction_only: bool = True,
) -> None:
    """Fetch BOE XMLs for sanction-like items in the history manifest."""
    from cnmv_enforcement.acquisition.rawstore import RawStore
    from cnmv_enforcement.sources.http import HttpClient

    manifest = manifest or runtime_root() / "boe_history.jsonl"
    corpus_dir = corpus_dir or data_root() / "corpus_historical"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    store = RawStore(data_root() / "raw")
    client = HttpClient()
    seen: set[str] = set()
    n = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        for item in rec.get("items", []):
            if sanction_only and not item.get("sanction_like"):
                continue
            bid = item["boe_id"]
            if bid in seen or (corpus_dir / f"{bid}.xml").exists():
                continue
            seen.add(bid)
            xml_url = BOE_XML_URL.format(boe_id=bid)
            fetched = client.get(xml_url)
            store.store(
                fetched,
                authority="BOE",
                document_type="publication_resolution",
                canonical_locator=bid,
                kind="boe_xml",
            )
            (corpus_dir / f"{bid}.xml").write_bytes(fetched.content)
            n += 1
    typer.echo(f"fetched {n} documents -> {corpus_dir}")


@app.command()
def fetch(
    corpus_dir: Path | None = None,
    limit: int | None = None,
) -> None:
    """Enumerate the register, resolve BOE ids, download every XML.

    Writes ``data/corpus/BOE-A-*.xml`` + ``index.json`` (deterministic
    corpus manifest). Raw bytes also land in the immutable raw store.
    """
    import re

    from cnmv_enforcement.acquisition.rawstore import RawStore
    from cnmv_enforcement.parsing.dates import parse_long_es
    from cnmv_enforcement.sources.boe.resolve import resolve_row
    from cnmv_enforcement.sources.boe.sumario import fetch_sumario
    from cnmv_enforcement.sources.cnmv.register import collect_register
    from cnmv_enforcement.sources.http import HttpClient

    corpus_dir = corpus_dir or _corpus()
    corpus_dir.mkdir(parents=True, exist_ok=True)
    store = RawStore(data_root() / "raw")
    client = HttpClient()
    snap = collect_register(client)
    day_cache: dict = {}
    index: list[dict] = []
    rows = snap.rows[:limit] if limit else snap.rows
    for row in rows:
        m = re.search(r"\(BOE de (\d+ de \w+ de \d{4})\)", row.title)
        if not m:
            index.append(
                {"boe_id": None, "title": row.title, "method": "NO_DATE"}
            )
            continue
        day = parse_long_es(m.group(1))
        if day is None:
            continue
        if day not in day_cache:
            day_cache[day] = fetch_sumario(client, day)
        res = resolve_row(row, day_cache[day][0].items)
        if not res.boe_id:
            index.append(
                {
                    "boe_id": None,
                    "title": row.title,
                    "method": res.method,
                    "register_entry_date": str(row.register_entry_date),
                }
            )
            continue
        xml_url = BOE_XML_URL.format(boe_id=res.boe_id)
        fetched = client.get(xml_url)
        store.store(
            fetched,
            authority="BOE",
            document_type="publication_resolution",
            canonical_locator=res.boe_id,
            kind="boe_xml",
        )
        (corpus_dir / f"{res.boe_id}.xml").write_bytes(fetched.content)
        index.append(
            {
                "boe_id": res.boe_id,
                "title": row.title,
                "register_entry_date": str(row.register_entry_date),
                "method": res.method,
                "score": res.score,
            }
        )
    (corpus_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    n = sum(1 for i in index if i["boe_id"])
    typer.echo(f"fetched {n} documents -> {corpus_dir}")


# ---------------------------------------------------------------- pipeline
@app.command()
def pdf_status(
    limit: int | None = None,
    snapshot: Path | None = None,
) -> None:
    """Fetch CNMV 'verdocumento' PDFs, extract status notes, diff snapshots.

    CNMV may regenerate these PDFs with later firmness/status notes — each
    run is a temporal observation. A changed sha256 or new status note is
    reported as a diff, and the snapshot file is updated.
    """
    import hashlib
    import re

    from cnmv_enforcement.acquisition.rawstore import RawStore
    from cnmv_enforcement.parsing.cnmv_pdf import extract_pdf_text
    from cnmv_enforcement.parsing.dates import parse_long_es
    from cnmv_enforcement.projections.state import FirmnessStatus
    from cnmv_enforcement.sources.boe.resolve import resolve_row
    from cnmv_enforcement.sources.boe.sumario import fetch_sumario
    from cnmv_enforcement.sources.cnmv.register import collect_register
    from cnmv_enforcement.sources.http import HttpClient

    snapshot = snapshot or runtime_root() / "cnmv_pdf_status.json"
    previous = (
        json.loads(snapshot.read_text(encoding="utf-8"))
        if snapshot.exists()
        else {}
    )
    client = HttpClient()
    store = RawStore(data_root() / "raw")
    snap = collect_register(client)
    day_cache: dict = {}
    rows = snap.rows[:limit] if limit else snap.rows
    current: dict[str, dict] = {}
    observed = datetime.now(UTC).isoformat()
    for row in rows:
        m = re.search(r"\(BOE de (\d+ de \w+ de \d{4})\)", row.title)
        if not m or not row.document_url:
            continue
        day = parse_long_es(m.group(1))
        if day is None:
            continue
        if day not in day_cache:
            day_cache[day] = fetch_sumario(client, day)
        res = resolve_row(row, day_cache[day][0].items)
        if not res.boe_id:
            continue
        url = row.document_url
        if url.startswith("/"):
            url = "https://www.cnmv.es" + url
        fetched = client.get(url)
        store.store(
            fetched,
            authority="CNMV",
            document_type="register_document",
            canonical_locator=res.boe_id,
            kind="cnmv_pdf",
        )
        sha = hashlib.sha256(fetched.content).hexdigest()
        retrieval = "OK"
        notes: list[dict] = []
        if not fetched.ok or not fetched.content.startswith(b"%PDF"):
            retrieval = "FETCH_FAILED"
        else:
            try:
                pt = extract_pdf_text(fetched.content)
                if pt.n_pages == 0 or not pt.text.strip():
                    retrieval = "EXTRACT_EMPTY"
                else:
                    notes = [
                        {"kind": n.kind, "page": n.page, "verbatim": n.verbatim}
                        for n in pt.status_notes
                    ]
            except Exception as exc:
                retrieval = "EXTRACT_FAILED"
                typer.echo(f"  PDF extract failed {res.boe_id}: {exc}")
        prev = previous.get(res.boe_id)
        if prev:
            if prev.get("sha256") != sha:
                typer.echo(f"  CHANGED-BYTES {res.boe_id}")
            elif prev.get("notes") != notes:
                typer.echo(f"  CHANGED-NOTES {res.boe_id}")
        status = FirmnessStatus.UNKNOWN
        kinds = {n["kind"] for n in notes}
        if "JUDGMENT_OBSERVED" in kinds:
            status = FirmnessStatus.JUDGMENT_OBSERVED
        elif "JUDICIAL_APPEAL_OBSERVED" in kinds:
            status = FirmnessStatus.APPEAL_OBSERVED
        elif kinds & {"ADMINISTRATIVE_FINALITY", "RENUNCIATION_TO_APPEAL"}:
            status = FirmnessStatus.FIRM_STATED
        elif "JUDICIAL_REVIEW_POSSIBLE" in kinds:
            status = FirmnessStatus.APPEAL_POSSIBLE
        # first-observation preserved across runs: observed_at is the
        # LAST verification, first_observed_at the FIRST — the knowledge
        # axis needs both (a re-run must not erase when a note appeared)
        current[res.boe_id] = {
            "sha256": sha,
            "notes": notes,
            "status": status,
            "retrieval": retrieval,
            "first_observed_at": (prev or {}).get("first_observed_at")
            or observed,
            "observed_at": observed,
        }
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(
        json.dumps(current, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    typer.echo(f"{len(current)} PDF observations -> {snapshot}")


@app.command()
def parse(corpus_dir: Path | None = None) -> None:
    """Parse corpus XMLs; print per-document summary and issues."""
    from cnmv_enforcement.parsing.boe_publication import parse_publication_xml

    corpus_dir = corpus_dir or _corpus()
    stats = {"docs": 0, "blocks": 0, "sanctions": 0, "issues": 0}
    for xml in sorted(corpus_dir.glob("BOE-A-*.xml")):
        pub = parse_publication_xml(xml.read_bytes())
        n = sum(len(b.sanctions) for b in pub.blocks)
        stats["docs"] += 1
        stats["blocks"] += len(pub.blocks)
        stats["sanctions"] += n
        stats["issues"] += len(pub.parse_issues)
        flag = "" if pub.blocks else "  <-- NO BLOCKS"
        typer.echo(f"{pub.boe_id}: {len(pub.blocks)} blocks, {n} sanctions{flag}")
    typer.echo(json.dumps(stats))


@app.command()
def build(
    corpus_dir: Path | None = None,
    exports_dir: Path | None = None,
    db_path: Path | None = None,
) -> None:
    """Full build: parse corpus -> assemble -> parquet + DuckDB + coverage."""
    from cnmv_enforcement.coverage.ledger import CoverageLedger, SourceCoverage
    from cnmv_enforcement.pipeline.build import build_corpus
    from cnmv_enforcement.storage.duckdb import build_duckdb
    from cnmv_enforcement.storage.parquet import write_parquet
    from cnmv_enforcement.storage.tables import flatten

    corpus_dir = corpus_dir or _corpus()
    exports_dir = exports_dir or exports_root() / datetime.now(UTC).date().isoformat()
    db_path = db_path or runtime_root() / "cnmv-enforcement.duckdb"

    dirs = [corpus_dir]
    hist = data_root() / "corpus_historical"
    if hist.exists() and any(hist.glob("BOE-A-*.xml")):
        dirs.append(hist)
    result = build_corpus(dirs)
    status_path = runtime_root() / "cnmv_pdf_status.json"
    pdf_obs = (
        json.loads(status_path.read_text(encoding="utf-8"))
        if status_path.exists()
        else None
    )
    # ── review ledger: seed + staleness ───────────────────────────
    from cnmv_enforcement.config import PARSER_VERSION, SCHEMA_VERSION
    from cnmv_enforcement.review.ledger import (
        append_ledger,
        load_ledger,
    )
    from cnmv_enforcement.review.model import (
        REVIEW_COMPAT_VERSION,
        apply_staleness,
        seed_from_defect_registry,
    )

    registry = data_root() / "review" / "defect_registry.yaml"
    ledger_path = data_root() / "review" / "review_ledger.jsonl"
    raw_sha_by_boe = {
        p.boe_id: p.raw_sha256 or ""
        for p in result.publications
        if p.boe_id
    }
    if registry.exists():
        append_ledger(
            ledger_path,
            seed_from_defect_registry(
                str(registry),
                raw_sha_by_boe,
                PARSER_VERSION,
                str(SCHEMA_VERSION),
            ),
        )
    items = apply_staleness(
        load_ledger(ledger_path), REVIEW_COMPAT_VERSION, raw_sha_by_boe
    )
    tables = flatten(
        result, pdf_status=pdf_obs, review_items=items
    )
    # ship the pdf-status manifest INSIDE the export — the coverage basis
    # for negative appeal claims must be reproducible from the release
    if status_path.exists():
        (exports_dir / "pdf_status_manifest.json").write_bytes(
            status_path.read_bytes()
        )
    written = write_parquet(tables, exports_dir / "parquet")
    counts = build_duckdb(exports_dir / "parquet", db_path)

    ledger = CoverageLedger(generated_at=result.built_at.isoformat())
    ledger.case_count = len(result.bundles)
    ledger.infringement_count = sum(len(b.infringements) for b in result.bundles)
    ledger.sanction_count = sum(len(b.sanctions) for b in result.bundles)
    ledger.respondent_count = len(
        {r.respondent_id for b in result.bundles for r in b.respondents}
    )
    pubs = [p for p in result.publications if p.publication_date]
    ledger.sources.append(
        SourceCoverage(
            source="boe_document",
            role="primary_publication",
            observed_from=(
                min(p.publication_date for p in pubs if p.publication_date)
                if pubs
                else None
            ),
            observed_to=(
                max(p.publication_date for p in pubs if p.publication_date)
                if pubs
                else None
            ),
            count=len(result.publications),
        )
    )
    if pubs:
        ledger.boe_date_range = {
            "from": str(min(p.publication_date for p in pubs if p.publication_date)),
            "to": str(max(p.publication_date for p in pubs if p.publication_date)),
        }
    # corpus reconciliation: N input docs = M cases + K non-case docs,
    # per corpus — never an unexplained count delta
    from collections import Counter

    per_corpus: dict[str, Counter] = {}
    for p in result.publications:
        c = per_corpus.setdefault(p.corpus, Counter())
        c["documents"] += 1
        c[p.document_kind] += 1
    # map bundles to corpus via publications
    pub_by_id = {p.boe_id: p for p in result.publications}
    case_corpus: Counter = Counter(
        pub_by_id[b.case.canonical_boe_id].corpus
        if b.case.canonical_boe_id in pub_by_id
        else "?"
        for b in result.bundles
    )
    ledger.historical_backfill = {
        "reconciliation": {
            corpus: {
                "documents": counts["documents"],
                "cases": case_corpus.get(corpus, 0),
                "non_case_documents": counts["documents"]
                - case_corpus.get(corpus, 0),
                "kinds": {
                    k: v for k, v in counts.items() if k != "documents"
                },
            }
            for corpus, counts in per_corpus.items()
        },
        "note": (
            "backfill corpus = BOE dept-1040 items whose titles match "
            "sanction-publication markers, enumerated 2018-01→2021-10 via "
            "the resumable sumario manifest — NOT exhaustive history"
        ),
    }
    for issue in result.issues:
        ledger.unresolved_or_ambiguous.append(
            f"{issue['boe_id']}: {issue['kind']} {issue.get('detail','')}"
        )
    coverage_path = exports_dir / "coverage.json"
    coverage_path.write_text(
        json.dumps(ledger.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    from cnmv_enforcement.storage.manifest import write_release

    manifest_path = write_release(
        exports_dir / "parquet",
        coverage_path=coverage_path,
        inputs={
            "corpus_dirs": [str(d) for d in dirs],
            "pdf_status": str(status_path)
            if (status_path := runtime_root() / "cnmv_pdf_status.json").exists()
            else None,
            "legal_rules": str(
                Path(__file__).resolve().parents[1]
                / "config"
                / "legal_rules.yaml"
            ),
        },
    )
    typer.echo(json.dumps(counts, indent=1))
    typer.echo(f"parquet -> {exports_dir / 'parquet'} ({len(written)} tables)")
    typer.echo(f"duckdb  -> {db_path}")
    typer.echo(f"coverage -> {coverage_path}")
    typer.echo(f"manifest -> {manifest_path}")


# ---------------------------------------------------------------- validation
@app.command()
def validate(corpus_dir: Path | None = None) -> None:
    """Run release gates over the corpus build (fail loudly)."""
    from cnmv_enforcement.validation.gates import run_gates

    corpus_dir = corpus_dir or _corpus()
    hist = data_root() / "corpus_historical"
    extra = [hist] if hist.exists() and any(hist.glob("BOE-A-*.xml")) else []
    report = run_gates(corpus_dir, extra_dirs=extra)
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ok"]:
        raise typer.Exit(1)


@app.command()
def coverage(exports_dir: Path | None = None) -> None:
    """Print the coverage ledger of the latest export."""
    exports_dir = exports_dir or exports_root()
    candidates = sorted(
        p for p in exports_dir.glob("*/coverage.json") if p.exists()
    )
    if not candidates:
        typer.echo("no coverage.json found — run `build` first")
        raise typer.Exit(1)
    typer.echo(candidates[-1].read_text(encoding="utf-8"))


# ---------------------------------------------------------------- query
@app.command()
def stats(db: Path | None = None) -> None:
    """Corpus statistics from the built DuckDB."""
    import duckdb

    db = db or runtime_root() / "cnmv-enforcement.duckdb"
    con = duckdb.connect(str(db), read_only=True)
    for q, label in [
        ("SELECT COUNT(*) FROM cases", "cases"),
        ("SELECT COUNT(*) FROM infringements", "infringements"),
        ("SELECT COUNT(*) FROM sanctions", "sanctions"),
        ("SELECT COUNT(*) FROM respondents", "respondents"),
        ("SELECT COUNT(DISTINCT respondent_id) FROM sanctions", "sanctioned parties"),
        ("SELECT SUM(amount) FROM sanctions WHERE amount IS NOT NULL", "total fines EUR"),
        (
            "SELECT severity, COUNT(*) FROM infringements GROUP BY 1 ORDER BY 1",
            "by severity",
        ),
        (
            "SELECT sanction_type, COUNT(*), SUM(amount) FROM sanctions "
            "GROUP BY 1 ORDER BY 1",
            "by sanction type",
        ),
        (
            "SELECT statute_normalized, COUNT(*) FROM infringements "
            "GROUP BY 1 ORDER BY 2 DESC",
            "by statute",
        ),
    ]:
        typer.echo(f"--- {label}")
        for row in con.execute(q).fetchall():
            typer.echo("   " + " | ".join(str(x) for x in row))
    con.close()


@app.command()
def case(
    case_id_or_boe: str,
    db: Path | None = None,
    known_at: str | None = None,
) -> None:
    """Inspect one case by case_id or BOE-A id.

    ``--known-at T`` restricts the view to observations the project had
    by T (AS_KNOWN_AT — observed_at <= T on the knowledge axis).
    """
    import duckdb

    db = db or runtime_root() / "cnmv-enforcement.duckdb"
    con = duckdb.connect(str(db), read_only=True)
    c = con.execute(
        "SELECT * FROM cases WHERE case_id = ? OR canonical_boe_id = ?",
        [case_id_or_boe, case_id_or_boe],
    ).fetchone()
    if not c:
        typer.echo("case not found")
        raise typer.Exit(1)
    cols = [d[0] for d in con.description]
    case_row = dict(zip(cols, c, strict=True))
    if known_at:
        from datetime import date, datetime, time

        try:
            if len(known_at.strip()) == 10:
                ts = datetime.combine(
                    date.fromisoformat(known_at.strip()),
                    time(23, 59, 59),
                ).isoformat()
            else:
                ts = datetime.fromisoformat(known_at.strip()).isoformat()
        except ValueError as exc:
            typer.echo(f"invalid --known-at: {known_at!r} (use ISO 8601)")
            raise typer.Exit(2) from exc
        cid = case_row["case_id"]
        evs = con.execute(
            "SELECT entity_id FROM evidence WHERE entity_id LIKE ? "
            "AND observed_at <= ?",
            [f"{cid}/%", ts],
        ).fetchall()
        known_ids = {r[0] for r in evs}
        case_known = bool(known_ids)
        case_row["history_mode"] = "AS_KNOWN_AT"
        case_row["known_at"] = ts
        if not case_known:
            case_row["observation_note"] = "NO_OBSERVATION_HISTORY"
        typer.echo(
            json.dumps(case_row, ensure_ascii=False, indent=2, default=str)
        )
        for t in ("infringements", "sanctions", "respondents"):
            typer.echo(f"--- {t} (known by {known_at})")
            if t == "respondents":
                if not case_known:
                    continue
                rows = con.execute(
                    "SELECT DISTINCT r.* FROM respondents r "
                    "JOIN case_respondents cr USING(respondent_id) "
                    "WHERE cr.case_id = ?",
                    [cid],
                ).fetchall()
            else:
                key = (
                    "infringement_id" if t == "infringements"
                    else "sanction_id"
                )
                cur = con.execute(
                    f"SELECT * FROM {t} WHERE case_id = ?", [cid]
                )
                rcols_t = [d[0] for d in cur.description]
                key_i = rcols_t.index(key)
                rows = [
                    r for r in cur.fetchall() if r[key_i] in known_ids
                ]
            rcols = [d[0] for d in con.description]
            for r in rows:
                drow = dict(zip(rcols, r, strict=True))
                typer.echo(
                    json.dumps(drow, ensure_ascii=False, default=str)
                )
        return
    typer.echo(json.dumps(case_row, ensure_ascii=False, indent=2, default=str))
    for t, _key in [
        ("infringements", "infringement_id"),
        ("sanctions", "sanction_id"),
        ("respondents", None),
    ]:
        typer.echo(f"--- {t}")
        if t == "infringements":
            rows = con.execute(
                "SELECT ordinal, severity, article_normalized, "
                "statute_normalized, rule_resolution_status, conduct_code "
                "FROM infringements WHERE case_id = ? ORDER BY ordinal",
                [case_row["case_id"]],
            ).fetchall()
        elif t == "sanctions":
            rows = con.execute(
                "SELECT s.ordinal, r.normalized_name, s.sanction_type, "
                "s.amount, s.currency, s.duration_raw "
                "FROM sanctions s JOIN respondents r USING(respondent_id) "
                "WHERE s.case_id = ? ORDER BY s.ordinal",
                [case_row["case_id"]],
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT DISTINCT r.normalized_name, r.respondent_type, r.role_raw "
                "FROM respondents r JOIN case_respondents cr USING(respondent_id) "
                "WHERE cr.case_id = ?",
                [case_row["case_id"]],
            ).fetchall()
        for row in rows:
            typer.echo("   " + " | ".join(str(x) for x in row))
    con.close()


@app.command()
def respondent(name: str, db: Path | None = None) -> None:
    """Look up a respondent by normalized-name substring."""
    import duckdb

    db = db or runtime_root() / "cnmv-enforcement.duckdb"
    con = duckdb.connect(str(db), read_only=True)
    rows = con.execute(
        "SELECT respondent_id, normalized_name, respondent_type "
        "FROM respondents WHERE lower(normalized_name) LIKE ?",
        [f"%{name.lower()}%"],
    ).fetchall()
    for rid, nm, rt in rows:
        n = con.execute(
            "SELECT COUNT(*), SUM(amount) FROM sanctions WHERE respondent_id = ?",
            [rid],
        ).fetchone()
        typer.echo(
            f"{nm}  [{rt}]  sanctions={n[0] if n else 0} "
            f"total={n[1] if n else 0}"
        )
    if not rows:
        typer.echo("no respondents matched")
    con.close()


@app.command()
def article(statute: str, art: str, db: Path | None = None) -> None:
    """List infringements typified under a statute + article."""
    import duckdb

    db = db or runtime_root() / "cnmv-enforcement.duckdb"
    con = duckdb.connect(str(db), read_only=True)
    rows = con.execute(
        "SELECT i.case_id, i.ordinal, i.severity, i.conduct_code, "
        "i.rule_resolution_status FROM infringements i "
        "WHERE i.statute_normalized ILIKE ? AND i.article_normalized = ?",
        [f"%{statute}%", art],
    ).fetchall()
    for row in rows:
        typer.echo(" | ".join(str(x) for x in row))
    typer.echo(f"{len(rows)} infringements")
    con.close()


@app.command()
def export(
    fmt: str = "jsonl",
    table: str = "sanctions",
    out: Path | None = None,
    db: Path | None = None,
) -> None:
    """Export a table as JSONL or CSV."""
    import duckdb

    db = db or runtime_root() / "cnmv-enforcement.duckdb"
    out = out or exports_root() / f"{table}.{fmt}"
    out.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db), read_only=True)
    if fmt == "jsonl":
        con.execute(
            f"COPY (SELECT * FROM {table}) TO ? (FORMAT JSON)", [str(out)]
        )
    elif fmt == "csv":
        con.execute(
            f"COPY (SELECT * FROM {table}) TO ? (HEADER, DELIMITER ',')", [str(out)]
        )
    else:
        typer.echo("fmt must be jsonl|csv")
        raise typer.Exit(1)
    con.close()
    typer.echo(f"exported -> {out}")


if __name__ == "__main__":
    app()
