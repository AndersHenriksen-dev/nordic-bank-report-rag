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
