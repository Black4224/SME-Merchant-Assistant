import hashlib
import json

import pytest
from sqlalchemy import func, select

from app.config import DATA_DIR
from app.models import Customer, ImportBatch, Transaction

HEADER = "date,type,amount,description,reference,payment_method,customer,supplier,category,status\n"
GOOD = (
    "2026-10-01,sale,100000,بيع نقدي,INV-1,cash,,,مبيعات,\n"
    "2026-10-02,sale,250000,بيع آجل,INV-2,credit,زبون جديد,,مبيعات,\n"
    "2026-10-03,expense,40000,نقل,,cash,,,نقل,\n"
)


def up(content, name="t.csv"):
    data = content.encode("utf-8") if isinstance(content, str) else content
    return {"file": (name, data, "text/csv")}


def count(session):
    session.expire_all()
    return session.scalar(select(func.count()).select_from(Transaction))


def test_preview_validates_and_writes_nothing(client, engine_session):
    r = client.post("/api/import/csv/preview", files=up(HEADER + GOOD))
    assert r.status_code == 200
    body = r.json()
    assert body["counts"] == {"total": 3, "valid": 3, "duplicate": 0, "invalid": 0}
    assert body["needs_mapping"] is False and body["mapping"]["amount"] == "amount"
    assert body["will_create"]["customers"] == ["زبون جديد"] and "مبيعات" in body["will_create"]["categories"]
    assert body["file_sha256"] == hashlib.sha256((HEADER + GOOD).encode()).hexdigest()
    assert count(engine_session) == 0 and engine_session.scalar(select(func.count()).select_from(ImportBatch)) == 0


def test_confirm_commits_and_links_batch(client, engine_session):
    r = client.post("/api/import/csv/confirm", files=up(HEADER + GOOD))
    assert r.status_code == 201
    res = r.json()
    assert (res["imported"], res["skipped_duplicates"], res["skipped_invalid"]) == (3, 0, 0)
    assert count(engine_session) == 3
    t = engine_session.scalars(select(Transaction).order_by(Transaction.id)).all()
    assert {x.import_batch_id for x in t} == {res["batch_id"]} and {x.source.value for x in t} == {"csv_import"}
    assert engine_session.scalar(select(Customer.name)) == "زبون جديد"
    debts = client.get("/api/reports/debts").json()
    assert debts["total_outstanding"] == 250_000


def test_reimporting_same_file_is_blocked_and_adds_nothing(client, engine_session):
    assert client.post("/api/import/csv/confirm", files=up(HEADER + GOOD)).status_code == 201
    pv = client.post("/api/import/csv/preview", files=up(HEADER + GOOD)).json()
    assert pv["already_imported"] is True and pv["counts"]["duplicate"] == 3 and pv["counts"]["valid"] == 0
    r = client.post("/api/import/csv/confirm", files=up(HEADER + GOOD))
    assert r.status_code == 409 and r.json()["error"]["code"] == "file_already_imported"
    assert count(engine_session) == 3


def test_overlapping_file_only_adds_new_rows(client, engine_session):
    client.post("/api/import/csv/confirm", files=up(HEADER + GOOD))
    more = GOOD + "2026-10-04,expense,9000,مصاريف نثرية,,cash,,,مصاريف متفرقة,\n"
    pv = client.post("/api/import/csv/preview", files=up(HEADER + more)).json()
    assert pv["counts"] == {"total": 4, "valid": 1, "duplicate": 3, "invalid": 0}
    res = client.post("/api/import/csv/confirm", files=up(HEADER + more)).json()
    assert (res["imported"], res["skipped_duplicates"]) == (1, 3) and count(engine_session) == 4


def test_duplicate_detection_ignores_arabic_spelling_and_digit_variants(client):
    a = HEADER + "2026-10-01,sale,100000,بيع أحمد,,cash,,,,\n"
    b = HEADER + "01/10/2026,sale,١٠٠٠٠٠,بيع احمد,,نقدا,,,,\n"   # day-first date, Arabic digits, Arabic words
    client.post("/api/import/csv/confirm", files=up(a))
    pv = client.post("/api/import/csv/preview", files=up(b)).json()
    assert pv["counts"]["duplicate"] == 1 and pv["counts"]["invalid"] == 0


