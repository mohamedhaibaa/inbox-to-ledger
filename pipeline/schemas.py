"""The 'forms' the LLM must fill in. Pydantic checks every answer against them."""
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class CapitalCall(BaseModel):
    fund_name: str
    investor_name: str = Field(description="Investor name exactly as written in the document")
    call_number: int | None = None
    amount: Decimal = Field(description="Amount of this call, a plain number like 250000.00")
    currency: str = "CAD"
    notice_date: date | None = None
    due_date: date
    reference: str | None = Field(None, description=(
        "The payment reference code the investor must quote on the wire, copied exactly. "
        "Only the code itself: leave out labels such as 'Ref:' and any words, brackets or "
        "punctuation after it. Example: in 'Our Ref: XYZ 123 (see note 4)', the reference is 'XYZ 123'."))


class Distribution(BaseModel):
    fund_name: str
    investor_name: str = Field(description="Investor name exactly as written in the document")
    amount: Decimal = Field(description="Distribution amount, a plain number like 410000.00")
    currency: str = "CAD"
    distribution_type: str | None = None
    notice_date: date | None = None
    payment_date: date


SCHEMAS = {"capital_call": CapitalCall, "distribution": Distribution}