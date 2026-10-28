"""Step 10: reconcile all 10 statements and score every status against the answer keys.
The ledger here is built from the capital call / distribution answer keys: i.e. what Steps 6-7
would have recorded (extraction was 168/168 on these). Code only, no API calls."""
import csv
import json
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from pipeline.reconcile import ExpectedCall, ExpectedDistribution, reconcile
from pipeline.statement import parse_statement
from pipeline.validate import MasterData

KEYS = Path("data/generated/answer_keys")
STATEMENTS = Path("data/generated/bank_statements")
RESULTS = Path("eval/results")


def load_ledger() -> tuple[dict, dict]:
    calls, dists = defaultdict(list), defaultdict(list)
    for f in sorted(KEYS.glob("CC-*.json")):
        k = json.loads(f.read_text())
        calls[k["fund_id"]].append(ExpectedCall(k["doc_id"], k["investor_id"], k["call_number"],
                                                Decimal(k["amount"]), date.fromisoformat(k["due_date"])))
    for f in sorted(KEYS.glob("DN-*.json")):
        k = json.loads(f.read_text())
        dists[k["fund_id"]].append(ExpectedDistribution(k["doc_id"], k["investor_id"], Decimal(k["amount"]),
                                                        date.fromisoformat(k["payment_date"])))
    return calls, dists


def truth(statement_key: dict) -> dict[str, str]:
    """doc_id -> what really happened, from the statement's answer key."""
    real = {line["matches_doc"]: ("paid" if line["outcome"] == "distribution" else line["outcome"])
            for line in statement_key["lines"] if line["matches_doc"]}
    real.update({doc_id: "unpaid" for doc_id in statement_key["unpaid_calls"]})
    return real


def main() -> None:
    master = MasterData.load()
    calls, dists = load_ledger()
    confusion = Counter()                         # (true status, our status) -> count
    report_rows, unmatched, other = [], 0, 0
    expected_total = received_total = Decimal("0")

    for pdf in sorted(STATEMENTS.glob("BS-*.pdf")):
        statement = parse_statement(pdf)
        fund_id = master.accounts[statement.account_number]
        rec = reconcile(statement, calls[fund_id], dists[fund_id], master)
        real = truth(json.loads((KEYS / f"{pdf.stem}.json").read_text()))
        unmatched += len(rec.unmatched)
        other += rec.other_lines

        for item in rec.calls + rec.distributions:
            confusion[(real.get(item.doc_id, "?"), item.status)] += 1
            if item.doc_id.startswith("CC"):
                expected_total += item.expected
                received_total += item.actual or Decimal("0")
        for item in rec.breaks:
            report_rows.append({"fund_id": fund_id, "doc_id": item.doc_id or "", "status": item.status,
                                "expected": item.expected or "", "received": item.actual or "",
                                "bank_line": item.line.description if item.line else "", "note": item.note})
        print(f"{fund_id} ({pdf.stem}): {len(rec.calls)} calls, {len(rec.distributions)} distributions, "
              f"{rec.other_lines} other lines -> {len(rec.breaks)} need review")

    right = sum(n for (t, s), n in confusion.items() if t == s)
    total = sum(confusion.values())
    print(f"\nStatus correct: {right}/{total}")
    print(f"Unmatched bank lines: {unmatched} (should be 0)   Other activity ignored: {other}")
    print(f"Capital called: {expected_total:,.2f}   received: {received_total:,.2f}   "
          f"outstanding: {expected_total - received_total:,.2f}")
    print("\n  true status      -> our status      count")
    for (t, s), n in sorted(confusion.items()):
        print(f"  {t:<16} -> {s:<16} {n:>4}{'' if t == s else '   <-- WRONG'}")
    print(f"\nBreaks for human review: {len(report_rows)}")
    for row in report_rows[:6]:
        print(f"  {row['fund_id']} {row['doc_id']:<8} {row['status']:<8} {row['note']}")

    RESULTS.mkdir(parents=True, exist_ok=True)
    with open(RESULTS / "breaks.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(report_rows[0]))
        writer.writeheader()
        writer.writerows(report_rows)
    (RESULTS / "reconciliation.json").write_text(json.dumps({
        "items": total, "status_correct": right, "unmatched_lines": unmatched,
        "capital_called": str(expected_total), "received": str(received_total),
        "confusion": [{"true": t, "ours": s, "count": n} for (t, s), n in sorted(confusion.items())],
        "breaks": len(report_rows)}, indent=2))
    print(f"\nSaved -> {RESULTS / 'breaks.csv'} and {RESULTS / 'reconciliation.json'}")


if __name__ == "__main__":
    main()