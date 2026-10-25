"""Query rewriting before keyword search.

The reports are in English, but questions may come in Danish. Keyword search cannot match "egenkapitalforrentning" to
"return on equity", so Danish finance terms in a question get the English wording of the reports appended. The original
words stay in the query. A fixed glossary is cheap and easy to inspect, and the evals show how much it adds.
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
_GLOSSARY_PATTERNS = [
    (re.compile(rf"\b(?:{danish})\b", re.IGNORECASE), english) for danish, english in GLOSSARY.items()
]
DANISH_RE = re.compile(r"[æøå]|\b(hvad|hvordan|hvorfor|hvilke|hvilken|hvor|hvem|blev|bliver|var)\b", re.IGNORECASE)


def is_danish(question: str) -> bool:
    """Tell whether a question looks Danish, from æ, ø, å or Danish question words."""
    return bool(DANISH_RE.search(question))


def expand_danish(question: str) -> str:
    """Append the English report wording for every Danish finance term in a Danish question.

    English questions come back unchanged, because some glossary entries (such as "strategi") also match English.
    """
    if not is_danish(question):
        return question
    added: list[str] = []
    for pattern, english in _GLOSSARY_PATTERNS:
        if pattern.search(question) and english not in added:
            added.append(english)
    return f"{question} {' '.join(added)}" if added else question
