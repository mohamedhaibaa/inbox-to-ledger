"""Step 10a: read a bank statement PDF into exact lines, with code (no LLM).
A statement is a table: the hard part is telling the In column from the Out column.
pdfplumber gives each word's position on the page; amounts are right-aligned under their header,
so an amount whose right edge lines up with "In" is money in, with "Out" money out."""
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pdfplumber

AMOUNT = re.compile(r"^\d{1,3}(,\d{3})*\.\d{2}$")          # 1,250,000.00
HEADER = re.compile(r"Account (?P<account>[\d-]+)")
DATE = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{2}$")   # "Feb 18"
PERIOD = re.compile(r"Statement: (?P<start>\w{3} \d{1,2}) - (?P<end>\w{3} \d{1,2}), (?P<year>\d{4})")


@dataclass
class StatementLine:
    date: date
    description: str
    amount_in: Decimal | None = None
    amount_out: Decimal | None = None


@dataclass
class Statement:
    account_number: str
    period_start: date
    period_end: date
    lines: list[StatementLine] = field(default_factory=list)


def parse_statement(path: str | Path) -> Statement:
    with pdfplumber.open(path) as pdf:
        words = [{**w, "page": page.page_number} for page in pdf.pages for w in page.extract_words()]
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    account = HEADER.search(text)["account"]
    period = PERIOD.search(text)
    year = int(period["year"])

    def day(month_day: str) -> date:                               # "Feb 18" -> 2026-02-18
        return datetime.strptime(f"{month_day} {year}", "%b %d %Y").date()

    in_edge = next(w["x1"] for w in words if w["text"] == "In")   # right edge of the "In" header
    out_edge = next(w["x1"] for w in words if w["text"] == "Out")

    rows: dict[tuple[int, int], list[dict]] = {}                   # words grouped by (page, line)
    for w in words:
        rows.setdefault((w["page"], round(w["top"])), []).append(w)

    lines = []
    for top in sorted(rows):
        row = sorted(rows[top], key=lambda w: w["x0"])
        if len(row) < 4 or not (DATE.match(f"{row[0]['text']} {row[1]['text']}")
                                and AMOUNT.match(row[-1]["text"])):
            continue                                               # headers, rulers, titles: not transactions
        amount_word = row[-1]
        amount = Decimal(amount_word["text"].replace(",", ""))
        is_in = abs(amount_word["x1"] - in_edge) < abs(amount_word["x1"] - out_edge)
        description = " ".join(w["text"] for w in row[2:-1])     # words 0-1 are the date
        lines.append(StatementLine(day(f"{row[0]['text']} {row[1]['text']}"), description,
                                   amount if is_in else None, None if is_in else amount))
    return Statement(account, day(period["start"]), day(period["end"]), lines)


if __name__ == "__main__":
    import json
    import sys

    doc_id = sys.argv[1] if len(sys.argv) > 1 else "BS-0001"
    statement = parse_statement(Path("data/generated/bank_statements") / f"{doc_id}.pdf")
    print(f"Account {statement.account_number}, {statement.period_start} to {statement.period_end}")
    for line in statement.lines:
        print(f"  {line.date}  {line.description:<40} in={line.amount_in}  out={line.amount_out}")

    # Check every statement against its answer key
    wrong = total = 0
    for pdf in sorted(Path("data/generated/bank_statements").glob("BS-*.pdf")):
        key = json.loads((Path("data/generated/answer_keys") / f"{pdf.stem}.json").read_text())
        got = parse_statement(pdf).lines
        want = key["lines"]
        total += len(want)
        if len(got) != len(want):
            print(f"{pdf.stem}: {len(got)} lines read, {len(want)} expected")
            wrong += len(want)
            continue
        for g, k in zip(got, want):
            ok = (g.date.isoformat() == k["date"]
                  and " ".join(g.description.split()) == " ".join(k["description"].split())
                  and (str(g.amount_in) if g.amount_in else None) == k["amount_in"]
                  and (str(g.amount_out) if g.amount_out else None) == k["amount_out"])
            if not ok:
                wrong += 1
                print(f"{pdf.stem} line {k['line_no']}: got {g}, expected {k}")
    print(f"\nRead {total - wrong}/{total} statement lines exactly right")