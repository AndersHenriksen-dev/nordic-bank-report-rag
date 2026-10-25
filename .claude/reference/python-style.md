# Python style guide

How Python code is written in this repo, by a human or an agent. This is the single source of truth: `CLAUDE.md` and
other docs link here instead of repeating it. If a rule below conflicts with a comment inside a specific file, this
file wins unless that comment explains a concrete, documented exception.

**Before writing or editing any `.py` file, read this file in full.** A `PreToolUse` hook
([hooks/check_python_style_read.py](../hooks/check_python_style_read.py), wired up in
[settings.json](../settings.json)) enforces this for agents: it blocks `Edit`/`Write`/`NotebookEdit` on a `.py` file
until this file has been read earlier in the same session.

## 1. Enforcement: what is automatic and what is on you

| Concern | Tool | Command | Where it runs |
|---|---|---|---|
| Formatting (PEP 8 layout, quotes, line length) | `ruff format` | `uv run ruff format .` | pre-commit, CI |
| Linting (unused imports, bugs, simplification, annotation presence, docstring presence and shape) | `ruff check` | `uv run ruff check .` | pre-commit, CI |
| Type correctness (not just presence) | `mypy` | `uv run mypy src` | pre-commit, CI |
| Tests | `pytest` | `uv run pytest` | CI |

Ruff and mypy complement each other. Ruff's `ANN` rules only require that a function *has* input and output
annotations; mypy checks that those annotations are consistent (a function annotated `-> int` cannot return a `str`).
Skipping either leaves a gap.

Everything in this table is config, not opinion: see `[tool.ruff]` and `[tool.mypy]` in `pyproject.toml` for the
exact rule sets. If a rule is wrong for this codebase, change the config and say why in the commit. Do not silence it
with `# noqa`.

## 2. Formatting and PEP 8

