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
- **One prompt line for side remarks.** The grounding check found 3 of 19 answers mentioning figures from other tables without citing them. Adding "leave out other tables, other entities and other figures that do not answer the question, and never mention a figure without citing the passage it comes from" brought it to 19 of 19 in three of the next four runs, with no other metric changing. The fourth run had 18 of 19: a comparison answer gave Nordea's correct figures without citing them. Answers vary from run to run, so the results page shows the latest run, not the best one.

## 14. A local web page that shows the evidence, not just the answer

The front-end (`make app`, Streamlit) shows, for each question, Claude's reasoning summary, the answer with citation markers, latency, cost and tokens, and one tab per cited page with the cited passage highlighted on an image of that page. A panel lists the six passages the search sent to Claude and which of them were cited, which also makes retrieval problems visible.

- **Streamlit, not FastAPI and HTML.** One Python file, no front-end build, and it follows the same style rules as the rest of the code.
- **Reasoning summaries.** Answers now request `thinking: {type: "adaptive", display: "summarized"}`. Thinking is billed the same whether it is shown or not, so showing the summary costs nothing extra. At low effort Claude skips reasoning on simple lookups, and the page says so.
- **Highlighting the cited passage on the page.** Claude cites passages as the parser wrote them, with tables rebuilt as rows and lines joined, so the passage is not searched as one string. Prose is searched in overlapping windows of 8 words, and a match only counts if a neighbouring window matched next to it, because short phrases repeat on a page. A table row is found by its label, and only figures on the label's line count, with no words in between, which tells a table row from a sentence that uses the same words. Rows without figures, such as "EURm | 2025 | 2024", are not highlighted.
- **Only the rows the answer uses.** Claude cites a whole table block, but an answer usually uses one or two rows. The page highlights and quotes only the rows that share a figure with the answer, plus header rows for context.
- **A close-up first.** Report pages are often wide spreads, so the page shows a crop around the highlighted area and keeps the whole page one click away.
- **Local only.** The page images need the PDFs, which are not in the repository, and every question spends API credit, so the server listens on `localhost` only. A public demo will be a recording, as the hand-off asks.

## 15. Hybrid search: BM25 and bge-m3 vectors fused by rank, then a cross-encoder reranker

The default search is now four steps: route the question to the banks and years it names, search BM25 and dense vectors separately, fuse the two rankings with reciprocal rank fusion (RRF), and let a cross-encoder rerank the fused top 30 down to the 6 passages Claude sees.

- **Embeddings: `BAAI/bge-m3`.** Multilingual (Danish questions, English reports), open (MIT), runs locally so the demo needs no second paid key, and handles inputs up to 8,192 tokens, so whole tables fit. Swappable with `BANKRAG_EMBED_MODEL`; the index rebuilds itself when the model or the chunks change.
- **Qdrant embedded.** Qdrant runs in-process with its data in `data/index/qdrant`, so there is no server or Docker. Bank and year routing become payload filters. The price is a folder lock: one process at a time.
- **Fusion in Python, not in Qdrant.** BM25 stays in `bm25s`, the same implementation the earlier evals measured, so the comparison changes one thing at a time. Qdrant's Query API could fuse sparse and dense vectors server-side with the same RRF; moving BM25 into Qdrant as sparse vectors is a possible next step, not a quality change.
- **Reranker: `BAAI/bge-reranker-v2-m3`** (Apache 2.0, multilingual) on the top 30. It reads question and passage together, so it judges whether a passage answers the question rather than whether it shares words or a topic with it.
- **GPU when there is one.** On my RTX 5070 building the index took about two minutes, including the 2.3 GB model download, and a reranked search takes about half a second (535 ms mean, 924 ms p95, against under 1 ms for BM25). On Windows PyTorch comes from the CUDA 13.0 index; on Linux, including CI, from the CPU index, which keeps CI small.

What the evals showed (22 answerable questions, all routed with the Danish glossary):

| Setup | Recall@1 | Recall@3 | Recall@6 | MRR |
|---|---|---|---|---|
| BM25 | 0.16 | 0.59 | 0.89 | 0.46 |
| Dense | 0.17 | 0.52 | 0.74 | 0.44 |
| Hybrid (RRF) | 0.36 | 0.64 | 0.85 | 0.58 |
| Hybrid + reranker | 0.41 | 0.83 | 0.94 | 0.65 |

