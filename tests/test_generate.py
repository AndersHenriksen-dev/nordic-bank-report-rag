"""Tests for turning chunks into citable search results, Claude's citations into numbered sources, and the trace log.

No API call is made: responses are built from the SDK's own `Message` model.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from anthropic.types import Message

from bankrag.answer import generate
from bankrag.answer.generate import (
    is_refusal,
    mark_quotes,
    render_with_citations,
    search_result_block,
    thinking_summary,
)
from bankrag.models import Answer, Chunk, Source
from bankrag.retrieve import Hit


def hit(page: int, body: str) -> Hit:
    chunk = Chunk(
        id=f"nordea-2025-p{page:03d}-c00",
        bank="nordea",
        year=2025,
        page=page,
        section="Board of Directors' report",
        heading="Financial review 2025",
        text=body,
        body=body,
        has_table=False,
    )
    return Hit(chunk, 1.0)


def message(content: list[dict[str, object]]) -> Message:
    return Message.model_validate(
        {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "claude-haiku-5-5",
            "content": content,
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        },
    )


def citation(index: int, cited_text: str) -> dict[str, object]:
    return {
        "type": "search_result_location",
        "cited_text": cited_text,
        "source": "nordea-2025-p40",
        "title": "Nordea",
        "search_result_index": index,
        "start_block_index": 0,
        "end_block_index": 1,
    }


def test_search_result_block_splits_paragraphs_and_names_the_page() -> None:
    block = search_result_block(hit(40, "Return on equity was 15.5%.\n\nCET1 ratio was 15.7%."))
    assert block["title"] == "Nordea, Annual Report 2025, page 40, Financial review 2025"
    assert [part["text"] for part in block["content"]] == ["Return on equity was 15.5%.", "CET1 ratio was 15.7%."]
    assert block["citations"] == {"enabled": True}


def test_render_numbers_sources_in_order_of_first_citation() -> None:
    hits = [hit(5, "a"), hit(40, "b")]
    response = message(
        [
            {"type": "text", "text": "Return on equity was 15.5%", "citations": [citation(1, "RoE 15.5%")]},
            {"type": "text", "text": " and CET1 was 15.7%", "citations": [citation(0, "CET1 15.7%")]},
            {"type": "text", "text": ".", "citations": None},
        ],
    )

    text, sources = render_with_citations(response, hits)

    assert text == "Return on equity was 15.5% [1] and CET1 was 15.7% [2]."
    assert [(source.n, source.page) for source in sources] == [(1, 40), (2, 5)]
    assert sources[0].cited_text == ["RoE 15.5%"]


def test_render_ignores_citations_outside_the_hits() -> None:
    response = message([{"type": "text", "text": "Something", "citations": [citation(7, "x")]}])
    text, sources = render_with_citations(response, [hit(40, "a")])
    assert text == "Something"
    assert sources == []


def test_is_refusal_ignores_case_and_markdown() -> None:
    assert is_refusal("Not in the documents. The reports do not forecast share prices.")
    assert is_refusal("**Not in the documents.** This system only reports what the reports say.")
    assert is_refusal("Ikke i dokumenterne. Rapporterne nævner ikke udbyttet for 2027.")
    assert not is_refusal("Danske Bank's cost/income ratio was 45.5% in 2025.")


def test_cited_quotes_stay_inline_after_own_words() -> None:
    hits = [hit(40, "a")]
    response = message(
        [
            {"type": "text", "text": "Nordeas egenkapitalforrentning var 15,5 % i 2025: ", "citations": None},
            {"type": "text", "text": "Return on equity was 15.5% (16.7%).", "citations": [citation(0, "RoE")]},
        ],
    )

    text, _ = render_with_citations(response, hits)

    assert text == "Nordeas egenkapitalforrentning var 15,5 % i 2025: Return on equity was 15.5% (16.7%). [1]"


def test_space_is_added_where_a_cited_block_follows_a_full_stop() -> None:
    response = message(
        [
            {"type": "text", "text": "Egenkapitalforrentningen var 15,5 %.", "citations": None},
            {"type": "text", "text": "Return on equity was 15.5%.", "citations": [citation(0, "RoE")]},
        ],
    )
    text, _ = render_with_citations(response, [hit(40, "a")])
    assert text == "Egenkapitalforrentningen var 15,5 %. Return on equity was 15.5%. [1]"


def test_thinking_summary_joins_thinking_blocks_only() -> None:
    response = message(
        [
            {"type": "thinking", "thinking": "The 2025 table gives 15.5%.", "signature": "s"},
            {"type": "text", "text": "Return on equity was 15.5%.", "citations": None},
        ],
    )
    assert thinking_summary(response) == "The 2025 table gives 15.5%."


def saved_answer(text: str) -> Answer:
    return Answer(
        question="What was Nordea's return on equity in 2025?",
        text=text,
        thinking="The financial review gives 15.5%.",
        sources=[],
        refused=False,
        model="claude-haiku-5-5",
        input_tokens=100,
        output_tokens=20,
        cache_read_tokens=0,
        cache_write_tokens=0,
        cost_usd=0.001,
        latency_s=3.0,
        retrieved=["nordea-2025-p040-c03"],
    )


class TestTraceLog:
    @pytest.fixture(autouse=True)
    def trace_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        path = tmp_path / "traces" / "answers.jsonl"
        monkeypatch.setattr(generate, "TRACE_FILE", path)
        return path

    def test_answers_come_back_as_they_were_logged(self) -> None:
        generate.log_trace(saved_answer("Return on equity was 15.5%."), eval_id="q05")
        generate.log_trace(saved_answer("15.5%."))
        traces = generate.load_traces()
        assert [traced.text for traced in traces] == ["Return on equity was 15.5%.", "15.5%."]
        assert [traced.eval_id for traced in traces] == ["q05", None]
        assert traces[0].thinking == "The financial review gives 15.5%."
        assert traces[0].retrieved == ["nordea-2025-p040-c03"]

    def test_unreadable_lines_are_skipped(self, trace_file: Path) -> None:
        generate.log_trace(saved_answer("Return on equity was 15.5%."))
        with trace_file.open("a", encoding="utf-8") as trace:
            trace.write('{"question": "cut off by a cra\n')
        generate.log_trace(saved_answer("15.5%."))
        assert [traced.text for traced in generate.load_traces()] == ["Return on equity was 15.5%.", "15.5%."]

    def test_no_log_means_no_answers(self) -> None:
        assert generate.load_traces() == []


OPEN, CLOSE = chr(0x201C), chr(0x201D)  # the quotation marks mark_quotes adds
SOFT_HYPHEN = chr(0xAD)
NORDEA_P40 = (
    "Capital position The CET1 capital ratio was 15.7% at the end of 2025 (15.8% last year), while CET1 capital was "
    "EUR 25.1bn (EUR 24.6bn last year).\n\nNet interest income decreased by 6%, mainly driven by lower deposit "
    f"margins as interest rates were down follow{SOFT_HYPHEN} ing policy rate reductions."
)


def cited(text: str, *cited_text: str) -> str:
    source = Source(n=1, chunk_id="nordea-2025-p040-c03", bank="nordea", year=2025, page=40, section="Financial review")
    source.cited_text.extend(cited_text)
    return mark_quotes(text, [source], {"nordea-2025-p040-c03": NORDEA_P40})


class TestMarkQuotes:
    def test_quote_run_on_from_own_words_gets_a_colon(self) -> None:
        text = "It was 15.7%, down from 15.8% a year earlier The CET1 capital ratio was 15.7% at the end of 2025. [1]"
        assert cited(text, "The CET1 capital ratio was 15.7%") == (
            f"It was 15.7%, down from 15.8% a year earlier: {OPEN}The CET1 capital ratio was 15.7% at the end of "
            f"2025.{CLOSE} [1]"
        )

    def test_quote_after_a_full_stop_needs_no_colon(self) -> None:
        text = "The ratio fell. The CET1 capital ratio was 15.7% at the end of 2025. [1]"
        assert cited(text) == f"The ratio fell. {OPEN}The CET1 capital ratio was 15.7% at the end of 2025.{CLOSE} [1]"

    def test_quote_that_continues_a_sentence_keeps_it(self) -> None:
        text = "Its ratio stood at 15.7% at the end of 2025 (15.8% last year). [1]"
        assert cited(text) == f"Its ratio stood at {OPEN}15.7% at the end of 2025 (15.8% last year).{CLOSE} [1]"

    def test_quote_matches_despite_soft_hyphens(self) -> None:
        text = (
            "Margins fell Net interest income decreased by 6%, mainly driven by lower deposit margins as interest "
            "rates were down following policy rate reductions. [1]"
        )
        assert cited(text).startswith(f"Margins fell: {OPEN}Net interest income decreased")

    def test_table_row_quote_loses_its_outer_bars(self) -> None:
        source = Source(n=1, chunk_id="c", bank="nordea", year=2025, page=40, section="Financial review")
        bodies = {"c": "| EURm | 2025 | 2024 | Chg % |\n| Net interest income | 7,167 | 7,594 | -6 |"}
        text = "It fell 6% | Net interest income | 7,167 | 7,594 | -6 | [1]."
        assert (
            mark_quotes(text, [source], bodies)
            == f"It fell 6%: {OPEN}Net interest income | 7,167 | 7,594 | -6{CLOSE} [1]."
        )

    def test_own_words_and_short_overlaps_stay_as_they_are(self) -> None:
        assert (
            cited("Nordea's CET1 ratio fell slightly to 15.7%. [1]")
            == "Nordea's CET1 ratio fell slightly to 15.7%. [1]"
        )

    def test_text_without_citations_is_unchanged(self) -> None:
        assert cited("Not in the documents.") == "Not in the documents."
