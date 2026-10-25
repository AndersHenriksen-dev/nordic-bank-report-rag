"""Streamlit front-end: ask a question and see Claude's reasoning, the cited answer and the highlighted report pages.

Run with `make app` or `uv run streamlit run src/bankrag/ui/app.py`. It needs the PDFs in data/raw/ for the page
images, the chunks and vector index from `bankrag ingest`, and ANTHROPIC_API_KEY in .env. Each question costs about
USD 0.001. Saved answers from the trace log are shown again without the API, the key or the search models.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from textwrap import shorten

import streamlit as st

from bankrag.answer import answer, load_traces, log_trace
from bankrag.config import DISCLAIMER, RAW_DIR, Bank, bank_name
from bankrag.figures import figures_in
from bankrag.ingest import load_chunks
from bankrag.models import Answer, Chunk, Source, TracedAnswer
from bankrag.retrieve import DEFAULT_RETRIEVER, Hit, Retriever, build_retriever, routed_search
from bankrag.ui.highlight import HighlightedPage, focus_passage, render_highlighted_page

TOP_K = 6
PASSAGE_WIDTH = 600
EXAMPLES = [
    "What was Danske Bank's cost/income ratio in 2025, and how did it change from 2024?",
    "Compare the CET1 ratio of the three banks at the end of 2025.",
    "How did Nordea's net interest income change from 2024 to 2025, and why?",
    "Which of the three banks mention AI in their 2025 annual reports, and how do they use it?",
    "Hvad var Nordeas egenkapitalforrentning i 2025?",
    "What will Danske Bank's share price be next year?",
]


@dataclass
class Result:
    """What one question produced, kept in the session so it survives Streamlit's reruns."""

    answer: Answer
    hits: list[Hit]
    saved_at: datetime | None = None  # set when the answer was replayed from the trace log


@st.cache_resource(show_spinner="Loading the search index...")
def _retriever() -> Retriever:
    return build_retriever(DEFAULT_RETRIEVER, load_chunks("structure"))


@st.cache_resource(show_spinner="Loading the chunks...")
def _chunks_by_id() -> dict[str, Chunk]:
    return {chunk.id: chunk for chunk in load_chunks("structure")}


@st.cache_data(show_spinner=False)
def _page_images(
    bank: Bank,
    year: int,
    page: int,
    passages: tuple[str, ...],
    focus: frozenset[float],
) -> HighlightedPage | None:
    """Render a cited page with its passages highlighted, or None if the PDF is not downloaded."""
    pdf = RAW_DIR / f"{bank}_{year}.pdf"
    return render_highlighted_page(pdf, page, list(passages), set(focus)) if pdf.exists() else None


def _ask(question: str) -> Result:
    hits = routed_search(_retriever(), question, k=TOP_K)
    result = answer(question, hits)
    log_trace(result)
    return Result(result, hits)


def _replay(traced: TracedAnswer) -> Result:
    """Rebuild a saved answer and the passages its search found, without calling the API or the search models.

    The trace keeps the ids of the retrieved chunks but not their reranker scores, so those show as blank.
    """
    chunks = _chunks_by_id()
    hits = [Hit(chunks[chunk_id], math.nan) for chunk_id in traced.retrieved if chunk_id in chunks]
    return Result(traced, hits, saved_at=traced.time)


def _saved_answers() -> dict[str, TracedAnswer]:
    """Return the latest saved answer to each question in the trace log, newest first."""
    latest = {traced.question: traced for traced in load_traces()}
    return dict(sorted(latest.items(), key=lambda item: item[1].time, reverse=True))


def _markdown(text: str) -> str:
    """Escape dollar signs, which Streamlit would otherwise render as maths."""
    return text.replace("$", r"\$")


def _show_answer(result: Answer) -> None:
    st.subheader("Answer")
    st.markdown(_markdown(result.text))
    latency, cost, tokens, cached = st.columns(4)
    latency.metric("Latency", f"{result.latency_s:.1f} s")
    cost.metric("Cost", f"DKK {result.cost_dkk:.3f}", help=f"USD {result.cost_usd:.5f}")
    tokens.metric("Tokens in / out", f"{result.input_tokens:,} / {result.output_tokens:,}")
    cached.metric("Cached prompt tokens", f"{result.cache_read_tokens:,}")


