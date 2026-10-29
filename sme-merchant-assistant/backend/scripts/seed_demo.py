"""Deterministic synthetic data for a fictional Iraqi grocery ("بقالة الرافدين التجريبية").

Everything here is invented. Same seed + same end date => byte-identical output.

Usage (from the backend/ folder):
    python -m scripts.seed_demo              # add demo data to the (empty) database
    python -m scripts.seed_demo --reset      # wipe the database first
    python -m scripts.seed_demo --csv-only   # only regenerate data/sample_transactions.csv
"""
import argparse
import csv
import random
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import DATA_DIR
from app.database import Base, SessionLocal, engine, init_db
from app.models import (
    Category,
    CategoryKind,
    Customer,
    PaymentMethod,
    ReconciliationStatus,
    Supplier,
    Transaction,
    TransactionSource,
    TransactionType,
)
from app.services.money import parse_amount
from app.services.settings_service import set_setting
from app.services.transactions import add_transaction

SEED = 20261015
DEFAULT_END_DATE = date(2026, 10, 15)  # a Thursday; fixed so the data never "moves"
DEFAULT_DAYS = 120
BUSINESS_NAME = "بقالة الرافدين التجريبية"
CSV_COLUMNS = [
    "date", "type", "amount", "description", "reference",
    "payment_method", "customer", "supplier", "category", "status",
]

# name, phone, behaviour: (daily chance of credit sale, typical sale, credit limit, daily chance of paying)
CUSTOMERS = {
    "أحمد كاظم الموسوي": (0.20, 150_000, 2_000_000, 0.10),   # reliable
    "زينب حسين العبيدي": (0.16, 120_000, 1_500_000, 0.08),   # reliable, smaller
    "علي صباح الجبوري": (0.14, 220_000, 3_500_000, 0.012),   # big and slow -> large/overdue debt
    "سارة محمد الربيعي": (0.10, 90_000, 900_000, 0.06),
    "مصطفى جاسم الساعدي": (0.12, 180_000, 2_800_000, 0.020),  # slow payer
    "حيدر ناصر التميمي": (0.07, 100_000, 800_000, 0.0),       # stopped paying
    "نور الهدى خالد": (0.08, 70_000, 600_000, 0.09),
    "مطعم السلام (خالد فرحان)": (0.18, 280_000, 4_000_000, 0.05),  # business customer
}
SUPPLIERS = {
    "شركة النهرين للمواد الغذائية": 0.6,
    "مخزن الرافدين بالجملة": 0.5,
    "مؤسسة دجلة للمنظفات": 0.7,
}
CATEGORIES = [
    ("مبيعات", CategoryKind.SALE),
    ("مشتريات بضاعة", CategoryKind.PURCHASE),
    ("إيجار", CategoryKind.EXPENSE),
    ("كهرباء ومولدة", CategoryKind.EXPENSE),
    ("رواتب", CategoryKind.EXPENSE),
    ("نقل", CategoryKind.EXPENSE),
    ("صيانة", CategoryKind.EXPENSE),
    ("اتصالات وإنترنت", CategoryKind.EXPENSE),
    ("مصاريف متفرقة", CategoryKind.EXPENSE),
]
WALLETS = [("زين كاش", "digital", "ZC"), ("فاست باي", "digital", "FP"), ("كي كارد", "bank", "QI")]


def _r(x: float, step: int = 250) -> int:
    """Round to a realistic IQD note step."""
    return max(step, int(round(x / step)) * step)


