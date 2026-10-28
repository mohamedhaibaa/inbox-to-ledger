"""Tests for Step 5: the document classifier."""
import pytest

from pipeline.classify import build_model, classify

TRAIN_TEXTS = [
    "CAPITAL CALL NOTICE #1 Amount of this call due date wire reference",
    "Drawdown Request capital contribution due payment deadline",
    "you are requested to contribute on or before capital call",
    "DISTRIBUTION NOTICE distribution amount payment date return of capital",
    "We are pleased to inform you of a distribution your share will be paid",
    "Statement Date Description In Out WIRE IN WIRE OUT BANK INTEREST",
    "Account statement WIRE IN CAP CALL AUDIT FEES MANAGEMENT FEE",
    "Quarterly Report portfolio update market conditions",
    "Investor Newsletter welcome to the latest update",
]
TRAIN_LABELS = ["capital_call"] * 3 + ["distribution"] * 2 + ["bank_statement"] * 2 + ["other"] * 2


@pytest.fixture(scope="module")
def model():
    return build_model().fit(TRAIN_TEXTS, TRAIN_LABELS)


def test_capital_call_is_recognised(model):
    """A clear capital call must be sorted as a capital call."""
    result = classify("CAPITAL CALL NOTICE #4 Amount of this call due date", model)
    assert result.doc_type == "capital_call"


def test_confidence_is_a_probability(model):
    """Confidence must be between 0 and 1 so thresholds make sense."""
    result = classify("DISTRIBUTION NOTICE payment date", model)
    assert 0.0 <= result.confidence <= 1.0


def test_unfamiliar_text_is_not_confident(model):
    """Text unlike anything seen in training must not be trusted; it goes to the LLM."""
    result = classify("recipe for chocolate cake with butter and sugar", model)
    assert result.confident is False