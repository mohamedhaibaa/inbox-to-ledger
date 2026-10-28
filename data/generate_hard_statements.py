"""Step 10b: a HARD set of bank statements, for testing reconciliation only.
Bugs it finds are fixed in the pipeline, never by editing this file; the fixes are then confirmed
on fresh seeds: python data/generate_hard_statements.py 32  (no argument = seed 31).
Same layout as the normal statements, same ledger (the capital call and distribution answer keys),
but the money behaves badly: overpayments, duplicate wires, split payments, wrong references,
strangers, boundary cases, a statement that ends early, and one long enough to need a second page."""
import csv
import json
import random
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 31
rng = random.Random(SEED)

ROOT = Path(__file__).parent
KEYS = ROOT / "generated" / "answer_keys"
OUT = ROOT / "generated" / "hard_statements"
OUT_KEYS = ROOT / "generated" / "hard_statement_keys"
OUT.mkdir(parents=True, exist_ok=True)
OUT_KEYS.mkdir(parents=True, exist_ok=True)

with open(ROOT / "master" / "funds.csv", newline="") as f:
    funds = list(csv.DictReader(f))
with open(ROOT / "master" / "investors.csv", newline="") as f:
    investors = {i["investor_id"]: i for i in csv.DictReader(f)}
calls = [json.loads(p.read_text()) for p in sorted(KEYS.glob("CC-*.json"))]
dists = [json.loads(p.read_text()) for p in sorted(KEYS.glob("DN-*.json"))]

# What really happened -> the status a correct reconciler should give (truth)
CHALLENGES = ["paid", "overpaid", "duplicate_wire", "split_payment", "fee_over_tolerance",
              "fee_at_tolerance", "paid_on_due_date", "wrong_call_number", "unknown_payer", "late_and_short"]
TRUTH = {"paid": "paid", "overpaid": "overpaid", "duplicate_wire": "paid", "split_payment": "split_paid",
         "fee_over_tolerance": "partial", "fee_at_tolerance": "paid_less_fee", "paid_on_due_date": "paid",
         "wrong_call_number": "wrong_reference", "unknown_payer": "unpaid", "late_and_short": "partial"}
NOISE = ["AUDIT FEES", "BANK INTEREST", "LEGAL FEES", "CUSTODY FEE", "MANAGEMENT FEE Q2"]


def money(amount: Decimal) -> str:
    return f"{amount:,.2f}"


def wire_in(day: date, ref: str, amount: Decimal, stray: bool = False) -> dict:
    """stray=True: a correct reconciler can't tie this line to an open item, so it must be flagged."""
    return {"date": day, "description": f"WIRE IN  {ref}", "in": amount, "out": None, "stray": stray}


def draw(path: Path, lines: list[str]) -> None:
    """Identical to the normal statements: Courier 9, 16pt rows, new page when full."""
    c = canvas.Canvas(str(path), pagesize=letter)
    y = 720
    for i, line in enumerate(lines):
        if y < 72:
            c.showPage()
            y = 720
        c.setFont("Courier-Bold" if i < 2 else "Courier", 9)
        c.drawString(60, y, line)
        y -= 16
    c.save()


