import pytest

SALE = {"date": "2026-10-10", "type": "sale", "amount": 150000, "description": "بيع نقدي", "payment_method": "cash"}


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["database"] == "ok"


def test_create_transaction_returns_201_and_row(client):
    r = client.post("/api/transactions", json=SALE)
    assert r.status_code == 201
    body = r.json()
    assert body["id"] == 1 and body["amount_iqd"] == 150000 and body["source"] == "manual"
    assert body["reconciliation_status"] == "reconciled"


@pytest.mark.parametrize("amount,expected", [("1,250,000", 1250000), ("١٢٥٠٠٠", 125000), ("5000.00", 5000)])
def test_amount_accepts_formatted_text(client, amount, expected):
    r = client.post("/api/transactions", json={**SALE, "amount": amount})
    assert r.status_code == 201 and r.json()["amount_iqd"] == expected


@pytest.mark.parametrize(
    "patch,field",
    [
        ({"amount": 12.5}, "amount"),
        ({"amount": 1500.0}, "amount"),
        ({"amount": -10}, "amount"),
        ({"amount": 0}, "amount"),
        ({"amount": "abc"}, "amount"),
        ({"amount": True}, "amount"),
        ({"type": "gift"}, "type"),
        ({"payment_method": "bitcoin"}, "payment_method"),
        ({"date": "2026-13-45"}, "date"),
        ({"date": "10/10/2026"}, "date"),
        ({"description": ""}, "description"),
        ({"description": "x" * 256}, "description"),
        ({"surprise": 1}, "surprise"),
    ],
)
def test_validation_errors_use_uniform_format(client, patch, field):
    r = client.post("/api/transactions", json={**SALE, **patch})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation_error"
    assert field in [d["field"] for d in err["details"]]


def test_missing_required_field(client):
    body = dict(SALE)
    del body["amount"]
    assert client.post("/api/transactions", json=body).status_code == 422


@pytest.mark.parametrize(
    "patch",
    [
        {"payment_method": "credit"},                                   # credit sale, no customer
        {"type": "customer_payment"},                                   # payment without customer
        {"type": "expense", "payment_method": "credit"},
        {"supplier_id": 1},                                             # sale with supplier
        {"customer_id": 999, "payment_method": "credit"},               # unknown customer
        {"category_id": 999},
    ],
)
def test_business_rule_violations_return_422(client, patch):
    r = client.post("/api/transactions", json={**SALE, **patch})
    assert r.status_code == 422 and r.json()["error"]["code"] == "business_rule"


def test_get_put_delete_lifecycle(client):
    tid = client.post("/api/transactions", json=SALE).json()["id"]
    assert client.get(f"/api/transactions/{tid}").json()["description"] == "بيع نقدي"

    r = client.put(f"/api/transactions/{tid}", json={**SALE, "amount": 99000, "description": "معدّل"})
    assert r.status_code == 200 and r.json()["amount_iqd"] == 99000 and r.json()["description"] == "معدّل"

    bad = client.put(f"/api/transactions/{tid}", json={**SALE, "payment_method": "credit"})
    assert bad.status_code == 422
    assert client.get(f"/api/transactions/{tid}").json()["amount_iqd"] == 99000  # unchanged after failed edit

    assert client.delete(f"/api/transactions/{tid}").json() == {"deleted": tid}
    for call in (client.get, client.delete):
        r = call(f"/api/transactions/{tid}")
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert client.put(f"/api/transactions/{tid}", json=SALE).status_code == 404


def test_edit_can_exclude_a_transaction_from_totals(client):
    tid = client.post("/api/transactions", json=SALE).json()["id"]
    client.put(f"/api/transactions/{tid}", json={**SALE, "reconciliation_status": "excluded"})
    s = client.get("/api/reports/summary", params={"start": "2026-10-10", "end": "2026-10-10"}).json()
    assert s["totals"]["sales_total"] == 0 and s["totals"]["excluded_count"] == 1


def test_non_numeric_id_is_422(client):
    assert client.get("/api/transactions/abc").status_code == 422