def _show_thinking(result: Answer) -> None:
    with st.expander("Claude's reasoning", expanded=False):
        if result.thinking:
            st.markdown(_markdown(result.thinking))
        else:
            st.caption("Claude answered this one without extended reasoning.")


def _show_source(source: Source, focus: frozenset[float]) -> None:
    st.caption(source.section)
    for passage in source.cited_text:
        text = " ".join(focus_passage(passage, set(focus)).split())
        st.markdown("> " + _markdown(shorten(text, PASSAGE_WIDTH, placeholder=" ...")))
    images = _page_images(source.bank, source.year, source.page, tuple(source.cited_text), focus)
    if images is None:
        st.warning(f"{bank_name(source.bank)} {source.year} is not in data/raw/, so the page cannot be shown.")
        return
    if images.close_up is None:
        st.caption("The cited passage could not be located on the page, so nothing is highlighted.")
        st.image(images.whole_page, caption=source.label, width="stretch")
        return
    st.image(images.close_up, caption=f"{source.label}, cited passage highlighted")
    with st.expander("Show the whole page"):
        st.image(images.whole_page, caption=source.label, width="stretch")


def _show_sources(result: Answer) -> None:
    st.subheader("Sources")
    if not result.sources:
        st.info("The answer cites no sources.")
        return
    tabs = st.tabs(
        [f"[{source.n}] {bank_name(source.bank)} {source.year}, p. {source.page}" for source in result.sources],
    )
    focus = frozenset(figures_in(result.text))
    for tab, source in zip(tabs, result.sources, strict=True):
        with tab:
            _show_source(source, focus)


def _show_retrieved(hits: list[Hit], sources: list[Source]) -> None:
    cited = {source.chunk_id for source in sources}
    with st.expander(f"What the search found ({len(hits)} passages sent to Claude)"):
        st.dataframe(
            [
                {
                    "Rank": rank,
                    "Report": f"{bank_name(hit.chunk.bank)} {hit.chunk.year}",
                    "Page": hit.chunk.page,
                    "Section": hit.chunk.heading or hit.chunk.section,
                    "Reranker score": None if math.isnan(hit.score) else round(hit.score, 2),
                    "Cited": "yes" if hit.chunk.id in cited else "",
                }
                for rank, hit in enumerate(hits, 1)
            ],
            hide_index=True,
        )


def _sidebar() -> None:
    st.sidebar.header("Try a question")
    for example in EXAMPLES:
        if st.sidebar.button(example, width="stretch"):
            st.session_state["question"] = example
            st.session_state["ask_now"] = True
    saved = _saved_answers()
    if saved:
        st.sidebar.header("Saved answers")
        choice = st.sidebar.selectbox(
            "Show an earlier answer again, without calling the API",
            list(saved),
            index=None,
            placeholder="Pick a question",
        )
        if choice and st.sidebar.button("Show saved answer", width="stretch"):
            st.session_state["result"] = _replay(saved[choice])
    st.sidebar.divider()
    st.sidebar.caption(
        "Six annual reports: Danske Bank, Nordea and Jyske Bank, 2024 and 2025. Search combines BM25 and bge-m3 "
        "vectors over 4,882 chunks, then bge-reranker-v2-m3 picks the best 6; answers come from Claude Haiku 5.5 "
        "with citations.",
    )


def main() -> None:
    """Draw the page: question form, then reasoning, answer, sources and retrieved passages."""
    st.set_page_config(page_title="Nordic Bank Report RAG", layout="wide")
    st.title("Questions over Nordic bank annual reports")
    st.caption(DISCLAIMER)
    _sidebar()

    with st.form("ask"):
        question = st.text_input("Question, in English or Danish", key="question")
        submitted = st.form_submit_button("Ask")
    if (submitted or st.session_state.pop("ask_now", False)) and question.strip():
        with st.spinner("Searching the reports and asking Claude..."):
            try:
                st.session_state["result"] = _ask(question.strip())
            except SystemExit as error:  # raised when no API key is configured
                st.error(str(error))

    result: Result | None = st.session_state.get("result")
    if result is None:
        return
    if result.saved_at:
        st.info(
            f"A saved answer from {result.saved_at:%d %B %Y, %H:%M} UTC, shown again without a new API call. "
            "Cost and latency are from when it was made.",
        )
    _show_thinking(result.answer)
    _show_answer(result.answer)
    _show_sources(result.answer)
    _show_retrieved(result.hits, result.answer.sources)


main()
