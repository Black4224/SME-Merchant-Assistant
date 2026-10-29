"""Creating transactions: business-rule validation and duplicate fingerprints.

This is the ONLY place that should create Transaction rows (API, CSV import
and the seed script all go through `add_transaction`).
"""
import hashlib
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import PaymentMethod as PM
from app.errors import NotFound
from app.models import (
    Category,
    Customer,
    ReconciliationStatus,
    Supplier,
    Transaction,
    TransactionSource,
)
from app.models import TransactionType as TT
from app.services.money import parse_amount
from app.services.text import normalize_text


class BusinessRuleError(ValueError):
    """The transaction is well-formed but violates a documented accounting rule."""


def check_transaction_rules(
    *,
    type: TT,
    payment_method: PM,
    customer_id: int | None,
    supplier_id: int | None,
) -> None:
    """Rules (see docs/business-rules.md):
    - `credit` is only valid for a sale (needs a customer) or a supplier purchase (needs a supplier).
    - customer_payment needs a customer and cannot be `credit`.
    - supplier_payment needs a supplier and cannot be `credit`.
    - expenses are paid now and link to no party.
    - a transaction can never reference a party type that does not belong to it.
    """
    if type == TT.SALE:
        if supplier_id is not None:
            raise BusinessRuleError("البيع لا يرتبط بمورد")
        if payment_method == PM.CREDIT and customer_id is None:
            raise BusinessRuleError("البيع بالآجل يحتاج إلى زبون")
    elif type == TT.CUSTOMER_PAYMENT:
        if customer_id is None:
            raise BusinessRuleError("تسديد الزبون يحتاج إلى زبون")
        if supplier_id is not None:
            raise BusinessRuleError("تسديد الزبون لا يرتبط بمورد")
        if payment_method == PM.CREDIT:
            raise BusinessRuleError("تسديد الزبون لا يمكن أن يكون آجلاً")
    elif type == TT.SUPPLIER_PURCHASE:
        if customer_id is not None:
            raise BusinessRuleError("شراء البضاعة لا يرتبط بزبون")
        if payment_method == PM.CREDIT and supplier_id is None:
            raise BusinessRuleError("الشراء بالآجل يحتاج إلى مورد")
    elif type == TT.SUPPLIER_PAYMENT:
        if supplier_id is None:
            raise BusinessRuleError("تسديد المورد يحتاج إلى مورد")
        if customer_id is not None:
            raise BusinessRuleError("تسديد المورد لا يرتبط بزبون")
        if payment_method == PM.CREDIT:
            raise BusinessRuleError("تسديد المورد لا يمكن أن يكون آجلاً")
    elif type == TT.EXPENSE:
        if customer_id is not None or supplier_id is not None:
            raise BusinessRuleError("المصروف التشغيلي لا يرتبط بزبون أو مورد")
        if payment_method == PM.CREDIT:
            raise BusinessRuleError("المصروف التشغيلي يُدفع مباشرة ولا يكون آجلاً")