def build_dataset(
    end_date: date = DEFAULT_END_DATE, days: int = DEFAULT_DAYS, seed: int = SEED
) -> list[dict]:
    rng = random.Random(seed)
    start = end_date - timedelta(days=days - 1)
    rows: list[dict] = []
    inv = 1000
    rcpt = 500
    pay = 300
    cust_bal = dict.fromkeys(CUSTOMERS, 0)
    supp_bal = dict.fromkeys(SUPPLIERS, 0)
    supplier_names = list(SUPPLIERS)
    order_no = 0

    def add(d, ttype, amount, desc, method, *, ref="", customer="", supplier="", category="", status="reconciled"):
        rows.append(dict(
            date=d.isoformat(), type=ttype, amount=amount, description=desc, reference=ref,
            payment_method=method, customer=customer, supplier=supplier, category=category, status=status,
        ))

    for i in range(days):
        d = start + timedelta(days=i)
        wd = d.weekday()  # Mon=0 .. Thu=3, Fri=4, Sat=5, Sun=6
        factor = {4: 0.75, 3: 1.2}.get(wd, 1.0)
        recent = (end_date - d).days < 3

        # --- cash sales: morning + evening till totals ---
        for part, label, lo, hi in (("AM", "الفترة الصباحية", 330_000, 700_000), ("PM", "الفترة المسائية", 400_000, 850_000)):
            add(d, "sale", _r(rng.uniform(lo, hi) * factor), f"مبيعات نقدية - {label}", "cash",
                ref=f"DAY-{d:%Y%m%d}-{part}", category="مبيعات")

        # --- wallet / card sales ---
        for _ in range(rng.choice([0, 1, 1, 2])):
            wallet, method, code = rng.choice(WALLETS)
            unrec = recent or rng.random() < 0.04
            add(d, "sale", _r(rng.uniform(40_000, 320_000) * factor), f"بيع بالدفع الإلكتروني عبر {wallet}", method,
                ref=f"{code}-{rng.randint(100000, 999999)}", category="مبيعات",
                status="unreconciled" if unrec else "reconciled")

        # --- credit sales ---
        for name, (p_sale, typical, limit, _) in CUSTOMERS.items():
            if rng.random() < p_sale * factor:
                amount = min(_r(rng.uniform(0.4, 1.8) * typical), 900_000)
                if cust_bal[name] + amount > limit:
                    continue
                inv += 1
                cust_bal[name] += amount
                add(d, "sale", amount, f"بيع آجل - فاتورة {inv}", "credit", ref=f"INV-{inv}", customer=name, category="مبيعات")

        # --- customer payments against debt ---
        for name, (_, _, _, p_pay) in CUSTOMERS.items():
            if cust_bal[name] > 0 and rng.random() < p_pay:
                frac = rng.choice([0.25, 0.4, 0.5, 0.75, 1.0, 1.0])
                amount = min(cust_bal[name], _r(cust_bal[name] * frac))
                rcpt += 1
                cust_bal[name] -= amount
                method = rng.choice(["cash", "cash", "digital"])
                add(d, "customer_payment", amount, "تسديد من الزبون", method, ref=f"RCPT-{rcpt}", customer=name)

        # --- supplier purchases (Sun & Wed) ---
        if wd in (6, 2):
            order_no += 1
            sname = supplier_names[order_no % len(supplier_names)]
            amount = _r(rng.uniform(2_300_000, 4_300_000), 5_000)
            on_credit = rng.random() < SUPPLIERS[sname]
            if on_credit:
                supp_bal[sname] += amount
            add(d, "supplier_purchase", amount, f"شراء بضاعة - طلبية {order_no}", "credit" if on_credit else "cash",
                ref=f"PO-{order_no}", supplier=sname, category="مشتريات بضاعة")

        # --- supplier payments (every Thursday) ---
        if wd == 3:
            for sname in supplier_names:
                if supp_bal[sname] > 0:
                    amount = min(supp_bal[sname], _r(supp_bal[sname] * rng.choice([0.5, 0.75, 1.0]), 5_000))
                    pay += 1
                    supp_bal[sname] -= amount
                    add(d, "supplier_payment", amount, "تسديد دفعة للمورد", rng.choice(["cash", "bank"]),
                        ref=f"PAY-{pay}", supplier=sname)

        # --- operating expenses ---
        if d.day == 1:
            add(d, "expense", 1_500_000, "إيجار المحل", "cash", category="إيجار")
        if d.day == 5:
            add(d, "expense", _r(rng.uniform(380_000, 430_000), 5_000), "اشتراك المولدة الأهلية", "cash", category="كهرباء ومولدة")
        if d.day == 10:
            add(d, "expense", 45_000, "اشتراك الإنترنت", "digital", category="اتصالات وإنترنت")
        if d.day == 28:
            add(d, "expense", 700_000, "راتب العامل - محمد", "cash", category="رواتب")
            add(d, "expense", 650_000, "راتب العامل - يوسف", "cash", category="رواتب")
        if wd == 0:
            add(d, "expense", _r(rng.uniform(40_000, 90_000)), "أجور نقل البضاعة الأسبوعية", "cash", category="نقل")
        if rng.random() < 0.04:
            add(d, "expense", _r(rng.uniform(60_000, 250_000)), "صيانة ثلاجة العرض", "cash", category="صيانة")
        if rng.random() < 0.30:
            add(d, "expense", _r(rng.uniform(5_000, 40_000)), "مصاريف نثرية (أكياس، تنظيف)", "cash", category="مصاريف متفرقة")

    rows = _plant_anomalies(rows, end_date)
    return rows


