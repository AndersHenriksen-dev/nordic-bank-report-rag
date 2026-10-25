from bankrag.retrieve.rewrite import expand_danish


def test_danish_terms_get_english_wording():
    q = expand_danish("Hvad var Nordeas egenkapitalforrentning i 2025?")
    assert q.startswith("Hvad var Nordeas egenkapitalforrentning i 2025?")
    assert "return on equity" in q


def test_several_terms():
    q = expand_danish("Hvad var Danske Banks nettoresultat og omkostningsprocent i 2025?")
    assert "net profit for the year" in q
    assert "cost/income ratio" in q


def test_english_questions_are_unchanged():
    q = "How does Nordea describe the role of AI in its strategy?"
    assert expand_danish(q) == q
