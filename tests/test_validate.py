"""Tests for Step 7: validation rules. Each test protects one business rule."""
from datetime import date
from decimal import Decimal

import pytest

from pipeline.schemas import CapitalCall
from pipeline.validate import MasterData, validate

FUNDS = [{"fund_id": "FND-001", "fund_name": "Maple Growth Fund I"}]
INVESTORS = [
    {"investor_id": "INV-0001", "legal_name": "Atlantic Pension Plan", "short_names": "APP|Atlantic Pension"},
    {"investor_id": "INV-0002", "legal_name": "Jasonfort Endowment", "short_names": "JE|Jasonfort Endowment"},
    {"investor_id": "INV-0003", "legal_name": "Jacquelineland Endowment", "short_names": "JE|Jacquelineland Endowment"},
]
COMMITMENTS = [{"fund_id": "FND-001", "investor_id": "INV-0001", "commitment": "1000000.00"}]


@pytest.fixture
def master():
    return MasterData(FUNDS, INVESTORS, COMMITMENTS)


def call(**changes):
    base = dict(fund_name="Maple Growth Fund I", investor_name="Atlantic Pension Plan", call_number=1,
                amount=Decimal("250000.00"), notice_date=date(2026, 11, 1), due_date=date(2026, 11, 15))
    return CapitalCall(**{**base, **changes})


def test_valid_call_passes_and_resolves_ids(master):
    """A correct call passes and is linked to the right fund and investor IDs."""
    result = validate(call(), master)
    assert result.passed
    assert (result.fund_id, result.investor_id) == ("FND-001", "INV-0001")


def test_short_name_resolves_to_investor(master):
    """A known short name ('Atlantic Pension') must find the same investor."""
    assert validate(call(investor_name="Atlantic Pension"), master).investor_id == "INV-0001"


def test_negative_amount_is_blocked(master):
    """A capital call can never have a negative amount."""
    assert not validate(call(amount=Decimal("-5.00")), master).passed


def test_call_larger_than_commitment_is_blocked(master):
    """An investor can't be asked for more than they promised."""
    result = validate(call(amount=Decimal("2000000.00")), master)
    assert any("exceeds commitment" in e for e in result.errors)


def test_unknown_investor_is_blocked(master):
    """An investor not in the register must never be recorded."""
    assert not validate(call(investor_name="Mystery Holdings"), master).passed


def test_ambiguous_reference_is_blocked_not_guessed(master):
    """'JE' matches two investors: it must be flagged, never guessed (the JE lesson from Step 1)."""
    result = validate(call(investor_name="JE"), master)
    assert any("ambiguous" in e for e in result.errors)
    assert result.investor_id is None


def test_due_date_before_notice_is_blocked(master):
    """Money can't be due before it was requested."""
    assert not validate(call(due_date=date(2026, 10, 1)), master).passed


def test_duplicate_call_is_blocked(master):
    """The same call recorded twice (e.g. the same PDF sent twice) must be caught."""
    recorded = {("FND-001", "INV-0001", 1)}
    result = validate(call(), master, recorded)
    assert any("duplicate" in e for e in result.errors)