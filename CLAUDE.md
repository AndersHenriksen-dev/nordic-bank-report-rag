# CLAUDE.md

Question answering over the 2024 and 2025 annual reports of Danske Bank, Nordea and Jyske Bank, with page citations and evals. Public portfolio repo: everything here is read by recruiters.

## Run things

```bash
uv sync                                  # install
uv run pre-commit install                # once: ruff, mypy, line endings and gitleaks on every commit
uv run python scripts/download.py        # fetch PDFs into data/raw/ (Jyske Bank: download by hand, see script output)
uv run bankrag ingest                    # parse PDFs (about 30 min the first time), chunk, build the Qdrant index
uv run bankrag search "question"         # show retrieved chunks, no API key needed; --retriever bm25|dense|hybrid|hybrid-rerank
uv run bankrag ask "question"            # answer with citations, needs ANTHROPIC_API_KEY in .env
uv run bankrag kpi show                  # the KPI table; `kpi extract` reads it with Claude (about USD 0.05: ask first)
uv run streamlit run src/bankrag/ui/app.py   # web page on localhost:8501, needs the key and the PDFs
uv run python evals/run_evals.py         # retrieval evals, no API key needed
uv run python evals/run_evals.py --answers   # answers and LLM judge too, costs money: ask first
uv run python scripts/find_pages.py "pattern" --report jyske_2025 --pages 20-25   # check a gold figure in the page text
uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest   # what CI runs
```

The `make` targets wrap the same commands.

## Index of `.claude/` and related files

| File | Read it when | What it covers |
|---|---|---|
| [.claude/reference/python-style.md](.claude/reference/python-style.md) | **Before writing or editing any `.py` file** | The single source of truth for Python here: PEP 8 via ruff, typing checked by mypy, Google-style docstrings, Pydantic models at boundaries, module structure, KISS/DRY/LEAN, comments, testing. |
| [.claude/hooks/check_python_style_read.py](.claude/hooks/check_python_style_read.py) | Debugging why a Python edit was blocked | `PreToolUse` hook that blocks editing `.py`/`.ipynb` files until the style guide has been read in the session. |
| [.claude/settings.json](.claude/settings.json) | Changing permissions or hooks | Allowed and denied commands, and the hook above. |
| [.pre-commit-config.yaml](.pre-commit-config.yaml) and [.github/workflows/ci.yml](.github/workflows/ci.yml) | Changing what runs on commit or in CI | The automatic half of the style guide, plus the gitleaks secret scan. |
| [docs/decisions.md](docs/decisions.md) | Changing a design choice | Why things are built the way they are. |
| [.claude/skills/add-eval-case/SKILL.md](.claude/skills/add-eval-case/SKILL.md) | Adding or correcting an eval question | How to find and check every gold figure and page in the parsed report text. |
| [evals/judge_rubric.md](evals/judge_rubric.md) | Changing how answers are judged | The LLM judge's rubric, sent as its system prompt. |

## Rules

- Every new feature needs an eval case in `evals/questions.yaml`, with the gold answer and source page checked against the PDF (use the `add-eval-case` skill).
- Never commit data or keys: `data/`, PDFs and `.env` are git-ignored. Never read `.env`.
- Page numbers are PDF page numbers (1-based), not the printed page labels.
- Run `run_evals.py --answers` only when asked: it calls the paid API.
- Qdrant runs embedded and locks `data/index/qdrant`: only one process (the web page, the evals or the CLI) can search at a time.
- The first search downloads `BAAI/bge-m3` and `BAAI/bge-reranker-v2-m3` (2.3 GB each) from Hugging Face. They run on the GPU when PyTorch finds one.
- Nothing from Anders's current or past employers goes in this repo. The banks appear only as the public subjects of their reports.
- The system must refuse forecasts, recommendations and investment advice. Keep the disclaimer in the README and the UI.
- Update `docs/BUILD_LOG.md` at the end of each session: date, hours, what was built, what Claude Code did, what Anders decided.
- Record design choices and their reasons in `docs/decisions.md`.

## Writing style (everything that is not Python)

- Never use em dashes anywhere: README, docs, comments, commit messages. Use commas, colons, full stops or parentheses.
- Plain English, short sentences, numbers instead of adjectives, no hype words. README in first person singular.
- Commits: short imperative header, a body that explains why, author `Anders Henriksen <anhenr.dev@gmail.com>`. Short branches, squash merge.

## Layout

- `src/bankrag/models.py`: Pydantic models for everything that crosses a boundary (page cache, chunks, eval questions, answers)
- `src/bankrag/ingest/`: PDF parsing (`pdf.py`), chunking (`chunk.py`), pipeline with a per-report page cache (`pipeline.py`) that runs each report in a crash-safe child process (`worker.py`)
- `src/bankrag/retrieve/`: BM25 (`bm25.py`), vectors in embedded Qdrant (`dense.py`), the local models (`neural.py`), rank fusion (`hybrid.py`), cross-encoder reranking (`rerank.py`), building a retriever by name (`factory.py`), bank and year routing (`route.py`), Danish query glossary (`rewrite.py`)
- `src/bankrag/answer/generate.py`: Claude call with `search_result` blocks, citations, prompt caching, refusals, cost, trace log
- `src/bankrag/ui/`: Streamlit page (`app.py`, which also replays saved answers from the trace log) and cited-passage highlighting on PDF pages (`highlight.py`)
- `src/bankrag/figures.py`: number and figure parsing in English and Danish formats, used by the evals and the UI
- `src/bankrag/evaluate.py`: metrics; `src/bankrag/judge.py`: the LLM judge; `evals/run_evals.py` runs them and writes `evals/RESULTS.md` with its chart and `evals/ANSWERS.md` (generated, do not edit by hand)
- `docs/images/`: README screenshots, made from saved answers so they cost nothing to retake
- `src/bankrag/kpi/`: the KPI table: extraction with structured output and automatic checks (`extract.py`), YAML and SQLite store with queries (`store.py`); the reviewed figures are in `kpi/figures.yaml`
- `docs/documents.md`: the six reports, their checksums and what to know about them
- `docs/concepts.md`: study guide to every concept the system uses, from BM25 to CET1; update it when a new technique is added
