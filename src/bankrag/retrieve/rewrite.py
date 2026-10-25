"""Query rewriting before keyword search.

The reports are in English, but questions may come in Danish. Keyword search
cannot match "egenkapitalforrentning" to "return on equity", so Danish finance
terms in the question get their English report wording appended. The original
words stay in the query.

This is a fixed glossary, cheap and easy to inspect. Multilingual embeddings
(milestone 2) should make it matter less; the evals show how much it adds.
"""

from __future__ import annotations

import re

# Danish term (lower case, regex) -> English wording used in the reports.
GLOSSARY = {
    r"egenkapitalforrentning\w*": "return on equity",
    r"(netto|års)resultat\w*|årets resultat": "net profit for the year",
    r"resultat før skat": "profit before tax",
    r"omkostningsprocent\w*|omkostningsandel\w*|cost/income\w*": "cost/income ratio",
    r"(egentlig )?kernekapital(procent|andel)\w*": "CET1 common equity tier 1 capital ratio",
    r"solvens(procent|andel)\w*|kapitalprocent\w*": "total capital ratio",
    r"nedskrivning\w*": "loan impairment charges",
    r"nettorenteindtægt\w*|renteindtægt\w*|netto renteindtægt\w*": "net interest income",
    r"gebyrindtægt\w*|nettogebyr\w*": "net fee income",
    r"udbytte\w*": "dividend",
    r"aktiekurs\w*": "share price",
    r"aktietilbagekøb\w*": "share buy-back",
    r"driftsomkostning\w*|omkostning\w*": "operating expenses costs",
    r"(samlede )?indtægt\w*": "total income",
    r"udlån\w*": "loans lending",
    r"indlån\w*": "deposits",
    r"kreditkvalitet\w*": "credit quality",
    r"likviditet\w*": "liquidity",
    r"kunstig intelligens": "artificial intelligence AI",
    r"strategi\w*": "strategy",
    r"bæredygtighed\w*": "sustainability",
    r"medarbejder\w*": "employees staff",
    r"forventning\w*|udsigt\w*": "outlook guidance expectations",
    r"risiko\w*|risici": "risk",
    r"kapital\w*": "capital",
}
_PATTERNS = [(re.compile(rf"\b(?:{da})\b", re.I), en) for da, en in GLOSSARY.items()]
DANISH_RE = re.compile(r"[æøå]|\b(hvad|hvordan|hvorfor|hvilke|hvilken|hvor|hvem|blev|bliver|var)\b", re.I)


def is_danish(question: str) -> bool:
    return bool(DANISH_RE.search(question))


def expand_danish(question: str) -> str:
    """Append the English report wording for every Danish finance term in the question."""
    if not is_danish(question):
        return question
    added = []
    for pattern, english in _PATTERNS:
        if pattern.search(question) and english not in added:
            added.append(english)
    return f"{question} {' '.join(added)}" if added else question
