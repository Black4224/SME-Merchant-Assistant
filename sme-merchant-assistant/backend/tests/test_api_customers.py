from datetime import date


def _by_name(items):
    return {c["name"]: c for c in items}


def test_customer_list_has_balances(seeded_client):
    r = seeded_client.get("/api/customers", params={"page_size": 50}).json()
    assert r["total"] == 8
    sizes = [c["outstanding"] for c in r["items"]]
    assert sizes == sorted(sizes, reverse=True)
    assert sum(c["outstanding"] for c in r["items"] if c["outstanding"] > 0) == 8_470_750
    assert "open_invoices" not in r["items"][0] and "open_invoices_count" in r["items"][0]


def test_customer_filters(seeded_client):
    assert seeded_client.get("/api/customers", params={"has_debt": True}).json()["total"] == 7
    assert seeded_client.get("/api/customers", params={"has_debt": False}).json()["total"] == 1
    r = seeded_client.get("/api/customers", params={"q": "الجبوري"}).json()
    assert [c["name"] for c in r["items"]] == ["علي صباح الجبوري"]


def test_debt_history_ends_at_outstanding_and_distinguishes_kinds(seeded_client):
    cust = seeded_client.get("/api/customers", params={"q": "الجبوري"}).json()["items"][0]
    r = seeded_client.get(f"/api/customers/{cust['customer_id']}/debts").json()
    hist = r["history"]
    assert {h["kind"] for h in hist} == {"credit_sale", "payment"}
    assert hist[-1]["balance_after"] == r["balance"]["outstanding"] == cust["outstanding"]
    assert sum(i["remaining"] for i in r["balance"]["open_invoices"]) == cust["outstanding"]
    assert r["balance"]["overdue_amount"] > 0


def test_unknown_customer_404(seeded_client):
    assert seeded_client.get("/api/customers/9999/debts").status_code == 404
    assert seeded_client.post("/api/customers/9999/payments", json={"amount": 5}).status_code == 404


def test_record_payment_reduces_debt_and_is_not_a_sale(seeded_client):
    cust = seeded_client.get("/api/customers", params={"q": "الجبوري"}).json()["items"][0]
    cid, out = cust["customer_id"], cust["outstanding"]
    before = seeded_client.get("/api/reports/summary", params={"start": "2026-10-15", "end": "2026-10-15"}).json()["totals"]

    r = seeded_client.post(f"/api/customers/{cid}/payments", json={"amount": 500_000, "payment_method": "digital", "reference": "RCPT-X"})
    assert r.status_code == 201
    body = r.json()
    assert (body["outstanding_before"], body["outstanding_after"]) == (out, out - 500_000)
    assert body["transaction"]["type"] == "customer_payment" and body["transaction"]["date"] == "2026-10-15"

    after = seeded_client.get("/api/reports/summary", params={"start": "2026-10-15", "end": "2026-10-15"}).json()["totals"]
    assert after["sales_total"] == before["sales_total"]                       # NOT new sales
    assert after["customer_payments"] == before["customer_payments"] + 500_000
    assert after["cash_in"] == before["cash_in"] + 500_000
    assert seeded_client.get(f"/api/customers/{cid}/debts").json()["history"][-1]["kind"] == "payment"


def test_overpayment_rejected_unless_explicitly_allowed(seeded_client):
    cust = seeded_client.get("/api/customers", params={"q": "التميمي"}).json()["items"][0]
    cid, out = cust["customer_id"], cust["outstanding"]
    r = seeded_client.post(f"/api/customers/{cid}/payments", json={"amount": out + 1})
    assert r.status_code == 422 and r.json()["error"]["code"] == "overpayment"
    assert r.json()["error"]["details"]["outstanding"] == out
    ok = seeded_client.post(f"/api/customers/{cid}/payments", json={"amount": out})   # exact settle
    assert ok.status_code == 201 and ok.json()["outstanding_after"] == 0
    # customer with no debt can only pay with the explicit flag
    assert seeded_client.post(f"/api/customers/{cid}/payments", json={"amount": 10}).status_code == 422
    forced = seeded_client.post(f"/api/customers/{cid}/payments", json={"amount": 10, "allow_overpayment": True})
    assert forced.status_code == 201 and forced.json()["outstanding_after"] == -10


def test_payment_validation(seeded_client):
    cid = seeded_client.get("/api/customers").json()["items"][0]["customer_id"]
    for body in ({"amount": -5}, {"amount": 0}, {"amount": 12.5}, {"amount": 100, "payment_method": "credit"},
                 {"amount": 100, "date": "nope"}, {}):
        assert seeded_client.post(f"/api/customers/{cid}/payments", json=body).status_code == 422, body


def test_payment_with_explicit_past_date_uses_that_date_balance(client, engine_session):
    from app.models import Customer
    from app.models import TransactionType as TT, PaymentMethod as PM
    from app.services.transactions import add_transaction

    c = Customer(name="زبون"); engine_session.add(c); engine_session.flush()
    add_transaction(engine_session, txn_date=date(2026, 10, 5), type=TT.SALE, amount=100_000, description="آجل", payment_method=PM.CREDIT, customer_id=c.id)
    engine_session.commit()
    early = client.post(f"/api/customers/{c.id}/payments", json={"amount": 10, "date": "2026-10-01"})
    assert early.status_code == 422                       # no debt existed yet on Oct 1
    assert client.post(f"/api/customers/{c.id}/payments", json={"amount": 100_000, "date": "2026-10-06"}).status_code == 201


def test_create_customer_and_duplicate_name(client):
    r = client.post("/api/customers", json={"name": "  أحمد   علي ", "phone": "0770"})
    assert r.status_code == 201 and r.json()["name"] == "أحمد علي"
    dup = client.post("/api/customers", json={"name": "احمد علي"})   # alef variant normalises to the same name
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "duplicate_name"
    assert client.post("/api/customers", json={"name": "   "}).status_code == 422


def test_suppliers_and_categories(seeded_client):
    sup = seeded_client.get("/api/suppliers").json()["items"]
    assert len(sup) == 3 and sup[0]["outstanding"] >= sup[-1]["outstanding"]
    cats = seeded_client.get("/api/categories").json()["items"]
    assert {c["kind"] for c in cats} == {"sale", "expense", "purchase"}
