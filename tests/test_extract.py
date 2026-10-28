"""Tests for Step 6: extraction. A fake client stands in for the API, so tests are free and offline."""
from decimal import Decimal
from types import SimpleNamespace

from pipeline.extract import extract


class FakeClient:
    """Pretends to be the Anthropic client and returns a prepared answer."""

    def __init__(self, answer):
        self.messages = SimpleNamespace(create=lambda **kwargs: SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", input=answer)]))


GOOD = {"fund_name": "Northern Credit Fund I", "investor_name": "East Jill Family Office",
        "call_number": 1, "amount": "975000.00", "due_date": "2026-10-21",
        "reference": "EJFO CAP CALL 1"}


def test_valid_answer_becomes_typed_form():
    """A correct answer must come back with an exact Decimal amount and a real date."""
    result = extract("...", "capital_call", client=FakeClient(GOOD))
    assert result.error is None
    assert result.data.amount == Decimal("975000.00")
    assert result.data.due_date.isoformat() == "2026-10-21"


def test_made_up_amount_is_rejected():
    """An amount that isn't a number (e.g. words) must be caught, not stored."""
    result = extract("...", "capital_call", client=FakeClient({**GOOD, "amount": "nine hundred thousand"}))
    assert result.data is None
    assert "invalid form" in result.error


def test_missing_required_field_is_rejected():
    """A form missing the due date must fail validation."""
    answer = {k: v for k, v in GOOD.items() if k != "due_date"}
    result = extract("...", "capital_call", client=FakeClient(answer))
    assert result.data is None


def test_unknown_document_type_is_not_sent_to_the_llm():
    """'other' documents have no form; nothing should be extracted (and no API cost)."""
    result = extract("Quarterly report", "other", client=None)
    assert result.data is None
    assert "no extraction form" in result.error