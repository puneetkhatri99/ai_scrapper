"""One-time import of the brokers CSV.

    python -m backend.companies.seed "Brokers (1).xlsx - Sheet1.csv"

Non-destructive and re-runnable: a company whose name is already in the table
is left alone, so this never undoes an edit made in the UI afterwards.

The sheet's own header row is misaligned -- "Method" sits one column right of
its values -- so the columns are read by position, not by name.
"""
import csv
import sys
from pathlib import Path

from backend.companies import db

# By position, because the header row lies. The two columns not taken are the
# "Status" ok-flag and the second count: both are hand bookkeeping that the job
# status and the live officer count now replace.
NAME, NMLS, LO_COUNT, COMPANY_URL, _STATUS, METHOD, _SCRAPED, SHEET_URL = range(8)


def _cell(row: list[str], i: int) -> str:
    return row[i].strip() if i < len(row) else ""


def _url(row: list[str], i: int) -> str | None:
    value = _cell(row, i)
    return value if value.startswith("http") else None


def parse(path: Path) -> list[dict]:
    """CSV rows -> company rows. Skips the header and anything unnamed."""
    companies = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for n, row in enumerate(csv.reader(fh)):
            name = _cell(row, NAME)
            if n == 0 or not name:          # the header, and any trailing blanks
                continue
            count = _cell(row, LO_COUNT)
            method = _cell(row, METHOD)
            companies.append({
                "name": name,
                "nmls_id": _cell(row, NMLS) or None,
                "lo_count": int(count) if count.isdigit() else None,
                "company_url": _url(row, COMPANY_URL),
                # The Method column is a url for most rows and an instruction
                # for the rest ("Search Button"). A url is where we point the
                # browser; anything else becomes a hint in the prompt.
                "directory_url": _url(row, METHOD),
                "note": None if method.startswith("http") else (method or None),
                "sheet_url": _url(row, SHEET_URL),
            })
    return companies


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    rows = parse(Path(argv[1]))
    added = db.add_missing(rows)
    print(f"{len(rows)} rows in the csv, {added} added, {len(rows) - added} already there")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