- Dense search alone is weaker than BM25 here. Annual reports are full of exact terms ("CET1", "cost/income ratio") and figures in tables, which keyword search matches directly.
- Fusion more than doubles recall@1, because a page both searches rank fairly high is usually the right one.
- The reranker lifts recall@3 from 0.59 to 0.83 and recall@6 from 0.89 to 0.94. It fixes the two misses I had listed in milestone 1 (Jyske Bank's impairment drivers, and the three-bank CET1 comparison), and it finds two pages with Jyske Bank's net interest income for both years that BM25 never ranked high. With it, 17 of 17 numeric answers are exact, up from 16 of 17, at about 10% more cost per answer (USD 0.00103 against 0.00093).
- It also loses two questions. For "What drove the increase in Danske Bank's net fee income?" it prefers business-unit pages ("Net fee income decreased 4%" in Personal Customers) over the group's financial review, and drops the gold page to rank 9. Group versus business-unit figures is a known weak spot.
- The Danish glossary still helps dense search a little (recall@6 0.70 to 0.74), so it stays on.
- These numbers include a correction: the reranked search surfaced pages 23 and 140 of Jyske Bank's 2025 report, which hold the net interest income figures but were missing from my gold list. I checked both in the PDF and added them, which raised every setup that finds them.

A mistake on the way: I first blamed the reranker's lost question on score ties, because the printed scores all read "1.00". The scores were only rounded in my printout; at full precision they differ and the order is the same in half and full precision. The reranker now reports raw scores, which are readable in the web page.

Rerun on the 44-question set (35 answerable): BM25 0.20 / 0.54 / 0.80 / 0.46, dense 0.24 / 0.57 / 0.74 / 0.50, hybrid 0.38 / 0.64 / 0.82 / 0.61, hybrid with the reranker 0.50 / 0.84 / 0.95 / 0.71 (recall@1, @3, @6, MRR). The order of the four setups holds. Dense search alone now beats BM25 at rank 1 but still finds less of the evidence in the top 6.

## 16. A bigger eval set, checked page by page, and an LLM judge with a written rubric

The eval set grew from 27 to 44 questions to meet the brief's 40 to 60: 10 lookups, 6 comparisons across years, 6 across banks, 7 "why" questions, 6 Danish questions and 9 that the reports cannot answer. The new questions fill the gaps the first set had: few 2024 figures, few Jyske Bank questions, and only three comparisons across banks.

- **Every gold figure and page is checked in the parsed page text**, with `scripts/find_pages.py`, following the `add-eval-case` project skill. That is how the new questions found a restatement (Jyske Bank's 2024 net interest income is DKK 9,455 million in the 2024 report and DKK 9,544 million in the 2025 report) and four different employee counts in one report (group key figures, an IFRS note, the sustainability statement and the parent company). Such questions stay in the set, with every defensible figure accepted, because a user would ask them.
- **A bank's own outlook is answerable.** "What net profit does Danske Bank expect for 2026?" has a cited answer in the report (DKK 22-24 billion). The system must report it, not refuse it as a forecast. Questions that ask the system itself to predict (a share price, next year's dividend) stay unanswerable.
- **The figure checks cannot grade a "why" answer** (are the right drivers named?) **or catch a comparison that contradicts itself** with correct figures, which happened once in milestone 1. An LLM judge reads the question, the gold answer and the system's answer, and decides three things: correct, complete and consistent. The rubric is a file, [evals/judge_rubric.md](../evals/judge_rubric.md), sent as the judge's system prompt, so the rubric a reader sees is the one the judge uses.
- **Three yes-or-no criteria instead of a 1 to 5 score.** A yes or no per criterion is easier to check by hand and to compare between runs than a score, and each verdict comes with a one-sentence reason written before the decision.
- **Structured output.** The verdict comes back as JSON that must match a Pydantic model, so a run never fails on an unreadable verdict. A judge that declines or is cut off is reported and skipped, not counted as a pass.
- **The judge does not see the report pages.** Whether figures come from the cited passages is already checked by the figure-grounding metric (D13); the judge compares with the gold answer, which is checked against the PDF.
- **Same cheap model as the answers.** Claude Haiku 5.5 at low effort should cost about USD 0.0003 per verdict, estimated from the token counts until a run measures it. A model grading its own family's answers may be lenient, so a stronger judge is one environment variable away (`BANKRAG_JUDGE_MODEL`), and the verdicts are written into `evals/ANSWERS.md` for me to spot-check.
