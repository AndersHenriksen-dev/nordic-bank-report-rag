# Concepts behind this project

A study guide to every idea the system uses, in the order a question meets them, with what each one looks like in this repository. Read it top to bottom once; afterwards the sections work as a reference. Each section ends with where to find the idea in the code or the docs.

Contents:

1. [Retrieval-augmented generation](#1-retrieval-augmented-generation)
2. [Turning PDFs into text](#2-turning-pdfs-into-text)
3. [Chunking](#3-chunking)
4. [Keyword search with BM25](#4-keyword-search-with-bm25)
5. [Routing and query rewriting](#5-routing-and-query-rewriting)
6. [Embeddings and vector search](#6-embeddings-and-vector-search)
7. [Hybrid search and reciprocal rank fusion](#7-hybrid-search-and-reciprocal-rank-fusion)
8. [Reranking with a cross-encoder](#8-reranking-with-a-cross-encoder)
9. [Generating the answer with Claude](#9-generating-the-answer-with-claude)
10. [Refusals and guardrails](#10-refusals-and-guardrails)
11. [Evaluation](#11-evaluation)
12. [LLM as a judge](#12-llm-as-a-judge)
13. [The engineering around it](#13-the-engineering-around-it)
14. [Banking terms in the reports](#14-banking-terms-in-the-reports)
15. [Questions to test yourself](#15-questions-to-test-yourself)
16. [Further reading](#16-further-reading)

---

## 1. Retrieval-augmented generation

**The idea.** A language model answers from what is in its prompt and what it learned in training. Training knowledge is old, cannot be cited, and is sometimes wrong. Retrieval-augmented generation (RAG) puts a search step in front of the model: find the few passages that hold the answer, give only those to the model, and ask it to answer from them and say which passage supports each claim.

**Why not give the model the whole report?** The twelve reports are about 4.1 million tokens (a token is roughly 3 to 4 characters). That is four times Claude Haiku 5.5's 1 million token context window. Even one report, about 350,000 tokens on average, would cost about USD 0.17 per question at Haiku's price for long prompts, against USD 0.001 for the 6 passages this system sends. Retrieval also makes each step measurable: you can test whether the search found the right page separately from whether the model read it correctly.

**The two halves.** Retrieval quality and generation quality fail in different ways. If the right page is not among the passages, no model can answer well. If it is, a cheap model usually can. In this project most of the gains came from the retrieval half (see [experiments.md](experiments.md)).

In this project: the whole pipeline is in the README's "How it works"; the search is in `src/bankrag/retrieve/`, the answer in `src/bankrag/answer/generate.py`.

## 2. Turning PDFs into text

**Why it is hard.** A PDF stores characters at positions on a page, not paragraphs or tables. Annual reports add multi-column layouts, charts with numbers as labels, tables without ruling lines, and navigation bars repeated on every page.

**What the parser does.**

- **Words with positions.** PyMuPDF returns every word with its coordinates. Lines and paragraphs are rebuilt from those.
- **Tables row by row.** PyMuPDF can find where a table is, but its cell output merged columns on many report tables, separating a row's label from its figures. So the parser takes the table's area and rebuilds each row from the words' vertical positions, writing it as `| label | 2025 figure | 2024 figure |`. A row whose label and figures stay together is what lets a search for "Cost/income ratio" find "45.5".
- **Layout model.** PyMuPDF 2.0 has a layout model (an ONNX neural network) that finds tables without ruling lines, which Nordea uses. It crashed the whole Python process on 3 of 3,553 pages, so each report is parsed in a child process. When the child dies, the parent restarts it at the crashing page with the layout model turned off for that page. No page is lost.
- **Sections.** Each page gets a section name from the PDF's outline, the active tab of the report's navigation bar, or a large heading. A chunk's section ("Financial review", "Notes to the financial statements") helps both the search and the reader.
- **Page numbers.** Everything uses the PDF page number (the one a viewer jumps to), not the printed page label. They differ: Nordea's printed numbers are one lower.

**What still goes wrong.** On some pages the parser breaks a paragraph into line-sized pieces. Claude can then cite the piece next to a figure rather than the piece with it.

In this project: `src/bankrag/ingest/pdf.py`, `pipeline.py`, `worker.py`; decisions 2, 8 and 10.

## 3. Chunking

**What a chunk is.** The unit the search indexes and returns. Too large and a chunk mixes topics, so it matches many questions weakly and costs more to send. Too small and it loses context: a table row without its header row, or a figure without the sentence that says which year it is.

**Two strategies, both measured.**

- **Fixed windows:** every 500 tokens, with 100 tokens of overlap, ignoring structure. Simple, and the baseline.
- **Structure chunks (the default):** paragraphs packed up to about 500 tokens (at most 800), never crossing a page, with the last paragraph repeated at the start of the next chunk as overlap. A table stays whole unless it is longer than 1,200 tokens; then it is cut between rows and the header rows are repeated.

**Why never cross a page.** Every chunk can then cite exactly one page, and a citation is something a reader can check.

**A context line.** Each chunk's indexed text starts with a line such as `[Danske Bank | Annual Report 2025 | page 6 | Executive summary]`, so the bank, year and section are searchable too. Claude gets the body without it.

In this project: `src/bankrag/ingest/chunk.py`; 8,700 structure chunks, 2,902 of them with a table. Decision 3.

## 4. Keyword search with BM25

**The idea.** Score each chunk by how well its words match the query's words. BM25 (Best Matching 25) is the standard formula, used by Elasticsearch and Lucene. For each query term it multiplies two things:

- **How rare the term is (IDF, inverse document frequency).** "CET1" appears in few chunks, so a match is strong evidence. "bank" appears everywhere, so it says little.
- **How often the term appears in the chunk, with diminishing returns (TF saturation).** The second "CET1" adds less than the first, and the tenth almost nothing.

It also divides by the chunk's length relative to the average, so a long chunk does not win just by containing more words.

```
score(chunk, query) = sum over query terms t of
    IDF(t) * tf(t) * (k1 + 1) / (tf(t) + k1 * (1 - b + b * length / average_length))
```

`k1` (1.5 here) controls how fast term frequency saturates; `b` (0.75) controls the length penalty.

**Tokenizing.** Text is lower-cased and split into terms. Figures stay whole ("23,037" is one term, so a query with that figure matches it exactly), and very common English and Danish words ("the", "og") are dropped as stopwords.

**Strengths and limits.** BM25 is exact, fast (under a millisecond here), needs no model, and is very good at the precise terms and figures annual reports are full of. It has no idea that "profit" and "earnings" mean the same, or that "egenkapitalforrentning" is Danish for "return on equity".

In this project: `src/bankrag/retrieve/bm25.py`, built with the `bm25s` library in memory at start-up (a second or two for 8,700 chunks).

## 5. Routing and query rewriting

**Routing (metadata filtering).** The question names banks and years. "What was Nordea's net profit in 2024?" should only search Nordea's 2024 report, so the search gets filters on bank and year. Bank names are matched in English and Danish forms; "the three banks" means all three.

**Balancing comparisons.** "Compare the CET1 ratio of the three banks" needs evidence from each bank. A single search tends to fill every slot with the bank whose wording matches best. So each bank is searched on its own and the results are interleaved by rank: each bank's best passage, then each bank's second best, and so on. With 6 slots and 3 banks, each bank gets 2. An early version sorted the merged list by score, which undid the balance; it was caught by reading the eval misses.

**Query rewriting.** Danish questions meet English reports. A glossary of 25 Danish finance terms appends the English wording the reports use: "Hvad var Nordeas egenkapitalforrentning i 2025?" gets "return on equity" added. The original words stay. It is cheap and easy to inspect, and it lifted keyword recall@6 from 0.68 to 0.77.

In this project: `src/bankrag/retrieve/route.py` and `rewrite.py`; decisions 4 and 11.

## 6. Embeddings and vector search

**Embeddings.** An embedding model turns a text into a list of numbers (a vector; 1,024 numbers for `bge-m3`) so that texts with similar meaning get vectors pointing in similar directions. It learned this from millions of pairs of related texts. "Net profit fell" and "earnings decreased" land close together, and so do a Danish question and an English passage about the same thing, because `bge-m3` is multilingual.

**Similarity.** Closeness is measured with cosine similarity: the cosine of the angle between two vectors, 1 for the same direction and 0 for unrelated. The vectors are normalized to length 1, so cosine similarity is just the dot product.

**Bi-encoder.** The question and each passage are embedded separately. That is what makes vector search fast: all 8,700 passages are embedded once at ingest, and a question needs one embedding and a comparison against the stored vectors.

**Vector database.** Qdrant stores the vectors with a payload (bank, year, chunk id), so the routing filters from section 5 work here too. It runs embedded, inside the Python process, with its data in `data/index/qdrant`: no server and no Docker, at the price of a folder lock that lets only one process search at a time. Large deployments use an approximate index such as HNSW (a graph of near neighbours) to search millions of vectors; at this size every vector can simply be compared.

**The index fingerprint.** The index stores a hash of the model name and every chunk's text. `bankrag ingest` rebuilds it only when that hash changes.

**Strengths and limits.** Dense search handles paraphrase and language well. It is weaker on exact figures and rare terms: "CET1" and "Common Equity Tier 1" may embed close together, but "23,037" is not a meaning. On this eval set dense search alone put the right page first about as often as BM25 (recall@1 0.24 against 0.23) but found less of the evidence in the top 6 (0.74 against 0.77).

**On the GPU.** The model has about 570 million parameters (2.3 GB in 32-bit floats). On a GPU it runs in 16-bit floats, which halves memory and time with no change in the results measured here.

In this project: `src/bankrag/retrieve/neural.py` (the models) and `dense.py` (Qdrant); decision 15.

## 7. Hybrid search and reciprocal rank fusion

**Why combine.** BM25 and dense search fail on different questions, so a page that both rank fairly high is usually the right one.

**Why not add the scores.** A BM25 score of 12.3 and a cosine similarity of 0.71 are on different scales, and the scales change from query to query. Normalizing them is fragile.

**Reciprocal rank fusion (RRF)** ignores the scores and uses only the ranks. Each search contributes `1 / (k + rank)` for every passage it returns, and the passages are sorted by the sum:

```
fused(passage) = 1 / (60 + rank in BM25) + 1 / (60 + rank in dense)
```

A passage ranked 1st by BM25 and 5th by dense scores 1/61 + 1/65 = 0.0318. One ranked 1st by BM25 and missing from dense scores 1/61 = 0.0164. Agreement wins. The constant `k = 60` comes from the original paper and damps the difference between rank 1 and rank 2, so one search's top hit cannot dominate. Each search contributes its top 30.

**What it did.** Recall@1 rose from 0.23 (BM25) to 0.39. Recall@6 rose only slightly, from 0.77 to 0.82, because fusion also pulls in passages that are merely on topic.

In this project: `src/bankrag/retrieve/hybrid.py`.

## 8. Reranking with a cross-encoder

**Cross-encoder against bi-encoder.** A bi-encoder (section 6) embeds question and passage separately and compares the results; the two texts never "see" each other. A cross-encoder reads the question and the passage together as one input and outputs one relevance score. It can notice that a passage about Personal Customers' fee income does not answer a question about the group's, which a similarity of topics cannot.

**Why only the top 30.** A cross-encoder must run once per question-passage pair, so it cannot score 8,700 passages per question. The usual pattern is two stages: a cheap search narrows to a few dozen candidates, and the expensive model reorders them. Here the fused top 30 are reranked and the best 6 go to Claude. On the GPU that takes about half a second.

**Scores.** The model outputs a raw score (a logit); higher is better. The default squashes it through a sigmoid into 0 to 1, but then every good match reads 0.999, so the system shows raw scores. The order is the same either way. (A printout rounded to two decimals once made the scores look tied; a full-precision rerun showed they were not.)

**What it did.** Recall@3 from 0.68 to 0.84, recall@6 from 0.82 to 0.94, MRR from 0.62 to 0.71. It still prefers business-unit pages over the group's financial review for some questions, the main weakness left.

In this project: `src/bankrag/retrieve/rerank.py` with `BAAI/bge-reranker-v2-m3`; decision 15.

## 9. Generating the answer with Claude

**The call.** One request to the Claude Messages API with Claude Haiku 5.5, the cheapest current model:

- **System prompt:** the rules (section 10), the same on every call.
- **User message:** the 6 passages, then the question.
- **Output:** text, plus a short summary of Claude's reasoning.

**Search result blocks and citations.** Each passage is sent as a `search_result` block with a title ("Nordea, Annual Report 2025, page 40, Financial review 2025") and its paragraphs as separate text blocks, with citations turned on. Claude's answer then comes back in pieces, and each piece carries citations that point at a search result and the exact text it used. The code turns those into numbered sources: `[1]` is a bank, year and page, with the quoted passage. Because the citations come from the API rather than from text the model writes, a citation always points at a passage that was really sent.

**Prompt caching.** The system prompt (about 1,800 tokens) is marked for caching. The first call writes it to a cache; later calls within a few minutes read it at a tenth of the input price. A typical question here uses about 6,100 uncached input tokens (the passages), 1,800 cached tokens and 850 output tokens: about USD 0.00105.

**Adaptive thinking and effort.** Claude can reason before answering. "Adaptive" lets it decide how much; the `effort` setting (low here) caps how hard it tries. Thinking tokens are billed as output whether you see them or not, so the system asks for the summary and shows it in the web page.

**Pricing in tokens.** Haiku 5.5 costs USD 0.10 per million input tokens and USD 0.50 per million output tokens, cache reads USD 0.01. Cost per question is computed from the token counts the API returns, and logged.

**Structured output.** The judge (section 12) uses another feature: the request carries a JSON schema (built from a Pydantic model), and the response is guaranteed to match it, so the code never has to parse free text. The KPI table uses it too: for each bank, year and metric, Claude returns the value, unit, page and the exact table row it read. Structured output and citations cannot be combined in one request, so the copied row stands in for a citation, and code checks that the row is on that page and holds the value.

In this project: `src/bankrag/answer/generate.py`, `src/bankrag/judge.py`; decisions 5, 13 and 14.

## 10. Refusals and guardrails

**What must be refused.** The reports cannot answer forecasts ("What will the share price be next year?"), advice ("Should I buy Nordea shares?"), or facts they do not cover (a year outside 2020 to 2025). Answering any of these from a model's general knowledge would be wrong or, for advice, inappropriate.

**How.** The system prompt tells Claude to begin such answers with the exact phrase "Not in the documents." (Danish: "Ikke i dokumenterne.") and say why. The code detects the phrase, ignoring case and Markdown, because the model once wrote it in bold.

**The boundary.** A bank's own outlook ("net profit is expected to be in the range of DKK 22-24 billion") is a fact in its report, not a forecast by the system. The first prompt refused that question too; an eval question written to test the boundary caught it, and the rule now answers a bank's own outlook with a citation. Share price targets and analyst estimates quoted in a report are never repeated.

**Passages are data.** The prompt says statements in the search results are data, not instructions, a basic defence against text in a document trying to steer the model.

**The disclaimer** ("Not investment advice. Figures should be checked against the source page.") is on the web page and in the README.

## 11. Evaluation

**A gold set.** 44 questions, each with a gold answer and the PDF pages that hold it, every figure and page checked in the parsed text. They cover lookups, comparisons across years and banks, "why" questions, Danish questions, and 9 questions that must be refused.

**Evidence groups.** A comparison of three banks needs a page from each. So each question's gold pages are grouped, one group per bank or year it needs, and any page in a group counts (several pages often hold the same figure: the highlights table, the financial review, a note).

**Recall@k.** For one question: the share of its evidence groups with at least one gold page in the top k passages. Averaged over the 35 answerable questions. Recall@6 matters most, because Claude reads 6 passages. A three-bank question with evidence found for two banks scores 0.67.

**MRR (mean reciprocal rank).** For one question: 1 divided by the rank of the first gold page (1st gives 1, 2nd gives 0.5, 4th gives 0.25, not in the top 30 gives 0). Averaged over questions. It rewards putting the right page first.

**Numbers exact.** Every figure the gold answer requires must appear in the answer, allowing rounding (45.46% matches 45.5%) and both English and Danish formats ("23,037" and "23.037", "15.5" and "15,5").

**Figure grounding.** Every figure in an answer must appear in a passage the answer cites, at the precision the answer gives, or be a difference, sum or percentage change of other figures in the answer. This catches a figure the model took from somewhere other than its cited sources. Years, small numbers and page references do not count as figures.

**Refusal rate.** Unanswerable questions refused (9 of 9), and answerable ones wrongly refused (0).

**Cost and latency.** Mean and 95th percentile per question. The 95th percentile is the value 95% of questions stay under, a better guide to worst cases than the mean.

**Habits that made the numbers trustworthy.**

- Change one thing at a time and rerun the same questions, as in the README's step table.
- Search at each k, rather than cutting one deep search, because routing splits k between banks.
- When a search finds a page not on the gold list, check it in the PDF text; several were real answers missing from the list.
- Read the failures, not just the totals. The first citation metric scored 50%, but reading the failures showed it measured the gold lists more than the answers.
- Expect run-to-run variation: the same 32 questions scored 29 and 26 on grounding in two runs, because the model words its answers differently each time.

In this project: `src/bankrag/evaluate.py`, `evals/run_evals.py`, `evals/questions.yaml`, and the generated `evals/RESULTS.md` and `evals/ANSWERS.md`.

## 12. LLM as a judge

**Why.** Figure checks cannot tell whether a "why" answer names the right drivers, or catch an answer that ranks Nordea above Jyske Bank and then says they cannot be ranked. A person could, but not on every run. An LLM judge reads the question, the gold answer and the system's answer, and grades it.

**The rubric.** A written rubric ([evals/judge_rubric.md](../evals/judge_rubric.md)), sent as the judge's system prompt, defines three yes-or-no criteria: correct (agrees with the gold answer), complete (has the main points, which the rubric lists per kind of question), consistent (does not contradict itself). Yes-or-no criteria are easier to check and to compare between runs than a 1 to 5 score. The judge writes a one-sentence reason before deciding.

**Validating the judge.** A judge is itself a model that makes mistakes, so its verdicts were checked against a reading of each answer:

- At low effort it failed 3 good answers, for missing details the rubric calls secondary.
- A sharper rubric alone fixed 2 of those and caused 2 new ones.
- The same rubric at medium effort left 1 wrong verdict in 34, and every clear fault still failed.

The method: judge the same saved answers under each setup, so only the judge changes.

**Known risks.** A model may grade answers from its own family leniently (self-preference), may favour longer answers, and gives different verdicts on reruns. Here the checked verdicts showed strictness rather than leniency. The judge model can be swapped with one setting.

In this project: `src/bankrag/judge.py`; decision 16 and the judge tables in [experiments.md](experiments.md).

## 13. The engineering around it

- **Pydantic models at boundaries.** Everything that crosses a boundary (a cache file, the parser process, the eval YAML, the API) is parsed into a typed model first, so bad data fails loudly at the edge instead of deep inside.
- **Type checking.** Every function has type hints, and mypy checks them in a strict mode. It caught, for example, an untyped value from the Claude SDK.
- **Linting and formatting.** Ruff enforces PEP 8, import order, docstrings and many bug patterns; its formatter removes style debates.
- **Tests without the expensive parts.** Unit tests use small fakes for the search models, an in-memory Qdrant, a PDF built in memory, and a fake HTTP transport for the Claude API. They run in about 10 seconds with no key, models or PDFs, which is why CI can run them.
- **Pre-commit and CI.** Every commit runs ruff, mypy, line-ending fixes and gitleaks (a scanner that blocks API keys and other secrets). GitHub Actions runs lint, types, tests and the secret scan on every pull request.
- **Crash isolation.** A library that crashes the interpreter (section 2) runs in a child process, so the parent can recover.
- **Caching work.** Parsed pages are cached per report, embeddings are rebuilt only when the fingerprint changes, and query embeddings and reranker scores are cached during an eval run.
- **Claude Code setup.** `CLAUDE.md` gives the agent the project's rules. A hook blocks Python edits until the style guide has been read. A project skill (`add-eval-case`) turns "check the gold answer in the PDF" into a repeatable procedure. Settings deny reading `.env`.

## 14. Banking terms in the reports

**The report itself.**

- **Annual report:** a bank's yearly publication. It has a management report (results, strategy, risk, capital), a sustainability statement (required in the EU under the CSRD from 2024), and the financial statements with notes, for the group and for the parent company.
- **Group, parent company, business unit (segment):** the group is the whole bank with its subsidiaries; the parent company is the legal entity at the top (Danske Bank A/S); business units are internal divisions such as Personal Customers or Large Corporates & Institutions. The same metric can appear for all three, which is the system's main source of confusion.
- **Restatement:** a later report changes a previous year's figure, for example after a change in accounting or in what is counted. Jyske Bank's 2024 net interest income is DKK 9,455 million in the 2024 report and DKK 9,544 million in the 2025 report.
- **Outlook or guidance:** the bank's own expectation for next year, such as Danske Bank's DKK 22-24 billion net profit for 2026.
- **Currencies:** Danske Bank and Jyske Bank report in DKK; Nordea, based in Helsinki, reports in EUR. The system never converts.

**Income and costs.**

- **Net interest income (NII):** interest earned on loans and investments minus interest paid on deposits and funding. The largest income line for all three banks.
- **Deposit margin:** what a bank earns on deposits, roughly the market rate minus the rate it pays depositors. When central banks cut rates, deposit margins shrink, which is why Nordea's and Jyske Bank's NII fell in 2025. Nordea's **deposit hedge** locks in rates on part of its deposits, which softens the fall.
- **Net fee and commission income:** fees from everyday banking, asset management (including **performance fees** when funds beat their benchmark), investment and capital markets services.
- **Total income (operating income):** all income lines together.
- **Operating expenses:** staff, IT and other costs.
- **Cost/income ratio:** operating expenses divided by total income. Lower is more efficient. Definitions differ: Danske Bank includes goodwill impairment, and Nordea also reports one excluding regulatory fees.
- **Loan impairment charges:** money set aside for expected loan losses. A net charge reduces profit; a net reversal (releasing earlier provisions) adds to it.
- **Expected credit loss (IFRS 9) and stages:** under the accounting standard IFRS 9, loans sit in stage 1 (performing), stage 2 (significantly more risky) or stage 3 (credit-impaired), with larger provisions in later stages.
- **Post-model adjustments:** provisions management adds on top of the models for risks the models do not capture, such as geopolitical tension. Releasing them lowers impairment charges.
- **Net profit:** profit after tax for the year.

**Returns and capital.**

- **Return on equity (ROE):** net profit divided by average shareholders' equity. Danske Bank 13.3% and Nordea 15.5% in 2025. Jyske Bank reports **return on tangible equity**, which leaves out intangible assets such as goodwill.
- **Risk exposure amount (risk-weighted assets, RWA):** the bank's assets weighted by risk; a safe government bond weighs little, a corporate loan more.
- **CET1 capital:** Common Equity Tier 1, the highest-quality capital (mainly shareholders' equity minus deductions).
- **CET1 ratio:** CET1 capital divided by the risk exposure amount. The key solvency measure. Danske Bank 17.3%, Jyske Bank 16.1% and Nordea 15.7% at the end of 2025. Regulators set a minimum plus buffers; banks hold a management buffer above that.
- **Basel IV / CRR III:** the final Basel III reforms, applied in the EU through the Capital Requirements Regulation from 1 January 2025. They changed how risk weights are calculated and raised Jyske Bank's risk exposure, one reason its CET1 ratio fell.
- **Deduction for expected payouts:** dividends and share buy-backs already planned are deducted from CET1 capital before they are paid.
- **Total capital ratio:** like CET1 but counting all qualifying capital.
- **Dividend, share buy-back, payout ratio:** cash paid per share; the bank buying its own shares; the share of profit returned to shareholders.
- **Basis point (bp):** 0.01 percentage point. **Percentage points** measure the difference between two percentages (17.8% to 17.3% is 0.5 points); **percent** measures relative change.

**Danish terms the glossary handles.** egenkapitalforrentning (return on equity), nettoresultat or årets resultat (net profit), egentlig kernekapitalprocent (CET1 ratio), nettorenteindtægter (net interest income), omkostningsprocent (cost/income ratio), nedskrivninger (impairment charges), udbytte (dividend), aktiekurs (share price), udlån and indlån (lending and deposits). Danish writes numbers the other way round: 23.037 is twenty-three thousand and thirty-seven, and 15,5% is fifteen and a half percent.

**Danmarks Nationalbank** is the Danish central bank. Its policy rate cuts in 2024 and 2025 drove the fall in Jyske Bank's net interest income in both years.

## 15. Questions to test yourself

Short answers below each; the sections above have the details.

1. **Why retrieval instead of sending the whole report?** 4.1 million tokens do not fit in the context window, one report alone would cost about 160 times more per question, and retrieval gives page-level citations and a step you can measure on its own.
2. **Why do chunks never cross a page?** So every citation is one page a reader can open and check.
3. **What does BM25 reward, and what can it not do?** Rare query terms that appear in a chunk, with diminishing returns for repeats and a penalty for length. It cannot match synonyms or another language.
4. **Why use both BM25 and dense vectors?** They fail on different questions: BM25 on paraphrase and Danish, dense on exact figures and terms. Pages both rank high are usually right.
5. **Why reciprocal rank fusion rather than adding scores?** The two scores are on different, query-dependent scales; ranks are comparable.
6. **What is the difference between a bi-encoder and a cross-encoder, and why use both?** A bi-encoder embeds texts separately, so passages can be embedded in advance and searched fast. A cross-encoder reads question and passage together, which is more accurate but needs one model run per pair, so it only reranks the top 30.
7. **What does recall@6 = 0.94 mean here?** Averaged over 35 questions, 94% of the evidence groups they need (one per bank or year) have a gold page among the 6 passages Claude reads.
8. **What does MRR add to recall?** Recall says whether the right page is in the top k; MRR says how high it is.
9. **How do you catch a made-up figure?** Citations come from the API and point at real passages, and the grounding check requires every figure in the answer to be in a cited passage.
10. **How do you trust an LLM judge?** Read its verdicts against the answers, change one thing at a time on the same saved answers, and report its error rate with the score.
11. **How does the system decide to refuse, and where is the line?** The prompt refuses forecasts and advice with a fixed phrase the code detects. A bank's own published outlook is answered, because it is a fact in the report.
12. **Why is the cheapest model enough?** Once the right passages are in the prompt, reading figures from them is easy; the gains came from retrieval.
13. **What fails most often, and what would you try?** Business-unit figures offered next to the group's. Ideas: label chunks as group or segment and prefer group pages, a table of key figures per bank and year that answers lookups directly, and merging paragraphs the parser split.
14. **What does prompt caching save here?** The 1,800-token system prompt is read from the cache at a tenth of the price on every call after the first within a few minutes.
15. **How would this scale to 100 banks?** A Qdrant server with an HNSW index, routing by a list of bank names, batch ingest, and a larger eval set that samples every bank.

## 16. Further reading

- Lewis et al. (2020), "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks", arXiv:2005.11401. The paper that named RAG.
- Robertson and Zaragoza (2009), "The Probabilistic Relevance Framework: BM25 and Beyond". Where BM25 comes from and why it works.
- Karpukhin et al. (2020), "Dense Passage Retrieval for Open-Domain Question Answering", arXiv:2004.04906. Dense retrieval with bi-encoders.
- Reimers and Gurevych (2019), "Sentence-BERT", arXiv:1908.10084. Sentence embeddings, and bi-encoders against cross-encoders.
- Chen et al. (2024), "BGE M3-Embedding", arXiv:2402.03216. The embedding model used here.
- Nogueira and Cho (2019), "Passage Re-ranking with BERT", arXiv:1901.04085. Cross-encoder reranking.
- Cormack, Clarke and Büttcher (2009), "Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods", SIGIR 2009. RRF and the constant 60.
- Malkov and Yashunin (2018), "Efficient and robust approximate nearest neighbor search using Hierarchical Navigable Small World graphs", arXiv:1603.09320. HNSW, for when the index grows.
- Zheng et al. (2023), "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena", arXiv:2306.05685. How well LLM judges agree with people, and their biases.
- The Claude API documentation on citations, search results, prompt caching, extended thinking and structured outputs, at platform.claude.com/docs.
- This repository: [decisions.md](decisions.md) for why each choice was made, [experiments.md](experiments.md) for every result, [documents.md](documents.md) for the six reports.
