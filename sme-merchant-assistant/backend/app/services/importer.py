"""CSV import: parse -> map columns -> validate -> detect duplicates -> (preview | commit).

Stateless two-step flow: preview and confirm both receive the file, so the server keeps no
temporary state. `confirm` can pin the exact previewed file with `expected_sha256`.

Duplicate rule: every valid row gets (dedup_key, occurrence n-th in this file). It is a duplicate
if the database already holds >= n rows with that key. So re-importing a file adds nothing, while
two identical rows inside one new file are both kept (and reported as a warning).
"""
import hashlib
import io
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import Conflict, PayloadTooLarge, Unprocessable
from app.models import (
    Category,
    CategoryKind,
    Customer,
    ImportBatch,
    PaymentMethod,
    ReconciliationStatus,
    Supplier,
    TransactionSource,
    TransactionType,
)
from app.services.money import InvalidAmount, parse_amount
from app.services.settings_service import get_reference_date
from app.services.text import normalize_text
from app.services.transactions import (
    BusinessRuleError,
    add_transaction,
    check_transaction_rules,
    dedup_key,
)

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 20_000
PREVIEW_ROWS = 200
MAX_REPORTED_ERRORS = 500
MIN_DATE = date(2000, 1, 1)
MAX_DATE = date(2100, 12, 31)

TARGET_FIELDS = ["date", "type", "amount", "description", "reference",
                 "payment_method", "customer", "supplier", "category", "status"]
REQUIRED_FIELDS = ["date", "type", "amount", "description", "payment_method"]


def _norm_set(*items: str) -> set[str]:
    return {normalize_text(i) for i in items}


HEADER_ALIASES = {
    "date": _norm_set("date", "التاريخ", "تاريخ", "day"),
    "type": _norm_set("type", "النوع", "نوع", "نوع العملية", "نوع الحركة", "transaction type"),
    "amount": _norm_set("amount", "المبلغ", "مبلغ", "القيمة", "الإجمالي", "total", "value"),
    "description": _norm_set("description", "الوصف", "البيان", "التفاصيل", "details", "desc", "note"),
    "reference": _norm_set("reference", "ref", "المرجع", "رقم الفاتورة", "رقم الوصل", "invoice"),
    "payment_method": _norm_set("payment_method", "payment method", "method", "payment", "طريقة الدفع", "طريقه الدفع", "الدفع"),
    "customer": _norm_set("customer", "الزبون", "زبون", "العميل", "اسم الزبون"),
    "supplier": _norm_set("supplier", "المورد", "مورد", "اسم المورد"),
    "category": _norm_set("category", "التصنيف", "الفئة", "تصنيف"),
    "status": _norm_set("status", "الحالة", "حالة"),
}

TYPE_VALUES = {
    TransactionType.SALE: _norm_set("sale", "sales", "بيع", "مبيعات", "مبيع"),
    TransactionType.CUSTOMER_PAYMENT: _norm_set("customer_payment", "تسديد", "تسديد زبون", "تسديد من الزبون", "دفعة زبون", "قبض", "سداد"),
    TransactionType.EXPENSE: _norm_set("expense", "مصروف", "مصاريف", "صرف"),
    TransactionType.SUPPLIER_PURCHASE: _norm_set("supplier_purchase", "purchase", "شراء", "مشتريات", "شراء بضاعة"),
    TransactionType.SUPPLIER_PAYMENT: _norm_set("supplier_payment", "دفع مورد", "تسديد مورد", "تسديد للمورد", "دفعة مورد"),
}
METHOD_VALUES = {
    PaymentMethod.CASH: _norm_set("cash", "نقد", "نقدا", "نقدي", "كاش"),
    PaymentMethod.DIGITAL: _norm_set("digital", "wallet", "محفظة", "زين كاش", "فاست باي", "الكتروني", "إلكتروني", "دفع الكتروني"),
    PaymentMethod.BANK: _norm_set("bank", "بنك", "تحويل", "تحويل بنكي", "كي كارد", "بطاقة", "card"),
    PaymentMethod.CREDIT: _norm_set("credit", "آجل", "اجل", "دين", "بالآجل", "ذمم"),
}
STATUS_VALUES = {
    ReconciliationStatus.RECONCILED: _norm_set("reconciled", "مطابق", ""),
    ReconciliationStatus.UNRECONCILED: _norm_set("unreconciled", "غير مطابق"),
    ReconciliationStatus.EXCLUDED: _norm_set("excluded", "مستبعد"),
}
CATEGORY_KIND = {
    TransactionType.SALE: CategoryKind.SALE,
    TransactionType.EXPENSE: CategoryKind.EXPENSE,
    TransactionType.SUPPLIER_PURCHASE: CategoryKind.PURCHASE,
}


