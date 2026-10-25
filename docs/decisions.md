# Design decisions

One entry per choice, with the reason. Newest last.

## 1. Cite PDF page numbers, not printed page labels

Nordea's printed page numbers are one lower than the PDF page numbers; Danske Bank's match. I cite the PDF page, because that is the page a reader can jump to in any PDF viewer, and gold answers in the eval set use the same numbering.

## 2. Rebuild tables row by row from word positions

PyMuPDF's table finder locates tables well, but its cell output merges columns on many report tables (for example the five-year overview on page 4 of Danske Bank's 2025 report). I keep the table regions it finds and rebuild each row from the word boxes inside: words on the same line form a row, and a gap wider than a normal space starts a new cell. Each label then sits next to its figures, which is what both keyword search and the answer model need.

Known weakness: when a table's header row (the years) sits in a separate region, the rebuilt table has no column headers. The prompt tells the model to say so rather than guess.

## 3. Chunks never cross a page

A chunk spans at most one page, so a citation always points at exactly one page. Paragraphs are packed to about 500 tokens (800 at most) with the last paragraph repeated as overlap. Tables are never split unless they exceed 1,200 tokens, in which case they are cut between rows with the header rows repeated. Each chunk starts with a context line (bank, report, page, section heading).

The evals compare this with fixed 500-token windows that ignore paragraphs and tables.

## 4. Route on bank names and years in the question

If a question names banks or years, search only those reports. For questions about two or three banks, each bank is searched separately and the results are interleaved by rank (each bank's best hit, then each bank's second best), because plain top-k search tends to fill every slot with the bank whose wording matches best. My first version sorted the per-bank results by score, which let one bank take all the top slots again once the list was cut to k. The evals compare search with and without routing.

## 5. Claude Haiku 5.5 for answers, with search-result citations

Anders asked to keep running costs as low as possible, so answers use Claude Haiku 5.5 (USD 0.10 per million input tokens, 0.50 per million output tokens, October 2026), configurable with `BANKRAG_MODEL`. Retrieved chunks go to Claude as `search_result` blocks with citations enabled, so each sentence in the answer carries citations that point at the exact passages used. The system prompt is the same on every call and marked for prompt caching.

## 6. Refusals use a fixed opening phrase

Citations cannot be combined with structured output, so the model signals a refusal by starting with "Not in the documents." (or "Ikke i dokumenterne."). The eval checks for that phrase.

## 7. Jyske Bank's reports are downloaded by hand

Jyske Bank's site answers scripted downloads with a bot check (HTTP 403). The download script does not try to get around it: it prints the URL, a person saves the file, and the script then verifies the checksum.

## 8. Parse each report in a child process that can crash and restart

PyMuPDF 2.0 detects tables with a layout model. Without it, the line-based detector finds none of Nordea's key figure tables, because they have no ruling lines (pages 40 and 42 of the 2025 report). But the model crashes the Python process with an access violation on some pages, for example page 3 of Nordea's 2025 report, on Python 3.12 and 3.14 alike.

So each report is parsed in a child process that writes every page to disk as soon as it is done. When the child crashes, the pipeline restarts it at the crashing page with the layout model switched off for that page only. A page that crashes even then is kept as an empty page. The ingest output lists every page that needed the fallback.

## 9. Pin Python 3.12

uv picked Python 3.14 when nothing was pinned. `.python-version` now pins 3.12, the version installed on my machine, which also has the most mature wheels for PyMuPDF and onnxruntime.

## 10. Sections from the PDF outline, the navigation bar or large headings

Every chunk carries a section path such as "Management's report > Financial review", which keyword search can match and which shows up in citations. Nordea's PDFs have an outline (bookmarks), which gives the path directly. Danske Bank's and Jyske Bank's do not, so the parser combines two signals:

- The navigation bar at the top of each page gives the part of the report. The current part is styled differently from the other tabs (white text at Danske Bank), and the tab that stands out most from the majority wins.
- Large headings (18 pt and up) start a new section within that part.

