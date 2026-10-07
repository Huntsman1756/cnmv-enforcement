"""BOE OpenData sumario client — the reproducible enumeration surface.

``GET /datosabiertos/api/boe/sumario/{yyyymmdd}`` with
``Accept: application/json``. Structure::

    data.sumario.diario[] .seccion[] .departamento[] .epigrafe[] .item

Hazards handled defensively (observed in G0-R):

- ``epigrafe`` may be a bare string;
- ``item`` may be a dict or a list;
- departamento may be absent or a string.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from cnmv_enforcement.config import BOE_DEPARTAMENTO_CODIGO, BOE_SUMARIO_URL
from cnmv_enforcement.sources.http import HttpClient

log = logging.getLogger("cnmv_enforcement.boe.sumario")

# Title signals for CNMV enforcement publications. Conservative: anything
# not matching lands in OTHER_OFFICIAL_DOCUMENT, never dropped silently.
ENFORCEMENT_TITLE_RE = re.compile(
    r"por la que se publica(?:n)?\s+"
    r"(?:el\s+)?(?:la\s+|las\s+)?sancion(?:es)?\b",
    re.IGNORECASE,
)
MEASURE_TITLE_RE = re.compile(
    r"por la que se publica(?:n)?\s+(?:el\s+|la\s+|las\s+|los\s+)?"
    r"(?:medidas?|resoluci[oó]n\s+(?:sancionadora|de\s+infracci))",
    re.IGNORECASE,
)
CORRECTION_TITLE_RE = re.compile(r"correcci[oó]n\s+de\s+errores", re.IGNORECASE)


@dataclass
class SumarioItem:
    identificador: str
    titulo: str
    seccion_codigo: str | None = None
    departamento_codigo: str | None = None
    epigrafe_nombre: str | None = None
    url_html: str | None = None
    url_xml: str | None = None
    url_pdf: str | None = None
    pagina_inicial: int | None = None
    pagina_final: int | None = None


@dataclass
class Sumario:
    fecha: date
    numero: int | None
    items: list[SumarioItem] = field(default_factory=list)


def _iter_items(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        if "identificador" in node and "titulo" in node:
            yield node
        else:
            for v in node.values():
                yield from _iter_items(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_items(v)


def _as_list(v: Any) -> list[Any]:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


def parse_sumario(payload: bytes | str, fecha: date) -> Sumario:
    data = json.loads(payload)
    root = data.get("data", data)
    sumario = root.get("sumario", {})
    diarios = _as_list(sumario.get("diario"))
    out = Sumario(fecha=fecha, numero=None)
    for diario in diarios:
        if not isinstance(diario, dict):
            continue
        num = diario.get("numero")
        if isinstance(num, dict):
            num = num.get("texto")
        try:
            out.numero = int(num) if num is not None else None
        except (TypeError, ValueError):
            out.numero = None
        for seccion in _as_list(diario.get("seccion")):
            if not isinstance(seccion, dict):
                continue
            for dept in _as_list(seccion.get("departamento")):
                if not isinstance(dept, dict):
                    continue
                for ep in _as_list(dept.get("epigrafe")):
                    if not isinstance(ep, dict):
                        continue
                    ep_name = ep.get("nombre")
                    if isinstance(ep_name, dict):
                        ep_name = ep_name.get("texto")
                    for item in _iter_items(ep):
                        pdf = item.get("url_pdf")
                        pdf_url = pdf.get("texto") if isinstance(pdf, dict) else pdf
                        pi = pf = None
                        if isinstance(pdf, dict):
                            try:
                                pi = int(pdf.get("pagina_inicial") or 0) or None
                                pf = int(pdf.get("pagina_final") or 0) or None
                            except (TypeError, ValueError):
                                pi = pf = None
                        out.items.append(
                            SumarioItem(
                                identificador=str(item.get("identificador") or ""),
                                titulo=str(item.get("titulo") or ""),
                                seccion_codigo=str(seccion.get("codigo") or "") or None,
                                departamento_codigo=str(dept.get("codigo") or "")
                                or None,
                                epigrafe_nombre=ep_name if isinstance(ep_name, str) else None,
                                url_html=item.get("url_html"),
                                url_xml=item.get("url_xml"),
                                url_pdf=pdf_url,
                                pagina_inicial=pi,
                                pagina_final=pf,
                            )
                        )
    return out


def cnmv_items(sumario: Sumario) -> list[SumarioItem]:
    """Items under departamento 1040 (CNMV). Title classification is a
    separate step — dept membership is necessary but NOT sufficient for
    'enforcement'."""
    return [i for i in sumario.items if i.departamento_codigo == BOE_DEPARTAMENTO_CODIGO]


def classify_item(item: SumarioItem) -> str:
    """BOE_PUBLICATION_RESOLUTION | BOE_CORRECTION | OTHER_OFFICIAL_DOCUMENT."""
    if item.departamento_codigo != BOE_DEPARTAMENTO_CODIGO:
        return "OTHER_OFFICIAL_DOCUMENT"
    if CORRECTION_TITLE_RE.search(item.titulo):
        return "BOE_CORRECTION"
    if ENFORCEMENT_TITLE_RE.search(item.titulo) or MEASURE_TITLE_RE.search(
        item.titulo
    ):
        return "BOE_PUBLICATION_RESOLUTION"
    return "OTHER_OFFICIAL_DOCUMENT"


def fetch_sumario(client: HttpClient, fecha: date) -> tuple[Sumario, bytes, str]:
    url = BOE_SUMARIO_URL.format(yyyymmdd=fecha.strftime("%Y%m%d"))
    res = client.get(url, accept="application/json")
    return parse_sumario(res.content, fecha), res.content, url


def iter_dates(start: date, end: date) -> Iterator[date]:
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)