def _lookup(table: dict, raw: str):
    n = normalize_text(raw)
    for key, values in table.items():
        if n in values:
            return key
    return None


def clean_name(value: str) -> str:
    return " ".join((value or "").split())


# ----------------------------------------------------------------- parsing
def decode_csv(content: bytes) -> str:
    if not content.strip():
        raise Unprocessable("الملف فارغ", code="empty_file")
    for enc in ("utf-8-sig", "cp1256"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    raise Unprocessable("تعذّر قراءة ترميز الملف. احفظه بصيغة CSV UTF-8", code="bad_encoding")


def _check_shape(text: str, sep: str) -> None:
    """pandas silently turns surplus fields into an index; refuse ragged files instead."""
    import csv

    reader = csv.reader(io.StringIO(text), delimiter=sep)
    width = None
    for row in reader:
        if width is None:
            width = len(row)
            continue
        if len(row) > width and any(c.strip() for c in row[width:]):
            raise Unprocessable(
                f"السطر {reader.line_num} يحتوي على {len(row)} أعمدة بينما العنوان فيه {width}. "
                "تأكد من وضع الفواصل داخل النصوص بين علامتي اقتباس",
                code="bad_csv",
            )


def read_table(content: bytes) -> pd.DataFrame:
    if len(content) > MAX_FILE_BYTES:
        raise PayloadTooLarge(f"حجم الملف أكبر من {MAX_FILE_BYTES // (1024 * 1024)} ميغابايت")
    text = decode_csv(content)
    first = text.splitlines()[0] if text.splitlines() else ""
    sep = max([",", ";", "\t"], key=first.count)
    _check_shape(text, sep)
    try:
        df = pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=False,
                         on_bad_lines="error", index_col=False)
    except (pd.errors.ParserError, pd.errors.EmptyDataError) as e:
        raise Unprocessable(f"ملف CSV غير صالح: {e}", code="bad_csv") from None
    df.columns = [str(c).strip() for c in df.columns]
    if len(df) == 0:
        raise Unprocessable("الملف لا يحتوي على صفوف بيانات", code="no_rows")
    if len(df) > MAX_ROWS:
        raise PayloadTooLarge(f"عدد الصفوف أكبر من الحد المسموح ({MAX_ROWS})")
    return df


