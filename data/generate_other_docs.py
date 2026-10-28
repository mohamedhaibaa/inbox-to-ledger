"""Generate distribution notices, bank statements and 'other' documents, with answer keys.

Run AFTER generate_capital_calls.py: bank statements are built from the capital calls,
so every payment can be traced back to the notice it pays (or doesn't).
"""
import csv
import json
import random
import textwrap
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from faker import Faker
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

SEED = 7
random.seed(SEED)
Faker.seed(SEED)
fake = Faker("en_CA")

ROOT = Path(__file__).parent
MASTER = ROOT / "master"
GEN = ROOT / "generated"
KEYS = GEN / "answer_keys"
for sub in ["distributions", "bank_statements", "other"]:
    (GEN / sub).mkdir(parents=True, exist_ok=True)

CENT = Decimal("0.01")


def load(name: str) -> list[dict]:
    with open(MASTER / name, newline="") as f:
        return list(csv.DictReader(f))


funds = {f["fund_id"]: f for f in load("funds.csv")}
investors = {i["investor_id"]: i for i in load("investors.csv")}
commitments = load("commitments.csv")
calls = [json.loads(p.read_text()) for p in sorted(KEYS.glob("CC-*.json"))]


def money(amount: Decimal, style: str = "plain") -> str:
    s = f"{amount:,.2f}"
    return {"dollar": f"${s}", "prefix": f"CAD {s}", "plain": s}[style]


def fmt_date(d: date, style: str) -> str:
    return {"long": d.strftime("%B %d, %Y"), "dmy": d.strftime("%d/%m/%Y"),
            "iso": d.isoformat()}[style]


def draw(path: Path, lines: list[str], bold: int = 0, mono: bool = False) -> None:
    """Write lines to a PDF, starting a new page when one fills up."""
    c = canvas.Canvas(str(path), pagesize=letter)
    y = 720
    for i, line in enumerate(lines):
        if y < 72:
            c.showPage()
            y = 720
        if mono:
            c.setFont("Courier-Bold" if i < bold else "Courier", 9)
        else:
            c.setFont("Helvetica-Bold" if i < bold else "Helvetica", 13 if i < bold else 11)
        c.drawString(60, y, line)
        y -= 16 if mono else 20
    c.save()


def save_key(doc_id: str, data: dict) -> None:
    (KEYS / f"{doc_id}.json").write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------- 1. Distributions
DIST_TYPES = ["Return of capital", "Realized gain", "Income distribution"]
distributions = []
for n in range(1, 41):
    com = random.choice(commitments)
    fund, inv = funds[com["fund_id"]], investors[com["investor_id"]]
    amount = (Decimal(com["commitment"]) * random.randint(2, 15) / 100).quantize(CENT)
    notice = date(2026, 1, 1) + timedelta(days=random.randint(0, 300))
    pay = notice + timedelta(days=7)
    dtype = random.choice(DIST_TYPES)
    ms, ds = random.choice(["dollar", "prefix"]), random.choice(["long", "dmy", "iso"])

    if random.random() < 0.5:
        layout, bold = "dist_notice", 2
        lines = [fund["fund_name"].upper(), "DISTRIBUTION NOTICE", "",
                 f"To:                    {inv['legal_name']}",
                 f"Date:                  {fmt_date(notice, ds)}", "",
                 f"Distribution amount:   {money(amount, ms)}",
                 f"Type:                  {dtype}",
                 f"Payment date:          {fmt_date(pay, ds)}", "",
                 f"Paid from: {fund['bank_name']}, Acct {fund['account_number']}"]
    else:
        layout, bold = "dist_letter", 0
        lines = [fmt_date(notice, ds), "", f"Dear {inv['legal_name']},", "",
                 f"Re: {fund['fund_name']} - Distribution", "",
                 "We are pleased to inform you of a distribution to limited partners.",
                 f"Your share of {money(amount, ms)} ({dtype.lower()}) will be paid on {fmt_date(pay, ds)}.",
                 "", "Sincerely,", "The General Partner"]

    doc_id = f"DN-{n:04d}"
    draw(GEN / "distributions" / f"{doc_id}.pdf", lines, bold)
    key = {"doc_id": doc_id, "doc_type": "distribution", "layout": layout,
           "fund_id": fund["fund_id"], "fund_name": fund["fund_name"],
           "investor_id": inv["investor_id"], "investor_name": inv["legal_name"],
           "amount": str(amount), "currency": "CAD", "distribution_type": dtype,
           "notice_date": notice.isoformat(), "payment_date": pay.isoformat()}
    save_key(doc_id, key)
    distributions.append(key)

# ---------------------------------------------------------------- 2. Bank statements
NOISE = [("MANAGEMENT FEE Q{q}", "out", 20_000, 80_000),
         ("BANK INTEREST", "in", 50, 900),
         ("AUDIT FEES", "out", 5_000, 25_000),
         ("WIRE OUT INVESTMENT {co}", "out", 500_000, 3_000_000)]

