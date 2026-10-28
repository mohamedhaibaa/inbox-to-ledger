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
    reference: str | None = Field(None, description="Payment reference to quote on the wire")


class Distribution(BaseModel):
    fund_name: str
    investor_name: str = Field(description="Investor name exactly as written in the document")
    amount: Decimal = Field(description="Distribution amount, a plain number like 410000.00")
    currency: str = "CAD"
    distribution_type: str | None = None
    notice_date: date | None = None
    payment_date: date


SCHEMAS = {"capital_call": CapitalCall, "distribution": Distribution}