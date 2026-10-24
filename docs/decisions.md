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

If a question names banks or years, search only those reports. For questions about two or three banks, each bank gets its own share of the results, because plain top-k search tends to fill every slot with the bank whose wording matches best. The evals compare search with and without routing.

## 5. Claude Haiku 5.5 for answers, with search-result citations

Anders asked to keep running costs as low as possible, so answers use Claude Haiku 5.5 (USD 0.10 per million input tokens, 0.50 per million output tokens, October 2026), configurable with `BANKRAG_MODEL`. Retrieved chunks go to Claude as `search_result` blocks with citations enabled, so each sentence in the answer carries citations that point at the exact passages used. The system prompt is the same on every call and marked for prompt caching.

## 6. Refusals use a fixed opening phrase

Citations cannot be combined with structured output, so the model signals a refusal by starting with "Not in the documents." (or "Ikke i dokumenterne."). The eval checks for that phrase.

## 7. Jyske Bank's reports are downloaded by hand

Jyske Bank's site answers scripted downloads with a bot check (HTTP 403). The download script does not try to get around it: it prints the URL, a person saves the file, and the script then verifies the checksum.
