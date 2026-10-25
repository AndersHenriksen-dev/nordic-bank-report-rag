"""Read bank and year filters from the question, and spread results across banks.

A comparison question ("Compare the CET1 ratio of the three banks") needs evidence from every bank. Plain top-k
search tends to fill all slots with the bank whose wording matches best, so for multi-bank questions each bank is
searched on its own and the results are interleaved.
"""

from __future__ import annotations

import itertools
import math
import re
from dataclasses import dataclass, field
from typing import Protocol

from bankrag.config import BANK_NAMES, YEARS, Bank
from bankrag.retrieve.bm25 import Hit
from bankrag.retrieve.rewrite import expand_danish

BANK_PATTERNS: dict[Bank, re.Pattern[str]] = {
    "danske": re.compile(r"\bdanske\b", re.IGNORECASE),
    "nordea": re.compile(r"\bnordea", re.IGNORECASE),  # no closing \b: matches the Danish genitive "Nordeas"
    "jyske": re.compile(r"\bjyske\b", re.IGNORECASE),
}
ALL_BANKS_RE = re.compile(r"\b(three|all|each|the) banks\b|\bbankerne\b|\balle tre\b|\bde tre\b", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(20\d\d)\b")


class Retriever(Protocol):
    """A search backend that can filter on bank and year."""

    def search(
        self,
        query: str,
        k: int,
        banks: list[Bank] | None = None,
        years: list[int] | None = None,
    ) -> list[Hit]:
        """Return up to `k` hits for the query, best first."""
        ...


@dataclass
class Filters:
    """The banks and report years a question names. Empty means no filter."""

    banks: list[Bank] = field(default_factory=list)
    years: list[int] = field(default_factory=list)


def detect_filters(question: str) -> Filters:
    """Find the banks and report years a question names, in English or Danish."""
    banks = [bank for bank, pattern in BANK_PATTERNS.items() if pattern.search(question)]
    if not banks and ALL_BANKS_RE.search(question):
        banks = list(BANK_NAMES)
    years = sorted({int(year) for year in YEAR_RE.findall(question) if int(year) in YEARS})
    return Filters(banks=banks, years=years)


def _interleave(hits_by_bank: list[list[Hit]]) -> list[Hit]:
    """Order hits by rank across banks: each bank's best, then each bank's second best, and so on.

    Any top slice then stays balanced. Scores are not comparable across separate searches anyway.
    """
    return [hit for rank in itertools.zip_longest(*hits_by_bank) for hit in rank if hit is not None]


def routed_search(retriever: Retriever, question: str, k: int, route: bool = True, expand: bool = True) -> list[Hit]:
    """Search only the reports a question names, and balance the results across banks.

    Args:
        retriever: The search backend.
        question: The user's question, in English or Danish.
        k: Number of chunks to return. For multi-bank questions it is split evenly between the banks.
        route: Filter on the banks and years the question names. Off only to measure what routing adds.
        expand: Add English wording for Danish finance terms. Off only to measure what the glossary adds.

    Returns:
        Up to `k` hits.
    """
    query = expand_danish(question) if expand else question
    if not route:
        return retriever.search(query, k=k)
    filters = detect_filters(question)
    years = filters.years or None
    if len(filters.banks) <= 1:
        return retriever.search(query, k=k, banks=filters.banks or None, years=years)
    per_bank = math.ceil(k / len(filters.banks))
    hits_by_bank = [retriever.search(query, k=per_bank, banks=[bank], years=years) for bank in filters.banks]
    return _interleave(hits_by_bank)[:k]
