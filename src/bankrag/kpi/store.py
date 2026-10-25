"""The KPI table: key figures per bank, year and metric, kept as reviewed YAML and queried through SQLite.

kpi/figures.yaml is the source of truth: committed, readable in a diff, and where each figure is marked verified after
a check against the PDF. data/kpi.sqlite is built from it, so the MCP tools and the CLI can query it with SQL.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from typing import get_args

import yaml
from pydantic import TypeAdapter

from bankrag.config import BANK_NAMES, DATA_DIR, ROOT, Bank
from bankrag.models import KpiFigure, Metric

KPI_FILE = ROOT / "kpi" / "figures.yaml"
KPI_DB = DATA_DIR / "kpi.sqlite"
HEADER = """\
# Key figures for each bank and year, read by `bankrag kpi extract` from the bank's own annual report for that year.
#
# Fields:
#   value, unit:   the figure in the unit the report uses. Loan impairment charges are positive for a net charge.
#   page, quote:   the PDF page and the table row or sentence the figure was read from.
#   label, note:   the report's own name for the figure, and how it differs from the metric, if it does.
#   failed_checks: automatic checks that failed: the page was not among the passages, the quote is not on the page,
#                  or the value is not in the quote. Empty when all passed.
#   verified:      false until Anders has checked the figure against the PDF himself. Extraction keeps verified figures.
"""
COLUMNS = ("bank", "year", "metric", "value", "unit", "page", "quote", "label", "note", "failed_checks", "verified")

_FIGURES_ADAPTER: TypeAdapter[list[KpiFigure]] = TypeAdapter(list[KpiFigure])


def _order(figure: KpiFigure) -> tuple[int, int, int]:
    return list(BANK_NAMES).index(figure.bank), figure.year, get_args(Metric).index(figure.metric)


def load_figures() -> list[KpiFigure]:
    """Read the KPI table's YAML, or nothing if no figures have been extracted yet."""
    if not KPI_FILE.exists():
        return []
    return _FIGURES_ADAPTER.validate_python(yaml.safe_load(KPI_FILE.read_text(encoding="utf-8")) or [])


def save_figures(figures: list[KpiFigure]) -> None:
    """Write the figures to the YAML file in a fixed order, so a rerun only shows what changed."""
    records = [figure.model_dump() for figure in sorted(figures, key=_order)]
    body = yaml.safe_dump(records, allow_unicode=True, sort_keys=False, width=120)
    KPI_FILE.parent.mkdir(parents=True, exist_ok=True)
    KPI_FILE.write_text(HEADER + "\n" + body, encoding="utf-8", newline="\n")


def build_db(figures: list[KpiFigure]) -> None:
    """Rebuild data/kpi.sqlite from the figures."""
    KPI_DB.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(KPI_DB)) as db, db:
        db.execute("DROP TABLE IF EXISTS kpi")
        db.execute(
            "CREATE TABLE kpi (bank TEXT, year INTEGER, metric TEXT, value REAL, unit TEXT, page INTEGER, quote TEXT,"
            " label TEXT, note TEXT, failed_checks TEXT, verified INTEGER, PRIMARY KEY (bank, year, metric))",
        )
        rows = [
            (
                *figure.model_dump(exclude={"failed_checks", "verified"}).values(),
                json.dumps(figure.failed_checks),
                figure.verified,
            )
            for figure in figures
        ]
        db.executemany(f"INSERT INTO kpi VALUES ({', '.join('?' * len(COLUMNS))})", rows)


def _query(where: str, parameters: tuple[str | int, ...]) -> list[KpiFigure]:
    """Read figures from the database, rebuilding it first if it is missing or older than the YAML."""
    if not KPI_DB.exists() or (KPI_FILE.exists() and KPI_FILE.stat().st_mtime > KPI_DB.stat().st_mtime):
        build_db(load_figures())
    with closing(sqlite3.connect(KPI_DB)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(f"SELECT {', '.join(COLUMNS)} FROM kpi WHERE {where}", parameters).fetchall()
    figures = [
        KpiFigure.model_validate({**dict(row), "failed_checks": json.loads(row["failed_checks"])}) for row in rows
    ]
    return sorted(figures, key=_order)


def get_kpi(bank: Bank, metric: Metric, year: int) -> KpiFigure | None:
    """Return one figure from the KPI table, or None if it is not there."""
    figures = _query("bank = ? AND metric = ? AND year = ?", (bank, metric, year))
    return figures[0] if figures else None


def compare_banks(metric: Metric, year: int) -> list[KpiFigure]:
    """Return one metric for every bank in a year, in the usual bank order."""
    return _query("metric = ? AND year = ?", (metric, year))
