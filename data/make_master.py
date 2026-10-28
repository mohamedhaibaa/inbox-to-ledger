"""Generate the master data: funds, investors and their commitments."""
import csv
import random
from pathlib import Path

from faker import Faker

SEED = 42                      # same seed = same data every run
random.seed(SEED)
Faker.seed(SEED)
fake = Faker("en_CA")          # Canadian names and places

OUT = Path(__file__).parent / "master"
OUT.mkdir(parents=True, exist_ok=True)

BANKS = ["Royal Bank of Canada", "TD Bank", "Scotiabank", "BMO", "CIBC"]
FUND_WORDS = ["Maple", "Harbour", "Northern", "Atlantic", "Summit",
              "Cedar", "Granite", "Lakeshore", "Bluewater", "Ironwood"]
FUND_TYPES = ["Growth", "Capital", "Infrastructure", "Credit", "Ventures"]
ROMAN = ["I", "II", "III", "IV"]
INVESTOR_TYPES = ["Pension Plan", "Endowment", "Family Office",
                  "Foundation", "Insurance Co."]


def acronym(name: str) -> str:
    """'Atlantic Pension Plan' -> 'APP' (what banks often print)."""
    return "".join(w[0] for w in name.replace(".", "").split() if w[0].isupper())


# Funds
funds = []
for i, word in enumerate(FUND_WORDS, start=1):
    funds.append({
        "fund_id": f"FND-{i:03d}",
        "fund_name": f"{word} {random.choice(FUND_TYPES)} Fund {random.choice(ROMAN)}",
        "bank_name": random.choice(BANKS),
        "account_number": f"{random.randint(10000, 99999)}-{random.randint(100000, 999999)}",
    })

# Investors
investors, used = [], set()
while len(investors) < 40:
    legal = f"{fake.city()} {random.choice(INVESTOR_TYPES)}"
    if legal in used:
        continue
    used.add(legal)
    short = acronym(legal)
    investors.append({
        "investor_id": f"INV-{len(investors) + 1:04d}",
        "legal_name": legal,
        "short_names": f"{short}|{' '.join(legal.split()[:2])}",
        "bank_reference": short,
    })

# Commitments: each investor promises money to 1-3 funds
commitments = []
for inv in investors:
    for fund in random.sample(funds, k=random.randint(1, 3)):
        amount = random.randrange(1_000_000, 10_000_001, 250_000)
        commitments.append({
            "fund_id": fund["fund_id"],
            "investor_id": inv["investor_id"],
            "commitment": f"{amount:.2f}",
        })


def write(name: str, rows: list[dict]) -> None:
    with open(OUT / name, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


write("funds.csv", funds)
write("investors.csv", investors)
write("commitments.csv", commitments)
print(f"{len(funds)} funds, {len(investors)} investors, {len(commitments)} commitments -> {OUT}")