"""Resumable historical enumeration of CNMV items in the BOE.

The sumario API is daily-only; enumerating 1961→today is a long batch
job. This module makes it *resumable*: every day is recorded in a JSONL
manifest (even days with zero CNMV items), so an interrupted run picks
up exactly where it stopped.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from cnmv_enforcement.sources.boe.sumario import cnmv_items, fetch_sumario
from cnmv_enforcement.sources.http import HttpClient

# Titles of CNMV items that are sanction-publication resolutions.
# Historical formats vary; match the action phrase, not the whole title.
_SANCTION_TITLE_MARKERS = (
    "se publica la sanción",
    "se publican las sanciones",
    "se publica la imposición de sanción",
    "se publican las imposiciones de sanciones",
    "se impone sanción",
    "se imponen sanciones",
    "se acuerda la imposición de sanción",
    "se acuerdan las imposiciones de sanciones",
    "infracción muy grave",
    "infracción grave",
    "resolución sancionadora",
)


def is_sanction_publication(title: str) -> bool:
    low = title.lower()
    return any(m in low for m in _SANCTION_TITLE_MARKERS)


def iter_dates(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def load_done_dates(manifest: Path) -> set[str]:
    """Dates successfully fetched — days recorded with an error are NOT
    done and will be retried on resume."""
    done: set[str] = set()
    if manifest.exists():
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                if "error" not in rec:
                    done.add(rec["date"])
    return done


def enumerate_range(
    client: HttpClient,
    start: date,
    end: date,
    manifest: Path,
) -> dict:
    """Fetch sumarios day by day; append {date, items:[...]} to manifest.

    Resumable: dates already in the manifest are skipped. Returns run
    stats.
    """
    manifest.parent.mkdir(parents=True, exist_ok=True)
    done = load_done_dates(manifest)
    stats = {"days": 0, "items": 0, "errors": 0}
    with manifest.open("a", encoding="utf-8") as fh:
        for day in iter_dates(start, end):
            key = day.isoformat()
            if key in done:
                continue
            try:
                sumario, _raw, _url = fetch_sumario(client, day)
                items = [
                    {
                        "boe_id": i.identificador,
                        "title": i.titulo,
                        "seccion": i.seccion_codigo,
                        "epigrafe": i.epigrafe_nombre,
                        "url_xml": i.url_xml,
                        "sanction_like": is_sanction_publication(i.titulo),
                    }
                    for i in cnmv_items(sumario)
                ]
            except Exception as exc:
                items = []
                stats["errors"] += 1
                fh.write(
                    json.dumps(
                        {"date": key, "error": str(exc), "items": []},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                fh.flush()
                continue
            stats["days"] += 1
            stats["items"] += len(items)
            fh.write(
                json.dumps({"date": key, "items": items}, ensure_ascii=False)
                + "\n"
            )
            fh.flush()
    return stats