def test_identical_rows_inside_one_file_are_both_kept_with_warning(client, engine_session):
    row = "2026-10-01,sale,5000,بيع,,cash,,,,\n"
    pv = client.post("/api/import/csv/preview", files=up(HEADER + row * 2)).json()
    assert pv["counts"]["valid"] == 2 and any("داخل الملف" in w for w in pv["rows"][1]["warnings"])
    client.post("/api/import/csv/confirm", files=up(HEADER + row * 2))
    assert count(engine_session) == 2
    again = client.post("/api/import/csv/preview", files=up(HEADER + row * 3)).json()   # 3rd is genuinely new
    assert again["counts"] == {"total": 3, "valid": 1, "duplicate": 2, "invalid": 0}


BAD = (
    "2026-10-01,sale,100000,ok,,cash,,,,\n"                 # row 2 valid
    "2026-02-30,sale,100000,bad date,,cash,,,,\n"           # row 3
    "2026-10-01,sale,-5,neg,,cash,,,,\n"                    # row 4
    "2026-10-01,sale,12.5,frac,,cash,,,,\n"                 # row 5
    "2026-10-01,gift,100,type,,cash,,,,\n"                  # row 6
    "2026-10-01,sale,100,method,,bitcoin,,,,\n"             # row 7
    "2026-10-01,sale,100,,,cash,,,,\n"                      # row 8 no description
    "2026-10-01,sale,100,credit no cust,,credit,,,,\n"      # row 9 business rule
    "2026-10-01,customer_payment,100,pay,,cash,,,,\n"       # row 10 business rule
    "2026-10-01,sale,100,st,,cash,,,,maybe\n"               # row 11 bad status
)


def test_invalid_rows_reported_with_row_numbers_and_fields(client, engine_session):
    pv = client.post("/api/import/csv/preview", files=up(HEADER + BAD)).json()
    assert pv["counts"] == {"total": 10, "valid": 1, "duplicate": 0, "invalid": 9}
    errs = {e["row_number"]: e["errors"][0]["field"] for e in pv["errors"]}
    assert errs == {3: "date", 4: "amount", 5: "amount", 6: "type", 7: "payment_method",
                    8: "description", 9: "row", 10: "row", 11: "status"}
    assert count(engine_session) == 0


def test_confirm_refuses_invalid_rows_unless_skipping(client, engine_session):
    r = client.post("/api/import/csv/confirm", files=up(HEADER + BAD))
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_rows"
    assert count(engine_session) == 0 and engine_session.scalar(select(func.count()).select_from(ImportBatch)) == 0
    ok = client.post("/api/import/csv/confirm", files=up(HEADER + BAD), data={"skip_invalid": "true"})
    assert ok.status_code == 201 and (ok.json()["imported"], ok.json()["skipped_invalid"]) == (1, 9)
    assert count(engine_session) == 1


