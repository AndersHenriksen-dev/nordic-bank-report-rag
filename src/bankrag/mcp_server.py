"""A read-only MCP server, so Claude Desktop or Claude Code can search the reports and read the KPI table directly.

Three tools: `search_reports` returns the passages the reranked search finds, with bank, year, page and section,
and `get_kpi` and `compare_banks` read the KPI table. Nothing here calls the Claude API or writes a file, so the tools
cost nothing and are safe to allow. Start it with `make mcp`. The search models load on the first search, and the
server holds Qdrant's folder lock while it runs, like the web page.
"""

from __future__ import annotations

from functools import cache

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from bankrag.config import DISCLAIMER, YEARS, Bank, bank_name
from bankrag.ingest import load_chunks
from bankrag.kpi import compare_banks as kpi_compare_banks
from bankrag.kpi import get_kpi as kpi_get_kpi
from bankrag.models import KpiFigure, Metric
from bankrag.retrieve import DEFAULT_RETRIEVER, Retriever, build_retriever, expand_danish, routed_search

MAX_PASSAGES = 10
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
INSTRUCTIONS = f"""\
Searches the 2022 to 2025 annual reports of Danske Bank, Nordea and Jyske Bank, and reads a table of key figures \
taken from them. Cite the bank, report year and page of every passage or figure you use. Danske Bank and Jyske Bank \
report in DKK and Nordea in EUR; do not convert. Refuse forecasts, recommendations and investment advice. \
{DISCLAIMER}"""

server: MCPServer = MCPServer(name="bankrag", instructions=INSTRUCTIONS)


class Passage(BaseModel):
    """One passage from a report, with what is needed to cite it."""

    bank: str
    year: int
    page: int
    section: str
    text: str
    score: float


@cache
def _retriever() -> Retriever:
    return build_retriever(DEFAULT_RETRIEVER, load_chunks("structure"))


def find_passages(retriever: Retriever, query: str, bank: Bank | None, year: int | None, k: int) -> list[Passage]:
    """Search with the bank and year given, or else with those the query names, balanced across banks.

    Raises:
        ToolError: If the year is outside the reports. MCP passes a ToolError's message on to the client; any other
            exception reaches it only as "Error executing tool".
    """
    if year is not None and year not in YEARS:
        raise ToolError(f"There is no {year} report. The reports cover {YEARS[0]} to {YEARS[-1]}.")
    k = max(1, min(k, MAX_PASSAGES))
    if bank or year:
        banks = [bank] if bank else None
        hits = retriever.search(expand_danish(query), k, banks=banks, years=[year] if year else None)
    else:
        hits = routed_search(retriever, query, k=k)
    return [
        Passage(
            bank=bank_name(hit.chunk.bank),
            year=hit.chunk.year,
            page=hit.chunk.page,
            section=hit.chunk.heading or hit.chunk.section,
            text=hit.chunk.body,
            score=round(hit.score, 2),
        )
        for hit in hits
    ]


@server.tool(annotations=READ_ONLY)
def search_reports(query: str, bank: Bank | None = None, year: int | None = None, k: int = 6) -> list[Passage]:
    """Search the 2022 to 2025 annual reports of Danske Bank, Nordea and Jyske Bank, best passages first.

    Each passage comes with its bank, report year, PDF page and section, so an answer can cite it. Without a bank or
    year, the banks and years named in the query are used, and a question about several banks gets passages from
    each. Tables are rows of cells separated by "|".

    Args:
        query: A question or search terms, in English or Danish.
        bank: Only search this bank's reports: danske, nordea or jyske.
        year: Only search the report for this financial year, 2022 to 2025.
        k: How many passages to return, 1 to 10.
    """
    return find_passages(_retriever(), query, bank, year, k)


@server.tool(annotations=READ_ONLY)
def get_kpi(bank: Bank, metric: Metric, year: int) -> KpiFigure:
    """Read one key figure for a bank and year from the KPI table, with the page and table row it came from.

    Metrics: net_profit, total_income, cost_income_ratio, return_on_equity, cet1_ratio, loan_impairment_charges
    (positive for a net charge) and lending, for 2024 and 2025. Values are in the unit the report uses. `verified`
    is true once the figure has been checked by hand against the PDF; `note` says where a bank's definition differs.

    Raises:
        ToolError: If the table has no such figure.
    """
    figure = kpi_get_kpi(bank, metric, year)
    if figure is None:
        raise ToolError(f"The KPI table has no {metric} for {bank_name(bank)} in {year}.")
    return figure


@server.tool(annotations=READ_ONLY)
def compare_banks(metric: Metric, year: int) -> list[KpiFigure]:
    """Read one key figure for all three banks in a year from the KPI table, to compare them.

    Nordea reports in EUR and the two Danish banks in DKK, so amounts are not comparable without converting currency;
    ratios are. See get_kpi for the metrics and fields.
    """
    return kpi_compare_banks(metric, year)


def main() -> None:
    """Run the server over stdio, which is how Claude Desktop and Claude Code start it."""
    server.run("stdio")


if __name__ == "__main__":
    main()
