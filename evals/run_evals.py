"""Run the eval set and write evals/results/*.json, evals/RESULTS.md and evals/ANSWERS.md.

python evals/run_evals.py              # retrieval metrics only, no API key needed
python evals/run_evals.py --answers    # also answer every question with Claude and grade the answers (costs money)
"""

from __future__ import annotations

import argparse
import io
import re
import statistics
import sys
from datetime import date
from pathlib import Path
from textwrap import shorten
from typing import NamedTuple

import matplotlib as mpl
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from pydantic import BaseModel, TypeAdapter, ValidationError

from bankrag.answer import answer, log_trace, mark_quotes
from bankrag.config import ANSWER_MODEL, EMBED_MODEL, JUDGE_MODEL, RERANK_MODEL, bank_name, parse_bank
from bankrag.evaluate import figures_grounded, load_questions, numbers_match, page_key, percentile, retrieval_scores
from bankrag.ingest import load_chunks
from bankrag.judge import judge
from bankrag.models import Question, Source, Verdict
from bankrag.retrieve import DEFAULT_RETRIEVER, BM25Retriever, Retriever, build_retriever, routed_search

EVAL_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVAL_DIR / "results"
ANSWERS_FILE = RESULTS_DIR / "answers.json"
K_VALUES = (1, 3, 6, 10)
SEARCH_DEPTH = 30  # how far down the ranking MRR looks
PASSAGE_WIDTH = 400  # characters of each cited passage shown in ANSWERS.md
PAGE_KEY_RE = re.compile(r"([a-z]+)-(\d{4})-p(\d+)")
CHART_K = (1, 3, 6)
LIGHT_CHART = "retrieval-light.svg"
DARK_CHART = "retrieval-dark.svg"


class ChartTheme(NamedTuple):
    """Colours for one GitHub theme, from the reference data-viz palette (series: its first three categorical slots)."""

    series: tuple[str, str, str]  # recall@1, @3, @6
    ink: str
    secondary: str
    grid: str
    line: str
    surface: str  # GitHub's page background, for the ring around each dot


CHART_THEMES = {
    LIGHT_CHART: ChartTheme(("#2a78d6", "#eb6834", "#1baf7a"), "#0b0b0b", "#52514e", "#e1e0d9", "#c3c2b7", "#ffffff"),
    DARK_CHART: ChartTheme(("#3987e5", "#d95926", "#199e70"), "#f0efec", "#c3c2b7", "#2c2c2a", "#383835", "#0d1117"),
}


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
    judge: Verdict | None = None  # None for refusals, unanswerable questions and runs before the judge existed
    judge_cost_usd: float = 0.0


class JudgeSummary(BaseModel):
    """How the LLM judge graded the answers it read: every answerable question that was not refused."""

    n: int
    passed: float
    correct: float
    complete: float
    consistent: float
    why_n: int
    why_passed: float | None
    cost_usd: float


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
    judge: JudgeSummary | None = None


class AnswerReport(BaseModel):
    """The answers file: when and with which model the answers were made, the summary and every record."""

    run_date: date
    model: str
    retriever: str = "bm25"  # answer runs before the hybrid retriever all used BM25
    judge_model: str | None = None
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
    verdict, judge_cost = None, 0.0
    if question.answerable and not result.refused:
        try:
            verdict, judge_cost = judge(question, result.text)
        except RuntimeError as error:
            print(f"  {error}")
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
        judge=verdict,
        judge_cost_usd=judge_cost,
    )


def _share(flags: list[bool]) -> float | None:
    return sum(flags) / len(flags) if flags else None


def _summarize_judge(records: list[AnswerRecord]) -> JudgeSummary | None:
    verdicts = [record.judge for record in records if record.judge]
    if not verdicts:
        return None
    why = [record.judge.passed for record in records if record.judge and record.category == "why"]
    return JudgeSummary(
        n=len(verdicts),
        passed=statistics.mean(verdict.passed for verdict in verdicts),
        correct=statistics.mean(verdict.correct for verdict in verdicts),
        complete=statistics.mean(verdict.complete for verdict in verdicts),
        consistent=statistics.mean(verdict.consistent for verdict in verdicts),
        why_n=len(why),
        why_passed=_share(why),
        cost_usd=sum(record.judge_cost_usd for record in records),
    )


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
        judge=_summarize_judge(records),
    )


