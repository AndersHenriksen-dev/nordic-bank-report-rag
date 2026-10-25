# What I tried, and what each change did

Every change below was measured on the eval set: 44 questions, 35 of them answerable from the reports and 9 that must be refused (see [evals/questions.yaml](../evals/questions.yaml)). The set grew from 27 questions during milestone 2; the retrieval table below is rerun on all 44. The latest numbers are in [evals/RESULTS.md](../evals/RESULTS.md), and the reasoning behind each choice is in [decisions.md](decisions.md), referred to below as D1, D2 and so on.

**Recall@k**: the share of a question's evidence (one page per bank or year it needs) found among the top k passages. Claude sees the top 6. **MRR**: 1 divided by the rank of the first right page, averaged. 1.0 means the right page always comes first.

## Retrieval, one change at a time

Measured over the six 2024 and 2025 reports. The same steps over all twelve reports follow in the next section.

| # | Change | Recall@1 | Recall@3 | Recall@6 | MRR | Kept? |
|---|---|---|---|---|---|---|
| 1 | BM25 over fixed 500-token windows (baseline) | 0.12 | 0.19 | 0.48 | 0.31 | Baseline |
| 2 | Chunks that follow sections, keep tables whole and never cross a page | 0.17 | 0.33 | 0.50 | 0.35 | Yes: recall@10 0.61 to 0.69, and one page per citation (D3) |
| 3 | Search only the banks and years the question names, balanced across banks | 0.20 | 0.45 | 0.71 | 0.43 | Yes (D4) |
| 4 | Add English report wording to Danish finance terms | 0.20 | 0.54 | 0.80 | 0.46 | Yes (D11) |
| 5 | Dense vectors (`bge-m3` in Qdrant) instead of BM25 | 0.24 | 0.57 | 0.74 | 0.50 | Not on its own: better at rank 1, but finds less of the evidence in the top 6 (D15) |
| 6 | Hybrid: BM25 and dense fused by reciprocal rank fusion | 0.38 | 0.64 | 0.82 | 0.61 | Yes, as the base for step 7 (D15) |
| 7 | Cross-encoder reranker (`bge-reranker-v2-m3`) on the hybrid top 30 | **0.50** | **0.84** | **0.95** | **0.71** | Yes, the default. Adds about 0.5 s per question on a GPU (D15) |

From step 1 to step 7 the right page comes first 4 times as often (recall@1 0.12 to 0.50), recall@3 rises from 0.19 to 0.84, and recall@6 from 0.48 to 0.95.

On the first 27 questions the same steps scored recall@6 0.52, 0.52, 0.80, 0.89, 0.74, 0.85 and 0.94. The 17 new questions (more 2024 figures, Jyske Bank, three-bank comparisons and Danish) are harder for BM25, whose recall@6 fell from 0.89 to 0.80, and for plain fusion (0.85 to 0.82), but not for the reranked search (0.94 to 0.95). Dense search alone gained at rank 1 (0.17 to 0.24) and now beats BM25 there.

## Adding the 2022 and 2023 reports

Twelve reports instead of six: 3,553 pages instead of 1,867, and 8,700 chunks instead of 4,882. The same 44 questions, none of which names 2022 or 2023:

| # | Change | Recall@1 | Recall@3 | Recall@6 | MRR |
|---|---|---|---|---|---|
| 1 | BM25 over fixed 500-token windows | 0.14 | 0.25 | 0.39 | 0.31 |
| 2 | Chunks that follow sections | 0.19 | 0.28 | 0.47 | 0.33 |
| 3 | Routing by bank and year | 0.23 | 0.44 | 0.68 | 0.44 |
| 4 | Danish glossary | 0.23 | 0.53 | 0.77 | 0.47 |
| 5 | Dense vectors instead of BM25 | 0.24 | 0.57 | 0.74 | 0.50 |
| 6 | Hybrid | 0.39 | 0.68 | 0.82 | 0.62 |
| 7 | Hybrid with the reranker | **0.50** | **0.84** | **0.94** | **0.71** |

