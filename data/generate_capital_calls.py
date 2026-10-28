"""Generate synthetic capital call notices (PDF) with answer keys (JSON)."""
import csv
import json
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

SEED = 42
N_DOCS = 60
random.seed(SEED)

ROOT = Path(__file__).parent
MASTER = ROOT / "master"
OUT_PDF = ROOT / "generated" / "capital_calls"
OUT_KEY = ROOT / "generated" / "answer_keys"
OUT_PDF.mkdir(parents=True, exist_ok=True)
OUT_KEY.mkdir(parents=True, exist_ok=True)


def load(name: str) -> list[dict]:
    with open(MASTER / name, newline="") as f:
        return list(csv.DictReader(f))


funds = {f["fund_id"]: f for f in load("funds.csv")}
investors = {i["investor_id"]: i for i in load("investors.csv")}
commitments = load("commitments.csv")

PURPOSES = ["New investment", "Management fees", "Follow-on investment", "Fund expenses"]
PERCENTS = [5, 10, 15, 20]


def money(amount: Decimal, style: str) -> str:
    s = f"{amount:,.2f}"
    return {"dollar": f"${s}", "prefix": f"CAD {s}", "suffix": f"{s} CAD"}[style]


def fmt_date(d: date, style: str) -> str:
    return {"long": d.strftime("%B %d, %Y"), "dmy": d.strftime("%d/%m/%Y"),
            "iso": d.isoformat()}[style]


# Three different layouts: each returns the lines of text to print
def layout_a(v):
    return [v["fund_name"].upper(), f"CAPITAL CALL NOTICE #{v['call_number']}", "",
            f"To:      {v['investor_name']}", f"Date:    {v['notice_date']}", "",
            f"Total commitment:       {v['commitment']}",
            f"Amount of this call:    {v['amount']}",
            f"Purpose:                {v['purpose']}",
            f"Due date:               {v['due_date']}", "",
            f"Wire to: {v['bank_name']}, Acct {v['account_number']}",
            f"Reference: {v['reference']}"]


def layout_b(v):
    return [v["fund_name"], "Drawdown Request", "",
            f"Investor: {v['investor_name']}",
            f"Notice date: {v['notice_date']}  |  Call No. {v['call_number']}", "",
            "Description                         Amount",
            f"Capital contribution due            {v['amount']}",
            f"({v['purpose']})", "",
            f"Payment deadline: {v['due_date']}",
            f"Quote reference {v['reference']} on your wire to {v['bank_name']} ({v['account_number']})."]


def layout_c(v):
    return [v["notice_date"], "", f"Dear {v['investor_name']},", "",
            f"Re: {v['fund_name']} - Capital Call {v['call_number']}", "",
            "In accordance with the Limited Partnership Agreement, you are requested to contribute",
            f"{v['amount']} on or before {v['due_date']} for: {v['purpose'].lower()}.", "",
            f"Kindly remit funds to {v['bank_name']}, account {v['account_number']},",
            f"quoting reference {v['reference']}.", "", "Sincerely,", "The General Partner"]


LAYOUTS = [(layout_a, 2), (layout_b, 2), (layout_c, 0)]   # (layout, number of bold title lines)


def draw(path: Path, lines: list[str], bold: int) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    y = 720
    for i, line in enumerate(lines):
        c.setFont("Helvetica-Bold" if i < bold else "Helvetica", 13 if i < bold else 11)
        c.drawString(72, y, line)
        y -= 20
    c.save()


call_counter = {}
for n in range(1, N_DOCS + 1):
    com = random.choice(commitments)
    fund, inv = funds[com["fund_id"]], investors[com["investor_id"]]

    pair = (fund["fund_id"], inv["investor_id"])
    call_counter[pair] = call_counter.get(pair, 0) + 1
    call_number = call_counter[pair]

    commitment = Decimal(com["commitment"])
    amount = (commitment * random.choice(PERCENTS) / 100).quantize(Decimal("0.01"))
    notice = date(2026, 1, 1) + timedelta(days=random.randint(0, 300))
    due = notice + timedelta(days=14)
    reference = f"{inv['bank_reference']} CAP CALL {call_number}"

    money_style = random.choice(["dollar", "prefix", "suffix"])
    date_style = random.choice(["long", "dmy", "iso"])
    name_shown = inv["legal_name"] if random.random() < 0.8 else inv["short_names"].split("|")[1]

    shown = {
        "fund_name": fund["fund_name"], "investor_name": name_shown,
        "call_number": call_number, "commitment": money(commitment, money_style),
        "amount": money(amount, money_style), "purpose": random.choice(PURPOSES),
        "notice_date": fmt_date(notice, date_style), "due_date": fmt_date(due, date_style),
        "bank_name": fund["bank_name"], "account_number": fund["account_number"],
        "reference": reference,
    }
    layout, bold = random.choice(LAYOUTS)
    doc_id = f"CC-{n:04d}"
    draw(OUT_PDF / f"{doc_id}.pdf", layout(shown), bold)

    answer = {
        "doc_id": doc_id, "doc_type": "capital_call", "layout": layout.__name__,
        "fund_id": fund["fund_id"], "fund_name": fund["fund_name"],
        "investor_id": inv["investor_id"], "investor_name": inv["legal_name"],
        "investor_name_shown": name_shown, "call_number": call_number,
        "amount": str(amount), "currency": "CAD",
        "notice_date": notice.isoformat(), "due_date": due.isoformat(),
        "reference": reference,
    }
    (OUT_KEY / f"{doc_id}.json").write_text(json.dumps(answer, indent=2))

print(f"{N_DOCS} capital calls -> {OUT_PDF}")