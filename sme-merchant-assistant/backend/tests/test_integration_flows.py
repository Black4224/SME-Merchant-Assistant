"""Whole-system consistency: the same number must come out of every surface, state must stay coherent under arbitrary
operations, and the recorded frontend fixtures must still match the live API."""
import json
import random
from datetime import date, timedelta

import pytest

from app.ai.tools import execute
from app.config import get_settings
from app.services.periods import PERIOD_NAMES
from evaluation import oracle as O
from tests.test_seed_data import REF

TODAY = date.today().isoformat()
ROWS = O.load()


# ------------------------------------------------------------------ 1. one number, every surface
@pytest.mark.parametrize("period", PERIOD_NAMES)
def test_dashboard_reports_tools_and_oracle_agree_for_every_period(seeded_client, seeded, period):
    s, e = O.period(period)
    truth = O.summarize(ROWS, s, e)
    dash = seeded_client.get("/api/dashboard/summary", params={"period": period}).json()["period_summary"]
    rep = seeded_client.get("/api/reports/summary", params={"period": period}).json()["totals"]
    sales = execute(seeded, "get_sales_summary", {"period": period})
    prof = execute(seeded, "get_profit_summary", {"period": period})
    exp = execute(seeded, "get_expenses_summary", {"period": period})
    fv = lambda r, key: next(f.value for f in r.figures if f.key == key)

    for surface in (dash, rep):
        assert (surface["sales_total"], surface["expenses_total"], surface["purchases_total"], surface["estimated_profit"], surface["net_cash_flow"]) == \
               (truth["sales"], truth["expenses"], truth["purchases"], truth["profit"], truth["net_cash"]), period
    assert fv(sales, "sales_total") == truth["sales"]
    assert (fv(prof, "estimated_profit"), fv(prof, "net_cash_flow")) == (truth["profit"], truth["net_cash"])
    assert (fv(exp, "expenses_total"), fv(exp, "purchases_total")) == (truth["expenses"], truth["purchases"])


def test_debts_agree_across_customers_dashboard_reports_tools_and_oracle(seeded_client, seeded):
    truth = {n: v for n, v in O.debts(ROWS).items() if v["outstanding"] > 0}
    total, overdue = sum(v["outstanding"] for v in truth.values()), sum(v["overdue"] for v in truth.values())
    dash = seeded_client.get("/api/dashboard/summary").json()["outstanding_debts"]
    rep = seeded_client.get("/api/reports/debts").json()
    tool = execute(seeded, "get_customer_debts", {"limit": 50})
    assert (dash["total"], dash["overdue_total"], dash["customers_count"]) == (total, overdue, len(truth))
    assert (rep["total_outstanding"], rep["total_overdue"]) == (total, overdue)
    assert {c["name"]: c["outstanding"] for c in rep["customers"]} == {n: v["outstanding"] for n, v in truth.items()}
    assert next(f.value for f in tool.figures if f.key == "total_outstanding") == total
    listed = seeded_client.get("/api/customers", params={"page_size": 50}).json()["items"]
    assert sum(c["outstanding"] for c in listed if c["outstanding"] > 0) == total
    for c in listed:                                                      # per-customer page agrees with the list
        d = seeded_client.get(f"/api/customers/{c['customer_id']}/debts").json()
        assert d["balance"]["outstanding"] == c["outstanding"] == (d["history"][-1]["balance_after"] if d["history"] else 0)


def test_same_question_twice_gives_identical_evidence(seeded_client):
    from app.ai.rules_provider import RulesProvider
    from app.api.assistant import get_llm_provider
    from app.main import app
    app.dependency_overrides[get_llm_provider] = lambda: RulesProvider()
    try:
        a = seeded_client.post("/api/assistant/chat", json={"message": "شكد ربحت هذا الشهر؟"}).json()
        b = seeded_client.post("/api/assistant/chat", json={"message": "شكد ربحت هذا الشهر؟"}).json()
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)
    assert a == b and a["kind"] == "answer"