def answer_eval(questions: list[Question], retriever: Retriever, k: int) -> tuple[list[AnswerRecord], AnswerSummary]:
    """Answer every question with Claude and score the answers.

    Calls the paid API once per question, and once more per answer the judge grades.
    """
    records = []
    for question in questions:
        record = _answer_one(question, retriever, k)
        status = "REFUSED" if record.refused else ("ok" if record.numbers_ok in (True, None) else "WRONG NUMBER")
        verdict = "" if record.judge is None else ("judge pass" if record.judge.passed else "JUDGE FAIL")
        print(f"  {record.id} {status:12s} {verdict:10s} {record.latency_s:4.1f}s  {record.answer[:80]!r}")
        records.append(record)
    return records, _summarize(records)


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _judge_rows(judged: JudgeSummary, model: str) -> list[str]:
    """Return the judge's rows of the answer table and a note on how it grades."""
    criteria = " / ".join(_percent(share) for share in (judged.correct, judged.complete, judged.consistent))
    return [
        f"| Answers the judge passed (correct, complete and consistent) | {_percent(judged.passed)} of {judged.n} |",
        f'| "Why" answers the judge passed | {_percent(judged.why_passed)} of {judged.why_n} |',
        f"| Judge criteria met: correct / complete / consistent | {criteria} |",
        f"| Judge cost for the whole run (USD) | {judged.cost_usd:.4f} |",
        "",
        f"The judge (`{model}`) grades every answered question against its gold answer, by the rubric in",
        "[judge_rubric.md](judge_rubric.md). Refusals are not judged; they are counted above.",
    ]


def _draw_retrieval_chart(retrieval: list[RetrievalResult], theme: ChartTheme) -> Figure:
    """Draw one row per search setup with a dot for each recall@k, and label the recall@6 the answer model sees."""
    figure = Figure(figsize=(8, 1.4 + 0.42 * len(retrieval)))
    figure.patch.set_alpha(0)
    axes = figure.add_axes((0.36, 0.12, 0.6, 0.66))
    axes.set_facecolor("none")
    rows = range(len(retrieval), 0, -1)  # first setup at the top, as in the table
    for row, result in zip(rows, retrieval, strict=True):
        values = [result.recall[k] for k in CHART_K]
        axes.plot([min(values), max(values)], [row, row], color=theme.line, linewidth=1.5, zorder=1)
        for value, color in zip(values, theme.series, strict=True):
            axes.plot(value, row, "o", markersize=7, color=color, markeredgecolor=theme.surface, markeredgewidth=1.5)
        axes.annotate(
            f"{values[-1]:.2f}",
            (values[-1], row),
            xytext=(8, 0),
            textcoords="offset points",
            va="center",
            color=theme.secondary,
            fontsize=9,
        )
    axes.set_xlim(0, 1.08)
    axes.set_ylim(0.4, len(retrieval) + 0.6)
    axes.set_xticks([0, 0.25, 0.5, 0.75, 1.0], ["0", "0.25", "0.5", "0.75", "1"])
    axes.set_yticks(list(rows), [result.config for result in retrieval])
    axes.tick_params(colors=theme.secondary, labelsize=9, length=0)
    axes.grid(axis="x", color=theme.grid, linewidth=0.75)
    axes.set_axisbelow(True)
    for spine in axes.spines.values():
        spine.set_visible(False)
    handles = [
        Line2D([], [], marker="o", linestyle="", markersize=7, color=color, markeredgecolor=theme.surface)
        for color in theme.series
    ]
    axes.legend(
        handles,
        [f"Recall@{k}" for k in CHART_K],
        loc="lower left",
        bbox_to_anchor=(0, 1.0),
        ncol=len(CHART_K),
        frameon=False,
        labelcolor=theme.ink,
        fontsize=9,
        handletextpad=0.3,
        columnspacing=1.2,
    )
    title = "Share of the needed evidence in the top k passages"
    figure.text(0.02, 0.96, title, color=theme.ink, fontsize=12, va="top")
    figure.text(
        0.02,
        0.96 - 0.3 / figure.get_figheight(),
        f"{retrieval[0].questions} answerable eval questions. Claude reads the top 6.",
        color=theme.secondary,
        fontsize=9,
        va="top",
    )
    return figure


