"""Read bank and year filters from the question, and spread results across banks.

A comparison question ("Compare the CET1 ratio of the three banks") needs
evidence from every bank. Plain top-k search tends to fill all slots with the
bank whose wording matches best, so for multi-bank questions each bank gets its
own share of the results.
"""

from __future__ import annotations

import itertools
import math
import re
from dataclasses import dataclass, field
from typing import Protocol

from bankrag.config import BANK_NAMES, YEARS
from bankrag.retrieve.bm25 import Hit
from bankrag.retrieve.rewrite import expand_danish

BANK_PATTERNS = {
    "danske": re.compile(r"\bdanske\b", re.I),
    "nordea": re.compile(r"\bnordea", re.I),
    "jyske": re.compile(r"\bjyske\b", re.I),
}
ALL_BANKS_PATTERN = re.compile(r"\b(three|all|each|the) banks\b|\bbankerne\b|\balle tre\b|\bde tre\b", re.I)


class Retriever(Protocol):
    name: str

    def search(
        self, query: str, k: int = 6, banks: list[str] | None = None, years: list[int] | None = None
    ) -> list[Hit]: ...


@dataclass
class Filters:
    banks: list[str] = field(default_factory=list)
    years: list[int] = field(default_factory=list)


def detect_filters(question: str) -> Filters:
    banks = [b for b, pattern in BANK_PATTERNS.items() if pattern.search(question)]
    if not banks and ALL_BANKS_PATTERN.search(question):
        banks = list(BANK_NAMES)
    years = sorted({int(y) for y in re.findall(r"\b(20\d\d)\b", question) if int(y) in YEARS})
    return Filters(banks=banks, years=years)


def routed_search(
    retriever: Retriever, question: str, k: int = 6, route: bool = True, expand: bool = True
) -> list[Hit]:
    query = expand_danish(question) if expand else question
    if not route:
        return retriever.search(query, k=k)
    f = detect_filters(question)
    if len(f.banks) <= 1:
        return retriever.search(query, k=k, banks=f.banks or None, years=f.years or None)
    per_bank = math.ceil(k / len(f.banks))
    by_bank = [retriever.search(query, k=per_bank, banks=[b], years=f.years or None) for b in f.banks]
    # Interleave by rank (each bank's best hit, then each bank's second best, ...), so
    # any top slice stays balanced. Scores are not comparable across banks anyway.
    hits = [h for rank in itertools.zip_longest(*by_bank) for h in rank if h is not None]
    return hits[:k]
