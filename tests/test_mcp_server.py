"""Tests for the MCP server: which tools it offers, how a search is filtered, and how a missing figure is reported.

No models load: the search is a fake that records its calls, and the KPI queries are replaced.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from bankrag import mcp_server
from bankrag.config import Bank
from bankrag.models import Chunk, KpiFigure
from bankrag.retrieve import Hit


def chunk(bank: Bank, year: int, page: int) -> Chunk:
    return Chunk(
        id=f"{bank}-{year}-p{page:03d}-c00",
        bank=bank,
        year=year,
        page=page,
        section="Financial review",
        heading="",
        text="CET1 ratio 15.7%",
        body="CET1 ratio 15.7%",
        has_table=False,
    )


@dataclass
class RecordingRetriever:
    calls: list[tuple[str, int, list[Bank] | None, list[int] | None]] = field(default_factory=list)

    def search(self, query: str, k: int, banks: list[Bank] | None = None, years: list[int] | None = None) -> list[Hit]:
        self.calls.append((query, k, banks, years))
        bank = banks[0] if banks else "nordea"
        return [Hit(chunk(bank, year, page), 1.234) for page, year in enumerate(years or [2025] * k, 40)][:k]


def test_the_three_tools_are_read_only() -> None:
    tools = asyncio.run(mcp_server.server.list_tools())
    assert sorted(tool.name for tool in tools) == ["compare_banks", "get_kpi", "search_reports"]
    assert all(tool.annotations and tool.annotations.read_only_hint for tool in tools)


class TestFindPassages:
    def test_given_filters_are_used_and_danish_terms_expanded(self) -> None:
        retriever = RecordingRetriever()
        passages = mcp_server.find_passages(retriever, "Hvad var egenkapitalforrentningen?", "nordea", 2025, 3)
        query, k, banks, years = retriever.calls[0]
        assert "return on equity" in query
        assert (k, banks, years) == (3, ["nordea"], [2025])
        assert passages[0].bank == "Nordea"
        assert passages[0].score == 1.23

    def test_without_filters_the_query_routes_to_each_bank_it_names(self) -> None:
        retriever = RecordingRetriever()
        mcp_server.find_passages(retriever, "Compare the CET1 ratio of Danske Bank and Nordea in 2025", None, None, 6)
        assert [(banks, years) for _, _, banks, years in retriever.calls] == [
            (["danske"], [2025]),
            (["nordea"], [2025]),
        ]

    def test_k_is_kept_between_1_and_10(self) -> None:
        retriever = RecordingRetriever()
        mcp_server.find_passages(retriever, "net profit", "danske", None, 50)
        assert retriever.calls[0][1] == mcp_server.MAX_PASSAGES

    def test_a_year_without_a_report_is_refused(self) -> None:
        with pytest.raises(ToolError, match="2022 to 2025"):
            mcp_server.find_passages(RecordingRetriever(), "net profit", "danske", 2012, 6)


def test_a_missing_figure_is_a_tool_error_with_its_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_server, "kpi_get_kpi", lambda bank, metric, year: None)
    with pytest.raises(ToolError, match="no lending for Jyske Bank in 2023"):
        asyncio.run(mcp_server.server.call_tool("get_kpi", {"bank": "jyske", "metric": "lending", "year": 2023}))


def test_compare_banks_returns_the_table_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    figures = [KpiFigure(bank="danske", year=2025, metric="cet1_ratio", value=17.3, unit="%", page=4)]
    monkeypatch.setattr(mcp_server, "kpi_compare_banks", lambda metric, year: figures)
    assert mcp_server.compare_banks("cet1_ratio", 2025) == figures
