"""Read numbers and figures from report and answer text, in both English and Danish number formats.

Used by the eval metrics (is a figure in the answer also in the cited passage?) and by the front-end (which rows of a
cited table does the answer use?).
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

Reading = tuple[float, int]  # absolute value, decimals shown


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


def figure_tokens(text: str) -> list[list[Reading]]:
    """Return the readings of every figure in the text, ignoring references, years and small counts."""
    clean = REFERENCE_RE.sub(" ", text)
    return [token for raw in NUMBER_RE.findall(clean) if is_figure(token := readings(raw))]


def figures_in(text: str) -> set[float]:
    """Return the values of every figure in the text."""
    return {value for token in figure_tokens(text) for value, _ in token}
