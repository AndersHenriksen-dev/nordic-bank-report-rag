# What I tried, and what each change did

Every change below was measured on the eval set: 44 questions, 35 of them answerable from the reports and 9 that must be refused (see [evals/questions.yaml](../evals/questions.yaml)). The set grew from 27 questions during milestone 2; the retrieval table below is rerun on all 44. The latest numbers are in [evals/RESULTS.md](../evals/RESULTS.md), and the reasoning behind each choice is in [decisions.md](decisions.md), referred to below as D1, D2 and so on.

**Recall@k**: the share of a question's evidence (one page per bank or year it needs) found among the top k passages. Claude sees the top 6. **MRR**: 1 divided by the rank of the first right page, averaged. 1.0 means the right page always comes first.

## Retrieval, one change at a time

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

## Answers: BM25 against the reranked search

The first 27 questions answered by Claude Haiku 5.5, once with the passages from step 4 and once from step 7. The full 44-question run, with the LLM judge, has not been done yet.

| | BM25 (step 4) | Hybrid + reranker (step 7) |
|---|---|---|
| Numeric answers exact | 16 of 17 | **17 of 17** |
| Answers with every figure in a cited passage | 18 or 19 of 19 over four runs | 18 of 19 |
| Answerable questions wrongly refused | 0 | 0 |
| Unanswerable questions refused | 5 of 5 | 5 of 5 |
| Cost per question (USD, mean) | 0.00093 | 0.00103 |
| Time per question (mean) | 4.2 s | 4.5 s for Claude, plus about 0.5 s of search |

The question the reranked search fixed is Jyske Bank's net interest income: it found two pages with both figures (a chart and a note table) that BM25 never ranked high.

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
| Evaluation | An LLM judge with a written rubric: correct, complete and consistent against the gold answer | Catches what figure checks cannot, such as a missing driver or a comparison that contradicts itself. Tested offline; not yet run on real answers | Yes (D16) |
| Web page | Highlighting cited passages on the page image | Repeated phrases, whole tables and header rows lit up at first | Kept with four rules: neighbouring windows must agree, table rows found by label with figures on the same line, only rows the answer uses, no rows without figures (D14) |

## Where it still breaks

- **Paragraphs split into pieces.** On some pages the parser breaks a paragraph into line-sized pieces. Claude then cites some pieces of a sentence but not the one with the figure, so a correct figure on the right page fails the strict check that it must be in the cited passage (Jyske Bank's post-model adjustments, "DKK 79m to DKK 1.7bn"). Merging such pieces back into paragraphs is the fix to try.
- **Group versus business unit.** Asked about Danske Bank's net fee income, the reranker prefers business-unit pages over the group's financial review. Asked for the three banks' cost/income ratios, it finds Large Corporates & Institutions' 40.0% and the page that defines the ratio, but not Danske Bank's group figure of 45.5%.
- **A comparison can contradict itself.** One three-bank answer called Danske Bank's 17.3% "the lowest" and then ranked it highest. Every figure was right, so the figure checks cannot catch it; an LLM judge is the next step.
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