The baseline is PEP 8, applied by `ruff format`. Do not hand-format and do not argue with it in review. The one
deliberate deviation is line length: **120**, not 79, because modern editors do not wrap at 79 and the extra width
avoids forced line breaks that hurt readability. Everything else in PEP 8 (naming, whitespace, import order through
ruff's `I` rules) applies as written.

Naming:

- `snake_case` for functions, methods, variables and modules.
- `PascalCase` for classes (including Pydantic models and exceptions).
- `UPPER_SNAKE_CASE` for module-level constants.
- Functions are verbs (`parse_report`, not `report_parser`) and data are nouns (`Chunk`, `retrieved_pages`). A
  function name should make a docstring redundant for *what* it does; the docstring carries what a name cannot (why,
  edge cases, units, side effects).

## 3. Typing: every function has input and output types

Every function and method signature declares the type of every parameter and its return value, including `-> None`.
No untyped `def`, no bare `**kwargs: Any` where a `TypedDict` or explicit keyword would do. `Any` is a last resort for
genuinely dynamic boundaries (for example PyMuPDF's untyped page dictionaries), not a way to silence the linter. If you
use it, a comment says why nothing narrower works.

Rules of thumb:

- Validate and parse untyped data (YAML, JSONL caches, CLI arguments, environment variables) at the boundary into a
  typed model. This repo uses Pydantic for that (see `src/bankrag/models.py`) and passes the typed model inward. Do
  not let `dict[str, Any]` travel past the function that parsed it.
- Prefer precise types over `object` or `Any`: `list[Chunk]` not `list`, `Literal["da", "en"]` not `str` for a closed
  set of values.
- Use `from __future__ import annotations` so forward references and modern generic syntax (`list[int]`, not
  `List[int]`) work on the minimum Python version.
- mypy runs in a strict-leaning profile (`disallow_untyped_defs`, `disallow_incomplete_defs`, `check_untyped_defs`,
  `warn_return_any`, `strict_equality`; see `pyproject.toml`). Third-party packages without type information are
  exempted per module in `[[tool.mypy.overrides]]`, not globally. A new untyped dependency needs its own entry.

## 4. Docstrings: Google style, module and function level

Every module and every public function, method and class has a docstring in
[Google style](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings). Ruff's `D` rules
(pydocstyle, `convention = "google"`) enforce presence and shape. They do not check that the content is useful; that
is a review concern.

**Module docstring**: one or two sentences at the top of the file on what the module is responsible for and, if the
path does not make it obvious, why it is a module of its own.

```python
"""Keyword search with BM25 over the chunks.

The index is built in memory from the chunk file: about 5,000 chunks index in under a second, so there is nothing to
cache.
"""
```

**Function and method docstring**: a one-line summary, then `Args`, `Returns` and `Raises` sections when there is
something non-obvious to say. A trivial function whose name says everything still gets a one-line docstring, but no
padded `Args`/`Returns` sections that repeat the type hints.

```python
def routed_search(retriever: Retriever, question: str, k: int = 6) -> list[Hit]:
    """Search only the reports a question names, and balance results across banks.

    Args:
        retriever: The search backend.
        question: The user's question, in English or Danish.
        k: Number of chunks to return. For multi-bank questions it is split between the banks.

    Returns:
        Up to `k` hits, interleaved by rank across banks.
    """
```

Exemptions are configured through `per-file-ignores` in `pyproject.toml`, not left to judgement: test functions and
classes under `tests/` do not need docstrings, because a name like `test_rejects_empty_question` already says what it
checks. Module docstrings are still required in test files.

## 5. Structure: code reads like a book of chapters

A reader should be able to tell what a module does by scanning its function names. Two practices get you there:

- **Order bottom-up.** Put the high-level orchestration function near the bottom of the module, where it reads like a
  table of contents, with the functions it calls above it in roughly the order they are called. Reading from the
  bottom up gives the narrative; a reader who needs a detail scrolls up or jumps to the definition.
- **One level of abstraction per function.** A function that mixes "parse a report" with "rebuild one table row from
  word boxes" does two jobs at two heights. Split it so each function reads as one clear step.

**Discoverability follows usage.** What other code reaches for often should be the easiest to find:

- A package's `__init__.py` re-exports the small set of names other modules are meant to import (its public API), so
  `from bankrag.retrieve import routed_search` works and callers do not need to know which file it lives in. Anything
  not re-exported is internal: importable, but not the intended entry point.
- Common helpers live where they are easy to find (the top of a module, or a clearly named module), not inside the
  one function that happens to need them.
- A helper used by exactly one caller stays next to that caller, or private to it (`_leading_underscore`), until a
  second caller needs it. Do not promote it "in case it is reused".

**Reusable code gets its own module once it is actually reused**, not before. When a package needs internal
structure, split it by what the code *does*, not by type. The current layout:

```
src/bankrag/
    __init__.py   # package docstring
    cli.py        # entry point: thin, parses arguments, delegates at once
    config.py     # paths, bank names, model and price settings
    models.py     # Pydantic models: the data contracts that cross a boundary (files, processes, the API)
    ingest/       # PDF parsing, chunking and the crash-safe parsing pipeline
    retrieve/     # BM25, routing by bank and year, query rewriting
    answer/       # the Claude call with citations, cost and the trace log
    evaluate.py   # eval metrics
```

Grow this structure when code that needs it is written. An empty folder, or a `utils/` with one two-line function
nobody calls, is worse than no folder.

## 6. KISS, DRY, LEAN in practice

- **KISS**: prefer the boring, obvious implementation. If you reach for a metaclass, a decorator factory or an `ABC`
  hierarchy and there is one concrete use case, write the plain version instead.
- **DRY, but not too early**: three similar lines are not a duplication problem. Extract a shared function once there
  is a *second real caller* with the *same* requirement. Code that only looks similar and will change for different
  reasons stays separate.
- **LEAN**: no speculative parameters, feature flags or config knobs for requirements nobody has yet. If a function
  takes an argument, something in the codebase passes a value other than the default; otherwise delete the argument.
- Small, pure functions over large stateful ones wherever the logic allows. They are the unit the tests are written
  against, and they make the bottom-up narrative in §5 work.

## 7. Comments explain why, not how

Default to no comment: a well-named function with a well-typed signature makes the *what* clear. Add a comment only
for something the code cannot say:

- A non-obvious constraint or invariant (`# Nordea's printed page numbers are one lower than the PDF's`).
- A workaround for a specific external bug or limitation, ideally with a reference.
- Why the not-obviously-simpler approach was chosen.
- Behaviour that would surprise a careful reader.

If removing a comment would not confuse a future reader, it does not earn its place. Never narrate the mechanics of
the next line (`# increment counter`).

## 8. Testing conventions

Tests use `pytest`:

- **Mock and monkeypatch at the boundary, not the logic.** Anything that leaves the process (HTTP calls, the file
  system, subprocesses, the clock, environment variables) is mocked (`unittest.mock`) or patched (pytest's
  `monkeypatch`); the code under test runs for real. Do not mock the function you are testing, and do not use a mock
  where a plain typed argument would do.
- **Test classes are fine, and often cleaner.** Where several tests share setup or a common contract, group them in a
  class rather than repeating the setup. Subclassing a base test class to run the same tests against another
  implementation (one base class per interface, one subclass per implementation) is a good use of inheritance here.
- Tests follow the same typing rule as everything else (§3), but test functions and classes are exempt from the
  docstring requirement (§4): `per-file-ignores` drops `D101`/`D102`/`D103` under `tests/`. Module docstrings in test
  files are still required.

## 9. Where this fits in the repo

This file is indexed from [CLAUDE.md](../../CLAUDE.md). It is enforced in two ways: automatically (`ruff`, `mypy`, the
pre-commit hooks in `.pre-commit-config.yaml` and the CI job in
[.github/workflows/ci.yml](../../.github/workflows/ci.yml)) for anything a tool can check, and by this document plus
code review for the judgement calls in §5, §6 and §7.
