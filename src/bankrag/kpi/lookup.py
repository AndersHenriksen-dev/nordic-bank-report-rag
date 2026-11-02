"""Send the KPI table's rows that a question asks for to Claude, next to the search results.

The search sometimes returns a business unit's page, a note or the parent company's figures instead of the group's key
figure table, and Claude then picks the wrong figure or says the figure is missing. When a question names a key
figure, a bank and a year, the matching rows of the KPI table go in front of the search results: each is the exact row
from the report page, checked automatically against that page, with a title that states the figure for that year.
"""

from __future__ import annotations

import math
import re

from bankrag.config import YEARS
from bankrag.kpi.store import get_kpi
from bankrag.models import Chunk, KpiFigure, Metric
from bankrag.retrieve import Hit, detect_filters
from bankrag.retrieve.rewrite import english_terms
from bankrag.retrieve.route import YEAR_RE

# Matched against the question plus the glossary's English wording, so "egenkapitalforrentning" counts as return on
# equity. The glossary applies here whatever the question's language: none of its key figure terms occur in English.
METRIC_PATTERNS: dict[Metric, re.Pattern[str]] = {
    "net_profit": re.compile(r"\bnet profit\b|\bprofit for the year\b|\bnet income\b", re.IGNORECASE),
    "total_income": re.compile(r"\btotal (?:operating )?income\b|\bcore income\b", re.IGNORECASE),
    "cost_income_ratio": re.compile(r"\bcost(?:/| to |-to-|-)income\b|\bc/i\b", re.IGNORECASE),
    "return_on_equity": re.compile(r"\breturn on (?:average |total |shareholders' )?equity\b|\broe\b", re.IGNORECASE),
    "cet1_ratio": re.compile(r"\bcet ?1\b|\bcommon equity tier 1\b", re.IGNORECASE),
    "loan_impairment_charges": re.compile(r"\bloan impairment|\bimpairment charges\b|\bloan losses\b", re.IGNORECASE),
    "lending": re.compile(r"\blending\b|\bloans\b|\blent\b", re.IGNORECASE),
}
MAX_KEY_FIGURES = 6


def asked_metrics(question: str) -> list[Metric]:
    """Return the key figures a question names, in English or Danish."""
    text = " ".join([question, *english_terms(question)])
    return [metric for metric, pattern in METRIC_PATTERNS.items() if pattern.search(text)]


def key_figures_for(question: str) -> list[KpiFigure]:
    """Return the KPI table's rows for every key figure, bank and year the question names.

    A question that names no bank or no report year gets none, and so does one that names a year after the last
    report: it asks about the future, which the table cannot answer. Only rows that passed the automatic checks count.
    """
    if any(int(year) > max(YEARS) for year in YEAR_RE.findall(question)):
        return []
    filters = detect_filters(question)
    found = (
        get_kpi(bank, metric, year)
        for metric in asked_metrics(question)
        for bank in filters.banks
        for year in filters.years
    )
    return [figure for figure in found if figure and figure.page and figure.quote and not figure.failed_checks][
        :MAX_KEY_FIGURES
    ]


def figure_key(figure: KpiFigure) -> str:
    """Name a KPI table row as the eval set does, for example "danske-2025-cost_income_ratio"."""
    return f"{figure.bank}-{figure.year}-{figure.metric}"


def _stated(figure: KpiFigure) -> str:
    """State a figure in words, for example "45.5%", "DKK 23,037 million" or "a net reversal of DKK 543 million"."""
    value = figure.value or 0.0
    number = f"{abs(value):,.0f}" if abs(value).is_integer() else f"{abs(value):,}"
    currency, _, scale = (figure.unit or "").partition(" ")
    amount = f"{number}%" if figure.unit == "%" else f"{currency} {number} {scale}".strip()
    if figure.metric == "loan_impairment_charges":
        return f"a net {'reversal' if value < 0 else 'charge'} of {amount}"
    return f"-{amount}" if value < 0 else amount


def key_figure_hit(figure: KpiFigure) -> Hit:
    """Turn a KPI table row into a passage: the row as it appears on the page, under a title that states the figure.

    A row from a key figure table holds several years' values without its header, so the title says which one is
    the figure, and for loan impairment charges whether it is a charge or a reversal, whatever sign the table prints.
    """
    label = figure.label or figure.metric.replace("_", " ")
    heading = f"key figure checked against this page: {label} for {figure.year} is {_stated(figure)}"
    chunk = Chunk(
        id=f"kpi-{figure_key(figure)}",
        bank=figure.bank,
        year=figure.year,
        page=figure.page or 0,
        section="Key figure table",
        heading=heading,
        text=f"{heading}\n{figure.quote}",
        body=figure.quote,
        has_table=figure.quote.lstrip().startswith("|"),
    )
    return Hit(chunk, math.nan)  # not ranked by a search, so it has no score


def with_key_figures(question: str, hits: list[Hit]) -> list[Hit]:
    """Put the KPI table rows a question asks for in front of its search results."""
    return [key_figure_hit(figure) for figure in key_figures_for(question)] + hits
