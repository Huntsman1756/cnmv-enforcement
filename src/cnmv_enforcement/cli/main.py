"""cnmv-enforcement CLI.

Commands follow the pipeline: probe → enumerate → fetch → parse →
build → validate → coverage. Query commands (case / respondent /
article / law / stats) read the built dataset.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
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
        parse_register_page,
    )
    from cnmv_enforcement.sources.http import HttpClient

    client = HttpClient()
    snap = collect_register(client)
    first = parse_register_page(
        snap.observed_at_pages[0].content.decode("utf-8"), 0
    )[0]
    typer.echo(
        json.dumps(
            {
                "declared_pages": snap.declared_pages,
                "rows": len(snap.rows),
                "first_row": {
                    "title": first.title[:120],
                    "register_entry_date": str(first.register_entry_date),
                },
                "date_range": [
                    str(min(r.register_entry_date for r in snap.rows)),
                    str(max(r.register_entry_date for r in snap.rows)),
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command()
def enumerate(out: Path | None = None) -> None:  # noqa: A002 — CLI name
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
        if day not in day_cache:
            day_cache[day] = fetch_sumario(client, day)
        res = resolve_row(row, day_cache[day].items)
        results.append(
            {
                "row": row.title,
                "boe_id": res.boe_id,
                "method": res.method,
                "score": res.score,
            }
        )
    unresolved = [r for r in results if not r["boe_id"]]
    typer.echo(
        f"{len(results) - len(unresolved)}/{len(results)} resolved; "
        f"{len(unresolved)} unresolved"
    )
    for r in unresolved:
        typer.echo(f"  UNRESOLVED: {r['row'][:110]}")
    if out:
        out.write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        typer.echo(f"written: {out}")


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
    from cnmv_enforcement.sources.boe.resolve import resolve_row
    from cnmv_enforcement.sources.boe.sumario import fetch_sumario
    from cnmv_enforcement.sources.cnmv.register import collect_register
    from cnmv_enforcement.sources.http import HttpClient
    from cnmv_enforcement.parsing.dates import parse_long_es

    corpus_dir = corpus_dir or _corpus()
    corpus_dir.mkdir(parents=True, exist_ok=True)
    store = RawStore()
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
        if day not in day_cache:
            day_cache[day] = fetch_sumario(client, day)
        res = resolve_row(row, day_cache[day].items)
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
        store.store_fetch(fetched, kind="boe_xml")
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
    typer.echo(f"fetched {n} documents → {corpus_dir}")


# ---------------------------------------------------------------- pipeline
@app.command()
def parse(corpus_dir: Path | None = None) -> None:  # noqa: A001 — CLI name
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
    """Full build: parse corpus → assemble → parquet + DuckDB + coverage."""
    from cnmv_enforcement.coverage.ledger import CoverageLedger, SourceCoverage
    from cnmv_enforcement.pipeline.build import build_corpus
    from cnmv_enforcement.storage.duckdb import build_duckdb
    from cnmv_enforcement.storage.parquet import write_parquet
    from cnmv_enforcement.storage.tables import flatten

    corpus_dir = corpus_dir or _corpus()
    exports_dir = exports_dir or exports_root() / datetime.now(UTC).date().isoformat()
    db_path = db_path or runtime_root() / "cnmv-enforcement.duckdb"

    result = build_corpus(corpus_dir)
    tables = flatten(result)
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
            observed_from=min(p.publication_date for p in pubs) if pubs else None,
            observed_to=max(p.publication_date for p in pubs) if pubs else None,
            count=len(result.publications),
        )
    )
    if pubs:
        ledger.boe_date_range = {
            "from": str(min(p.publication_date for p in pubs)),
            "to": str(max(p.publication_date for p in pubs)),
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
    typer.echo(json.dumps(counts, indent=1))
    typer.echo(f"parquet → {exports_dir / 'parquet'} ({len(written)} tables)")
    typer.echo(f"duckdb  → {db_path}")
    typer.echo(f"coverage → {coverage_path}")


# ---------------------------------------------------------------- validation
@app.command()
def validate(corpus_dir: Path | None = None) -> None:
    """Run release gates over the corpus build (fail loudly)."""
    from cnmv_enforcement.validation.gates import run_gates

    corpus_dir = corpus_dir or _corpus()
    report = run_gates(corpus_dir)
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
def case(case_id_or_boe: str, db: Path | None = None) -> None:
    """Inspect one case by case_id or BOE-A id."""
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
    typer.echo(json.dumps(case_row, ensure_ascii=False, indent=2, default=str))
    for t, key in [
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
        typer.echo(f"{nm}  [{rt}]  sanctions={n[0]} total={n[1]}")
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
    typer.echo(f"exported → {out}")


if __name__ == "__main__":
    app()
