from datetime import date as Date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import PaymentMethod, ReconciliationStatus, TransactionType
from app.services.money import parse_amount


class _AmountMixin(BaseModel):
    # Integer dinars, or text such as "1,250,000" / "١٢٥٠٠٠٠". Floats and booleans are rejected.
    amount: int

    @field_validator("amount", mode="before")
    @classmethod
    def _amount_ok(cls, v):
        return parse_amount(v)


class TransactionIn(_AmountMixin):
    model_config = ConfigDict(extra="forbid")
    date: Date
    type: TransactionType
    description: str = Field(min_length=1, max_length=255)
    payment_method: PaymentMethod
    reference: str | None = Field(default=None, max_length=64)
    customer_id: int | None = None
    supplier_id: int | None = None
    category_id: int | None = None
    reconciliation_status: ReconciliationStatus | None = None


class CustomerPaymentIn(_AmountMixin):
    model_config = ConfigDict(extra="forbid")
    date: Date | None = None  # default: today's reference date
    payment_method: Literal["cash", "digital", "bank"] = "cash"
    description: str = Field(default="تسديد من الزبون", min_length=1, max_length=255)
    reference: str | None = Field(default=None, max_length=64)
    allow_overpayment: bool = False


class PartyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=32)

    @field_validator("name")
    @classmethod
    def _clean(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("الاسم مطلوب")
        return v


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    business_name: str | None = Field(default=None, min_length=1, max_length=80)
    credit_terms_days: int | None = Field(default=None, ge=1, le=365)
    currency_display: Literal["د.ع", "IQD"] | None = None


class ResetDemoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: str
