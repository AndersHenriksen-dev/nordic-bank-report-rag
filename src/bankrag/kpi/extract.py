"""Extract the KPI table's figures from the reports with Claude's structured output, and check each one.

For every bank, year and metric, the search finds the passages most likely to hold the figure, and Claude returns it
as a typed `ExtractedKpi`: the value, its unit, the page and the exact table row or sentence it read. Three automatic
checks follow, and a person checks the rest against the PDF before the figure counts as verified.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import NamedTuple

from pydantic import ValidationError

from bankrag.answer import api_client, cost_usd
from bankrag.config import ANSWER_MODEL, BANK_NAMES, YEARS, Bank, bank_name
from bankrag.figures import close_to, numbers_in
from bankrag.models import Chunk, ExtractedKpi, KpiFigure, Metric
from bankrag.retrieve import Hit, Retriever, routed_search

PASSAGES = 6
MAX_OUTPUT_TOKENS = 4096  # thinking counts towards the limit; a figure uses a few hundred tokens
# Every metric is in the report's key figure tables, on these PDF pages (checked by hand in the page text). The search
# alone sometimes returns a note, the parent company or a business unit instead, so these pages are always sent too.
KEY_FIGURE_PAGES: dict[tuple[Bank, int], tuple[int, ...]] = {
    ("danske", 2024): (4,),
    ("danske", 2025): (4,),
    ("nordea", 2024): (40, 42, 43),
    ("nordea", 2025): (40, 42, 43),
    ("jyske", 2024): (7, 8),
    ("jyske", 2025): (7, 8),
}

SYSTEM_PROMPT = """\
You read key figures from passages of a bank's annual report. Use only the passages.