# ---------------- list / filter / paginate (seeded data) ----------------
def test_pagination(seeded_client):
    r = seeded_client.get("/api/transactions", params={"page_size": 100, "page": 2}).json()
    assert r["total"] == 650 and r["pages"] == 7 and len(r["items"]) == 100 and r["page"] == 2
    last = seeded_client.get("/api/transactions", params={"page_size": 100, "page": 7}).json()
    assert len(last["items"]) == 50
    assert seeded_client.get("/api/transactions", params={"page": 99}).json()["items"] == []


@pytest.mark.parametrize("params", [{"page": 0}, {"page_size": 0}, {"page_size": 201}, {"sort": "bogus"}, {"order": "up"}, {"type": "gift"}])
def test_bad_list_params_are_422(seeded_client, params):
    assert seeded_client.get("/api/transactions", params=params).status_code == 422


def test_filter_by_type_and_method(seeded_client):
    r = seeded_client.get("/api/transactions", params={"type": "expense", "page_size": 200}).json()
    assert r["total"] > 0 and all(i["type"] == "expense" for i in r["items"])
    r = seeded_client.get("/api/transactions", params={"payment_method": "credit", "type": "sale", "page_size": 200}).json()
    assert all(i["customer"] for i in r["items"])


def test_date_filter_is_inclusive_and_validated(seeded_client):
    r = seeded_client.get("/api/transactions", params={"date_from": "2026-10-15", "date_to": "2026-10-15", "page_size": 200}).json()
    assert r["total"] > 0 and {i["date"] for i in r["items"]} == {"2026-10-15"}
    bad = seeded_client.get("/api/transactions", params={"date_from": "2026-10-16", "date_to": "2026-10-01"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_date_range"


def test_amount_filter(seeded_client):
    r = seeded_client.get("/api/transactions", params={"min_amount": "1,500,000", "max_amount": "1500000"}).json()
    assert r["total"] > 0 and all(i["amount_iqd"] == 1_500_000 for i in r["items"])
    assert seeded_client.get("/api/transactions", params={"min_amount": "9", "max_amount": "1"}).status_code == 422
    assert seeded_client.get("/api/transactions", params={"min_amount": "abc"}).status_code == 422


def test_text_search_matches_description_reference_and_party(seeded_client):
    by_desc = seeded_client.get("/api/transactions", params={"q": "إيجار"}).json()
    assert by_desc["total"] >= 4 and all("إيجار" in i["description"] for i in by_desc["items"])
    by_party = seeded_client.get("/api/transactions", params={"q": "الجبوري", "page_size": 200}).json()
    assert by_party["total"] > 0 and all("الجبوري" in i["customer"]["name"] for i in by_party["items"])
    by_ref = seeded_client.get("/api/transactions", params={"q": "INV-1001"}).json()
    assert by_ref["total"] == 1
    assert seeded_client.get("/api/transactions", params={"q": "%"}).json()["total"] == 0  # wildcard is escaped


def test_sorting(seeded_client):
    items = seeded_client.get("/api/transactions", params={"sort": "amount", "order": "desc", "page_size": 5}).json()["items"]
    amounts = [i["amount_iqd"] for i in items]
    assert amounts == sorted(amounts, reverse=True)
    asc = seeded_client.get("/api/transactions", params={"sort": "date", "order": "asc", "page_size": 1}).json()["items"][0]
    assert asc["date"] == "2026-06-18"


def test_planted_anomalies_visible_as_flags_in_list(seeded_client):
    items = seeded_client.get("/api/transactions", params={"page_size": 200, "date_from": "2026-10-01", "date_to": "2026-10-31"}).json()["items"]
    codes = {f["code"] for i in items for f in i["flags"]}
    assert {"possible_duplicate", "amount_outlier", "future_date"} <= codes
    assert seeded_client.get("/api/transactions/594").json()["flags"][0]["code"] == "possible_duplicate"


def test_unexpected_error_returns_generic_500_without_leaking(api_engine, monkeypatch):
    from tests.conftest import _make_client
    import app.api.transactions as mod

    def boom(*a, **k):
        raise RuntimeError("secret internals")

    monkeypatch.setattr(mod, "list_transactions", boom)
    c = _make_client(api_engine, raise_exceptions=False)
    r = c.get("/api/transactions")
    assert r.status_code == 500 and r.json()["error"]["code"] == "internal_error"
    assert "secret" not in r.text
    from app.main import app
    app.dependency_overrides.clear()
