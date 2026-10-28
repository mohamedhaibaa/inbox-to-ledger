"""Step 10b: reconcile the HARD statements and score against what really happened.
Outcomes per ledger item (as in 7b and 9):
  correct     - our status is the true status
  flagged     - truth needs a person, we flagged it (with a different label): safe
  false_alarm - truth was fine, we flagged it: safe, but wastes a person's time
  SILENT      - truth needs a person, we said it was fine (or a wrong 'fine' status): dangerous"""
import json
from collections import Counter, defaultdict
from pathlib import Path

from eval.reconciliation import load_ledger
from pipeline.reconcile import reconcile
from pipeline.statement import parse_statement
from pipeline.validate import MasterData

HARD = Path("data/generated/hard_statements")
KEYS = Path("data/generated/hard_statement_keys")
RESULTS = Path("eval/results")
FINE = {"paid", "paid_less_fee", "not_due"}


def outcome(truth: str, ours: str) -> str:
    if truth == ours:
        return "correct"
    if truth in FINE:
        return "false_alarm" if ours not in FINE else "SILENT"
    return "flagged" if ours not in FINE else "SILENT"


def main() -> None:
    master = MasterData.load()
    calls, dists = load_ledger()
    per_truth = defaultdict(Counter)              # true status -> outcome counts
    problems, lines_ok, lines_total = [], 0, 0

    for pdf in sorted(HARD.glob("HS-*.pdf")):
        key = json.loads((KEYS / f"{pdf.stem}.json").read_text())
        statement = parse_statement(pdf)
        rec = reconcile(statement, calls[key["fund_id"]], dists[key["fund_id"]], master)

        read_ok = len(statement.lines) == key["lines"]
        lines_ok += len(statement.lines) if read_ok else 0
        lines_total += key["lines"]
        unmatched_ok = len(rec.unmatched) == key["expected_unmatched_lines"]
        print(f"{pdf.stem} {key['fund_id']}: read {len(statement.lines)}/{key['lines']} lines"
              f"{'' if read_ok else '  <-- LINES MISSING'}; unmatched {len(rec.unmatched)} "
              f"(expected {key['expected_unmatched_lines']}){'' if unmatched_ok else '  <-- DIFFERENT'}")

        for item in rec.calls + rec.distributions:
            truth = key["truth"][item.doc_id]
            result = outcome(truth, item.status)
            per_truth[truth][result] += 1
            if result != "correct":
                problems.append({"statement": pdf.stem, "doc_id": item.doc_id, "truth": truth,
                                 "ours": item.status, "outcome": result, "note": item.note})

    totals = Counter()
    print(f"\n{'true status':<18}{'correct':>8}{'flagged':>9}{'false_alarm':>13}{'SILENT':>8}")
    for truth, counts in sorted(per_truth.items()):
        print(f"{truth:<18}{counts['correct']:>8}{counts['flagged']:>9}{counts['false_alarm']:>13}{counts['SILENT']:>8}")
        totals.update(counts)
    print(f"\nStatement lines read: {lines_ok}/{lines_total}")
    print(f"Items: {sum(totals.values())}  correct {totals['correct']}, flagged {totals['flagged']}, "
          f"false alarms {totals['false_alarm']}, SILENT {totals['SILENT']}")
    for p in sorted(problems, key=lambda p: p["outcome"] != "SILENT")[:12]:
        print(f"  {p['outcome']:<11} {p['statement']} {p['doc_id']:<8} truth={p['truth']:<15} ours={p['ours']:<13} {p['note']}")

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "hard_reconciliation.json").write_text(json.dumps({
        "lines_read": lines_ok, "lines_total": lines_total, "outcomes": dict(totals),
        "per_truth": {t: dict(c) for t, c in per_truth.items()}, "problems": problems}, indent=2))
    print(f"\nSaved -> {RESULTS / 'hard_reconciliation.json'}")


if __name__ == "__main__":
    main()