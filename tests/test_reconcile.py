"""Tests for Step 10: reading statements and reconciling. Built from tiny hand-made data, so each
test shows one rule clearly and never depends on the generated files."""
from datetime import date
from decimal import Decimal

import pytest
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from pipeline.reconcile import ExpectedCall, ExpectedDistribution, reconcile
from pipeline.statement import Statement, StatementLine, parse_statement
from pipeline.validate import MasterData

D = Decimal
DUE = date(2026, 6, 15)


@pytest.fixture
def master():
    funds = [{"fund_id": "F1", "fund_name": "Fund One", "account_number": "111-222"}]
    investors = [{"investor_id": "I1", "legal_name": "Lake Debra Pension Plan", "short_names": "LDPP|Lake Debra",
                  "bank_reference": "LDPP"}]
    return MasterData(funds, investors, [{"fund_id": "F1", "investor_id": "I1", "commitment": "5000000.00"}])


def run(master, lines, calls=None, dists=None, end=date(2026, 12, 31)):
    statement = Statement("111-222", date(2026, 1, 1), end, lines)
    call = [ExpectedCall("CC-1", "I1", 1, D("500000.00"), DUE)] if calls is None else calls
    return reconcile(statement, call, dists or [], master)


def wire_in(amount, day=date(2026, 6, 10), text="WIRE IN LDPP CAP CALL 1"):
    return StatementLine(day, text, amount_in=D(amount))


def test_exact_payment_on_time_is_paid(master):
    assert run(master, [wire_in("500000.00")]).calls[0].status == "paid"


def test_small_bank_fee_is_accepted_with_a_note(master):
    item = run(master, [wire_in("499975.00")]).calls[0]
    assert item.status == "paid_less_fee" and "25.00" in item.note and not item.needs_review


def test_short_by_more_than_the_fee_tolerance_is_partial(master):
    item = run(master, [wire_in("499900.00")]).calls[0]          # short by 100 > 50 tolerance
    assert item.status == "partial" and item.needs_review


def test_payment_after_due_date_is_late(master):
    assert run(master, [wire_in("500000.00", day=date(2026, 6, 20))]).calls[0].status == "late"


def test_too_much_is_overpaid(master):
    assert run(master, [wire_in("510000.00")]).calls[0].status == "overpaid"


def test_nothing_received_is_unpaid(master):
    result = run(master, [])
    assert result.calls[0].status == "unpaid" and len(result.breaks) == 1


def test_not_yet_due_is_not_a_break(master):
    result = run(master, [], end=date(2026, 5, 31))              # statement ends before the due date
    assert result.calls[0].status == "not_due" and result.breaks == []


def test_second_wire_for_same_call_is_flagged_not_absorbed(master):
    """A duplicate or split payment must reach a human, never silently disappear."""
    result = run(master, [wire_in("500000.00"), wire_in("500000.00", day=date(2026, 6, 12))])
    assert result.calls[0].status == "paid"
    assert len(result.unmatched) == 1 and result.unmatched[0].needs_review


def test_unknown_payer_is_flagged(master):
    result = run(master, [wire_in("500000.00", text="WIRE IN NORTHWIND CAPITAL CALL 1")])
    assert result.unmatched and result.calls[0].status == "unpaid"


def test_fees_and_interest_are_ignored(master):
    lines = [wire_in("500000.00"), StatementLine(date(2026, 3, 1), "BANK INTEREST", amount_in=D("42.00"))]
    result = run(master, lines)
    assert result.other_lines == 1 and result.breaks == []


def test_distribution_paid_out_matches(master):
    dist = ExpectedDistribution("DN-1", "I1", D("250000.00"), date(2026, 7, 1))
    line = StatementLine(date(2026, 7, 1), "WIRE OUT LDPP DISTRIBUTION", amount_out=D("250000.00"))
    result = run(master, [line], calls=[], dists=[dist])
    assert result.distributions[0].status == "paid"

def test_same_amount_twice_goes_to_the_closest_date(master):
    """Two equal distributions to one investor: the January wire must pay the January one."""
    jan = ExpectedDistribution("DN-JAN", "I1", D("250000.00"), date(2026, 1, 21))
    nov = ExpectedDistribution("DN-NOV", "I1", D("250000.00"), date(2026, 11, 2))
    line = StatementLine(date(2026, 1, 21), "WIRE OUT LDPP DISTRIBUTION", amount_out=D("250000.00"))
    result = run(master, [line], calls=[], dists=[nov, jan])
    status = {item.doc_id: item.status for item in result.distributions}
    assert status == {"DN-JAN": "paid", "DN-NOV": "unpaid"}


def test_distribution_after_statement_end_is_not_due(master):
    dist = ExpectedDistribution("DN-1", "I1", D("250000.00"), date(2026, 9, 1))
    result = run(master, [], calls=[], dists=[dist], end=date(2026, 6, 30))
    assert result.distributions[0].status == "not_due" and result.breaks == []


def test_statement_parser_reads_every_page(tmp_path):
    """A long statement spills onto page 2. Lines on page 2 must not merge with page 1."""
    path = tmp_path / "long.pdf"
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setFont("Courier", 9)
    rows = ["TEST BANK - Account 111-222", "Fund One     Statement: Jan 1 - Dec 31, 2026", "",
            f"{'Date':<8}{'Description':<44}{'In':>16}{'Out':>16}", "-" * 84]
    rows += [f"{'Mar 01':<8}{'AUDIT FEES':<44}{'':>16}{f'{1000 + i:,}.00':>16}" for i in range(60)]
    y = 720
    for row in rows:
        if y < 72:
            c.showPage()
            c.setFont("Courier", 9)
            y = 720
        c.drawString(60, y, row)
        y -= 16
    c.save()

    lines = parse_statement(path).lines
    assert len(lines) == 60
    assert [line.amount_out for line in lines] == [D(1000 + i) for i in range(60)]

def test_statement_parser_tells_in_from_out(tmp_path):
    """Same layout as the generated statements: right-aligned In and Out columns."""
    path = tmp_path / "statement.pdf"
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setFont("Courier", 9)
    rows = ["TEST BANK - Account 111-222", "Fund One     Statement: Jan 1 - Dec 31, 2026", "",
            f"{'Date':<8}{'Description':<44}{'In':>16}{'Out':>16}", "-" * 84,
            f"{'Jun 10':<8}{'WIRE IN LDPP CAP CALL 1':<44}{'500,000.00':>16}{'':>16}",
            f"{'Jun 11':<8}{'AUDIT FEES':<44}{'':>16}{'9,295.00':>16}"]
    for i, row in enumerate(rows):
        c.drawString(60, 720 - 16 * i, row)
    c.save()

    statement = parse_statement(path)
    assert statement.account_number == "111-222"
    assert statement.lines[0].amount_in == D("500000.00") and statement.lines[0].amount_out is None
    assert statement.lines[1].amount_out == D("9295.00") and statement.lines[1].amount_in is None