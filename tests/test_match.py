"""Tests for Step 9: matching bank lines to investors. Uses a tiny made-up register, so it never
depends on the generated data."""
import pytest

from pipeline.match import match_investor, parse_line
from pipeline.validate import MasterData

INVESTORS = [
    {"investor_id": "I1", "legal_name": "Lake Debra Pension Plan", "short_names": "LDPP|Lake Debra", "bank_reference": "LDPP"},
    {"investor_id": "I2", "legal_name": "Lake Chad Foundation", "short_names": "LCF|Lake Chad", "bank_reference": "LCF"},
    {"investor_id": "I3", "legal_name": "Jacquelineland Endowment", "short_names": "JE|Jacquelineland Endowment", "bank_reference": "JE"},
    {"investor_id": "I4", "legal_name": "Jasonfort Endowment", "short_names": "JE|Jasonfort Endowment", "bank_reference": "JE"},
]
COMMITMENTS = [{"fund_id": "F1", "investor_id": i, "commitment": "1000000.00"} for i in ("I1", "I2", "I3")]
COMMITMENTS += [{"fund_id": "F2", "investor_id": "I4", "commitment": "1000000.00"}]


@pytest.fixture
def master():
    return MasterData([{"fund_id": "F1", "fund_name": "Fund One"}, {"fund_id": "F2", "fund_name": "Fund Two"}],
                      INVESTORS, COMMITMENTS)


def test_parse_capital_call_line():
    line = parse_line("WIRE IN  LDPP CAP CALL 2")
    assert (line.kind, line.payer, line.call_number) == ("capital_call", "LDPP", 2)


def test_parse_distribution_and_noise():
    assert parse_line("WIRE OUT LCF DISTRIBUTION").kind == "distribution"
    assert parse_line("WIRE OUT INVESTMENT DAVIS GROUP").kind == "unrelated"
    assert parse_line("BANK INTEREST").kind == "unrelated"


def test_bank_code_matches_exactly(master):
    assert match_investor("LDPP", master).investor_id == "I1"


def test_shared_code_is_ambiguous_not_guessed(master):
    result = match_investor("JE", master)
    assert result.investor_id is None and result.ambiguous


def test_fund_context_resolves_shared_code(master):
    """Only one 'JE' investor is in fund F1, so the fund tells us which one paid."""
    assert match_investor("JE", master, fund_id="F1").investor_id == "I3"


def test_truncated_name_matches(master):
    """Banks cut names off: 'LAKE DEBRA PENS' is still Lake Debra Pension Plan."""
    assert match_investor("LAKE DEBRA PENS", master).investor_id == "I1"


def test_different_kind_is_not_matched(master):
    """'Lake Chad Insurance Co.' is NOT Lake Chad Foundation, however similar the letters."""
    assert match_investor("Lake Chad Insurance Co.", master).investor_id is None


def test_stranger_is_not_matched(master):
    assert match_investor("Northwind Capital Partners", master).investor_id is None


def test_investor_outside_the_fund_is_not_matched(master):
    """Jasonfort has no commitment in F1, so a payment into F1 must not be credited to it."""
    assert match_investor("Jasonfort Endowment", master, fund_id="F1").investor_id is None