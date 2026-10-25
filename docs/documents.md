# The documents

The system answers questions from six annual reports: the 2024 and 2025 reports of Danske Bank, Nordea and Jyske Bank, the three largest Danish banks. All six are in English. The reports belong to the banks and are not in this repository; `scripts/download.py` fetches them and checks each file against the SHA-256 checksum below, so anyone can rebuild exactly the data set the evals were run on.

## The six reports

| Bank | Report | PDF pages | Size | Currency | Parsed tables | Chunks (with tables) | SHA-256 (first 12) |
|---|---|---|---|---|---|---|---|
| Danske Bank | [Annual Report 2024](https://danskebank.com/-/media/danske-bank-com/file-cloud/2025/2/danske-bank---annual-report-2024.pdf) | 280 | 15.1 MB | DKK | 282 | 734 (243) | `b662c01b9704` |
| Danske Bank | [Annual Report 2025](https://danskebank.com/-/media/danske-bank-com/file-cloud/2026/2/annual-report-2025.pdf) | 286 | 13.5 MB | DKK | 271 | 704 (215) | `5003490703c7` |
| Nordea | [Annual Report 2024](https://www.nordea.com/en/doc/annual-report-nordea-bank-abp-2024-0.pdf) | 384 | 14.2 MB | EUR | 476 | 1,213 (376) | `4e729ee653f3` |
| Nordea | [Annual Report 2025](https://www.nordea.com/en/doc/nordea-annual-report-2025.pdf) | 378 | 16.1 MB | EUR | 471 | 1,137 (359) | `cce7c2004fbe` |
| Jyske Bank | [Annual Report 2024](https://jyskebank.com/wps/wcm/connect/jbc/db0d2cb1-8b88-4ddd-bbcc-b04dc5330d64/Jyske+Bank+Annual+Report+2024.pdf?MOD=AJPERES) | 275 | 12.9 MB | DKK | 239 | 548 (176) | `16de19868025` |
| Jyske Bank | [Annual Report 2025](https://jyskebank.com/wps/wcm/connect/jbc/50bd88a1-062f-4e35-a27f-0052b3b66571/Jyske+Bank+Annual+Report+2025.pdf?MOD=AJPERES) | 264 | 5.4 MB | DKK | 247 | 546 (189) | `6143b08a1898` |
| **Total** | | **1,867** | | | **1,986** | **4,882 (1,558)** | |

Full checksums are in [scripts/download.py](../scripts/download.py). Chunk counts are for the default "structure" chunking.

## What is in them

Each report covers one financial year and has the same broad parts: a management report (results, strategy, risk, capital), a sustainability statement, and the financial statements for the group and for the parent company. The parts as each report names them, which the parser uses as the top level of every chunk's section:

- **Danske Bank:** Management's report, Management's report - Sustainability, Financial statements Danske Bank Group, Financial statements Danske Bank A/S, Statements.
- **Nordea:** Introduction, Strategic report, Our stakeholders, Business areas, Board of Directors' report, Financial statements, Other.
- **Jyske Bank:** Introduction, Our business, Financial Review, Sustainability, Corporate Governance, Directorships, Financial Statements, EU Taxonomy, Statements.

Most key figures sit in tables, for example the five-year highlights near the front of each report and the income statement in the financial statements. That is why the parser rebuilds tables row by row (see [decisions.md](decisions.md), decision 2).

## Things to know when reading the answers

- **Page numbers are PDF page numbers**, the page a PDF viewer jumps to. Nordea's printed page numbers are one lower.
- **Group and parent company figures differ.** Each report has both. Net profit, capital ratios and return on equity are different for "Danske Bank Group" and "Danske Bank A/S", and an answer should say which one it gives.
- **Currencies differ.** Nordea reports in EUR, the two others in DKK. The system does not convert.
- **Restated figures.** A 2025 report can restate a 2024 figure; for example Danske Bank's 2024 return on equity is 13.4% in the 2024 report and 13.5% in the 2025 report. The eval set accepts both where this happens.
- **The PDF is not always the official version.** Danske Bank's PDF states that the XHTML file filed under the EU's ESEF rules is the official version and the PDF a copy; Jyske Bank's investor relations page also labels its xHTML version official. The figures used here come from the PDFs.

## Where they come from

All six were found on the banks' investor relations sites in October 2026. Danske Bank's 2024 report is no longer linked from its reports page and was found through the site's file search. Jyske Bank's site refuses scripted downloads (HTTP 403 behind a bot check), so `scripts/download.py` asks for those two files to be saved by hand and then verifies them; it does not try to get around the check.

Built on public annual reports for demonstration. Not investment advice. Figures should be checked against the source page.