def _plant_anomalies(rows: list[dict], end_date: date) -> list[dict]:
    """Insert a few deliberate data-quality problems. Documented in docs/synthetic-data.md."""
    rows = [dict(r) for r in rows]

    # 1) exact duplicate of a credit sale ~12 days before the end
    cutoff = (end_date - timedelta(days=12)).isoformat()
    idx = next(i for i, r in enumerate(rows) if r["date"] >= cutoff and r["payment_method"] == "credit" and r["type"] == "sale")
    dup = dict(rows[idx], status="unreconciled")
    rows.insert(idx + 1, dup)

    # 2) generator subscription entered with an extra zero (10x)
    idx = max(i for i, r in enumerate(rows) if r["category"] == "كهرباء ومولدة")
    rows[idx]["amount"] *= 10
    rows[idx]["status"] = "unreconciled"

    # 3) a sale typed with a date 3 days in the future
    future = end_date + timedelta(days=3)
    rows.append(dict(
        date=future.isoformat(), type="sale", amount=275_000, description="مبيعات نقدية - تاريخ مُدخل بالخطأ",
        reference="DAY-TYPO-01", payment_method="cash", customer="", supplier="", category="مبيعات", status="unreconciled",
    ))
    rows.sort(key=lambda r: r["date"])  # stable sort keeps same-day generation order
    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:  # BOM so Excel shows Arabic correctly
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerows(rows)


def load_rows_into_db(session: Session, rows: list[dict], source: TransactionSource = TransactionSource.SEED) -> int:
    cats = {c.name: c for c in session.scalars(select(Category))}
    for name, kind in CATEGORIES:
        if name not in cats:
            cats[name] = Category(name=name, kind=kind)
            session.add(cats[name])
    custs = {c.name: c for c in session.scalars(select(Customer))}
    supps = {s.name: s for s in session.scalars(select(Supplier))}
    for r in rows:
        if r["customer"] and r["customer"] not in custs:
            custs[r["customer"]] = Customer(name=r["customer"])
            session.add(custs[r["customer"]])
        if r["supplier"] and r["supplier"] not in supps:
            supps[r["supplier"]] = Supplier(name=r["supplier"])
            session.add(supps[r["supplier"]])
    session.flush()

    for r in rows:
        add_transaction(
            session,
            txn_date=date.fromisoformat(r["date"]),
            type=TransactionType(r["type"]),
            amount=parse_amount(r["amount"]),
            description=r["description"],
            reference=r["reference"] or None,
            payment_method=PaymentMethod(r["payment_method"]),
            customer_id=custs[r["customer"]].id if r["customer"] else None,
            supplier_id=supps[r["supplier"]].id if r["supplier"] else None,
            category_id=cats[r["category"]].id if r["category"] else None,
            source=source,
            status=ReconciliationStatus(r["status"]),
            party_key=r["customer"] or r["supplier"],
        )
    return len(rows)


def seed_database(session: Session, end_date: date = DEFAULT_END_DATE, days: int = DEFAULT_DAYS) -> int:
    rows = build_dataset(end_date, days)
    n = load_rows_into_db(session, rows)
    set_setting(session, "business_name", BUSINESS_NAME)
    set_setting(session, "is_demo_data", "true")
    set_setting(session, "reference_date", end_date.isoformat())
    session.commit()
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reset", action="store_true", help="drop and recreate all tables first")
    ap.add_argument("--csv-only", action="store_true", help="only write data/sample_transactions.csv")
    ap.add_argument("--end-date", type=date.fromisoformat, default=DEFAULT_END_DATE)
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    args = ap.parse_args()

    rows = build_dataset(args.end_date, args.days)
    csv_path = DATA_DIR / "sample_transactions.csv"
    write_csv(rows, csv_path)
    print(f"wrote {len(rows)} rows -> {csv_path}")
    if args.csv_only:
        return

    if args.reset:
        Base.metadata.drop_all(engine)
    init_db()
    with SessionLocal() as session:
        if session.scalar(select(Transaction.id).limit(1)) is not None:
            raise SystemExit("Database already has transactions. Re-run with --reset to wipe it.")
        n = seed_database(session, args.end_date, args.days)
    print(f"seeded {n} transactions into {engine.url}")


if __name__ == "__main__":
    main()
