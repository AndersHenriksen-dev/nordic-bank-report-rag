.PHONY: setup download ingest ask eval-retrieval eval test lint

setup:
	uv sync

download:
	uv run python scripts/download.py

ingest:
	uv run bankrag ingest

# make ask Q="What was Danske Bank's net profit in 2025?"
ask:
	uv run bankrag ask "$(Q)"

eval-retrieval:
	uv run python evals/run_evals.py

eval:
	uv run python evals/run_evals.py --answers

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .
