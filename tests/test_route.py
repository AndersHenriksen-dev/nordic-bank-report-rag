from bankrag.retrieve.route import detect_filters


def test_single_bank_and_years():
    f = detect_filters("What was Danske Bank's cost/income ratio in 2025, and how did it change from 2024?")
    assert f.banks == ["danske"]
    assert f.years == [2024, 2025]


def test_danish_genitive():
    assert detect_filters("Hvad var Nordeas egenkapitalforrentning i 2025?").banks == ["nordea"]


def test_all_banks():
    assert detect_filters("Compare the CET1 ratio of the three banks").banks == ["danske", "nordea", "jyske"]


def test_years_outside_the_reports_are_ignored():
    assert detect_filters("What was Nordea's net profit in 2012?").years == []


class FakeRetriever:
    name = "fake"

    def search(self, query, k=6, banks=None, years=None):
        from bankrag.ingest.chunk import Chunk
        from bankrag.retrieve.bm25 import Hit

        bank = banks[0]
        # Danske's chunks always score highest, as if its wording matched best.
        base = {"danske": 100, "nordea": 10, "jyske": 1}[bank]
        return [Hit(Chunk(f"{bank}-{i}", bank, 2025, i, "", "", "", "", False), base - i) for i in range(k)]


def test_multi_bank_results_are_interleaved_and_cut_to_k():
    from bankrag.retrieve.route import routed_search

    hits = routed_search(FakeRetriever(), "Compare the CET1 ratio of the three banks", k=4)
    assert [h.chunk.bank for h in hits] == ["danske", "nordea", "jyske", "danske"]
