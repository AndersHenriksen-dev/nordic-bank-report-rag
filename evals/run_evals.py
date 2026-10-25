"""Run the eval set and write evals/results/*.json, evals/RESULTS.md and evals/ANSWERS.md.

python evals/run_evals.py              # retrieval metrics only, no API key needed
python evals/run_evals.py --answers    # also answer every question with Claude (costs money)
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys
from datetime import date
from pathlib import Path
from textwrap import shorten
from typing import NamedTuple

from pydantic import BaseModel, TypeAdapter, ValidationError

from bankrag.answer import answer, log_trace
from bankrag.config import ANSWER_MODEL, EMBED_MODEL, RERANK_MODEL, bank_name, parse_bank
from bankrag.evaluate import figures_grounded, load_questions, numbers_match, page_key, percentile, retrieval_scores
from bankrag.ingest import load_chunks
from bankrag.models import Question, Source
from bankrag.retrieve import DEFAULT_RETRIEVER, BM25Retriever, Retriever, build_retriever, routed_search

EVAL_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVAL_DIR / "results"
ANSWERS_FILE = RESULTS_DIR / "answers.json"
K_VALUES = (1, 3, 6, 10)
SEARCH_DEPTH = 30  # how far down the ranking MRR looks
PASSAGE_WIDTH = 400  # characters of each cited passage shown in ANSWERS.md
PAGE_KEY_RE = re.compile(r"([a-z]+)-(\d{4})-p(\d+)")


class RetrievalConfig(NamedTuple):
    """One retrieval setup to compare."""

    name: str
    retriever: Retriever
    route: bool
    expand: bool


class RetrievalResult(BaseModel):
    """Recall at each k and MRR for one retrieval setup."""

    config: str
    questions: int
    recall: dict[int, float]
    mrr: float


class AnswerRecord(BaseModel):
    """How one answer scored."""

    id: str
    category: str
    answerable: bool
    refused: bool
    numbers_ok: bool | None
    has_citation: bool
    figures_grounded: bool | None
    cost_usd: float
    latency_s: float
    cache_read_tokens: int
    answer: str
    sources: list[Source]


class AnswerSummary(BaseModel):
    """Answer metrics over the whole eval set."""

    numeric_exact: float | None
    numeric_n: int
    answered_with_citation: float
    figures_grounded: float | None
    figures_grounded_n: int
    false_refusals: int
    unanswerable_refused: int
    unanswerable_n: int
    cost_usd_mean: float
    cost_usd_p95: float
    latency_s_mean: float
    latency_s_p95: float


class AnswerReport(BaseModel):
    """The answers file: when and with which model the answers were made, the summary and every record."""

    run_date: date
    model: str
    retriever: str = "bm25"  # answer runs before the hybrid retriever all used BM25
    summary: AnswerSummary
    records: list[AnswerRecord]


_RETRIEVAL_ADAPTER: TypeAdapter[list[RetrievalResult]] = TypeAdapter(list[RetrievalResult])


def _evaluate_config(config: RetrievalConfig, questions: list[Question]) -> RetrievalResult:
    recalls: dict[int, list[float]] = {k: [] for k in K_VALUES}
    reciprocal_ranks = []
    for question in questions:
        for k in K_VALUES:
            # Search at each k, because routing splits k between banks: the top k of a deeper search is not what the
            # answer model would get.
            hits = routed_search(config.retriever, question.question, k=k, route=config.route, expand=config.expand)
            recalls[k].append(retrieval_scores(question, [page_key(hit.chunk) for hit in hits], k)[0])
        hits = routed_search(
            config.retriever,
            question.question,
            k=SEARCH_DEPTH,
            route=config.route,
            expand=config.expand,
        )
        ranked_pages = list(dict.fromkeys(page_key(hit.chunk) for hit in hits))
        reciprocal_ranks.append(retrieval_scores(question, ranked_pages, SEARCH_DEPTH)[1])
    return RetrievalResult(
        config=config.name,
        questions=len(questions),
        recall={k: statistics.mean(values) for k, values in recalls.items()},
        mrr=statistics.mean(reciprocal_ranks),
    )


def retrieval_eval(questions: list[Question], configs: list[RetrievalConfig]) -> list[RetrievalResult]:
    """Score every retrieval setup on the answerable questions."""
    answerable = [question for question in questions if question.answerable]
    return [_evaluate_config(config, answerable) for config in configs]


def _answer_one(question: Question, retriever: Retriever, k: int) -> AnswerRecord:
    hits = routed_search(retriever, question.question, k=k)
    result = answer(question.question, hits)
    log_trace(result, eval_id=question.id)
    return AnswerRecord(
        id=question.id,
        category=question.category,
        answerable=question.answerable,
        refused=result.refused,
        numbers_ok=numbers_match(question, result.text) if question.answerable else None,
        has_citation=bool(result.sources),
        figures_grounded=figures_grounded(result.text, result.sources) if question.answerable else None,
        cost_usd=result.cost_usd,
        latency_s=result.latency_s,
        cache_read_tokens=result.cache_read_tokens,
        answer=result.text,
        sources=result.sources,
    )


def _share(flags: list[bool]) -> float | None:
    return sum(flags) / len(flags) if flags else None


def _summarize(records: list[AnswerRecord]) -> AnswerSummary:
    answerable = [record for record in records if record.answerable]
    unanswerable = [record for record in records if not record.answerable]
    numeric = [record.numbers_ok for record in answerable if record.numbers_ok is not None]
    grounded = [record.figures_grounded for record in answerable if record.figures_grounded is not None]
    costs = [record.cost_usd for record in records]
    latencies = [record.latency_s for record in records]
    return AnswerSummary(
        numeric_exact=_share(numeric),
        numeric_n=len(numeric),
        answered_with_citation=_share([r.has_citation and not r.refused for r in answerable]) or 0.0,
        figures_grounded=_share(grounded),
        figures_grounded_n=len(grounded),
        false_refusals=sum(record.refused for record in answerable),
        unanswerable_refused=sum(record.refused for record in unanswerable),
        unanswerable_n=len(unanswerable),
        cost_usd_mean=statistics.mean(costs),
        cost_usd_p95=percentile(costs, 95),
        latency_s_mean=statistics.mean(latencies),
        latency_s_p95=percentile(latencies, 95),
    )


def answer_eval(questions: list[Question], retriever: Retriever, k: int) -> tuple[list[AnswerRecord], AnswerSummary]:
    """Answer every question with Claude and score the answers. Calls the paid API once per question."""
    records = []
    for question in questions:
        record = _answer_one(question, retriever, k)
        status = "REFUSED" if record.refused else ("ok" if record.numbers_ok in (True, None) else "WRONG NUMBER")
        print(f"  {record.id} {status:12s} {record.latency_s:4.1f}s  {record.answer[:90]!r}")
        records.append(record)
    return records, _summarize(records)


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def write_results_md(retrieval: list[RetrievalResult], report: AnswerReport | None, n_questions: int) -> None:
    """Write evals/RESULTS.md from the latest retrieval results and the last answer run."""
    lines = [
        "# Eval results",
        "",
        f"Generated by `evals/run_evals.py` on {date.today().isoformat()} over {n_questions} questions.",
        "Do not edit by hand.",
        "",
        "## Retrieval",
        "",
        "Recall@k: share of a question's evidence groups (one per bank or year it needs) with a gold page",
        "among the top k chunks, averaged over answerable questions. MRR: mean reciprocal rank of the first",
        "gold page in the top 30. Routed: search only the banks and years the question names.",
        "Danish glossary: add English report wording for Danish finance terms. Dense: cosine similarity of",
        f"`{EMBED_MODEL}` embeddings in Qdrant. Hybrid: reciprocal rank fusion of BM25 and dense. Reranker:",
        f"`{RERANK_MODEL}` reorders the hybrid top 30.",
        "",
        "| Config | " + " | ".join(f"Recall@{k}" for k in K_VALUES) + " | MRR |",
        "|---|" + "---|" * (len(K_VALUES) + 1),
    ]
    for result in retrieval:
        cells = " | ".join(f"{result.recall[k]:.2f}" for k in K_VALUES)
        lines.append(f"| {result.config} | {cells} | {result.mrr:.2f} |")
    if report:
        answers = report.summary
        lines += [
            "",
            "## Answers",
            "",
            f"From the last answer run on {report.run_date.isoformat()} with `{report.model}` and the "
            f"`{report.retriever}` retriever. Every question and",
            "answer, with the passages it cites, is in [ANSWERS.md](ANSWERS.md).",
            "",
            "| Metric | Value |",
            "|---|---|",
            f"| Numeric answers exact | {_percent(answers.numeric_exact)} of {answers.numeric_n} |",
            f"| Answerable questions answered with a citation | {_percent(answers.answered_with_citation)} |",
            f"| Answers whose figures all appear in a cited passage | {_percent(answers.figures_grounded)} of "
            f"{answers.figures_grounded_n} |",
            f"| Answerable questions wrongly refused | {answers.false_refusals} |",
            f"| Unanswerable questions refused | {answers.unanswerable_refused} of {answers.unanswerable_n} |",
            f"| Cost per question, mean / p95 (USD) | {answers.cost_usd_mean:.5f} / {answers.cost_usd_p95:.5f} |",
            f"| Latency per question, mean / p95 (s) | {answers.latency_s_mean:.1f} / {answers.latency_s_p95:.1f} |",
        ]
    (EVAL_DIR / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _yes_no(value: bool | None) -> str:
    return "n/a" if value is None else ("yes" if value else "no")


def _page_label(key: str) -> str:
    """Turn an evidence key like "danske-2025-p4" into "Danske Bank 2025 p. 4"."""
    match = PAGE_KEY_RE.fullmatch(key)
    if not match:
        return key
    return f"{bank_name(parse_bank(match.group(1)))} {match.group(2)} p. {match.group(3)}"


def _passage(source: Source) -> str:
    return shorten(" ".join(" ".join(source.cited_text).split()), PASSAGE_WIDTH, placeholder=" ...")


def _question_section(question: Question, record: AnswerRecord) -> list[str]:
    gold_pages = "; ".join(" or ".join(_page_label(key) for key in group) for group in question.evidence)
    lines = [
        f"## {question.id}",  # only the id, so the summary table can link to "#q01"
        "",
        f"**Question:** {question.question}",
        "",
        f"Category: {question.category}. Language: {question.lang}. "
        f"Gold answer checked by hand: {_yes_no(question.verified)}.",
        "",
        f"**Gold answer:** {question.gold_answer}",
        "",
    ]
    if gold_pages:
        lines += [f"**Gold pages:** {gold_pages}", ""]
    lines += [f"**Answer** ({record.latency_s:.1f} s, USD {record.cost_usd:.5f}):", ""]
    lines += [f"> {line}" if line.strip() else ">" for line in record.answer.splitlines()]
    lines += ["", "**Sources:**", ""]
    lines += [f'{source.n}. {source.label}, {source.section}: "{_passage(source)}"' for source in record.sources]
    if not record.sources:
        lines.append("None.")
    lines += [
        "",
        f"**Checks:** figures exact: {_yes_no(record.numbers_ok)}. Figures in cited passages: "
        f"{_yes_no(record.figures_grounded)}. Refused: {_yes_no(record.refused)}.",
        "",
    ]
    return lines


def write_answers_md(questions: list[Question], report: AnswerReport) -> None:
    """Write evals/ANSWERS.md: every question with its gold answer, the system's answer and the cited passages."""
    records = {record.id: record for record in report.records}
    asked = [question for question in questions if question.id in records]
    lines = [
        "# Questions and answers",
        "",
        f"Every eval question with its gold answer and the system's answer from the last answer run on "
        f"{report.run_date.isoformat()} with `{report.model}`. Generated by `evals/run_evals.py`; do not edit by hand.",
        "",
        "Answers are shown as the system returned them, with citation markers like [1]. Each source gives the page",
        "and the start of the passage Claude cited. Page numbers are PDF page numbers. Gold answers are drafts",
        "until checked by hand against the PDFs. The reports are listed in [docs/documents.md](../docs/documents.md).",
        "",
        "| ID | Category | Question | Figures exact | Figures in cited passages | Refused |",
        "|---|---|---|---|---|---|",
    ]
    for question in asked:
        record = records[question.id]
        lines.append(
            f"| [{question.id}](#{question.id}) | {question.category} | {question.question} | "
            f"{_yes_no(record.numbers_ok)} | {_yes_no(record.figures_grounded)} | {_yes_no(record.refused)} |",
        )
    lines.append("")
    for question in asked:
        lines += _question_section(question, records[question.id])
    (EVAL_DIR / "ANSWERS.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def _load_last_answers() -> AnswerReport | None:
    """Load the last answer run, so a retrieval-only run keeps its results in RESULTS.md."""
    if not ANSWERS_FILE.exists():
        return None
    try:
        return AnswerReport.model_validate_json(ANSWERS_FILE.read_text(encoding="utf-8"))
    except ValidationError:
        print(f"{ANSWERS_FILE} has an older format; run with --answers to refresh it.")
        return None


def main() -> int:
    """Run the retrieval evals, and the answer evals if asked, then write the results."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to a code page without "æøå"
    parser = argparse.ArgumentParser()
    parser.add_argument("--answers", action="store_true", help="also run the answer evals (needs an API key)")
    parser.add_argument("--k", type=int, default=6, help="chunks passed to the answer model")
    args = parser.parse_args()

    questions = load_questions(EVAL_DIR / "questions.yaml")
    chunks = load_chunks("structure")
    bm25 = BM25Retriever(chunks)
    dense = build_retriever("dense", chunks)
    best = build_retriever(DEFAULT_RETRIEVER, chunks)
    configs = [
        RetrievalConfig("BM25, fixed chunks", BM25Retriever(load_chunks("fixed")), route=False, expand=False),
        RetrievalConfig("BM25, structure chunks", bm25, route=False, expand=False),
        RetrievalConfig("BM25, structure chunks, routed", bm25, route=True, expand=False),
        RetrievalConfig("BM25, structure chunks, routed, Danish glossary", bm25, route=True, expand=True),
        RetrievalConfig("Dense, routed", dense, route=True, expand=False),
        RetrievalConfig("Dense, routed, Danish glossary", dense, route=True, expand=True),
        RetrievalConfig("Hybrid, routed, Danish glossary", build_retriever("hybrid", chunks), route=True, expand=True),
        RetrievalConfig("Hybrid + reranker, routed, Danish glossary", best, route=True, expand=True),
    ]
    retrieval = retrieval_eval(questions, configs)
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "retrieval.json").write_bytes(_RETRIEVAL_ADAPTER.dump_json(retrieval, indent=2) + b"\n")
    for result in retrieval:
        recalls = "  ".join(f"R@{k} {result.recall[k]:.2f}" for k in K_VALUES)
        print(f"{result.config:50s} {recalls}  MRR {result.mrr:.2f}")

    report = _load_last_answers()
    if args.answers:
        print("\nanswering...")
        records, summary = answer_eval(questions, best, args.k)
        report = AnswerReport(
            run_date=date.today(),
            model=ANSWER_MODEL,
            retriever=DEFAULT_RETRIEVER,
            summary=summary,
            records=records,
        )
        ANSWERS_FILE.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")
        print(summary.model_dump_json(indent=2))

    write_results_md(retrieval, report, len(questions))
    if report:
        write_answers_md(questions, report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
