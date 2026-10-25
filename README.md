# Nordic Bank Report RAG

I am building a question answering system over the 2024 and 2025 annual reports of Danske Bank, Nordea and Jyske Bank. Every answer cites the report and page it comes from, and the system is measured against a test set of questions with known answers.

Work in progress. The full README, setup steps and a demo will follow here. What exists so far:

- A web page (`make app`): ask a question in English or Danish and see Claude's reasoning, the answer with citations, and each cited report page with the passage highlighted. It runs on your own machine, because it needs the downloaded PDFs and an API key.
- [docs/documents.md](docs/documents.md): the six reports, where they come from, and what to know when reading them.
- [evals/RESULTS.md](evals/RESULTS.md): retrieval and answer metrics from the latest eval run.
- [evals/ANSWERS.md](evals/ANSWERS.md): every eval question with its gold answer, the system's answer and the passages it cites.
- [evals/judge_rubric.md](evals/judge_rubric.md): the written rubric an LLM judge uses to grade each answer against its gold answer.
- [docs/decisions.md](docs/decisions.md): the design choices and why I made them.
- [docs/experiments.md](docs/experiments.md): every strategy I tried, what it did to the numbers, and what I kept.

## What I tried

Each step was measured on the 35 answerable questions of a 44-question eval set (lookups, comparisons across banks and years, "why" questions, 8 in Danish, and 9 the reports cannot answer). Recall@k is the share of the needed evidence found in the top k passages; Claude reads the top 6.

| Step | Recall@1 | Recall@3 | Recall@6 |
|---|---|---|---|
| BM25 over fixed 500-token windows | 0.12 | 0.19 | 0.48 |
| + chunks that follow sections and keep tables whole | 0.17 | 0.33 | 0.50 |
| + search only the banks and years the question names | 0.20 | 0.45 | 0.71 |
| + English report wording for Danish finance terms | 0.20 | 0.54 | 0.80 |
| Dense vectors (`bge-m3`) alone, for comparison | 0.24 | 0.57 | 0.74 |
| BM25 and dense fused by reciprocal rank fusion | 0.38 | 0.64 | 0.82 |
| + cross-encoder reranker (`bge-reranker-v2-m3`) on the top 30 | **0.50** | **0.84** | **0.95** |

On the first 27 questions with the reranked search, 17 of 17 numeric answers were exact (16 of 17 with BM25), and all 5 questions the reports cannot answer were refused. Answers to the full set, graded by an LLM judge as well, are next.

What I take from it:

- **Search quality came from the documents and the search, not the model.** Rebuilding tables row by row, routing by bank and year, and reranking moved the numbers; the answer model stayed the cheapest one (Claude Haiku 5.5, about USD 0.001 per question).
- **Dense vectors alone do not replace BM25 on annual reports**, which are full of exact terms and figures. They put the right page first a little more often (recall@1 0.24 against 0.20) but find less of the evidence in the top 6 (0.74 against 0.80). Fused with BM25 they nearly double how often the right page comes first, and the reranker lifts that to 2.5 times BM25.
- **The eval had to be debugged too.** My first citation metric scored 50%, but it measured my gold page lists more than the answers. Its replacement checks that every figure in an answer appears in a passage the answer cites: 18 or 19 of 19 answers pass, depending on the run. Better searches also kept finding pages that hold the answer but were missing from my gold lists; each one is checked in the PDF text before it is added.
- **Where it breaks:** group versus business-unit pages, paragraphs the parser splits into pieces so a citation covers only part of a sentence, and a comparison that contradicted itself with correct figures. Details, and every other strategy with its result, are in [docs/experiments.md](docs/experiments.md).

## Disclaimer

Built on public annual reports for demonstration. Not investment advice. Figures should be checked against the source page.

The annual reports belong to the banks. This repository does not contain them: `scripts/download.py` fetches them from each bank's investor relations site. The code is MIT licensed.
