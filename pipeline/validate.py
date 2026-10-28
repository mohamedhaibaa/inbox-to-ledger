"""Step 7: business rules in plain code that check every extracted form before it can reach the ledger."""
import csv
import json
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from pipeline.schemas import CapitalCall, Distribution

MASTER = Path(__file__).resolve().parents[1] / "data" / "master"
MAX_NOTICE_DAYS = 60   # a due date further than this after the notice is unusual


@dataclass
class ValidationResult:
    passed: bool
    errors: list[str] = field(default_factory=list)     # block the document (goes to human review)
    warnings: list[str] = field(default_factory=list)   # allowed, but flagged
    fund_id: str | None = None
    investor_id: str | None = None


class MasterData:
    """Look-ups over funds, investors and commitments (the investor register)."""

    def __init__(self, funds: list[dict], investors: list[dict], commitments: list[dict]):
        self.funds = {f["fund_name"].lower(): f["fund_id"] for f in funds}
        self.accounts = {f["account_number"]: f["fund_id"] for f in funds if f.get("account_number")}
        self.investor_names = {}
        self.legal_names = {inv["investor_id"]: inv["legal_name"] for inv in investors}
        for inv in investors:
            names = [inv["legal_name"]] + inv["short_names"].split("|")
            for name in names:
                self.investor_names.setdefault(name.lower(), set()).add(inv["investor_id"])
        self.commitments = {(c["fund_id"], c["investor_id"]): Decimal(c["commitment"]) for c in commitments}

    @classmethod
    def load(cls, folder: Path = MASTER) -> "MasterData":
        def read(name):
            with open(folder / name, newline="") as f:
                return list(csv.DictReader(f))
        return cls(read("funds.csv"), read("investors.csv"), read("commitments.csv"))

    def fund_id(self, name: str) -> str | None:
        return self.funds.get(name.strip().lower())

    def investor_ids(self, name: str) -> set[str]:
        return self.investor_names.get(name.strip().lower(), set())
    
    def investors_in(self, fund_id: str) -> set[str]:
        """Investors with a commitment to this fund."""
        return {inv for (fund, inv) in self.commitments if fund == fund_id}

def validate(form: CapitalCall | Distribution, master: MasterData,
             recorded_calls: set[tuple] | None = None) -> ValidationResult:
    """Check one extracted form. recorded_calls = (fund_id, investor_id, call_number) already in the ledger."""
    result = ValidationResult(passed=True)
    errors, warnings = result.errors, result.warnings

    # Amount
    if form.amount <= 0:
        errors.append(f"amount must be positive (got {form.amount})")
    if form.amount != form.amount.quantize(Decimal("0.01")):
        errors.append(f"amount has more than 2 decimals (got {form.amount})")
    if form.currency != "CAD":
        warnings.append(f"unexpected currency {form.currency}")

    # Who: fund and investor must exist
    result.fund_id = master.fund_id(form.fund_name)
    if result.fund_id is None:
        errors.append(f"unknown fund '{form.fund_name}'")
    ids = master.investor_ids(form.investor_name)
    if not ids:
        errors.append(f"unknown investor '{form.investor_name}'")
    elif len(ids) > 1:
        errors.append(f"ambiguous investor '{form.investor_name}' matches {sorted(ids)}")
    else:
        result.investor_id = next(iter(ids))

    # Commitment: this investor must have promised money to this fund
    commitment = None
    if result.fund_id and result.investor_id:
        commitment = master.commitments.get((result.fund_id, result.investor_id))
        if commitment is None:
            errors.append(f"{result.investor_id} has no commitment to {result.fund_id}")

    # Rules specific to capital calls
    if isinstance(form, CapitalCall):
        if commitment is not None and form.amount > commitment:
            errors.append(f"call {form.amount} exceeds commitment {commitment}")
        if form.notice_date and form.due_date < form.notice_date:
            errors.append(f"due date {form.due_date} is before notice date {form.notice_date}")
        if form.notice_date and form.due_date > form.notice_date + timedelta(days=MAX_NOTICE_DAYS):
            warnings.append(f"due date is more than {MAX_NOTICE_DAYS} days after the notice")
        if form.call_number is None:
            warnings.append("no call number")
        elif recorded_calls is not None and result.fund_id and result.investor_id:
            key = (result.fund_id, result.investor_id, form.call_number)
            if key in recorded_calls:
                errors.append(f"duplicate: call #{form.call_number} already recorded")

    # Rules specific to distributions
    if isinstance(form, Distribution):
        if form.notice_date and form.payment_date < form.notice_date:
            errors.append(f"payment date {form.payment_date} is before notice date {form.notice_date}")

    result.passed = not errors
    return result


if __name__ == "__main__":
    # Sanity check: run every CORRECT answer key through the rules. A good rule set raises no false alarms.
    master = MasterData.load()
    keys = Path(__file__).resolve().parents[1] / "data" / "generated" / "answer_keys"
    recorded, checked, failed = set(), 0, []
    for path in sorted(keys.glob("*.json")):
        key = json.loads(path.read_text())
        if key["doc_type"] not in ("capital_call", "distribution"):
            continue
        data = {**key, "investor_name": key.get("investor_name_shown", key["investor_name"])}
        form = (CapitalCall if key["doc_type"] == "capital_call" else Distribution).model_validate(data)
        result = validate(form, master, recorded)
        checked += 1
        if result.passed and isinstance(form, CapitalCall):
            recorded.add((result.fund_id, result.investor_id, form.call_number))
        if not result.passed:
            failed.append((key["doc_id"], result.errors))
    print(f"Checked {checked} correct documents: {checked - len(failed)} passed, {len(failed)} flagged")
    for doc_id, errors in failed:
        print(f"  {doc_id}: {errors}")