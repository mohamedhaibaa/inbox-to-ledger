"""Step 11b: the morning run. "As of" a given day: reconcile every statement up to that day, send each
break to the review queue, and raise a deadline alert for calls due soon that haven't been paid.
    python -m pipeline.daily 2026-07-01          (optional 2nd argument: alert window in days, default 7)"""
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

from eval.reconciliation import load_ledger
from pipeline.reconcile import reconcile
from pipeline.review import DB, ReviewQueue
from pipeline.statement import parse_statement
from pipeline.validate import MasterData

STATEMENTS = Path("data/generated/bank_statements")


def run(as_of: date, queue: ReviewQueue, window: int = 7) -> dict[str, int]:
    master = MasterData.load()
    calls, dists = load_ledger()
    due_dates = {c.doc_id: c.due_date for fund in calls.values() for c in fund}
    counts = {"breaks": 0, "due_soon": 0, "new": 0}
    seen: set[str] = set()                                       # every problem found today

    for pdf in sorted(STATEMENTS.glob("BS-*.pdf")):
        full = parse_statement(pdf)
        # What the bank had shown by the morning of as_of: only lines dated before that day
        so_far = replace(full, period_end=as_of, lines=[ln for ln in full.lines if ln.date < as_of])
        fund_id = master.accounts[full.account_number]
        rec = reconcile(so_far, calls[fund_id], dists[fund_id], master)

        for item in rec.breaks:
            counts["breaks"] += 1
            line = f" | bank: {item.line.description}" if item.line else ""
            key = f"{item.status}:{item.doc_id or item.line.description}:{item.line.date if item.line else ''}"
            seen.add(key)
            counts["new"] += queue.add(key, item.status, f"{item.note}{line}", fund_id, item.doc_id,
                                       item.expected or item.actual)
        for item in rec.calls:                                   # deadline alerts
            days = (due_dates[item.doc_id] - as_of).days
            if item.status == "not_due" and days <= window:
                counts["due_soon"] += 1
                key = f"due_soon:{item.doc_id}"
                seen.add(key)
                counts["new"] += queue.add(key, "due_soon",
                                           f"due in {days} day(s) on {due_dates[item.doc_id]}, nothing received yet",
                                           fund_id, item.doc_id, item.expected)
    counts["closed"] = queue.close_missing(seen, as_of.isoformat())
    return counts


def print_queue(queue: ReviewQueue, limit: int = 15) -> None:
    items = queue.open_items()
    print(f"\nOpen review items: {len(items)} (highest priority first)")
    print(f"  {'id':>3} {'prio':>4}  {'kind':<10} {'fund':<8} {'doc':<8} {'amount':>14}  detail")
    for i in items[:limit]:
        amount = f"{i.amount:,.2f}" if i.amount is not None else ""
        print(f"  {i.id:>3} {i.priority:>4}  {i.kind:<10} {i.fund_id or '':<8} {i.doc_id or '':<8} {amount:>14}  {i.detail[:70]}")
    if len(items) > limit:
        print(f"  ... and {len(items) - limit} more")


if __name__ == "__main__":
    as_of = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2026, 7, 1)
    window = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    queue = ReviewQueue(DB)
    counts = run(as_of, queue, window)
    print(f"As of {as_of}: {counts['breaks']} breaks, {counts['due_soon']} calls due within {window} days; "
          f"{counts['new']} new, {counts['closed']} closed because the problem is gone")
    print_queue(queue)