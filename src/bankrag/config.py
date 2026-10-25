"""Settings shared by the whole package: paths, the three banks, the search and answer models, and prices."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import TypeAdapter

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
INDEX_DIR = DATA_DIR / "index"
TRACE_DIR = DATA_DIR / "traces"

load_dotenv(ROOT / ".env")

Bank = Literal["danske", "nordea", "jyske"]
BANK_NAMES: dict[Bank, str] = {
    "danske": "Danske Bank",
    "nordea": "Nordea",
    "jyske": "Jyske Bank",
}
YEARS = (2024, 2025)

DISCLAIMER = (
    "Built on public annual reports for demonstration. Not investment advice. "
    "Figures should be checked against the source page."
)

ANSWER_MODEL = os.getenv("BANKRAG_MODEL", "claude-haiku-5-5")
# The eval's LLM judge. The same cheap model as the answers by default; a stronger judge is one variable away.
JUDGE_MODEL = os.getenv("BANKRAG_JUDGE_MODEL", "claude-haiku-5-5")

# Local open models from Hugging Face, multilingual because questions come in Danish and English. Changing the
# embedding model makes `bankrag ingest` rebuild the vector index.
EMBED_MODEL = os.getenv("BANKRAG_EMBED_MODEL", "BAAI/bge-m3")
RERANK_MODEL = os.getenv("BANKRAG_RERANK_MODEL", "BAAI/bge-reranker-v2-m3")

# USD per million tokens: (input, output). Cache writes cost 1.25x input, cache reads 0.1x.
# Source: Anthropic pricing, checked October 2026.
PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}
# A fixed rate keeps cost figures comparable between eval runs.
USD_TO_DKK = float(os.getenv("BANKRAG_USD_TO_DKK", "6.8"))

_BANK_ADAPTER: TypeAdapter[Bank] = TypeAdapter(Bank)


def parse_bank(value: str) -> Bank:
    """Validate a bank key read from a file name or the command line.

    Raises:
        pydantic.ValidationError: If `value` is not one of the three banks.
    """
    return _BANK_ADAPTER.validate_python(value)


def bank_name(bank: Bank) -> str:
    """Return the display name of a bank, for example "Danske Bank" for "danske"."""
    return BANK_NAMES[bank]