def test_commit_is_atomic(client, engine_session, monkeypatch):
    import app.services.importer as imp

    real, calls = imp.add_transaction, {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("disk full")
        return real(*a, **k)

    monkeypatch.setattr(imp, "add_transaction", flaky)
    from tests.conftest import _make_client
    c = _make_client(engine_session.get_bind(), raise_exceptions=False)
    assert c.post("/api/import/csv/confirm", files=up(HEADER + GOOD)).status_code == 500
    assert count(engine_session) == 0
    assert engine_session.scalar(select(func.count()).select_from(ImportBatch)) == 0
    assert engine_session.scalar(select(func.count()).select_from(Customer)) == 0


def test_expected_sha_pins_the_previewed_file(client):
    sha = client.post("/api/import/csv/preview", files=up(HEADER + GOOD)).json()["file_sha256"]
    r = client.post("/api/import/csv/confirm", files=up(HEADER + GOOD + "2026-10-09,sale,1,x,,cash,,,,\n"), data={"expected_sha256": sha})
    assert r.status_code == 409 and r.json()["error"]["code"] == "file_changed"
    assert client.post("/api/import/csv/confirm", files=up(HEADER + GOOD), data={"expected_sha256": sha}).status_code == 201


def test_column_mapping_flow(client, engine_session):
    csv_text = "when,kind,iqd,memo,how\n2026-10-01,sale,5000,test,cash\n2026-10-02,expense,1000,cost,cash\n"
    pv = client.post("/api/import/csv/preview", files=up(csv_text)).json()
    assert pv["needs_mapping"] is True and set(pv["missing_required_fields"]) == {"date", "type", "amount", "description", "payment_method"}
    assert pv["headers"] == ["when", "kind", "iqd", "memo", "how"] and pv["rows"] == []
    mapping = {"date": "when", "type": "kind", "amount": "iqd", "description": "memo", "payment_method": "how"}
    r = client.post("/api/import/csv/confirm", files=up(csv_text), data={"mapping": json.dumps(mapping)})
    assert r.status_code == 201 and r.json()["imported"] == 2
    # confirm without mapping on an unmappable file is refused
    r2 = client.post("/api/import/csv/confirm", files=up(csv_text.replace("5000", "5001")))
    assert r2.status_code == 422 and r2.json()["error"]["code"] == "mapping_required"


@pytest.mark.parametrize(
    "mapping",
    ["not json", "[1]", '{"date": 5}', '{"bogus": "when"}', '{"date": "nope"}', '{"date": "when", "type": "when"}'],
)
def test_bad_mappings_rejected(client, mapping):
    r = client.post("/api/import/csv/preview", files=up("when,kind\n1,2\n"), data={"mapping": mapping})
    assert r.status_code == 422 and r.json()["error"]["code"] == "bad_mapping"


def test_arabic_headers_values_semicolons_and_cp1256(client):
    text = "التاريخ;النوع;المبلغ;البيان;طريقة الدفع;الزبون\n15/10/2026;بيع;١٢٥٠٠٠٠;بيع آجل;آجل;سعد\n16/10/2026;تسديد زبون;250000;دفعة;نقدي;سعد\n"
    for data in (text.encode("utf-8-sig"), text.replace("١٢٥٠٠٠٠", "1250000").encode("cp1256")):
        pv = client.post("/api/import/csv/preview", files=up(data)).json()
        assert pv["needs_mapping"] is False, pv
        assert pv["counts"]["valid"] == 2
        assert pv["rows"][0]["data"]["amount_iqd"] == 1_250_000 and pv["rows"][0]["data"]["date"] == "2026-10-15"
        assert pv["rows"][0]["data"]["payment_method"] == "credit" and pv["rows"][1]["data"]["type"] == "customer_payment"


@pytest.mark.parametrize("content,code", [(b"", "empty_file"), (b"   \n", "empty_file"), (HEADER.encode(), "no_rows")])
def test_empty_or_header_only_file(client, content, code):
    r = client.post("/api/import/csv/preview", files=up(content))
    assert r.status_code == 422 and r.json()["error"]["code"] == code


def test_ragged_csv_is_rejected_cleanly(client):
    r = client.post("/api/import/csv/preview", files=up("a,b\n1,2,3,4\n"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "bad_csv"


def test_oversized_file_rejected(client):
    r = client.post("/api/import/csv/preview", files=up(HEADER + "x" * (5 * 1024 * 1024 + 10)))
    assert r.status_code == 413


def test_missing_file_is_422(client):
    assert client.post("/api/import/csv/preview").status_code == 422


def test_future_dated_row_gets_warning(client):
    pv = client.post("/api/import/csv/preview", files=up(HEADER + "2099-01-01,sale,100,x,,cash,,,,\n")).json()
    assert pv["counts"]["valid"] == 1 and "بعد تاريخ اليوم" in pv["rows"][0]["warnings"][0]


# ---------- the shipped sample file is the gold-standard import ----------
SAMPLE = (DATA_DIR / "sample_transactions.csv").read_bytes()


def test_sample_csv_imports_into_empty_db_with_identical_totals(client, engine_session):
    pv = client.post("/api/import/csv/preview", files=up(SAMPLE, "sample.csv")).json()
    assert pv["counts"] == {"total": 650, "valid": 650, "duplicate": 0, "invalid": 0}
    assert client.post("/api/import/csv/confirm", files=up(SAMPLE, "sample.csv")).status_code == 201
    r = client.get("/api/reports/summary", params={"start": "2026-06-18", "end": "2026-10-18"}).json()["totals"]
    from tests.test_seed_data import _csv_rows, _oracle
    from datetime import date
    o = _oracle(_csv_rows(), date(2026, 6, 18), date(2026, 10, 18))
    assert (r["sales_total"], r["expenses_total"], r["purchases_total"], r["customer_payments"]) == (o["sales"], o["expenses"], o["purchases"], o["payments"])
    assert client.get("/api/reports/debts").json()["total_outstanding"] == 8_470_750
    assert len(client.get("/api/customers", params={"page_size": 50}).json()["items"]) == 8


def test_sample_csv_into_seeded_db_is_entirely_duplicates(seeded_client, engine_session):
    pv = seeded_client.post("/api/import/csv/preview", files=up(SAMPLE, "sample.csv")).json()
    assert pv["counts"] == {"total": 650, "valid": 0, "duplicate": 650, "invalid": 0}
    assert count(engine_session) == 650
    res = seeded_client.post("/api/import/csv/confirm", files=up(SAMPLE, "sample.csv"))
    assert res.status_code == 201 and res.json()["imported"] == 0 and res.json()["skipped_duplicates"] == 650
    assert count(engine_session) == 650