challenge_cycle = CHALLENGES * 10
rng.shuffle(challenge_cycle)
for n, fund in enumerate(funds, start=1):
    fund_calls = [c for c in calls if c["fund_id"] == fund["fund_id"]]
    fund_dists = [d for d in dists if d["fund_id"] == fund["fund_id"]]
    period_end = date(2026, 6, 30) if fund["fund_id"] == "FND-010" else date(2026, 12, 31)   # ends early
    rows, truth, used = [], {}, []

    for call in fund_calls:
        challenge = "paid" if period_end.month == 6 else challenge_cycle.pop()
        amount, due = Decimal(call["amount"]), date.fromisoformat(call["due_date"])
        ref, on_time = call["reference"], due - timedelta(days=rng.randint(1, 5))

        if challenge in ("paid", "duplicate_wire"):
            rows.append(wire_in(on_time, ref, amount))
            if challenge == "duplicate_wire":
                rows.append(wire_in(on_time + timedelta(days=2), ref, amount, stray=True))
        elif challenge == "overpaid":
            rows.append(wire_in(on_time, ref, amount + Decimal(rng.choice([1000, 25000]))))
        elif challenge == "split_payment":
            first = (amount * Decimal("0.6")).quantize(Decimal("0.01"))
            rows.append(wire_in(on_time - timedelta(days=3), ref, first))
            rows.append(wire_in(on_time, ref, amount - first, stray=True))
        elif challenge == "fee_over_tolerance":
            rows.append(wire_in(on_time, ref, amount - Decimal("75.00")))
        elif challenge == "fee_at_tolerance":
            rows.append(wire_in(on_time, ref, amount - Decimal("50.00")))
        elif challenge == "paid_on_due_date":
            rows.append(wire_in(due, ref, amount))
        elif challenge == "wrong_call_number":
            rows.append(wire_in(on_time, ref.rsplit(" ", 1)[0] + f" {call['call_number'] + 5}", amount, stray=True))
        elif challenge == "unknown_payer":
            rows.append(wire_in(on_time, f"NORTHWIND CAPITAL CALL {call['call_number']}", amount, stray=True))
        elif challenge == "late_and_short":
            rows.append(wire_in(due + timedelta(days=6), ref, amount - Decimal("20000.00")))

        expected = TRUTH[challenge]
        if period_end.month == 6:                       # short statement: judge by what's inside it
            expected = "not_due" if due > period_end else ("paid" if on_time <= period_end else "unpaid")
        truth[call["doc_id"]] = expected
        used.append({"doc_id": call["doc_id"], "challenge": challenge})

    for i, dist in enumerate(fund_dists):               # distributions: the first one pays the wrong amount
        code = investors[dist["investor_id"]]["bank_reference"]
        pay_day = date.fromisoformat(dist["payment_date"])
        wrong = i == 0
        rows.append({"date": pay_day, "description": f"WIRE OUT {code} DISTRIBUTION", "in": None,
                     "out": Decimal(dist["amount"]) + (Decimal("1000.00") if wrong else 0), "stray": wrong})
        if pay_day > period_end:                        # after the statement ends: not due yet
            truth[dist["doc_id"]] = "not_due"
        else:
            truth[dist["doc_id"]] = "amount_mismatch" if wrong else "paid"

    noise = 45 if fund["fund_id"] == "FND-009" else rng.randint(4, 8)   # FND-009: long, two pages
    for _ in range(noise):
        rows.append({"date": date(2026, 1, 1) + timedelta(days=rng.randint(0, 330)),
                     "description": rng.choice(NOISE), "in": None,
                     "out": Decimal(rng.randint(500, 30000)).quantize(Decimal("0.01")), "stray": False})

    rows = sorted((r for r in rows if r["date"] <= period_end), key=lambda r: r["date"])
    header = f"{fund['bank_name'].upper()} - Account {fund['account_number']}"
    period = f"Statement: Jan 1 - {period_end.strftime('%b')} {period_end.day}, 2026"
    lines = [header, f"{fund['fund_name']}     {period}", "",
             f"{'Date':<8}{'Description':<44}{'In':>16}{'Out':>16}", "-" * 84]
    lines += [f"{r['date'].strftime('%b %d'):<8}{r['description'][:42]:<44}"
              f"{money(r['in']) if r['in'] else '':>16}{money(r['out']) if r['out'] else '':>16}" for r in rows]

    doc_id = f"HS-{n:04d}"
    draw(OUT / f"{doc_id}.pdf", lines)
    (OUT_KEYS / f"{doc_id}.json").write_text(json.dumps({
        "doc_id": doc_id, "fund_id": fund["fund_id"], "period_end": period_end.isoformat(),
        "lines": len(rows), "truth": truth, "challenges": used,
        "expected_unmatched_lines": sum(r["stray"] for r in rows)}, indent=2))
    print(f"{doc_id} {fund['fund_id']}: {len(rows)} lines, {len(fund_calls)} calls, {len(fund_dists)} distributions")