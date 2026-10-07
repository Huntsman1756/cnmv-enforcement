"""Project paths and constants. No domain logic here."""

from __future__ import annotations

import os
from pathlib import Path

USER_AGENT = (
    "cnmv-enforcement/0.1 (+https://github.com/Huntsman1756/cnmv-enforcement; "
    "public enforcement data research)"
)

SCHEMA_VERSION = 1
PARSER_VERSION = "0.1.0"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def data_root() -> Path:
    return Path(os.environ.get("CNMV_ENFORCEMENT_DATA", repo_root() / "data"))


def raw_root() -> Path:
    return data_root() / "raw"


def runtime_root() -> Path:
    return data_root() / "runtime"


def exports_root() -> Path:
    return data_root() / "exports"


def artifacts_root() -> Path:
    return Path(os.environ.get("CNMV_ENFORCEMENT_ARTIFACTS", repo_root() / "artifacts"))


def coverage_root() -> Path:
    return Path(os.environ.get("CNMV_ENFORCEMENT_COVERAGE", repo_root() / "coverage"))


def config_root() -> Path:
    return repo_root() / "config"


# CNMV register
CNMV_REGISTER_URL = (
    "https://www.cnmv.es/portal/consultas/registrosanciones/verregsanciones"
)
CNMV_REGISTER_INTRO_URL = (
    "https://www.cnmv.es/Portal/Consultas/RegistroSanciones/IniRegSanciones.aspx"
)
# BOE
BOE_SUMARIO_URL = "https://www.boe.es/datosabiertos/api/boe/sumario/{yyyymmdd}"
BOE_XML_URL = "https://www.boe.es/diario_boe/xml.php?id={boe_id}"
BOE_HTML_URL = "https://www.boe.es/diario_boe/txt.php?id={boe_id}"
BOE_DEPARTAMENTO_CODIGO = "1040"  # Comisión Nacional del Mercado de Valores
