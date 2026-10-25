# Nordic Bank Report RAG

I am building a question answering system over the 2024 and 2025 annual reports of Danske Bank, Nordea and Jyske Bank. Every answer cites the report and page it comes from, and the system is measured against a test set of questions with known answers.

Work in progress. The full README, setup steps and a demo will follow here. What exists so far:

- [docs/documents.md](docs/documents.md): the six reports, where they come from, and what to know when reading them.
- [evals/RESULTS.md](evals/RESULTS.md): retrieval and answer metrics from the latest eval run.
- [evals/ANSWERS.md](evals/ANSWERS.md): every eval question with its gold answer, the system's answer and the passages it cites.
- [docs/decisions.md](docs/decisions.md): the design choices and why I made them.

## Disclaimer

Built on public annual reports for demonstration. Not investment advice. Figures should be checked against the source page.

The annual reports belong to the banks. This repository does not contain them: `scripts/download.py` fetches them from each bank's investor relations site. The code is MIT licensed.
