from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.common import page_params, paginate
from app.database import get_session
from app.errors import Unprocessable
from app.models import PaymentMethod, ReconciliationStatus, TransactionType
from app.schemas.transactions import TransactionIn
from app.services.anomalies import detect_anomalies
from app.services.money import InvalidAmount, parse_amount
from app.services.transaction_queries import TxnFilters, flags_by_transaction, list_transactions, serialize
from app.services.transactions import add_transaction, delete_transaction, get_transaction, update_transaction

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


def _amount_filter(v: str | None, name: str) -> int | None:
    if v is None or v == "":
        return None
    try:
        return parse_amount(v)
    except InvalidAmount as e:
        raise Unprocessable(f"{name}: {e}", code="invalid_amount") from None


@router.get("")
def list_(
    q: str | None = Query(None, max_length=100),
    type: TransactionType | None = None,
    payment_method: PaymentMethod | None = None,
    status: ReconciliationStatus | None = None,
    customer_id: int | None = None,
    supplier_id: int | None = None,
    category_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    min_amount: str | None = None,
    max_amount: str | None = None,
    sort: str = Query("date", pattern="^(date|amount|id)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    paging: tuple[int, int] = Depends(page_params),
    session: Session = Depends(get_session),
):
    if date_from and date_to and date_from > date_to:
        raise Unprocessable("تاريخ البداية بعد تاريخ النهاية", code="invalid_date_range")
    lo, hi = _amount_filter(min_amount, "min_amount"), _amount_filter(max_amount, "max_amount")
    if lo is not None and hi is not None and lo > hi:
        raise Unprocessable("الحد الأدنى للمبلغ أكبر من الحد الأعلى", code="invalid_amount_range")
    filters = TxnFilters(q, type, payment_method, status, customer_id, supplier_id, category_id, date_from, date_to, lo, hi)
    page, size = paging
    rows, total = list_transactions(session, filters, page=page, page_size=size, sort=sort, descending=order == "desc")
    flags = flags_by_transaction(detect_anomalies(session))
    return paginate([serialize(t, flags) for t in rows], total, page, size)


def _kwargs(body: TransactionIn) -> dict:
    return dict(
        txn_date=body.date, type=body.type, amount=body.amount, description=body.description,
        payment_method=body.payment_method, reference=body.reference, customer_id=body.customer_id,
        supplier_id=body.supplier_id, category_id=body.category_id,
    )


@router.post("", status_code=201)
def create(body: TransactionIn, session: Session = Depends(get_session)):
    txn = add_transaction(
        session, **_kwargs(body),
        status=body.reconciliation_status or ReconciliationStatus.RECONCILED,
    )
    session.commit()
    return serialize(txn)


@router.get("/{txn_id}")
def read(txn_id: int, session: Session = Depends(get_session)):
    txn = get_transaction(session, txn_id)
    return serialize(txn, flags_by_transaction(detect_anomalies(session)))


@router.put("/{txn_id}")
def replace(txn_id: int, body: TransactionIn, session: Session = Depends(get_session)):
    txn = update_transaction(session, get_transaction(session, txn_id), **_kwargs(body), status=body.reconciliation_status)
    session.commit()
    return serialize(txn)


@router.delete("/{txn_id}")
def remove(txn_id: int, session: Session = Depends(get_session)):
    delete_transaction(session, get_transaction(session, txn_id))
    session.commit()
    return {"deleted": txn_id}
