---
name: add-eval-case
description: Add or correct a question in evals/questions.yaml, with the gold answer and every source page checked in the parsed report text. Use when growing the eval set, when a new feature needs an eval case, or when a search finds a page the gold list lacks.
---

# Add an eval case

Every question in `evals/questions.yaml` must have a gold answer and gold pages that someone can check in the PDF. This skill is how they get checked. Never take a page on trust from the retriever or from memory.

## 1. Pick what the question tests

Count what the set already covers, then pick a gap (a bank, a year, a category or a language with few questions):

```bash
uv run python -c "import collections, yaml; q = yaml.safe_load(open('evals/questions.yaml', encoding='utf-8')); print(len(q), collections.Counter(x['category'] for x in q), collections.Counter(x['lang'] for x in q))"
```

Each question should test one thing a user would really ask. Prefer figures the reports state in words or in a key figures table over figures only in a chart, because chart labels are not in the parsed text.

## 2. Find the answer in the page text

```bash
uv run python scripts/find_pages.py "net interest income" --report jyske_2025 --pages 20-25
uv run python scripts/find_pages.py "Common equity tier 1" --report jyske_2025 --pages 34 --whole-page
```

`--report` takes a cache file name (`danske_2024`, `nordea_2025`, ...) and defaults to all six. Page numbers are PDF page numbers, as everywhere in this repo.

Check, for every figure:

- **The column.** Key figure tables list several years; read the header row with `--whole-page`.
- **The unit and currency.** Nordea reports in EUR, the Danish banks in DKK; millions against billions.
- **Restatements.** The next year's report may restate the figure (Danske Bank's 2024 return on equity is 13.4% in the 2024 report and 13.5% in the 2025 report). Put both in `numbers` and say so in the gold answer.
- **Several definitions.** Group against parent company or business unit, including against excluding a fee or a group of employees. Name the one the gold answer uses, and accept the others in `numbers` only if a reader could fairly call them the answer.

## 3. Collect every page that holds the answer

Search the summary pages (financial highlights, executive summary, CEO letter), the financial review and the notes. Every page that states the figure goes into the same evidence group; a search that finds any of them has found the answer. Questions that need two banks or two years get one group each.

## 4. Write the entry

```yaml
- id: q45                       # next free number
  question: What was Nordea's CET1 ratio at the end of 2024?
  lang: en                      # en or da
  category: lookup              # lookup, compare_years, compare_banks, why, danish, unanswerable
  answerable: true
  gold_answer: 15.8% at the end of 2024 (17.0% a year earlier).
  numbers: [[15.8]]             # one inner list per required figure, with its acceptable spellings
  evidence:
    - [nordea-2024-p40, nordea-2025-p40]
  verified: false               # only Anders sets this to true, after checking the PDF himself
```

- `numbers` is empty for "why" questions unless a figure is the point of the question.
- Danish questions get a Danish gold answer with Danish number formats (15,5%).
- Unanswerable questions have `answerable: false`, no numbers and no evidence. Search for the topic first to make sure the reports really do not answer it (a bank's own outlook for next year is in the report and is answerable).
- Update the dated note at the top of the file when an existing question's gold pages change.

## 5. Check that it runs

```bash
uv run bankrag search "the new question"     # does the search find a gold page?
uv run python evals/run_evals.py             # retrieval metrics, free
```

A question the search misses is still a good question: it shows a weakness. Do not tune the question until the search finds it.

Do not run `evals/run_evals.py --answers` without asking Anders first: it calls the paid API.
