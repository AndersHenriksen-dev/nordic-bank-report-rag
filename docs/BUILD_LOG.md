# Build log

One line per session: date, hours, what was built, what Claude Code did and what I decided.

| Date | Hours | Built | Claude Code did | I decided |
|---|---|---|---|---|
| 2026-10-24 | 2.5 (estimate) | M1 start: repo, download script, PDF parsing and chunking, BM25 search with bank and year routing, cited answers with Claude Haiku 5.5, first 19 eval questions, eval runner | Found the six report URLs (Danske Bank's 2024 file only through their file API), wrote all code and tests, drafted gold answers from the PDFs. Caught that PyMuPDF's table cells merge columns and switched to rebuilding rows from word positions. | Repo name and public visibility, cheapest model for answers, Jyske Bank PDFs downloaded by hand instead of working around the site's bot check |