Large text is only treated as a heading if it reads like one: at least four letters, mostly letters, starting with a capital or a digit, at most 12 words, and not a figure callout such as "DKK 6,307 million". Without this filter, chart labels like "'24" and arrows became section names, and the notes to Danske Bank's financial statements were all filed under "Contents".

## 11. A Danish glossary for keyword search

The reports are in English, so keyword search cannot match a Danish question such as "Hvad var Nordeas egenkapitalforrentning i 2025?". When a question looks Danish (æ, ø, å or Danish question words), about 25 Danish finance terms are expanded with the English wording the reports use ("egenkapitalforrentning" adds "return on equity"). The original words stay in the query. It is a fixed list, cheap and easy to inspect. Multilingual embeddings in milestone 2 should make it matter less, and the evals show how much it adds.

## 12. Python follows my standard style guide

All Python follows [.claude/reference/python-style.md](../.claude/reference/python-style.md), my standard guide from another project, adapted with this project's examples. In short: ruff with a 120-character line, typed signatures checked by mypy in a strict profile, Google-style docstrings, Pydantic models for every piece of data that crosses a boundary, high-level functions at the bottom of each module, and comments that explain why. Ruff, mypy, line-ending fixes and gitleaks run in pre-commit and CI, and a Claude Code hook makes an agent read the guide before it edits Python.

Choices made while adopting it:

- **Google docstrings, not NumPy.** An older guide of mine uses NumPy-style docstrings for API documentation. The newer guide, which comes with the enforcement setup, uses Google style, so that is the one followed here.
- **Pydantic at the boundaries.** Page caches, chunk files, eval questions and answers are Pydantic models (`src/bankrag/models.py`). A page cache line cut off by a crash now fails validation and is parsed again, instead of relying on a JSON error.
- **Local ruff and mypy hooks.** Pre-commit runs ruff and mypy through `uv run`, so they use the versions in `uv.lock` rather than a second pinned copy.
- **Rules not adopted.** The source project also bans any credit to the agent in commits and pull requests. That conflicts with this repo's purpose, which is to show openly what Claude Code built, so it is not adopted here.

The rewrite changed no behaviour: re-chunking the cached pages gives byte-identical chunks, and the retrieval evals give the same numbers.

## 13. Answers keep citations inline, and figures are checked against the cited passages

- **Citations stay inline.** Claude uses a cited block in two ways: for its own claim, or, more often with Haiku 5.5, for a verbatim quote of the source (an English sentence or a table row) placed after its own uncited sentence. I tried turning cited blocks into footnotes, but where a cited block carried the claim, the sentence broke ("It notes that the balance [2]."). Inline keeps every claim. The cost is cosmetic: English quotes inside Danish answers.
- **Plain text and a robust refusal check.** The prompt asks for plain text in the reader's language. The refusal check ignores case and Markdown, after the model once bolded "Not in the documents." and the eval missed the refusal.
- **No analyst price targets.** Asked for a future share price, the model refused but then quoted the analysts' average price target from the report. The prompt now forbids price targets, analyst estimates and recommendations, while still allowing the bank's own guidance.
- **Figure grounding instead of a page list.** My first citation metric (each cited page is a gold page or quotes a gold figure) scored 50%, because good answers also cite definitions and supporting tables. It is replaced by a check of what the hand-off asks: does the cited passage contain the claim? Every figure in an answer must appear in a passage the answer cites, at the precision given, or be the difference, sum or percentage change of two figures in the answer. Years, numbers below 10, page and note references and product names are not figures. Claims without figures need an LLM judge, planned for milestone 2.
- **One prompt line for side remarks.** The grounding check found 3 of 19 answers mentioning figures from other tables without citing them. Adding "leave out other tables, other entities and other figures that do not answer the question, and never mention a figure without citing the passage it comes from" brought it to 19 of 19 in two consecutive runs, with no other metric changing.
