"""Download the six annual reports into data/raw/ and verify their checksums.

The reports belong to the banks and are not committed to this repository.
This script fetches them from each bank's investor relations site, so anyone
can rebuild the same data set.

Usage:
    python scripts/download.py            # download missing files, verify all
    python scripts/download.py --force    # download again even if present
    python scripts/download.py --print-checksums
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

# Some IR sites reject the default Python user agent.
USER_AGENT = "Mozilla/5.0 (compatible; nordic-bank-report-rag/0.1; +https://github.com/AndersHenriksen-dev/nordic-bank-report-rag)"


@dataclass(frozen=True)
class Report:
    bank: str
    year: int
    url: str
    sha256: str

    @property
    def filename(self) -> str:
        return f"{self.bank}_{self.year}.pdf"


# Found on each bank's investor relations site in October 2026.
REPORTS = [
    Report(
        bank="danske",
        year=2024,
        url="https://danskebank.com/-/media/danske-bank-com/file-cloud/2025/2/danske-bank---annual-report-2024.pdf",
        sha256="b662c01b9704b51c62d0e085f0e30f257ed7aff41ae4dd53f08c672f29ffd3d2",
    ),
    Report(
        bank="danske",
        year=2025,
        url="https://danskebank.com/-/media/danske-bank-com/file-cloud/2026/2/annual-report-2025.pdf",
        sha256="5003490703c721bd5474e1a5d3f3c60fe85835d23f545627114ced038dcaa944",
    ),
    Report(
        bank="nordea",
        year=2024,
        url="https://www.nordea.com/en/doc/annual-report-nordea-bank-abp-2024-0.pdf",
        sha256="4e729ee653f35ead55030884f0f3b84c1e03b6593012fbe9d9f0ff5b44797054",
    ),
    Report(
        bank="nordea",
        year=2025,
        url="https://www.nordea.com/en/doc/nordea-annual-report-2025.pdf",
        sha256="cce7c2004fbeca8b652ea9977be08500c1297c0cd307349bd016c1dc4de11e1e",
    ),
    Report(
        bank="jyske",
        year=2024,
        url="https://jyskebank.com/wps/wcm/connect/jbc/db0d2cb1-8b88-4ddd-bbcc-b04dc5330d64/Jyske+Bank+Annual+Report+2024.pdf?MOD=AJPERES",
        sha256="",
    ),
    Report(
        bank="jyske",
        year=2025,
        url="https://jyskebank.com/wps/wcm/connect/jbc/50bd88a1-062f-4e35-a27f-0052b3b66571/Jyske+Bank+Annual+Report+2025.pdf?MOD=AJPERES",
        sha256="",
    ),
]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(report: Report, target: Path) -> None:
    request = urllib.request.Request(report.url, headers={"User-Agent": USER_AGENT})
    tmp = target.with_suffix(".part")
    with urllib.request.urlopen(request, timeout=120) as response, tmp.open("wb") as f:
        content_type = response.headers.get("Content-Type", "")
        if "pdf" not in content_type.lower():
            raise RuntimeError(f"{report.url} returned {content_type!r}, not a PDF")
        while block := response.read(1 << 20):
            f.write(block)
    tmp.replace(target)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--force", action="store_true", help="download again even if the file exists")
    parser.add_argument("--print-checksums", action="store_true", help="print the SHA-256 of each local file")
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    failures = 0
    for report in REPORTS:
        target = RAW_DIR / report.filename
        if args.force or not target.exists():
            print(f"downloading {report.filename} from {report.url}")
            try:
                download(report, target)
            except urllib.error.HTTPError as e:
                if e.code != 403:
                    raise
                # Jyske Bank's site sits behind a bot check that refuses scripts.
                # We do not try to get around it: a person downloads the file instead.
                print(f"  {report.filename}: the site refused a scripted download (HTTP 403).")
                print(
                    f"  Open the URL above in a browser, save the PDF as {target}, and run this script again."
                )
                failures += 1
                continue

        actual = sha256_of(target)
        size_mb = target.stat().st_size / 1e6
        if args.print_checksums:
            print(f"{report.filename}  {size_mb:5.1f} MB  {actual}")
        elif not report.sha256:
            print(f"{report.filename}: no checksum recorded yet ({actual})")
        elif actual != report.sha256:
            print(f"{report.filename}: CHECKSUM MISMATCH, expected {report.sha256}, got {actual}")
            print("  The bank may have republished the report. Check the file before updating the checksum.")
            failures += 1
        else:
            print(f"{report.filename}: ok ({size_mb:.1f} MB)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
