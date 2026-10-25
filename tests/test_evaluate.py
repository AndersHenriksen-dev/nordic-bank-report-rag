from bankrag.evaluate import Question, citation_ok, numbers_in, numbers_match, retrieval_scores


def q(**kw) -> Question:
    base = dict(id="t", question="?", lang="en", category="lookup", answerable=True, gold_answer="")
    return Question(**{**base, **kw})


def test_numbers_in_reads_english_and_danish_formats():
    assert 23037.0 in numbers_in("DKK 23,037 million")
    assert 23037.0 in numbers_in("23.037 mio. kr.")
    assert 15.5 in numbers_in("15,5%")
    assert 45.5 in numbers_in("45.5%")


def test_numbers_match_needs_every_figure():
    question = q(numbers=[[45.5], [45.6]])
    assert numbers_match(question, "45.5% in 2025 against 45.6% in 2024")
    assert not numbers_match(question, "45.5% in 2025")


def test_numbers_match_accepts_alternative_units():
    question = q(numbers=[[23037, 23.0]])
    assert numbers_match(question, "DKK 23.0 billion")
    assert numbers_match(question, "DKK 23,037 million")
    assert not numbers_match(question, "DKK 23,629 million")


def test_numbers_match_is_none_without_figures():
    assert numbers_match(q(numbers=[]), "anything") is None


def test_retrieval_scores_counts_groups():
    question = q(evidence=[["a-2025-p4", "a-2025-p5"], ["b-2025-p40"]])
    recall, rr = retrieval_scores(question, ["x-2025-p1", "a-2025-p5", "y-2025-p2"], k=3)
    assert recall == 0.5
    assert rr == 0.5


def test_citation_ok_by_page_or_quoted_figure():
    question = q(numbers=[[17.3]], evidence=[["danske-2025-p32"]])
    assert citation_ok(question, "danske-2025-p32", [])
    assert citation_ok(question, "danske-2025-p6", ["The CET1 capital ratio was 17.3%"])
    assert not citation_ok(question, "danske-2025-p99", ["Net profit was DKK 23,037 million"])