# ------------------------------------------------------------------ 2. a merchant's day, end to end
def test_a_full_day_through_the_api(client, monkeypatch):
    from app.ai.rules_provider import RulesProvider
    from app.api.assistant import get_llm_provider
    from app.main import app
    app.dependency_overrides[get_llm_provider] = lambda: RulesProvider()
    try:
        summary = lambda: client.get("/api/reports/summary", params={"period": "today"}).json()["totals"]
        debts = lambda: client.get("/api/reports/debts").json()["total_outstanding"]
        txn = lambda **kw: client.post("/api/transactions", json={"date": TODAY, "description": "x", **kw})

        cust = client.post("/api/customers", json={"name": "زبون الاختبار"}).json()
        assert txn(type="sale", amount="1,000,000", payment_method="cash", description="بيع نقدي").status_code == 201
        credit = txn(type="sale", amount=400_000, payment_method="credit", customer_id=cust["id"], description="بيع آجل")
        assert credit.status_code == 201
        assert txn(type="supplier_purchase", amount=300_000, payment_method="cash", description="بضاعة").status_code == 201
        assert txn(type="expense", amount=50_000, payment_method="cash", description="نقل").status_code == 201

        t = summary()
        assert (t["sales_total"], t["sales_credit"], t["purchases_total"], t["expenses_total"]) == (1_400_000, 400_000, 300_000, 50_000)
        assert t["estimated_profit"] == 1_050_000 and t["net_cash_flow"] == 1_000_000 - 300_000 - 50_000      # the credit sale is not cash yet
        assert debts() == 400_000

        asked = client.post("/api/assistant/chat", json={"message": "منو بعده ما دايفعلي؟"}).json()
        assert asked["kind"] == "answer" and "زبون الاختبار" in asked["answer_ar"] and "400,000 د.ع" in asked["answer_ar"]
        assert credit.json()["id"] in asked["evidence"][0]["transaction_ids"]                       # the answer is traceable to the sale

        before = summary()
        pay = client.post(f"/api/customers/{cust['id']}/payments", json={"amount": 150_000, "date": TODAY})
        assert pay.status_code == 201 and pay.json()["outstanding_after"] == 250_000
        after = summary()
        assert after["sales_total"] == before["sales_total"] and after["customer_payments"] == 150_000       # a payment is not a sale
        assert after["net_cash_flow"] == before["net_cash_flow"] + 150_000 and debts() == 250_000

        sale_id = credit.json()["id"]                                                                 # edit the credit sale down to 300k
        client.put(f"/api/transactions/{sale_id}", json={"date": TODAY, "type": "sale", "amount": 300_000, "description": "بيع آجل", "payment_method": "credit", "customer_id": cust["id"]})
        assert debts() == 150_000 and summary()["sales_total"] == 1_300_000

        client.put(f"/api/transactions/{sale_id}", json={"date": TODAY, "type": "sale", "amount": 300_000, "description": "بيع آجل", "payment_method": "credit", "customer_id": cust["id"], "reconciliation_status": "excluded"})
        assert debts() == 0 and summary()["sales_total"] == 1_000_000 and summary()["excluded_count"] == 1   # excluded = ignored everywhere

        csv = ("date,type,amount,description,reference,payment_method,customer,supplier,category,status\n"
               f"{TODAY},sale,200000,من الملف,F-1,cash,,,,\n{TODAY},expense,20000,من الملف,F-2,cash,,,,\n").encode()
        imp = client.post("/api/import/csv/confirm", files={"file": ("d.csv", csv, "text/csv")})
        assert imp.status_code == 201 and imp.json()["imported"] == 2
        assert summary()["sales_total"] == 1_200_000 and summary()["expenses_total"] == 70_000
        assert client.post("/api/import/csv/confirm", files={"file": ("d.csv", csv, "text/csv")}).status_code == 409

        for t_ in client.get("/api/transactions", params={"page_size": 100}).json()["items"]:
            assert client.delete(f"/api/transactions/{t_['id']}").status_code == 200
        z = summary()
        assert (z["sales_total"], z["expenses_total"], z["purchases_total"], z["net_cash_flow"]) == (0, 0, 0, 0) and debts() == 0
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)


def test_reset_returns_exactly_to_the_documented_baseline(seeded_client):
    seeded_client.post("/api/transactions", json={"date": "2026-10-10", "type": "sale", "amount": 5, "description": "x", "payment_method": "cash"})
    assert seeded_client.post("/api/settings/reset-demo", json={"confirm": "RESET"}).status_code == 200
    d = seeded_client.get("/api/dashboard/summary").json()
    assert (d["period_summary"]["sales_total"], d["outstanding_debts"]["total"]) == (21_582_250, 8_470_750)


# ------------------------------------------------------------------ 3. invariants under random operations
def _all(client):
    out, page = [], 1
    while True:
        r = client.get("/api/transactions", params={"page_size": 200, "page": page}).json()
        out += r["items"]
        if page >= r["pages"]:
            return out
        page += 1


def _truth(items):
    live = [t for t in items if t["reconciliation_status"] != "excluded"]
    s = lambda f: sum(t["amount_iqd"] for t in live if f(t))
    credit = {}
    for t in live:
        if t["customer"] and ((t["type"] == "sale" and t["payment_method"] == "credit") or t["type"] == "customer_payment"):
            credit[t["customer"]["id"]] = credit.get(t["customer"]["id"], 0) + (t["amount_iqd"] if t["type"] == "sale" else -t["amount_iqd"])
    sales, purchases, expenses = s(lambda t: t["type"] == "sale"), s(lambda t: t["type"] == "supplier_purchase"), s(lambda t: t["type"] == "expense")
    cash_in = s(lambda t: t["type"] == "sale" and t["payment_method"] != "credit") + s(lambda t: t["type"] == "customer_payment")
    cash_out = expenses + s(lambda t: t["type"] == "supplier_purchase" and t["payment_method"] != "credit") + s(lambda t: t["type"] == "supplier_payment")
    return {"sales": sales, "profit": sales - purchases - expenses, "net_cash": cash_in - cash_out, "debts": sum(v for v in credit.values() if v > 0)}


