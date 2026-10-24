"""Metrics for the eval set: retrieval recall and MRR, number matching, citation checks."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from bankrag.ingest.chunk import Chunk

NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)*")


@dataclass
class Question:
    id: str
    question: str
    lang: str
    category: str
    answerable: bool
    gold_answer: str
    numbers: list[list[float]] = field(default_factory=list)
    evidence: list[list[str]] = field(default_factory=list)
    verified: bool = False


def load_questions(path: Path) -> list[Question]:
    return [Question(**q) for q in yaml.safe_load(path.read_text(encoding="utf-8"))]


def page_key(chunk: Chunk) -> str:
    return f"{chunk.bank}-{chunk.year}-p{chunk.page}"


def retrieval_scores(q: Question, ranked_pages: list[str], k: int) -> tuple[float, float]:
    """Recall@k over evidence groups, and reciprocal rank of the first relevant page."""
    top = ranked_pages[:k]
    groups_hit = sum(any(p in top for p in group) for group in q.evidence)
    recall = groups_hit / len(q.evidence)
    relevant = {p for group in q.evidence for p in group}
    rr = next((1 / (i + 1) for i, p in enumerate(ranked_pages) if p in relevant), 0.0)
    return recall, rr


def numbers_in(text: str) -> set[float]:
    """Every number in the text, read both the English and the Danish way.

    "23,037" and "23.037" can each mean 23037 or 23.037, so both readings are kept.
    """
    out: set[float] = set()
    for raw in NUMBER_RE.findall(text):
        for thousands, decimal in ((",", "."), (".", ",")):
            parts = raw.split(decimal)
            if len(parts) > 2:
                continue
            whole = parts[0]
            if thousands in whole and not all(len(g) == 3 for g in whole.split(thousands)[1:]):
                continue
            out.add(float(whole.replace(thousands, "") + ("." + parts[1] if len(parts) == 2 else "")))
    return out


def numbers_match(q: Question, answer_text: str) -> bool | None:
    """True when every required figure appears in the answer. None if the question has no figures."""
    if not q.numbers:
        return None
    found = numbers_in(answer_text)
    return all(
        any(abs(f - alt) <= 0.011 * max(1.0, abs(alt) / 100) for f in found for alt in alts)
        for alts in q.numbers
    )


def citation_ok(q: Question, page: str, cited_text: list[str]) -> bool:
    """A citation counts as correct if it points at a gold page or quotes a gold figure."""
    if any(page in group for group in q.evidence):
        return True
    text_numbers = numbers_in(" ".join(cited_text))
    return any(abs(f - alt) < 1e-6 for alts in q.numbers for alt in alts for f in text_numbers)


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    i = min(len(s) - 1, max(0, round(p / 100 * (len(s) - 1))))
    return s[i]
