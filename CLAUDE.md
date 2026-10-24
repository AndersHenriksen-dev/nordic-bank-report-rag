# CLAUDE.md

Question answering over the 2024 and 2025 annual reports of Danske Bank, Nordea and Jyske Bank, with page citations and evals. Public portfolio repo: everything here is read by recruiters.

## Run things

```bash
uv sync                                  # install
uv run python scripts/download.py        # fetch PDFs into data/raw/ (Jyske Bank: download by hand, see script output)
uv run bankrag ingest                    # parse PDFs, write data/processed/
uv run bankrag search "question"         # show retrieved chunks, no API key needed
uv run bankrag ask "question"            # answer with citations, needs ANTHROPIC_API_KEY in .env
uv run python evals/run_evals.py         # retrieval evals, no API key needed
uv run python evals/run_evals.py --answers   # full evals, costs money: ask first
uv run pytest && uv run ruff check .     # tests and lint
```

The `make` targets wrap the same commands.

## Rules

- Every new feature needs an eval case in `evals/questions.yaml`, with the gold answer and source page checked against the PDF.
- Never commit data or keys: `data/`, PDFs and `.env` are git-ignored. Never read `.env`.
- Page numbers are PDF page numbers (1-based), not the printed page labels.
- Run `run_evals.py --answers` only when asked: it calls the paid API.
- Nothing from Anders's current or past employers goes in this repo. The banks appear only as the public subjects of their reports.
- The system must refuse forecasts, recommendations and investment advice. Keep the disclaimer in the README and the UI.
- Update `docs/BUILD_LOG.md` at the end of each session: date, hours, what was built, what Claude Code did, what Anders decided.
- Record design choices and their reasons in `docs/decisions.md`.

## Style

- Python 3.11+, type hints, ruff (config in `pyproject.toml`), pytest.
- Never use em dashes anywhere: README, docs, comments, commit messages. Use commas, colons, full stops or parentheses.
- Plain English, short sentences, numbers instead of adjectives, no hype words. README in first person singular.
- Commits: short imperative header, a body that explains why, author `Anders Henriksen <anhenr.dev@gmail.com>`. Short branches, squash merge.

## Layout

- `src/bankrag/ingest/`: PDF parsing (`pdf.py`), chunking (`chunk.py`), pipeline with page cache (`pipeline.py`)
- `src/bankrag/retrieve/`: BM25 (`bm25.py`), bank and year routing (`route.py`)
- `src/bankrag/answer/generate.py`: Claude call with `search_result` blocks, citations, prompt caching, refusals, cost, trace log
- `src/bankrag/evaluate.py`: metrics; `evals/run_evals.py` runs them and writes `evals/RESULTS.md`