for s, fund in enumerate(funds.values(), start=1):
    rows, unpaid = [], []

    # Capital call payments IN, with deliberate real-world problems
    for call in (c for c in calls if c["fund_id"] == fund["fund_id"]):
        amount, due = Decimal(call["amount"]), date.fromisoformat(call["due_date"])
        r = random.random()
        if r < 0.10:                                   # never paid
            unpaid.append(call["doc_id"])
            continue
        elif r < 0.20:                                 # paid only part
            outcome = "partial"
            received = (amount * random.randint(50, 90) / 100).quantize(CENT)
            paid = due - timedelta(days=random.randint(0, 5))
        elif r < 0.28:                                 # paid after the deadline
            outcome, received = "late", amount
            paid = due + timedelta(days=random.randint(3, 15))
        else:                                          # paid on time, maybe minus a bank fee
            fee = Decimal(random.choice([0, 0, 15, 25]))
            outcome = "paid" if fee == 0 else "paid_less_fee"
            received = amount - fee
            paid = due - timedelta(days=random.randint(0, 5))

        ref = call["reference"]
        if random.random() < 0.10:                     # bank printed the name instead of the code
            ref = f"{call['investor_name'].upper()[:22]} CALL {call['call_number']}"
        rows.append({"date": paid, "description": f"WIRE IN  {ref}", "in": received,
                     "out": None, "matches_doc": call["doc_id"], "outcome": outcome})

    # Distribution payments OUT
    for d in (d for d in distributions if d["fund_id"] == fund["fund_id"]):
        ref = investors[d["investor_id"]]["bank_reference"]
        rows.append({"date": date.fromisoformat(d["payment_date"]),
                     "description": f"WIRE OUT {ref} DISTRIBUTION", "in": None,
                     "out": Decimal(d["amount"]), "matches_doc": d["doc_id"],
                     "outcome": "distribution"})

    # Unrelated activity (noise the reconciler must ignore)
    for _ in range(random.randint(4, 8)):
        text, direction, lo, hi = random.choice(NOISE)
        text = text.format(q=random.randint(1, 4), co=fake.company().upper()[:20])
        value = Decimal(random.randint(lo, hi)).quantize(CENT)
        rows.append({"date": date(2026, 1, 1) + timedelta(days=random.randint(0, 330)),
                     "description": text, "in": value if direction == "in" else None,
                     "out": value if direction == "out" else None,
                     "matches_doc": None, "outcome": "unrelated"})

    rows.sort(key=lambda row: row["date"])
    lines = [f"{fund['bank_name'].upper()} - Account {fund['account_number']}",
             f"{fund['fund_name']}     Statement: Jan 1 - Dec 31, 2026", "",
             f"{'Date':<8}{'Description':<44}{'In':>16}{'Out':>16}", "-" * 84]
    for row in rows:
        lines.append(f"{row['date'].strftime('%b %d'):<8}{row['description'][:42]:<44}"
                     f"{money(row['in']) if row['in'] else '':>16}"
                     f"{money(row['out']) if row['out'] else '':>16}")

    doc_id = f"BS-{s:04d}"
    draw(GEN / "bank_statements" / f"{doc_id}.pdf", lines, bold=2, mono=True)
    save_key(doc_id, {
        "doc_id": doc_id, "doc_type": "bank_statement", "fund_id": fund["fund_id"],
        "fund_name": fund["fund_name"], "account_number": fund["account_number"],
        "period_start": "2026-01-01", "period_end": "2026-12-31",
        "lines": [{"line_no": i, "date": row["date"].isoformat(),
                   "description": row["description"],
                   "amount_in": str(row["in"]) if row["in"] else None,
                   "amount_out": str(row["out"]) if row["out"] else None,
                   "matches_doc": row["matches_doc"], "outcome": row["outcome"]}
                  for i, row in enumerate(rows, start=1)],
        "unpaid_calls": unpaid})

# ---------------------------------------------------------------- 3. Other documents
def wrap(text: str) -> list[str]:
    return textwrap.wrap(text, width=90)


FILLER = [
    "Market conditions remained stable throughout the period.",
    "The investment team continues to evaluate opportunities across the sector.",
    "Portfolio companies reported steady revenue growth compared to last year.",
    "We remain focused on disciplined underwriting and long-term value creation.",
    "Valuations across the portfolio were reviewed by an independent third party.",
    "The team expanded its presence in Western Canada during the period.",
    "Several portfolio companies completed strategic acquisitions.",
    "Environmental, social and governance reporting will be shared in the annual report.",
    "Interest rate movements had a limited impact on portfolio performance.",
    "We thank our limited partners for their continued support.",
    "Detailed financial statements are available on the investor portal.",
    "Please contact investor relations with any questions.",
]


def filler(n: int) -> str:
    return " ".join(random.sample(FILLER, n))


def quarterly(fund):
    return [f"{fund['fund_name']}", f"Q{random.randint(1, 4)} 2026 Quarterly Report", ""] + wrap(
        f"Portfolio update: the fund made {random.randint(1, 4)} new investments this quarter. "
        f"Capital called to date represents {random.randint(20, 80)}% of total commitments. "
        + filler(4))


def newsletter(fund):
    return [f"Investor Newsletter - {fake.month_name()} 2026", ""] + wrap(
        f"Welcome to the latest update from {fund['fund_name']}. " + filler(6))


def agm(fund):
    return [f"{fund['fund_name']}", "Annual General Meeting - Invitation", ""] + wrap(
        f"You are invited to attend the annual general meeting on {fake.date_this_year().strftime('%B %d, %Y')} "
        f"at {fake.city()}. " + filler(3))


def marketing(fund):
    return [f"Introducing the {fake.last_name()} Opportunities Fund", ""] + wrap(
        f"Minimum commitment: ${random.randint(1, 5)},000,000. Target return {random.randint(8, 20)}%. "
        + filler(5))


OTHER = [quarterly, newsletter, agm, marketing]
for n in range(1, 21):
    fund = random.choice(list(funds.values()))
    make = random.choice(OTHER)
    doc_id = f"OT-{n:04d}"
    draw(GEN / "other" / f"{doc_id}.pdf", make(fund), bold=2)
    save_key(doc_id, {"doc_id": doc_id, "doc_type": "other", "subtype": make.__name__})

print(f"{len(distributions)} distributions, {len(funds)} bank statements, 20 other documents")