def test_random_operations_never_break_the_accounting_identities(client):
    rng = random.Random(2026)
    custs = [client.post("/api/customers", json={"name": f"زبون {i}"}).json()["id"] for i in range(4)]
    sups = [client.post("/api/suppliers", json={"name": f"مورد {i}"}).json()["id"] for i in range(2)]
    day = lambda: (date.today() - timedelta(days=rng.randrange(0, 20))).isoformat()
    ids = []

    def body():
        kind = rng.choice(["sale_cash", "sale_credit", "payment", "expense", "purchase_cash", "purchase_credit", "supplier_payment"])
        b = {"date": day(), "amount": rng.randrange(1, 900) * 1000, "description": f"عملية {rng.random():.6f}"}
        return {**b, **{"sale_cash": dict(type="sale", payment_method=rng.choice(["cash", "digital", "bank"])),
                        "sale_credit": dict(type="sale", payment_method="credit", customer_id=rng.choice(custs)),
                        "payment": dict(type="customer_payment", payment_method="cash", customer_id=rng.choice(custs)),
                        "expense": dict(type="expense", payment_method="cash"),
                        "purchase_cash": dict(type="supplier_purchase", payment_method="bank"),
                        "purchase_credit": dict(type="supplier_purchase", payment_method="credit", supplier_id=rng.choice(sups)),
                        "supplier_payment": dict(type="supplier_payment", payment_method="cash", supplier_id=rng.choice(sups))}[kind]}

    for step in range(150):
        op = rng.choice(["create"] * 5 + ["edit", "delete", "exclude"])
        if op == "create" or not ids:
            r = client.post("/api/transactions", json=body())
            assert r.status_code == 201, r.text
            ids.append(r.json()["id"])
        else:
            tid = rng.choice(ids)
            if op == "delete":
                assert client.delete(f"/api/transactions/{tid}").status_code == 200
                ids.remove(tid)
            else:
                cur = client.get(f"/api/transactions/{tid}").json()
                new = {"date": cur["date"], "type": cur["type"], "amount": rng.randrange(1, 900) * 1000 if op == "edit" else cur["amount_iqd"],
                       "description": cur["description"], "payment_method": cur["payment_method"], "customer_id": cur["customer"] and cur["customer"]["id"],
                       "supplier_id": cur["supplier"] and cur["supplier"]["id"], "reconciliation_status": "excluded" if op == "exclude" else cur["reconciliation_status"]}
                assert client.put(f"/api/transactions/{tid}", json=new).status_code == 200

        if step % 5 == 0 or step == 149:
            truth = _truth(_all(client))
            t = client.get("/api/reports/summary", params={"start": (date.today() - timedelta(days=40)).isoformat(), "end": TODAY}).json()["totals"]
            assert t["sales_total"] == truth["sales"], f"step {step}"
            assert t["estimated_profit"] == truth["profit"] and t["net_cash_flow"] == truth["net_cash"], f"step {step}"
            assert client.get("/api/reports/debts").json()["total_outstanding"] == truth["debts"], f"step {step}"
            assert t["estimated_profit"] == t["sales_total"] - t["purchases_total"] - t["expenses_total"]
            assert t["net_cash_flow"] == t["cash_in"] - t["cash_out"] and t["sales_total"] == t["sales_collected"] + t["sales_credit"]


# ------------------------------------------------------------------ 4. frontend fixtures must match the live API
def _shape(x):
    if isinstance(x, dict):
        return {k: _shape(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_shape(x[0])] if x else []
    return "null" if x is None else "number" if isinstance(x, (int, float)) and not isinstance(x, bool) else type(x).__name__


def _same(a, b, path="$"):
    if a == "null" or b == "null":
        return []
    if isinstance(a, dict) and isinstance(b, dict):
        out = [f"{path}: key sets differ {sorted(set(a) ^ set(b))}"] if set(a) != set(b) else []
        return out + [p for k in set(a) & set(b) for p in _same(a[k], b[k], f"{path}.{k}")]
    if isinstance(a, list) and isinstance(b, list):
        return _same(a[0], b[0], path + "[]") if a and b else []
    return [] if a == b else [f"{path}: {a} != {b}"]


def test_recorded_frontend_fixtures_still_match_the_live_api(tmp_path):
    from scripts.export_frontend_fixtures import OUT, main
    from app.api.assistant import get_llm_provider
    main(tmp_path)
    from app.main import app
    app.dependency_overrides.pop(get_llm_provider, None)
    fresh, committed = {p.stem: json.loads(p.read_text("utf-8")) for p in tmp_path.glob("*.json")}, {p.stem: json.loads(p.read_text("utf-8")) for p in OUT.glob("*.json")}
    assert set(fresh) == set(committed), "fixture files differ - run: python -m scripts.export_frontend_fixtures"
    problems = {name: _same(_shape(fresh[name]), _shape(committed[name])) for name in fresh}
    assert not any(problems.values()), f"stale frontend fixtures (re-run python -m scripts.export_frontend_fixtures): { {k: v[:3] for k, v in problems.items() if v} }"