def write_retrieval_chart(retrieval: list[RetrievalResult]) -> None:
    """Write the retrieval chart as SVG for GitHub's light and dark themes; RESULTS.md shows the matching one.

    A fixed hash salt and no date keep the files identical between runs with the same numbers, so they only show up
    in a diff when the results change. Lines end in a bare line feed with no trailing spaces, as the pre-commit hooks
    require; matplotlib's own file output uses the platform's line endings.
    """
    with mpl.rc_context({"svg.hashsalt": "bankrag"}):
        for filename, theme in CHART_THEMES.items():
            buffer = io.StringIO()
            _draw_retrieval_chart(retrieval, theme).savefig(
                buffer,
                format="svg",
                metadata={"Date": None},
                bbox_inches="tight",  # fit the longest setup name
                pad_inches=0.15,
            )
            svg = "".join(line.rstrip() + "\n" for line in buffer.getvalue().splitlines())
            (RESULTS_DIR / filename).write_text(svg, encoding="utf-8", newline="\n")


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
    best = max(retrieval, key=lambda result: result.recall[6])
    alt = (
        f"Dot plot of recall@1, @3 and @6 for each search setup. The highest recall@6 is {best.recall[6]:.2f}, "
        f"for {best.config}."
    )
    lines += [
        "",
        "<picture>",
        f'  <source media="(prefers-color-scheme: dark)" srcset="results/{DARK_CHART}">',
        f'  <img alt="{alt}" src="results/{LIGHT_CHART}" width="760">',
        "</picture>",
    ]
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
        if answers.judge:
            lines += _judge_rows(answers.judge, report.judge_model or JUDGE_MODEL)
    (EVAL_DIR / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _yes_no(value: bool | None) -> str:
    return "n/a" if value is None else ("yes" if value else "no")


def _verdict(verdict: Verdict | None) -> str:
    return "n/a" if verdict is None else ("pass" if verdict.passed else "fail")


def _page_label(key: str) -> str:
    """Turn an evidence key like "danske-2025-p4" into "Danske Bank 2025 p. 4"."""
    match = PAGE_KEY_RE.fullmatch(key)
    if not match:
        return key
    return f"{bank_name(parse_bank(match.group(1)))} {match.group(2)} p. {match.group(3)}"


def _passage(source: Source) -> str:
    return shorten(" ".join(" ".join(source.cited_text).split()), PASSAGE_WIDTH, placeholder=" ...")


def _question_section(question: Question, record: AnswerRecord, bodies: dict[str, str]) -> list[str]:
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
    shown = mark_quotes(record.answer, record.sources, bodies)
    lines += [f"> {line}" if line.strip() else ">" for line in shown.splitlines()]
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
    if record.judge:
        lines += [
            f"**Judge:** {_verdict(record.judge)}. Correct: {_yes_no(record.judge.correct)}. "
            f"Complete: {_yes_no(record.judge.complete)}. Consistent: {_yes_no(record.judge.consistent)}. "
            f"{record.judge.reason}",
            "",
        ]
    return lines


def write_answers_md(questions: list[Question], report: AnswerReport, bodies: dict[str, str]) -> None:
    """Write evals/ANSWERS.md: every question with its gold answer, the system's answer and the cited passages."""
    records = {record.id: record for record in report.records}
    asked = [question for question in questions if question.id in records]
    lines = [
        "# Questions and answers",
        "",
        f"Every eval question with its gold answer and the system's answer from the last answer run on "
        f"{report.run_date.isoformat()} with `{report.model}`. Generated by `evals/run_evals.py`; do not edit by hand.",
        "",
        "Answers are shown as the web page shows them: citation markers like [1], and text Claude copied word for word",
        "from a source in quotation marks. Each source gives the page and the start of the passage Claude cited. Page",
        "numbers are PDF page numbers. Gold answers are drafts until checked by hand against the PDFs. The reports are",
        "listed in [docs/documents.md](../docs/documents.md).",
        "",
        "| ID | Category | Question | Figures exact | Figures in cited passages | Refused | Judge |",
        "|---|---|---|---|---|---|---|",
    ]
    for question in asked:
        record = records[question.id]
        lines.append(
            f"| [{question.id}](#{question.id}) | {question.category} | {question.question} | "
            f"{_yes_no(record.numbers_ok)} | {_yes_no(record.figures_grounded)} | {_yes_no(record.refused)} | "
            f"{_verdict(record.judge)} |",
        )
    lines.append("")
    for question in asked:
        lines += _question_section(question, records[question.id], bodies)
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
            judge_model=JUDGE_MODEL,
            summary=summary,
            records=records,
        )
        ANSWERS_FILE.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")
        print(summary.model_dump_json(indent=2))

    write_retrieval_chart(retrieval)
    write_results_md(retrieval, report, len(questions))
    if report:
        write_answers_md(questions, report, {chunk.id: chunk.body for chunk in chunks})
    return 0


if __name__ == "__main__":
    sys.exit(main())
