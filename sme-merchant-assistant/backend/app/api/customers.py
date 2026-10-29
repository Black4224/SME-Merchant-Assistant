from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.common import page_params, paginate
from app.database import get_session
from app.errors import Conflict, NotFound, Unprocessable
from app.models import Customer, PaymentMethod, Supplier
from app.models import TransactionType as TT
from app.schemas.transactions import CustomerPaymentIn, PartyIn
from app.services.customers import all_customer_balances, customer_ledger
from app.services.money import format_iqd
from app.services.settings_service import get_reference_date
from app.services.suppliers import supplier_payables
from app.services.text import normalize_text
from app.services.transaction_queries import serialize
from app.services.transactions import add_transaction

router = APIRouter(prefix="/api", tags=["customers"])


def _summary(b) -> dict:
    d = b.to_dict()
    d["open_invoices_count"] = len(d.pop("open_invoices"))
    d.pop("credit_sale_ids"), d.pop("payment_ids")
    return d


def _get_customer(session: Session, customer_id: int) -> Customer:
    c = session.get(Customer, customer_id)
    if c is None:
        raise NotFound("الزبون غير موجود")
    return c


@router.get("/customers")
def list_customers(
    q: str | None = Query(None, max_length=100),
    has_debt: bool | None = None,
    paging: tuple[int, int] = Depends(page_params),
    session: Session = Depends(get_session),
):
    rows = all_customer_balances(session)
    if q and q.strip():
        needle = normalize_text(q)
        rows = [b for b in rows if needle in normalize_text(b.name)]
    if has_debt is True:
        rows = [b for b in rows if b.outstanding > 0]
    elif has_debt is False:
        rows = [b for b in rows if b.outstanding <= 0]
    rows.sort(key=lambda b: (-b.outstanding, b.name))
    page, size = paging
    window = rows[(page - 1) * size : page * size]
    return paginate([_summary(b) for b in window], len(rows), page, size)


@router.post("/customers", status_code=201)
def create_customer(body: PartyIn, session: Session = Depends(get_session)):
    if any(normalize_text(c.name) == normalize_text(body.name) for c in session.scalars(select(Customer))):
        raise Conflict("يوجد زبون بنفس الاسم", code="duplicate_name")
    c = Customer(name=body.name, phone=body.phone)
    session.add(c)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise Conflict("يوجد زبون بنفس الاسم", code="duplicate_name") from None
    return {"id": c.id, "name": c.name, "phone": c.phone}


@router.get("/customers/{customer_id}/debts")
def customer_debts(customer_id: int, session: Session = Depends(get_session)):
    c = _get_customer(session, customer_id)
    balance = next(b for b in all_customer_balances(session) if b.customer_id == c.id)
    return {
        "customer": {"id": c.id, "name": c.name, "phone": c.phone},
        "as_of": get_reference_date(session).isoformat(),
        "balance": balance.to_dict(),
        "history": [
            {"transaction_id": e.transaction_id, "date": e.date.isoformat(), "kind": e.kind,
             "amount": e.amount, "description": e.description, "payment_method": e.payment_method,
             "balance_after": e.balance_after}
            for e in customer_ledger(session, c.id)
        ],
    }


@router.post("/customers/{customer_id}/payments", status_code=201)
def record_payment(customer_id: int, body: CustomerPaymentIn, session: Session = Depends(get_session)):
    c = _get_customer(session, customer_id)
    pay_date = body.date or get_reference_date(session)
    before = next(b for b in all_customer_balances(session, as_of=pay_date) if b.customer_id == c.id).outstanding
    if not body.allow_overpayment and body.amount > max(before, 0):
        raise Unprocessable(
            f"المبلغ {format_iqd(body.amount)} أكبر من الدين المستحق {format_iqd(max(before, 0))}",
            code="overpayment", details={"outstanding": max(before, 0), "amount": body.amount},
        )
    txn = add_transaction(
        session, txn_date=pay_date, type=TT.CUSTOMER_PAYMENT, amount=body.amount,
        description=body.description, payment_method=PaymentMethod(body.payment_method),
        reference=body.reference, customer_id=c.id,
    )
    session.commit()
    after = next(b for b in all_customer_balances(session) if b.customer_id == c.id)
    return {"transaction": serialize(txn), "outstanding_before": before, "outstanding_after": after.outstanding}


@router.get("/suppliers")
def list_suppliers(session: Session = Depends(get_session)):
    return {"items": supplier_payables(session)}


@router.post("/suppliers", status_code=201)
def create_supplier(body: PartyIn, session: Session = Depends(get_session)):
    if any(normalize_text(s.name) == normalize_text(body.name) for s in session.scalars(select(Supplier))):
        raise Conflict("يوجد مورد بنفس الاسم", code="duplicate_name")
    s = Supplier(name=body.name, phone=body.phone)
    session.add(s)
    session.commit()
    return {"id": s.id, "name": s.name, "phone": s.phone}
