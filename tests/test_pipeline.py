"""Tests for the crash-safe parsing pipeline, with the worker process replaced at the subprocess boundary."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from bankrag.ingest import pipeline
from bankrag.models import Page

ACCESS_VIOLATION = 3221225477  # 0xC0000005, how a native crash exits on Windows
REPORT = pipeline.ReportFile(Path("nordea_2025.pdf"), "nordea", 2025)


class FakeWorker:
    """Stands in for `subprocess.run` of the worker: writes pages and 'crashes' on chosen pages."""

    def __init__(self, total_pages: int, crash_with_layout: set[int], crash_always: set[int]) -> None:
        """Set up a report of `total_pages` pages.

        Args:
            total_pages: Pages in the fake report.
            crash_with_layout: Pages that crash unless they are in the worker's --no-layout list.
            crash_always: Pages that crash even without the layout model.
        """
        self.total_pages = total_pages
        self.crash_with_layout = crash_with_layout
        self.crash_always = crash_always
        self.calls: list[tuple[int, list[int]]] = []

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        start = int(command[command.index("--start") + 1])
        no_layout = {int(page) for page in command[command.index("--no-layout") + 1].split(",") if page}
        self.calls.append((start, sorted(no_layout)))
        with Path(command[6]).open("a", encoding="utf-8") as out:
            for number in range(start, self.total_pages + 1):
                if number in self.crash_always or (number in self.crash_with_layout and number not in no_layout):
                    return subprocess.CompletedProcess(command, ACCESS_VIOLATION, "", "")
                page = Page(bank="nordea", year=2025, page=number, section="", heading=f"p{number}")
                out.write(page.model_dump_json() + "\n")
        return subprocess.CompletedProcess(command, 0, "", "")


class TestParseReport:
    @pytest.fixture(autouse=True)
    def pages_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.setattr(pipeline, "PAGES_DIR", tmp_path)
        return tmp_path

    def test_restarts_at_crashing_page_without_layout(self, pages_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        worker = FakeWorker(total_pages=6, crash_with_layout={3, 5}, crash_always=set())
        monkeypatch.setattr(pipeline.subprocess, "run", worker)

        summary = pipeline._parse_report(REPORT)

        pages = pipeline._read_pages(pages_dir / "nordea_2025.jsonl")
        assert [page.page for page in pages] == [1, 2, 3, 4, 5, 6]
        assert worker.calls == [(1, []), (3, [3]), (5, [3, 5])]
        assert "[3, 5]" in summary

    def test_page_that_always_crashes_is_kept_empty(self, pages_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pipeline.subprocess, "run", FakeWorker(4, crash_with_layout=set(), crash_always={2}))

        summary = pipeline._parse_report(REPORT)

        pages = pipeline._read_pages(pages_dir / "nordea_2025.jsonl")
        assert [page.page for page in pages] == [1, 2, 3, 4]
        assert pages[1].blocks == []
        assert "page(s) [2] left empty" in summary

    def test_python_error_is_raised_not_retried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def failing_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(command, 1, "", "Traceback (most recent call last):\n  ImportError")

        monkeypatch.setattr(pipeline.subprocess, "run", failing_run)
        with pytest.raises(RuntimeError, match="ImportError"):
            pipeline._parse_report(REPORT)

    def test_line_cut_off_by_a_crash_is_parsed_again(self, pages_dir: Path) -> None:
        cache = pages_dir / "nordea_2025.partial.jsonl"
        complete = Page(bank="nordea", year=2025, page=1, section="", heading="").model_dump_json()
        cache.write_text(complete + "\n" + complete[:20], encoding="utf-8")

        assert [page.page for page in pipeline._read_pages(cache)] == [1]