def dedup_key(
    *,
    txn_date: date,
    type: TT,
    amount_iqd: int,
    payment_method: PM,
    description: str,
    reference: str | None,
    party_key: str,
) -> str:
    """Stable hash of a transaction's business content (no ids, no timestamps)."""
    parts = [
        txn_date.isoformat(),
        type.value,
        str(amount_iqd),
        payment_method.value,
        normalize_text(description),
        normalize_text(reference),
        normalize_text(party_key),
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _party_name(session: Session, customer_id: int | None, supplier_id: int | None) -> str:
    if customer_id is not None:
        c = session.get(Customer, customer_id)
        if c is None:
            raise BusinessRuleError("الزبون غير موجود")
        return c.name
    if supplier_id is not None:
        s = session.get(Supplier, supplier_id)
        if s is None:
            raise BusinessRuleError("المورد غير موجود")
        return s.name
    return ""


def _prepare(
    session: Session,
    *,
    txn_date: date,
    type: TT,
    amount: object,
    description: str,
    payment_method: PM,
    reference: str | None,
    customer_id: int | None,
    supplier_id: int | None,
    category_id: int | None,
    party_key: str | None,
    exclude_id: int | None = None,
) -> dict:
    """Validate everything and compute the dedup fields. Raises on any problem."""
    amount_iqd = parse_amount(amount)
    description = (description or "").strip()
    if not description:
        raise BusinessRuleError("الوصف مطلوب")
    if len(description) > 255:
        raise BusinessRuleError("الوصف طويل جداً (الحد 255 حرفاً)")
    reference = (reference or "").strip() or None
    if reference and len(reference) > 64:
        raise BusinessRuleError("المرجع طويل جداً (الحد 64 حرفاً)")
    check_transaction_rules(
        type=type, payment_method=payment_method, customer_id=customer_id, supplier_id=supplier_id
    )
    if category_id is not None and session.get(Category, category_id) is None:
        raise BusinessRuleError("التصنيف غير موجود")

    key = dedup_key(
        txn_date=txn_date,
        type=type,
        amount_iqd=amount_iqd,
        payment_method=payment_method,
        description=description,
        reference=reference,
        party_key=party_key or _party_name(session, customer_id, supplier_id),
    )
    q = select(func.coalesce(func.max(Transaction.dedup_seq), 0)).where(Transaction.dedup_key == key)
    if exclude_id is not None:
        q = q.where(Transaction.id != exclude_id)
    seq = (session.scalar(q) or 0) + 1
    return dict(
        txn_date=txn_date,
        type=type,
        amount_iqd=amount_iqd,
        description=description,
        reference=reference,
        payment_method=payment_method,
        customer_id=customer_id,
        supplier_id=supplier_id,
        category_id=category_id,
        dedup_key=key,
        dedup_seq=seq,
    )


def add_transaction(
    session: Session,
    *,
    txn_date: date,
    type: TT,
    amount: object,
    description: str,
    payment_method: PM,
    reference: str | None = None,
    customer_id: int | None = None,
    supplier_id: int | None = None,
    category_id: int | None = None,
    import_batch_id: int | None = None,
    source: TransactionSource = TransactionSource.MANUAL,
    status: ReconciliationStatus = ReconciliationStatus.RECONCILED,
    party_key: str | None = None,
) -> Transaction:
    """Validate and insert one transaction (flushes, does not commit)."""
    fields = _prepare(
        session, txn_date=txn_date, type=type, amount=amount, description=description,
        payment_method=payment_method, reference=reference, customer_id=customer_id,
        supplier_id=supplier_id, category_id=category_id, party_key=party_key,
    )
    txn = Transaction(
        **fields, import_batch_id=import_batch_id, source=source, reconciliation_status=status
    )
    session.add(txn)
    session.flush()
    return txn


def get_transaction(session: Session, txn_id: int) -> Transaction:
    txn = session.get(Transaction, txn_id)
    if txn is None:
        raise NotFound("المعاملة غير موجودة")
    return txn


def update_transaction(
    session: Session,
    txn: Transaction,
    *,
    txn_date: date,
    type: TT,
    amount: object,
    description: str,
    payment_method: PM,
    reference: str | None = None,
    customer_id: int | None = None,
    supplier_id: int | None = None,
    category_id: int | None = None,
    status: ReconciliationStatus | None = None,
) -> Transaction:
    """Full replacement (PUT). Re-validates all rules and recomputes duplicate fingerprints."""
    fields = _prepare(
        session, txn_date=txn_date, type=type, amount=amount, description=description,
        payment_method=payment_method, reference=reference, customer_id=customer_id,
        supplier_id=supplier_id, category_id=category_id, party_key=None, exclude_id=txn.id,
    )
    for k, v in fields.items():
        setattr(txn, k, v)
    if status is not None:
        txn.reconciliation_status = status
    session.flush()
    return txn


def delete_transaction(session: Session, txn: Transaction) -> None:
    """Hard delete. To keep a record but ignore it in totals, set status to `excluded` instead."""
    session.delete(txn)
    session.flush()
