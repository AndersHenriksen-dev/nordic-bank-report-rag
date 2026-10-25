"""Paths, bank names and settings shared by the whole package."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
INDEX_DIR = DATA_DIR / "index"
TRACE_DIR = DATA_DIR / "traces"

load_dotenv(ROOT / ".env")

BANK_NAMES = {
    "danske": "Danske Bank",
    "nordea": "Nordea",
    "jyske": "Jyske Bank",
}
YEARS = (2024, 2025)

# The cheapest current Claude model by default. Override with BANKRAG_MODEL.
ANSWER_MODEL = os.getenv("BANKRAG_MODEL", "claude-haiku-5-5")

# USD per million tokens: (input, output). Cache writes cost 1.25x input, cache reads 0.1x.
# Source: Anthropic pricing, checked October 2026.
PRICES_USD_PER_MTOK = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}
# Fixed rate so cost figures are comparable between runs. Update when it drifts.
USD_TO_DKK = float(os.getenv("BANKRAG_USD_TO_DKK", "6.8"))


def bank_name(bank: str) -> str:
    return BANK_NAMES.get(bank, bank)
