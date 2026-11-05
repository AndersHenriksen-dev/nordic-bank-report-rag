"""Tests for the KPI table: the automatic checks, the extraction request, the store, and the rows sent with answers.

No API call is made: the SDK's HTTP transport is replaced by one that records the request and returns a canned reply,
and the search is a fake that returns fixed passages.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anthropic
import httpx2
import pytest

from bankrag.config import Bank
from bankrag.kpi import extract, lookup, store
from bankrag.models import Chunk, ExtractedKpi, KpiFigure, Metric
from bankrag.retrieve.bm25 import Hit
from bankrag.retrieve.route import Retriever

HIGHLIGHTS = (
    "| DKK million | 2025 | 2024 | Index |\n"
    "| Net profit | 23,037 | 23,629 | 97 |\n"
    "| Loan impairment charges | 294 | -543 | - |"
)
NET_PROFIT_ROW = "| Net profit | 23,037 | 23,629 | 97 |"


def hit(page: int, body: str) -> Hit:
    chunk = Chunk(
        id=f"danske-2025-p{page:03d}-c00",
        bank="danske",
        year=2025,
        page=page,
        section="Financial highlights",
        heading="Financial highlights - Danske Bank Group",
        text=body,
        body=body,
        has_table=True,
    )
    return Hit(chunk, 1.0)


HITS = [hit(4, HIGHLIGHTS), hit(10, "Net profit decreased 3% to DKK 23,037 million.")]


def extracted(value: float | None, page: int | None = 4, quote: str | None = NET_PROFIT_ROW) -> ExtractedKpi:
    return ExtractedKpi(
        found=value is not None,
        value=value,
        unit="DKK million",
        page=page,
        quote=quote,
        label="Net profit",
        note=None,
    )


class TestFailedChecks:
    def test_a_figure_read_from_its_row_passes(self) -> None:
        assert extract.failed_checks(extracted(23037), HITS) == []

    def test_a_figure_from_a_sentence_passes(self) -> None:
        figure = extracted(23037, page=10, quote="Net profit decreased 3% to DKK 23,037 million.")
        assert extract.failed_checks(figure, HITS) == []

    def test_a_sign_flipped_to_a_charge_still_matches_the_row(self) -> None:
        figure = extracted(543, quote="| Loan impairment charges | 294 | -543 | - |")
        assert extract.failed_checks(figure, HITS) == []

    def test_a_page_that_was_not_sent_fails(self) -> None:
        assert extract.failed_checks(extracted(23037, page=5), HITS) == ["page 5 was not among the passages"]

    def test_a_quote_that_is_not_on_the_page_fails(self) -> None:
        figure = extracted(23037, quote="| Net profit | 23,037 | 23,629 | 98 |")
        assert extract.failed_checks(figure, HITS) == ["the quote is not on the page"]

    def test_a_value_in_the_wrong_unit_fails(self) -> None:
        assert extract.failed_checks(extracted(23.0), HITS) == ["the value is not in the quote"]

    def test_a_figure_that_was_not_found_fails(self) -> None:
        assert extract.failed_checks(extracted(None, page=None, quote=None), HITS) == ["no passage states it"]


class FakeRetriever:
    def search(self, query: str, k: int, banks: list[Bank] | None = None, years: list[int] | None = None) -> list[Hit]:
        return [hit(4, HIGHLIGHTS)]


def fake_client(answer: dict[str, Any], requests: list[dict[str, Any]]) -> anthropic.Anthropic:
    def handle(request: httpx2.Request) -> httpx2.Response:
        requests.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": "claude-haiku-5-5",
                "content": [{"type": "text", "text": json.dumps(answer)}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 2000, "output_tokens": 300},
            },
        )

    transport = httpx2.MockTransport(handle)
    return anthropic.Anthropic(api_key="test", http_client=anthropic.DefaultHttpxClient(transport=transport))


def test_extract_figure_sends_the_passages_and_checks_the_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[dict[str, Any]] = []
    client = fake_client(extracted(23037).model_dump(), requests)
    monkeypatch.setattr(extract, "api_client", lambda: client)

    key_figures = [hit(4, HIGHLIGHTS)]
    figure, cost = extract.extract_figure("danske", 2025, "net_profit", FakeRetriever(), key_figures)

    assert (figure.value, figure.unit, figure.page, figure.failed_checks) == (23037, "DKK million", 4, [])
    assert cost == pytest.approx((2000 * 0.10 + 300 * 0.50) / 1e6)
    message = requests[0]["messages"][0]["content"]
    assert '<passage page="4"' in message
    assert "Bank: Danske Bank\nFinancial year: 2025" in message
    required = set(requests[0]["output_config"]["format"]["schema"]["required"])
    assert {"found", "value", "unit", "page", "quote"} <= required


def test_extract_table_keeps_figures_verified_by_hand(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Bank, int, Metric]] = []

    def fake_extract(
        bank: Bank,
        year: int,
        metric: Metric,
        retriever: Retriever,
        key_figures: list[Hit],
    ) -> tuple[KpiFigure, float]:
        calls.append((bank, year, metric))
        return KpiFigure(bank=bank, year=year, metric=metric, value=1.0, unit="%", page=1), 0.001

    monkeypatch.setattr(extract, "extract_figure", fake_extract)
    checked = KpiFigure(bank="nordea", year=2025, metric="cet1_ratio", value=15.7, unit="%", page=40, verified=True)

    results = list(extract.extract_table(FakeRetriever(), [], [checked]))

    assert len(results) == 42
    assert len(calls) == 41
    assert (checked, 0.0) in results


FIGURES = [
    KpiFigure(bank="nordea", year=2025, metric="cet1_ratio", value=15.7, unit="%", page=40, verified=True),
    KpiFigure(bank="danske", year=2025, metric="cet1_ratio", value=17.3, unit="%", page=4),
    KpiFigure(
        bank="danske",
        year=2025,
        metric="net_profit",
        value=None,
        unit=None,
        page=None,
        failed_checks=["no passage states it"],
    ),
]


class TestStore:
    @pytest.fixture(autouse=True)
    def paths(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(store, "KPI_FILE", tmp_path / "kpi" / "figures.yaml")
        monkeypatch.setattr(store, "KPI_DB", tmp_path / "data" / "kpi.sqlite")

    def test_figures_come_back_from_yaml_in_table_order(self) -> None:
        store.save_figures(FIGURES)
        loaded = store.load_figures()
        assert [(figure.bank, figure.metric) for figure in loaded] == [
            ("danske", "net_profit"),
            ("danske", "cet1_ratio"),
            ("nordea", "cet1_ratio"),
        ]
        assert loaded[0].failed_checks == ["no passage states it"]

    def test_queries_read_the_database_built_from_the_yaml(self) -> None:
        store.save_figures(FIGURES)
        nordea = store.get_kpi("nordea", "cet1_ratio", 2025)
        assert nordea is not None
        assert (nordea.value, nordea.verified) == (15.7, True)
        assert [figure.bank for figure in store.compare_banks("cet1_ratio", 2025)] == ["danske", "nordea"]
        assert store.get_kpi("jyske", "cet1_ratio", 2025) is None

    def test_no_yaml_means_an_empty_table(self) -> None:
        assert store.load_figures() == []
        assert store.compare_banks("cet1_ratio", 2025) == []


TABLE = {
    ("danske", "cost_income_ratio", 2024): KpiFigure(
        bank="danske",
        year=2024,
        metric="cost_income_ratio",
        value=45.6,
        unit="%",
        page=4,
        quote="| Cost/income ratio (C/I), (%) | 45.6 | 48.6 |",
        label="Cost/income ratio (C/I), (%)",
    ),
    ("danske", "cost_income_ratio", 2025): KpiFigure(
        bank="danske",
        year=2025,
        metric="cost_income_ratio",
        value=45.5,
        unit="%",
        page=4,
        quote="| Cost/income ratio (C/I), (%) | 45.5 | 45.6 |",
        label="Cost/income ratio (C/I), (%)",
    ),
    ("danske", "net_profit", 2024): KpiFigure(
        bank="danske",
        year=2024,
        metric="net_profit",
        value=23629,
        unit="DKK million",
        page=4,
        quote="| Net profit | 23,629 | 21,262 |",
        label="Net profit",
    ),
    ("nordea", "net_profit", 2024): KpiFigure(
        bank="nordea",
        year=2024,
        metric="net_profit",
        value=5059,
        unit="EUR million",
        page=40,
        quote="| Net profit for the year | 5,059 | 4,934 |",
        label="Net profit for the year",
    ),
    ("jyske", "net_profit", 2024): KpiFigure(
        bank="jyske",
        year=2024,
        metric="net_profit",
        value=5312,
        unit="DKK million",
        page=7,
        quote="| Profit for the year | 5,312 |",
        failed_checks=["the value is not in the quote"],
    ),
    ("danske", "loan_impairment_charges", 2024): KpiFigure(
        bank="danske",
        year=2024,
        metric="loan_impairment_charges",
        value=-543,
        unit="DKK million",
        page=4,
        quote="| Loan impairment charges | -543 | 262 |",
        label="Loan impairment charges",
    ),
}


class TestKeyFigures:
    @pytest.fixture(autouse=True)
    def table(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(lookup, "get_kpi", lambda bank, metric, year: TABLE.get((bank, metric, year)))

    def test_metrics_are_read_in_english_and_danish(self) -> None:
        assert lookup.asked_metrics("What was Danske Bank's cost/income ratio in 2025?") == ["cost_income_ratio"]
        assert lookup.asked_metrics("Sammenlign Danske Banks og Nordeas nettoresultat for 2024.") == ["net_profit"]
        assert lookup.asked_metrics("How did Nordea's net interest income change?") == []

    def test_a_question_gets_a_row_for_each_bank_and_year_it_names(self) -> None:
        figures = lookup.key_figures_for(
            "What was Danske Bank's cost/income ratio in 2025, and how did it change from 2024?",
        )
        assert [lookup.figure_key(figure) for figure in figures] == [
            "danske-2024-cost_income_ratio",
            "danske-2025-cost_income_ratio",
        ]

    def test_rows_that_failed_a_check_are_left_out(self) -> None:
        figures = lookup.key_figures_for("Compare the net profit of the three banks in 2024.")
        assert [figure.bank for figure in figures] == ["danske", "nordea"]

    def test_no_bank_no_year_or_a_future_year_means_no_rows(self) -> None:
        assert lookup.key_figures_for("What was the cost/income ratio in 2025?") == []
        assert lookup.key_figures_for("What was Danske Bank's cost/income ratio?") == []
        assert lookup.key_figures_for("What net profit does Danske Bank expect for 2026, after 2024?") == []

    def test_a_row_becomes_a_passage_titled_with_its_figure(self) -> None:
        hit = lookup.key_figure_hit(TABLE[("danske", "net_profit", 2024)])
        assert hit.chunk.id == "kpi-danske-2024-net_profit"
        assert (hit.chunk.page, hit.chunk.body) == (4, "| Net profit | 23,629 | 21,262 |")
        assert hit.chunk.heading.endswith("Net profit for 2024 is DKK 23,629 million")

    def test_a_negative_impairment_charge_is_called_a_reversal(self) -> None:
        hit = lookup.key_figure_hit(TABLE[("danske", "loan_impairment_charges", 2024)])
        assert hit.chunk.heading.endswith("is a net reversal of DKK 543 million")

    def test_rows_go_in_front_of_the_search_results(self) -> None:
        searched = [hit(10, "Net profit was DKK 23,629 million.")]
        hits = lookup.with_key_figures("What was Danske Bank's net profit in 2024?", searched)
        assert [found.chunk.id for found in hits] == ["kpi-danske-2024-net_profit", searched[0].chunk.id]
