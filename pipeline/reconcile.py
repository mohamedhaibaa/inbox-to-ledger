"""Step 10b: reconciliation. Compare what the ledger EXPECTS (capital calls and distributions we
recorded) with what the bank SAYS happened, line by line, and list every difference ("break").
Exact Decimal arithmetic throughout: a cent off is a cent off."""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from pipeline.match import match_investor, parse_line
from pipeline.statement import Statement, StatementLine
from pipeline.validate import MasterData

FEE_TOLERANCE = Decimal("50.00")   # banks may deduct a wire fee; short by up to this = paid, with a note
NEEDS_REVIEW = {"partial", "overpaid", "late", "unpaid", "unmatched"}


@dataclass
class ExpectedCall:
    doc_id: str
    investor_id: str
    call_number: int
    amount: Decimal
    due_date: date


@dataclass
class ExpectedDistribution:
    doc_id: str
    investor_id: str
    amount: Decimal
    payment_date: date


@dataclass
class Item:
    """One result line of the reconciliation report."""
    status: str                      # paid, paid_less_fee, late, partial, overpaid, unpaid, not_due, unmatched
    doc_id: str | None
    expected: Decimal | None
    actual: Decimal | None
    note: str = ""
    line: StatementLine | None = None

    @property
    def needs_review(self) -> bool:
        return self.status in NEEDS_REVIEW


@dataclass
class Reconciliation:
    fund_id: str
    calls: list[Item] = field(default_factory=list)
    distributions: list[Item] = field(default_factory=list)
    unmatched: list[Item] = field(default_factory=list)    # bank lines we couldn't tie to anything
    other_lines: int = 0                                     # fees, interest, investments: not ours to match

    @property
    def breaks(self) -> list[Item]:
        return [i for i in self.calls + self.distributions + self.unmatched if i.needs_review]


def call_status(call: ExpectedCall, line: StatementLine) -> Item:
    received = line.amount_in
    short = call.amount - received
    if short < 0:
        return Item("overpaid", call.doc_id, call.amount, received, f"over by {-short:,.2f}", line)
    if short > FEE_TOLERANCE:
        return Item("partial", call.doc_id, call.amount, received, f"short by {short:,.2f}", line)
    if line.date > call.due_date:
        return Item("late", call.doc_id, call.amount, received,
                    f"{(line.date - call.due_date).days} days after due date {call.due_date}", line)
    if short > 0:
        return Item("paid_less_fee", call.doc_id, call.amount, received, f"bank fee {short:,.2f}", line)
    return Item("paid", call.doc_id, call.amount, received, "", line)


def reconcile(statement: Statement, calls: list[ExpectedCall], distributions: list[ExpectedDistribution],
              master: MasterData) -> Reconciliation:
    fund_id = master.accounts[statement.account_number]
    result = Reconciliation(fund_id)
    open_calls = {(c.investor_id, c.call_number): c for c in calls}
    open_dists = list(distributions)

    for line in statement.lines:
        parsed = parse_line(line.description)
        if parsed.kind == "unrelated":
            result.other_lines += 1
            continue
        match = match_investor(parsed.payer, master, fund_id)
        if match.investor_id is None:
            result.unmatched.append(Item("unmatched", None, None, line.amount_in or line.amount_out,
                                         f"can't tell who {parsed.payer!r} is ({match.reason})", line))
            continue

        if parsed.kind == "capital_call":
            call = open_calls.pop((match.investor_id, parsed.call_number), None)
            if call is None:
                result.unmatched.append(Item("unmatched", None, None, line.amount_in,
                                             f"no open call #{parsed.call_number} for {match.investor_id} "
                                             "(already paid, or never recorded)", line))
            else:
                result.calls.append(call_status(call, line))
        else:                                                    # distribution paid out
            candidates = [d for d in open_dists if d.investor_id == match.investor_id
                          and d.amount == line.amount_out]
            # Same investor, same amount, more than once? Take the one due closest to the payment date.
            dist = min(candidates, key=lambda d: abs((d.payment_date - line.date).days), default=None)

            if dist is None:
                result.unmatched.append(Item("unmatched", None, None, line.amount_out,
                                             f"no recorded distribution of {line.amount_out:,.2f} "
                                             f"to {match.investor_id}", line))
            else:
                open_dists.remove(dist)
                result.distributions.append(Item("paid", dist.doc_id, dist.amount, line.amount_out, "", line))

    for call in open_calls.values():                              # nothing arrived for these
        if call.due_date > statement.period_end:
            result.calls.append(Item("not_due", call.doc_id, call.amount, None, f"due {call.due_date}"))
        else:
            result.calls.append(Item("unpaid", call.doc_id, call.amount, None,
                                     f"nothing received; was due {call.due_date}"))
    for dist in open_dists:                                       # nothing paid out for these
        if dist.payment_date > statement.period_end:
            result.distributions.append(Item("not_due", dist.doc_id, dist.amount, None, f"due {dist.payment_date}"))
        else:
            result.distributions.append(Item("unpaid", dist.doc_id, dist.amount, None,
                                             f"not paid out; was due {dist.payment_date}"))
    return result