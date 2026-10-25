---
name: run-evals-and-report
description: Run the eval suite, compare it with the last committed results, explain every change down to the questions behind it, and update the docs that quote the numbers. Use after any change to parsing, chunking, search, prompts or the eval set, or when asked for the current results.
---

# Run the evals and report

The numbers in the README, `docs/experiments.md` and `docs/decisions.md` must always match `evals/RESULTS.md`, and every change in them must have an explanation that names the questions behind it. This skill is the procedure that keeps them so. It was written down after doing it by hand for every change from the hybrid search to the twelve reports.

## 1. Run what is free

```bash
uv run python evals/run_evals.py
```

Retrieval only: no API calls, a few minutes on a GPU. It rewrites `evals/RESULTS.md`, its charts and `evals/results/retrieval.json`, and regenerates `evals/ANSWERS.md` from the last answer run. Qdrant allows one process at a time, so stop the web page and the MCP server first.

**Never add `--answers` without asking Anders first.** It answers all 44 questions with Claude and grades them with the judge: about USD 0.05 per run. Say the cost when asking.

## 2. Compare with the last committed results

```bash
git diff evals/RESULTS.md evals/results/retrieval.json evals/ANSWERS.md
```

`ANSWERS.md` changes without an answer run only when a gold answer or the display of answers changed; check that is all it is.

## 3. Find the questions behind every change

```bash
uv run python scripts/retrieval_by_question.py --misses
uv run python scripts/retrieval_by_question.py --ids q01,q12 --k 10
```

Compare with the same command on the previous commit if needed (`git stash`, rerun, `git stash pop`). For each question that changed, say why. Typical causes so far:

- a page outside the gold lists now ranks higher (marked `*`);
- BM25 term statistics shift when the corpus changes, even inside routed reports;
- a question without a year reaches another year's report.

## 4. Check unexpected pages before touching a gold list

A page marked `*` may hold the answer. Check it in the page text, never on trust:

```bash
uv run python scripts/find_pages.py "cost/income|45\.5" --report danske_2025 --pages 35
```

If it holds the answer, add it with the `add-eval-case` skill and note the change at the top of `evals/questions.yaml`. If not, it is a real miss: leave the gold list alone.

## 5. After a paid answer run

Read every failed check and every failed judge verdict, not just the totals. The `eval-reviewer` agent (`.claude/agents/eval-reviewer.md`) sorts each failure into retrieval, parsing, generation, gold answer or judge. Verify its findings before they go into a doc.

## 6. Update the docs that quote numbers

- `README.md`: the headline results and the "What I tried" table.
- `docs/experiments.md`: a new section or table row for the change. Keep earlier tables as they were measured; they are the history.
- `docs/decisions.md`: only if a design choice changed.
- `docs/BUILD_LOG.md`: one row for the session.
- Never edit `evals/RESULTS.md` or `evals/ANSWERS.md` by hand; they are generated.

## 7. Report

Before and after for each metric, the questions behind each change with their cause, what was checked in the page text, and what any paid run cost.
