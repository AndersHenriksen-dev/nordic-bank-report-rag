.PHONY: setup download ingest ask app mcp eval-retrieval eval test lint check

setup:
	uv sync
	uv run pre-commit install

download:
	uv run python scripts/download.py

ingest:
	uv run bankrag ingest

# make ask Q="What was Danske Bank's net profit in 2025?"
ask:
	uv run bankrag ask "$(Q)"

# Web page on http://localhost:8501: question, reasoning, cited answer and highlighted report pages.
app:
	uv run streamlit run src/bankrag/ui/app.py

# Read-only MCP server over stdio for Claude Desktop or Claude Code: report search and the KPI table.
mcp:
	uv run bankrag-mcp

eval-retrieval:
	uv run python evals/run_evals.py

eval:
	uv run python evals/run_evals.py --answers

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src

# Everything CI runs.
check: lint test
