import json
import subprocess
from pathlib import Path

import pytest

from bankrag.ingest import pipeline
from bankrag.ingest.pdf import Page, fill_sections

ACCESS_VIOLATION = 3221225477  # 0xC0000005 on Windows


def fake_worker(total_pages: int, crash_with_layout: set[int], crash_always: set[int]):
    """Stand-in for the worker process: writes pages and 'crashes' on chosen pages."""
    calls = []

    def run(cmd, **kwargs):
        start = int(cmd[cmd.index("--start") + 1])
        no_layout = {int(p) for p in cmd[cmd.index("--no-layout") + 1].split(",") if p}
        calls.append((start, sorted(no_layout)))
        out = Path(cmd[6])
        with out.open("a", encoding="utf-8") as f:
            for pno in range(start, total_pages + 1):
                if pno in crash_always or (pno in crash_with_layout and pno not in no_layout):
                    return subprocess.CompletedProcess(cmd, ACCESS_VIOLATION, "", "")
                page = Page(bank="nordea", year=2025, page=pno, section="", heading=f"p{pno}")
                f.write(json.dumps(page.to_dict()) + "\n")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    return run, calls


@pytest.fixture
def pages_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "PAGES_DIR", tmp_path)
    return tmp_path


def test_restarts_at_crashing_page_without_layout(pages_dir, monkeypatch):
    run, calls = fake_worker(total_pages=6, crash_with_layout={3, 5}, crash_always=set())
    monkeypatch.setattr(pipeline.subprocess, "run", run)

    summary = pipeline._parse_report(Path("nordea_2025.pdf"), "nordea", 2025)

    pages = pipeline._read_pages(pages_dir / "nordea_2025.jsonl")
    assert [p["page"] for p in pages] == [1, 2, 3, 4, 5, 6]
    assert calls == [(1, []), (3, [3]), (5, [3, 5])]
    assert "[3, 5]" in summary


def test_page_that_always_crashes_is_kept_empty(pages_dir, monkeypatch):
    run, _ = fake_worker(total_pages=4, crash_with_layout=set(), crash_always={2})
    monkeypatch.setattr(pipeline.subprocess, "run", run)

    summary = pipeline._parse_report(Path("nordea_2025.pdf"), "nordea", 2025)

    pages = pipeline._read_pages(pages_dir / "nordea_2025.jsonl")
    assert [p["page"] for p in pages] == [1, 2, 3, 4]
    assert pages[1]["blocks"] == []
    assert "page(s) [2] left empty" in summary


def test_python_error_is_raised_not_retried(pages_dir, monkeypatch):
    def run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, "", "Traceback (most recent call last):\n  ImportError")

    monkeypatch.setattr(pipeline.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="ImportError"):
        pipeline._parse_report(Path("nordea_2025.pdf"), "nordea", 2025)


def test_fill_sections_carries_forward():
    pages = [
        Page(bank="danske", year=2025, page=1, section="Financial review", heading=""),
        Page(bank="danske", year=2025, page=2, section="", heading=""),
        Page(bank="danske", year=2025, page=3, section="Risk management", heading=""),
    ]
    assert [p.section for p in fill_sections(pages)] == [
        "Financial review",
        "Financial review",
        "Risk management",
    ]


def test_is_title_rejects_chart_labels_and_figures():
    from bankrag.ingest.pdf import is_title

    for good in ["Financial review", "Capital and liquidity management", "G11. Loan impairment charges"]:
        assert is_title(good), good
    for bad in ["DKK 6,307 million", "'24 …", "↘ 65%", "E", "statements", "Contents", "Annual Report 2024"]:
        assert not is_title(bad), bad