- **Routing keeps doubling the corpus cheap.** Every question that names a year searches only that year's reports, so the reranked search is unchanged except recall@6 (0.95 to 0.94).
- **Searches without routing pay the price.** Fixed windows lose most (recall@6 0.48 to 0.39): more reports means more passages about the same topic from other years.
- **The one lost point is not a new report.** For q01 (Danske Bank's cost/income ratio, 2025 against 2024) an investor relations page of the 2025 report now outranks page 5 of the 2024 report ("Danske Bank at a glance"). BM25 counts how rare a term is across all chunks, so a bigger corpus moves scores even inside the routed reports.
- **Older pages appear only where a question names no year.** q12 (how Nordea describes AI) now also gets a page of the 2023 report, but still finds its 2025 gold pages.
- **The new reports exposed a parser bug.** Nordea's 2023 outline has an entry that points at page -1, and the parser took it to start before every page, so 383 of 386 pages were labelled "Annual General Meeting 21 March 2024". Jyske Bank's 2022 and 2023 outlines only name the report. Skipping such entries and ignoring outlines with fewer than 5 usable entries fixed both (D18), checked by re-parsing the three reports.
- **Parsing the six new reports took 23.5 minutes**, with 3 reports at a time in child processes. The layout model crashed on one more page (Nordea 2022, p. 26), which the worker re-parsed without it.

## Answers: BM25 against the reranked search

The first 27 questions answered by Claude Haiku 5.5, once with the passages from step 4 and once from step 7.

| | BM25 (step 4) | Hybrid + reranker (step 7) |
|---|---|---|
| Numeric answers exact | 16 of 17 | **17 of 17** |
| Answers with every figure in a cited passage | 18 or 19 of 19 over four runs | 18 of 19 |
| Answerable questions wrongly refused | 0 | 0 |
| Unanswerable questions refused | 5 of 5 | 5 of 5 |
| Cost per question (USD, mean) | 0.00093 | 0.00103 |
| Time per question (mean) | 4.2 s | 4.5 s for Claude, plus about 0.5 s of search |

The question the reranked search fixed is Jyske Bank's net interest income: it found two pages with both figures (a chart and a note table) that BM25 never ranked high.

## Answers on all 44 questions, with the LLM judge

Two runs with Claude Haiku 5.5 and the reranked search. Between them the refusal rule changed (a bank's own published outlook is now answered) and the judge got a sharper rubric and medium effort instead of low (see below).

| Metric | Run 1 | Run 2 |
|---|---|---|
| Numeric answers exact | 27 of 28 | 27 of 28 |
| Answers with every figure in a cited passage | 29 of 32 | 26 of 32 |
| Unanswerable questions refused | 9 of 9 | 9 of 9 |
| Answerable questions wrongly refused | 1 of 35 | **0 of 35** |
| Answers the judge passed (correct, complete, consistent) | 26 of 34 | 27 of 35 |
| "Why" answers the judge passed | 4 of 7 | 4 of 7 |
| Judge verdicts that a reading of the answer agrees with | 31 of 34 | 34 of 35 |
| Cost per question, mean (USD) | 0.00106, plus 0.00013 per verdict | 0.00105, plus 0.0002 per verdict |
| Time per question, mean | 4.8 s | 5.1 s, plus about 0.5 s of search |

The grounding drop in run 2 comes from answers that quote a source sentence without a citation marker, or add an uncited side remark (one answer has no citations at all). The prompt change touched only the refusal rule, so this looks like the run-to-run variation seen in milestone 1 (16 to 19 of 19), but two runs cannot prove it.

### The judge, measured on identical answers

To separate the judge from the answers, the 34 answers of run 1 were judged three times:

| Judge | Passed | Wrong verdicts, by reading |
|---|---|---|
| First rubric, low effort (run 1) | 26 | 3: q06, q24 and q40 failed for missing secondary details or an explained side remark |
| Rubric with main and secondary points defined, low effort | 26 | 3: q06 and q24 fixed, but q23 and q38 newly failed as "inconsistent" for clumsy wording, and q40 still failed |
| Same rubric, medium effort | 28 | 1: q40 |

q10 failed under all three, which is defensible: the answer says the group figure is not in its passages, and the rubric fails an answer that says the documents lack what the gold answer shows. (The first review of run 1 counted q10 as a wrong verdict; on a second reading it is not.) The four clear faults (q11, q26, q34, q35) failed under all three. A rubric change alone moved errors around instead of removing them, and the low-effort judge disagreed with itself on unchanged answers. Medium effort costs USD 0.0002 instead of 0.00013 per verdict, so it became the default. These readings were made by Claude Code and are still to be checked by hand.

### What the judge failed in run 2

| Question | What is wrong with the answer | Real fault? |
|---|---|---|
| q09 CET1 of Danske Bank and Nordea | States Nordea's 15.7%, then says it cannot tell whether 15.5% on another page is the year-end ratio | Yes: hedges its own figure |
| q10 Danske Bank's fee income drivers | Right drivers, then a second growth rate for a segment it cannot place | Yes: group versus business unit |
| q11 Danske Bank's impairment charges | A business unit's DKK 1,260 million next to the group's DKK 294 million, with no choice between them | Yes: group versus business unit |
| q12 How Nordea uses AI | Gives virtual assistants but not churn prediction or fraud detection | Yes: a thinner answer |
| q26 How the three banks use AI | Misses the advisers' AI tools at Danske Bank and Jyske Bank | Yes: a thinner answer |
| q34 Three banks' cost/income ratios | No Danske Bank figure, and calls Nordea the lowest | Yes: the search found a business unit's ratio |
| q35 Three banks' net profit | Calls Danske Bank's figure the highest, then says the three cannot be ranked | Yes: a mild self-contradiction |
| q40 Jyske Bank's employees (Danish) | Says the report does not explain the gap of 50 between two counts | No: that is true; the footnote explains a gap of 23 |

## Everything else, by stage

| Stage | What I tried | What happened | Kept? |
|---|---|---|---|
| Parsing | PyMuPDF's own table cell output | Merged columns on many report tables, separating labels from figures | No: rows are rebuilt from word positions instead (D2) |
| Parsing | PyMuPDF 2.0's layout model for tables | The only way to find Nordea's tables without ruling lines, but it crashed the process on 2 of 1,867 pages | Yes, in a child process that restarts at a crashing page without the model; no page lost (D8) |
| Parsing | Sections from the PDF outline, the navigation bar or large headings | Chart labels and figure callouts first became section names; a title filter fixed it | Yes (D10) |
| Retrieval | Per-bank results sorted by score | One bank took every top slot again once the list was cut to k | No: interleaved by rank instead (D4) |
| Retrieval | Reranker in half precision | Same order as full precision on every eval question, half the memory | Yes (D15) |
| Answers | Claude Haiku 5.5 with `search_result` citations and a cached system prompt | USD 0.0009 and about 4 s per question | Yes (D5) |
| Answers | Citations as footnotes, quotes moved out of the text | Broke sentences where the cited block carried the claim | No: reverted to inline (D13) |
| Answers | Refusal check on the exact phrase | Missed a refusal the model wrote in bold | Replaced by a check that ignores formatting (D13) |
| Answers | Refusals that mention related figures | One quoted the analysts' share price target, which is close to advice | Prompt now forbids price targets and estimates (D13) |
| Answers | One prompt line against uncited side remarks | Answers with every figure in a cited passage: 16 of 19 to 19 of 19 in three of four runs | Yes (D13) |
| Answers | Showing Claude's reasoning summary | Free: thinking is billed the same whether shown or not | Yes (D14) |
| Evaluation | Citation metric: cited page is on my gold list or quotes a gold figure | 50%, but it mostly measured how complete my gold lists were | No: replaced by figure grounding, every figure must be in a cited passage (D13) |
| Evaluation | Gold evidence lists drafted from my own reading of the PDFs | Better searches kept finding other pages that also hold the answer (a chart, a note table) | Widened for 4 questions, each page checked in the PDF text first |
| Evaluation | Recall@k from one deep search cut to k | Not what the answer model sees, because routing splits k between banks | No: the eval searches at each k |
| Evaluation | 17 more questions, written with a project skill that makes every figure and page checked in the parsed text (`add-eval-case`) | 44 questions: 10 lookups, 6 year comparisons, 6 bank comparisons, 7 "why", 6 Danish and 9 unanswerable. The new ones found a restatement (Jyske Bank's 2024 net interest income), four different employee counts in one report, and two more pages missing from gold lists | Yes (D16) |
| Evaluation | An LLM judge with a written rubric: correct, complete and consistent against the gold answer | Caught a self-contradicting ranking and a business unit's figure offered as the group's, which the figure checks passed. At low effort it also failed 3 good answers | Yes (D16) |
| Evaluation | Defining main and secondary points in the judge's rubric | On the same answers, fixed 2 wrong verdicts and caused 2 new ones | Kept, with medium effort |
| Evaluation | The judge at medium effort instead of low | On the same answers, wrong verdicts fell from 3 to 1, at USD 0.0002 instead of 0.00013 per verdict | Yes (D16) |
| Answers | A refusal rule for forecasts that lets the answer point to the bank's own outlook | The question "What net profit does Danske Bank expect for 2026?" was answered correctly but opened with "Not in the documents.", so it counted as a refusal | No: a bank's own outlook is now answered as a fact in its report, while forecasts by the system are still refused. 0 wrong refusals, 9 of 9 refusals kept (D16) |
| Web page | Highlighting cited passages on the page image | Repeated phrases, whole tables and header rows lit up at first | Kept with four rules: neighbouring windows must agree, table rows found by label with figures on the same line, only rows the answer uses, no rows without figures (D14) |

## Where it still breaks

- **Paragraphs split into pieces.** On some pages the parser breaks a paragraph into line-sized pieces. Claude then cites some pieces of a sentence but not the one with the figure, so a correct figure on the right page fails the strict check that it must be in the cited passage (Jyske Bank's post-model adjustments, "DKK 79m to DKK 1.7bn"). Merging such pieces back into paragraphs is the fix to try.
- **Group versus business unit.** Asked about Danske Bank's net fee income, the reranker prefers business-unit pages over the group's financial review. Asked for the three banks' cost/income ratios, it finds Large Corporates & Institutions' 40.0% and the page that defines the ratio, but not Danske Bank's group figure of 45.5%.
- **A comparison can contradict itself.** One three-bank answer called Danske Bank's 17.3% "the lowest" and then ranked it highest. Another ranked Nordea's EUR 4,840 million above Jyske Bank's DKK 5,414 million and then said the two could not be ranked. Every figure was right, so only the LLM judge catches these.
- **Hedging between figures it cannot place.** When the passages hold a business unit's figure or a figure from a highlights page next to the group's, the answer often reports both and says it cannot tell which is right, instead of preferring the group's financial review. Four of the eight answers the judge failed in run 2 do this.
- **Uncited quotes and side remarks.** Some answers copy a source sentence into the text without a citation marker, or add a figure in a sentence without a citation (Danmarks Nationalbank's average policy rate, the change in Jyske Bank's headcount). The figure-grounding check flags them: 3 to 6 of 32 answers per run.
- **Danish answers quote English.** Claude often adds a verbatim quote of the English source after its own Danish sentence.

## Mistakes along the way, and how they were caught

| Mistake | Caught by |
|---|---|
| Routed results sorted by score, undoing the balance between banks | Reading the eval misses |
| Recall@k computed from one deep search cut to k | Re-reading the eval code while fixing the above |
| The first crash-restart logic would have left crashing pages empty | Its own unit test |
| A number-parser crash introduced during the style rewrite | The first full answer eval |
| A citation metric that measured the gold lists more than the answers | Reading every failing answer |
| The reranker's lost question blamed on score ties | A rerun at full precision: the ties were rounding in a printout |
| Gold evidence lists missing pages that hold the answer, which undercounted recall | Checking every unexpected page a search found against the PDF text |
| A refusal rule that also refuses a bank's own published outlook | An eval question written to test that boundary |
| A judge stricter than its rubric, failing answers for missing secondary details | Reading every failed verdict against the answer |