def suggest_mapping(headers: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for fld, aliases in HEADER_ALIASES.items():
        for h in headers:
            if normalize_text(h) in aliases and h not in mapping.values():
                mapping[fld] = h
                break
    return mapping


def validate_mapping(mapping: dict[str, str], headers: list[str]) -> dict[str, str]:
    for fld, col in mapping.items():
        if fld not in TARGET_FIELDS:
            raise Unprocessable(f"حقل غير معروف في الربط: {fld}", code="bad_mapping")
        if col not in headers:
            raise Unprocessable(f"العمود '{col}' غير موجود في الملف", code="bad_mapping")
    if len(set(mapping.values())) != len(mapping):
        raise Unprocessable("لا يمكن ربط عمود واحد بأكثر من حقل", code="bad_mapping")
    return mapping


def parse_import_date(text: str) -> date:
    t = normalize_text(text).split("t")[0].split(" ")[0]
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", t)
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", t)  # day-first (Iraq)
        if not m:
            raise ValueError("صيغة التاريخ غير مفهومة (استخدم YYYY-MM-DD أو DD/MM/YYYY)")
        d, mo, y = map(int, m.groups())
    try:
        result = date(y, mo, d)
    except ValueError:
        raise ValueError("تاريخ غير موجود في التقويم") from None
    if not MIN_DATE <= result <= MAX_DATE:
        raise ValueError("التاريخ خارج النطاق المعقول")
    return result


# ----------------------------------------------------------------- row validation
@dataclass
class RowResult:
    row_number: int
    status: str = "valid"  # valid | duplicate | invalid
    data: dict = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dedup_key: str | None = None
    occurrence: int = 0

    def to_dict(self) -> dict:
        return {"row_number": self.row_number, "status": self.status, "data": self.data,
                "errors": self.errors, "warnings": self.warnings}


def _validate_row(raw: dict[str, str], mapping: dict[str, str], row_number: int, ref_date: date) -> RowResult:
    res = RowResult(row_number)

    def get(fld: str) -> str:
        col = mapping.get(fld)
        return (raw.get(col, "") if col else "").strip()

    def err(fld: str, msg: str) -> None:
        res.errors.append({"field": fld, "message": msg})

    d = ttype = method = amount = None
    status = ReconciliationStatus.RECONCILED
    try:
        d = parse_import_date(get("date"))
    except ValueError as e:
        err("date", str(e))
    ttype = _lookup(TYPE_VALUES, get("type"))
    if ttype is None:
        err("type", f"نوع العملية غير معروف: '{get('type')}'")
    method = _lookup(METHOD_VALUES, get("payment_method"))
    if method is None:
        err("payment_method", f"طريقة الدفع غير معروفة: '{get('payment_method')}'")
    try:
        amount = parse_amount(get("amount"))
    except InvalidAmount as e:
        err("amount", str(e))
    description = " ".join(get("description").split())
    if not description:
        err("description", "الوصف مطلوب")
    elif len(description) > 255:
        err("description", "الوصف طويل جداً (الحد 255 حرفاً)")
    reference = get("reference") or None
    if reference and len(reference) > 64:
        err("reference", "المرجع طويل جداً (الحد 64 حرفاً)")
    customer, supplier, category = clean_name(get("customer")), clean_name(get("supplier")), clean_name(get("category"))
    for fld, val, limit in (("customer", customer, 120), ("supplier", supplier, 120), ("category", category, 80)):
        if len(val) > limit:
            err(fld, f"الاسم طويل جداً (الحد {limit})")
    if get("status"):
        st = _lookup(STATUS_VALUES, get("status"))
        if st is None:
            err("status", f"حالة غير معروفة: '{get('status')}'")
        else:
            status = st

    if ttype and method and not res.errors:
        try:
            check_transaction_rules(type=ttype, payment_method=method,
                                    customer_id=1 if customer else None, supplier_id=1 if supplier else None)
        except BusinessRuleError as e:
            err("row", str(e))

    if res.errors:
        res.status = "invalid"
        res.data = {k: v for k, v in raw.items()}
        return res

    if category and ttype not in CATEGORY_KIND:
        res.warnings.append("التصنيف يُتجاهل لهذا النوع من المعاملات")
        category = ""
    if d > ref_date:
        res.warnings.append("التاريخ بعد تاريخ اليوم")
    res.data = {
        "date": d.isoformat(), "type": ttype.value, "amount_iqd": amount, "description": description,
        "reference": reference, "payment_method": method.value, "customer": customer or None,
        "supplier": supplier or None, "category": category or None, "status": status.value,
    }
    res.dedup_key = dedup_key(txn_date=d, type=ttype, amount_iqd=amount, payment_method=method,
                              description=description, reference=reference, party_key=customer or supplier or "")
    return res


# ----------------------------------------------------------------- analysis
@dataclass
class ImportAnalysis:
    filename: str
    sha256: str
    headers: list[str]
    suggested_mapping: dict[str, str]
    mapping: dict[str, str]
    missing_required: list[str]
    rows: list[RowResult]
    already_imported: bool
    new_customers: list[str] = field(default_factory=list)
    new_suppliers: list[str] = field(default_factory=list)
    new_categories: list[str] = field(default_factory=list)

    @property
    def needs_mapping(self) -> bool:
        return bool(self.missing_required)

    def count(self, status: str) -> int:
        return sum(1 for r in self.rows if r.status == status)

    def to_dict(self) -> dict:
        invalid = [r for r in self.rows if r.status == "invalid"]
        return {
            "filename": self.filename,
            "file_sha256": self.sha256,
            "headers": self.headers,
            "suggested_mapping": self.suggested_mapping,
            "mapping": self.mapping,
            "needs_mapping": self.needs_mapping,
            "missing_required_fields": self.missing_required,
            "already_imported": self.already_imported,
            "counts": {"total": len(self.rows), "valid": self.count("valid"),
                       "duplicate": self.count("duplicate"), "invalid": len(invalid)},
            "will_create": {"customers": self.new_customers, "suppliers": self.new_suppliers,
                            "categories": self.new_categories},
            "rows": [r.to_dict() for r in self.rows[:PREVIEW_ROWS]],
            "errors": [r.to_dict() for r in invalid[:MAX_REPORTED_ERRORS]],
            "errors_truncated": len(invalid) > MAX_REPORTED_ERRORS,
        }


def analyze_csv(session: Session, content: bytes, filename: str, mapping: dict[str, str] | None = None) -> ImportAnalysis:
    sha = hashlib.sha256(content).hexdigest()
    df = read_table(content)
    headers = list(df.columns)
    suggested = suggest_mapping(headers)
    use = validate_mapping(mapping, headers) if mapping else suggested
    missing = [f for f in REQUIRED_FIELDS if f not in use]
    already = session.scalar(select(ImportBatch.id).where(ImportBatch.file_sha256 == sha)) is not None
    analysis = ImportAnalysis(filename, sha, headers, suggested, use, missing, [], already)
    if missing:
        return analysis

    ref = get_reference_date(session)
    results = [
        _validate_row(rec, use, i + 2, ref) for i, rec in enumerate(df.to_dict(orient="records"))
    ]

    valid = [r for r in results if r.status == "valid"]
    keys = list({r.dedup_key for r in valid})
    db_max: dict[str, int] = {}
    from app.models import Transaction

    for i in range(0, len(keys), 500):
        chunk = keys[i : i + 500]
        for k, mx in session.execute(
            select(Transaction.dedup_key, func.max(Transaction.dedup_seq))
            .where(Transaction.dedup_key.in_(chunk)).group_by(Transaction.dedup_key)
        ):
            db_max[k] = mx
    seen: Counter[str] = Counter()
    for r in valid:
        seen[r.dedup_key] += 1
        r.occurrence = seen[r.dedup_key]
        if r.occurrence <= db_max.get(r.dedup_key, 0):
            r.status = "duplicate"
            r.warnings.append("موجودة مسبقاً في قاعدة البيانات وستُتخطى")
        elif r.occurrence > 1:
            r.warnings.append("صف مكرر داخل الملف نفسه (سيُستورد لأنه قد يكون عملية حقيقية متكررة)")

    existing_c = {normalize_text(c.name) for c in session.scalars(select(Customer))}
    existing_s = {normalize_text(s.name) for s in session.scalars(select(Supplier))}
    existing_k = {normalize_text(k.name) for k in session.scalars(select(Category))}
    for r in results:
        if r.status != "valid":
            continue
        for name, pool, bucket in (
            (r.data["customer"], existing_c, analysis.new_customers),
            (r.data["supplier"], existing_s, analysis.new_suppliers),
            (r.data["category"], existing_k, analysis.new_categories),
        ):
            if name and normalize_text(name) not in pool:
                pool.add(normalize_text(name))
                bucket.append(name)
    analysis.rows = results
    return analysis


# ----------------------------------------------------------------- commit
def commit_import(session: Session, analysis: ImportAnalysis, *, skip_invalid: bool) -> dict:
    """Write all valid, non-duplicate rows in ONE database transaction (caller commits)."""
    if analysis.needs_mapping:
        raise Unprocessable("يجب ربط الأعمدة المطلوبة أولاً: " + "، ".join(analysis.missing_required), code="mapping_required")
    if analysis.already_imported:
        raise Conflict("هذا الملف نفسه تم استيراده مسبقاً", code="file_already_imported")
    invalid = analysis.count("invalid")
    if invalid and not skip_invalid:
        raise Unprocessable(f"يوجد {invalid} صف غير صالح. صحّح الملف أو اختر تخطي الصفوف غير الصالحة",
                            code="invalid_rows", details={"invalid_count": invalid})

    to_import = [r for r in analysis.rows if r.status == "valid"]
    batch = ImportBatch(filename=analysis.filename[:255], file_sha256=analysis.sha256,
                        row_count=len(analysis.rows), imported_count=len(to_import),
                        duplicate_count=analysis.count("duplicate"), invalid_count=invalid)
    session.add(batch)
    session.flush()

    custs = {normalize_text(c.name): c for c in session.scalars(select(Customer))}
    supps = {normalize_text(s.name): s for s in session.scalars(select(Supplier))}
    cats = {normalize_text(c.name): c for c in session.scalars(select(Category))}

    def get_or_create(pool: dict, model, name: str | None, **extra):
        if not name:
            return None
        k = normalize_text(name)
        if k not in pool:
            pool[k] = model(name=name, **extra)
            session.add(pool[k])
            session.flush()
        return pool[k]

    for r in to_import:
        d = r.data
        ttype = TransactionType(d["type"])
        cust = get_or_create(custs, Customer, d["customer"])
        supp = get_or_create(supps, Supplier, d["supplier"])
        cat = get_or_create(cats, Category, d["category"], kind=CATEGORY_KIND[ttype]) if d["category"] else None
        add_transaction(
            session,
            txn_date=date.fromisoformat(d["date"]), type=ttype, amount=d["amount_iqd"],
            description=d["description"], reference=d["reference"],
            payment_method=PaymentMethod(d["payment_method"]),
            customer_id=cust.id if cust else None, supplier_id=supp.id if supp else None,
            category_id=cat.id if cat else None, import_batch_id=batch.id,
            source=TransactionSource.CSV_IMPORT, status=ReconciliationStatus(d["status"]),
            party_key=d["customer"] or d["supplier"] or "",
        )
    return {
        "batch_id": batch.id,
        "filename": analysis.filename,
        "total_rows": len(analysis.rows),
        "imported": len(to_import),
        "skipped_duplicates": analysis.count("duplicate"),
        "skipped_invalid": invalid,
        "created": {"customers": analysis.new_customers, "suppliers": analysis.new_suppliers,
                    "categories": analysis.new_categories},
    }
