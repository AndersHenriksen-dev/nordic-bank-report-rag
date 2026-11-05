"""Tests for the Danish query glossary."""

from __future__ import annotations

from bankrag.retrieve.rewrite import english_terms, expand_danish


def test_danish_terms_get_english_wording() -> None:
    query = expand_danish("Hvad var Nordeas egenkapitalforrentning i 2025?")
    assert query.startswith("Hvad var Nordeas egenkapitalforrentning i 2025?")
    assert "return on equity" in query


def test_several_terms() -> None:
    query = expand_danish("Hvad var Danske Banks nettoresultat og omkostningsprocent i 2025?")
    assert "net profit for the year" in query
    assert "cost/income ratio" in query


def test_english_questions_are_unchanged() -> None:
    question = "How does Nordea describe the role of AI in its strategy?"
    assert expand_danish(question) == question


def test_english_terms_ignore_the_language_check() -> None:
    assert english_terms("Sammenlign Danske Banks og Nordeas nettoresultat for 2024.") == ["net profit for the year"]
    assert expand_danish("Sammenlign Danske Banks og Nordeas nettoresultat for 2024.").endswith("2024.")
