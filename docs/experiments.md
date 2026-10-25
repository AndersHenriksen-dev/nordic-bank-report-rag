# What I tried, and what each change did

Every change below was measured on the eval set: 27 questions, 22 of them answerable from the reports and 5 that must be refused (see [evals/ANSWERS.md](../evals/ANSWERS.md)). The latest numbers are in [evals/RESULTS.md](../evals/RESULTS.md), and the reasoning behind each choice is in [decisions.md](decisions.md), referred to below as D1, D2 and so on.

**Recall@k**: the share of a question's evidence (one page per bank or year it needs) found among the top k passages. Claude sees the top 6. **MRR**: 1 divided by the rank of the first right page, averaged. 1.0 means the right page always comes first.

## Retrieval, one change at a time

| # | Change | Recall@1 | Recall@3 | Recall@6 | MRR | Kept? |
|---|---|---|---|---|---|---|
| 1 | BM25 over fixed 500-token windows (baseline) | 0.17 | 0.17 | 0.52 | 0.34 | Baseline |
| 2 | Chunks that follow sections, keep tables whole and never cross a page | 0.11 | 0.31 | 0.52 | 0.32 | Yes: recall@10 0.68 to 0.76, and one page per citation (D3) |
| 3 | Search only the banks and years the question names, balanced across banks | 0.16 | 0.50 | 0.80 | 0.43 | Yes (D4) |
| 4 | Add English report wording to Danish finance terms | 0.16 | 0.59 | 0.89 | 0.45 | Yes (D11) |
| 5 | Dense vectors (`bge-m3` in Qdrant) instead of BM25 | 0.17 | 0.52 | 0.70 | 0.43 | Not on its own: weaker on figures and exact terms (D15) |
| 6 | Hybrid: BM25 and dense fused by reciprocal rank fusion | 0.36 | 0.64 | 0.85 | 0.57 | Yes, as the base for step 7 (D15) |
| 7 | Cross-encoder reranker (`bge-reranker-v2-m3`) on the hybrid top 30 | **0.41** | **0.79** | **0.89** | **0.62** | Yes, the default. Adds about 0.5 s per question on a GPU (D15) |

From step 1 to step 7 the right page comes first 2.4 times as often (recall@1 0.17 to 0.41), and recall@3 rises from 0.17 to 0.79.

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
| Evaluation | Recall@k from one deep search cut to k | Not what the answer model sees, because routing splits k between banks | No: the eval searches at each k |
| Web page | Highlighting cited passages on the page image | Repeated phrases, whole tables and header rows lit up at first | Kept with four rules: neighbouring windows must agree, table rows found by label with figures on the same line, only rows the answer uses, no rows without figures (D14) |

## Where it still breaks

- **One figure question no setup answers.** Only dense search finds the pages with Jyske Bank's net interest income for both years, at ranks 19 and 23. BM25 does not have them in its top 30, so fusion never ranks them high and the reranker never sees them. The model says the figure is missing instead of guessing. Fusing deeper, or letting the reranker see more candidates, are the next things to try.
- **Group versus business unit.** Asked about Danske Bank's net fee income, the reranker prefers business-unit pages over the group's financial review.
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