- Give the figure for the whole group, never for a business unit, a segment or the parent company alone.
- Give the figure for the financial year asked about. Tables are rows of cells separated by "|". Check the header \
row to see which column is which year; in key figure tables the first figure column is usually the latest year.
- Copy the quote exactly as it appears in one passage: the whole table row, or the sentence that states the figure.
- Give the value as a plain number without thousands separators, in the unit the passage uses: 23,037 in a table in \
DKK million is 23037 with the unit "DKK million", and 15.7% is 15.7 with the unit "%".
- If the bank defines the figure differently from the one asked for, give the bank's figure and say how it differs \
in the note.
- If no passage states the figure, set found to false and every other field to null.
"""


class MetricSpec(NamedTuple):
    """How to ask for one metric: its name in a question, and the definition the extraction follows."""

    name: str
    definition: str


METRICS: dict[Metric, MetricSpec] = {
    "net_profit": MetricSpec("net profit", "Net profit for the year (profit after tax) for the whole group."),
    "total_income": MetricSpec(
        "total income",
        "Total income for the whole group: all income lines together, called total income, total operating income "
        "or, at Jyske Bank, core income.",
    ),
    "cost_income_ratio": MetricSpec(
        "cost/income ratio",
        "The group's cost/income ratio in %. If the bank reports more than one, give the headline ratio and name "
        "the other in the note.",
    ),
    "return_on_equity": MetricSpec(
        "return on equity",
        "The group's return on equity in %. Jyske Bank reports it as profit for the year as a percentage of "
        "average equity; use that, not return on tangible equity.",
    ),
    "cet1_ratio": MetricSpec("CET1 capital ratio", "The group's common equity tier 1 (CET1) capital ratio in %."),
    "loan_impairment_charges": MetricSpec(
        "loan impairment charges",
        "The group's loan impairment charges or net loan losses for the year, positive for a net charge and "
        "negative for a net reversal, whatever sign the report prints.",
    ),
    "lending": MetricSpec(
        "lending",
        "The group's lending to customers at the end of the year: loans at Danske Bank, loans to the public at "
        "Nordea, loans and advances at Jyske Bank.",
    ),
}


def _user_message(bank: Bank, year: int, spec: MetricSpec, hits: list[Hit]) -> str:
    passages = [
        f'<passage page="{hit.chunk.page}" section="{hit.chunk.heading or hit.chunk.section}">\n'
        f"{hit.chunk.body}\n</passage>"
        for hit in hits
    ]
    figure = f"Figure: {spec.definition}\nBank: {bank_name(bank)}\nFinancial year: {year}"
    return "\n\n".join([*passages, figure])


def _squash(text: str) -> str:
    return " ".join(text.split()).casefold()


def failed_checks(extracted: ExtractedKpi, hits: list[Hit]) -> list[str]:
    """Run the automatic checks on one extracted figure.

    Returns:
        A short description of each failed check: the page was not among the passages sent, the quote is not on that
        page, or the value is not in the quote. Empty when all passed.
    """
    if not extracted.found or extracted.value is None:
        return ["no passage states it"]
    on_page = [hit.chunk.body for hit in hits if hit.chunk.page == extracted.page]
    if not on_page:
        return [f"page {extracted.page} was not among the passages"]
    failed = []
    quote = _squash(extracted.quote or "").strip("| ")
    if not quote or quote not in _squash(" ".join(on_page)):
        failed.append("the quote is not on the page")
    if not any(close_to(number, abs(extracted.value)) for number in numbers_in(extracted.quote or "")):
        failed.append("the value is not in the quote")
    return failed


def key_figure_passages(chunks: list[Chunk], bank: Bank, year: int) -> list[Hit]:
    """Return the chunks on a report's key figure pages, to send along with every metric's search results."""
    pages = KEY_FIGURE_PAGES[(bank, year)]
    return [Hit(chunk, 0.0) for chunk in chunks if (chunk.bank, chunk.year) == (bank, year) and chunk.page in pages]


def extract_figure(
    bank: Bank,
    year: int,
    metric: Metric,
    retriever: Retriever,
    key_figures: list[Hit],
) -> tuple[KpiFigure, float]:
    """Find and read one figure from the key figure pages and the search results. Calls the paid API once.

    Returns:
        The figure, with the automatic checks it failed, and the cost of the call in USD.

    Raises:
        SystemExit: If no API key is configured.
    """
    spec = METRICS[metric]
    found = routed_search(retriever, f"What was {bank_name(bank)}'s {spec.name} in {year}?", k=PASSAGES)
    sent = {hit.chunk.id for hit in key_figures}
    hits = [*key_figures, *(hit for hit in found if hit.chunk.id not in sent)]
    try:
        response = api_client().messages.parse(
            model=ANSWER_MODEL,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _user_message(bank, year, spec, hits)}],
            output_config={"effort": "medium"},
            output_format=ExtractedKpi,
        )
    except ValidationError:  # output cut off at the token limit is not valid JSON
        return KpiFigure(
            bank=bank,
            year=year,
            metric=metric,
            value=None,
            unit=None,
            page=None,
            failed_checks=["the model's output was not a complete figure"],
        ), 0.0
    extracted = response.parsed_output or ExtractedKpi(
        found=False,
        value=None,
        unit=None,
        page=None,
        quote=None,
        label=None,
        note=None,
    )
    figure = KpiFigure(
        bank=bank,
        year=year,
        metric=metric,
        value=extracted.value if extracted.found else None,
        unit=extracted.unit if extracted.found else None,
        page=extracted.page if extracted.found else None,
        quote=extracted.quote or "",
        label=extracted.label or "",
        note=extracted.note or "",
        failed_checks=failed_checks(extracted, hits),
    )
    return figure, cost_usd(ANSWER_MODEL, response.usage)


def extract_table(
    retriever: Retriever,
    chunks: list[Chunk],
    existing: list[KpiFigure],
) -> Iterator[tuple[KpiFigure, float]]:
    """Extract every figure of the table, one API call each, keeping the figures already verified by hand.

    Yields:
        Each figure and the cost of extracting it in USD (0 for a kept figure).
    """
    verified = {(figure.bank, figure.year, figure.metric): figure for figure in existing if figure.verified}
    for bank in BANK_NAMES:
        for year in YEARS:
            key_figures = key_figure_passages(chunks, bank, year)
            for metric in METRICS:
                kept = verified.get((bank, year, metric))
                yield (kept, 0.0) if kept else extract_figure(bank, year, metric, retriever, key_figures)
