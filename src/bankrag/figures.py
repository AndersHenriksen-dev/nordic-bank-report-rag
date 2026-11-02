"""Read numbers and figures from report and answer text, in both English and Danish number formats.

Used by the answers and the eval metrics (is a figure in the answer also in the cited passage?) and by the front-end
(which rows of a cited table does the answer use?).
"""

from __future__ import annotations

import re

NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)*")
YEARS_NOT_FIGURES = range(1990, 2036)
# Citation markers and page or note references, which hold numbers that are not figures from a report.
REFERENCE_RE = re.compile(
    r"\[\d+\]"  # citation markers
    r"|\b(?:pages?|p\.|sider?|note)\s+[A-Z]?\d+(?:\s*(?:and|og|,|-|\u2013)\s*\d+)*"  # page and note references
    r"|\b[A-Z]\d{1,3}\b"  # note numbers such as G41 or P30
    r"|\b(?:Microsoft|Office|M)\s?365\b",  # product names
    re.IGNORECASE,
)

NUMBER_TOLERANCE = 0.011  # allows rounding to one decimal, e.g. 45.46 matches 45.5

Reading = tuple[float, int]  # absolute value, decimals shown


def close_to(number: float, target: float) -> bool:
    """Tell whether a number is the target within rounding: one decimal for small figures, about 0.01% for large."""
    return abs(number - target) <= NUMBER_TOLERANCE * max(1.0, abs(target) / 100)


def readings(raw: str) -> list[Reading]:
    """Return the valid readings of a number token, English and Danish.

    "23,037" can mean 23037 or 23.037, so both readings are returned; "1,022.3" read the Danish way is not a number.
    """
    found = []
    for thousands, decimal in ((",", "."), (".", ",")):
        parts = raw.lstrip("-").split(decimal)
        if len(parts) > 2:
            continue
        whole, fraction = parts[0], parts[1] if len(parts) == 2 else ""
        if thousands in fraction:
            continue
        if thousands in whole and not all(len(group) == 3 for group in whole.split(thousands)[1:]):
            continue
        found.append((float(whole.replace(thousands, "") + ("." + fraction if fraction else "")), len(fraction)))
    return found


def numbers_in(text: str) -> set[float]:
    """Find every number in the text, with both readings of ambiguous ones."""
    return {value for raw in NUMBER_RE.findall(text) for value, _ in readings(raw)}


def is_figure(token_readings: list[Reading]) -> bool:
    """Tell figures from years and small counts, which text can state without a source."""
    return any(
        not value.is_integer() or not (value < 10 or int(value) in YEARS_NOT_FIGURES) for value, _ in token_readings
    )


def _figures(text: str) -> list[tuple[str, list[Reading]]]:
    """Return every figure in the text as written, with its readings, ignoring references, years and small counts."""
    clean = REFERENCE_RE.sub(" ", text)
    return [(raw, token) for raw in NUMBER_RE.findall(clean) if is_figure(token := readings(raw))]


def figure_tokens(text: str) -> list[list[Reading]]:
    """Return the readings of every figure in the text, ignoring references, years and small counts."""
    return [token for _, token in _figures(text)]


def _rounds_to(value: float, decimals: int, pool: set[float]) -> bool:
    return any(abs(round(candidate, decimals) - value) < 1e-9 for candidate in pool)


def ungrounded_figures(text: str, passages: list[str]) -> list[str]:
    """Return the figures in an answer that no cited passage holds, as the answer writes them.

    A figure counts as grounded if a passage holds it at the precision the answer gives (23.0 billion matches 23,037
    million), or if it is the difference or percentage change between two other figures in the answer (a fall of 0.1
    points from 45.6% to 45.5%). Years, numbers below 10, page and note references, product names and citation
    markers are not figures.

    Args:
        text: The answer.
        passages: The text the answer cites.
    """
    figures = _figures(text)
    cited = {value for passage in passages for value in numbers_in(passage)}
    cited |= {value / 1000 for value in cited}  # millions restated as billions
    stated = [value for _, token in figures for value, _ in token]
    # Sums cover changes across zero, such as from a reversal of 543 to a charge of 294 (figures are unsigned).
    derived = {abs(a - b) for a in stated for b in stated} | {a + b for a in stated for b in stated}
    derived |= {abs(a - b) / b * 100 for a in stated for b in stated if b}
    pool = cited | derived
    missing = (raw for raw, token in figures if not any(_rounds_to(value, decimals, pool) for value, decimals in token))
    return list(dict.fromkeys(missing))


def figures_in(text: str) -> set[float]:
    """Return the values of every figure in the text."""
    return {value for token in figure_tokens(text) for value, _ in token}
