from datetime import date

import pytest

from tests.test_seed_data import REF, _csv_rows, _oracle


# ---------------------------------------------------------------- dashboard
def test_dashboard_matches_independent_oracle(seeded_client):
    d = seeded_client.get("/api/dashboard/summary").json()
    o_month = _oracle(_csv_rows(), date(2026, 10, 1), REF)
    o_today = _oracle(_csv_rows(), REF, REF)
    assert d["reference_date"] == "2026-10-15" and d["period"]["name"] == "this_month"
    assert d["period"]["start"] == "2026-10-01" and d["period"]["end"] == "2026-10-15"
    assert d["period_summary"]["sales_total"] == o_month["sales"] == 21_582_250
    assert d["period_summary"]["estimated_profit"] == o_month["sales"] - o_month["purchases"] - o_month["expenses"]
    assert d["today"]["sales_total"] == o_today["sales"] and d["today"]["expenses_total"] == o_today["expenses"]
    assert d["outstanding_debts"]["total"] == 8_470_750 and d["outstanding_debts"]["customers_count"] == 7
    assert d["outstanding_debts"]["overdue_total"] > 0
    assert d["business"]["is_demo_data"] is True and d["business"]["name"] == "بقالة الرافدين التجريبية"


def test_dashboard_chart_recent_and_attention(seeded_client):
    d = seeded_client.get("/api/dashboard/summary").json()
    assert len(d["chart"]) == 15 and d["chart"][0]["date"] == "2026-10-01" and d["chart"][-1]["date"] == "2026-10-15"
    assert sum(x["sales"] for x in d["chart"]) == d["period_summary"]["sales_total"]
    assert len(d["recent_transactions"]) == 10
    ids = [t["id"] for t in d["recent_transactions"]]
    assert d["recent_transactions"][0]["date"] >= d["recent_transactions"][-1]["date"] and len(set(ids)) == 10
    att = d["attention"]
    assert att["flags_by_code"]["possible_duplicate"] == 1 and att["flags_by_code"]["amount_outlier"] == 1
    assert att["unreconciled_count"] > 0 and att["overdue_customers"][0]["overdue_amount"] >= att["overdue_customers"][-1]["overdue_amount"]
    assert {f["code"] for f in att["top_flags"]} <= {"possible_duplicate", "future_date", "amount_outlier", "customer_overpayment"}


def test_dashboard_weekly_performance_compares_equal_lengths(seeded_client):
    w = seeded_client.get("/api/dashboard/summary").json()["weekly_performance"]
    assert w["current"]["date_range"]["start"] == "2026-10-11" and w["previous"]["date_range"]["start"] == "2026-10-04"
    assert w["current"]["date_range"]["days"] == w["previous"]["date_range"]["days"] == 5
    assert w["length_warning"] is None and w["metrics"]["sales_total"]["change"] == w["metrics"]["sales_total"]["current"] - w["metrics"]["sales_total"]["previous"]


def test_dashboard_custom_and_named_periods(seeded_client):
    d = seeded_client.get("/api/dashboard/summary", params={"start": "2026-09-01", "end": "2026-09-30"}).json()
    assert d["period"]["name"] == "custom" and d["period_summary"]["sales_total"] == 41_562_500 and len(d["chart"]) == 30
    d = seeded_client.get("/api/dashboard/summary", params={"period": "last_month"}).json()
    assert d["period_summary"]["estimated_profit"] == 8_225_500
    assert d["period_summary"]["profit_basis"] == "purchases_basis_estimate"


@pytest.mark.parametrize(
    "params",
    [{"start": "2026-09-01"}, {"end": "2026-09-01"}, {"start": "2026-10-02", "end": "2026-10-01"},
     {"period": "next_year"}, {"period": "today", "start": "2026-10-01", "end": "2026-10-02"},
     {"start": "x", "end": "y"}, {"start": "1990-01-01", "end": "2026-01-01"}],
)
def test_dashboard_rejects_bad_ranges(seeded_client, params):
    r = seeded_client.get("/api/dashboard/summary", params=params)
    assert r.status_code == 422 and r.json()["error"]["code"] in ("invalid_date_range", "validation_error")


def test_dashboard_on_empty_database_does_not_crash(client):
    d = client.get("/api/dashboard/summary", params={"period": "last_7_days"}).json()
    assert d["period_summary"]["sales_total"] == 0 and d["recent_transactions"] == [] and d["outstanding_debts"]["total"] == 0
    assert d["business"]["is_demo_data"] is False


# ---------------------------------------------------------------- reports
@pytest.mark.parametrize("gran", ["daily", "weekly", "monthly"])
def test_report_series_sum_to_totals(seeded_client, gran):
    r = seeded_client.get("/api/reports/summary", params={"start": "2026-08-15", "end": "2026-10-15", "granularity": gran}).json()
    t, s = r["totals"], r["series"]
    assert sum(b["sales"] for b in s) == t["sales_total"]
    assert sum(b["estimated_profit"] for b in s) == t["estimated_profit"]
    assert sum(b["net_cash_flow"] for b in s) == t["net_cash_flow"]
    assert s[0]["start"] == "2026-08-15" and s[-1]["end"] == "2026-10-15"
    assert "تقديرية" in r["estimate_note"]
    expected = {"daily": 62, "weekly": 10, "monthly": 3}[gran]
    assert len(s) == expected


def test_monthly_bucket_equals_standalone_summary(seeded_client):
    r = seeded_client.get("/api/reports/summary", params={"start": "2026-07-01", "end": "2026-09-30", "granularity": "monthly"}).json()
    sept = next(b for b in r["series"] if b["start"] == "2026-09-01")
    solo = seeded_client.get("/api/reports/summary", params={"start": "2026-09-01", "end": "2026-09-30"}).json()["totals"]
    assert sept["sales"] == solo["sales_total"] == 41_562_500 and sept["estimated_profit"] == solo["estimated_profit"]


def test_weekly_buckets_start_on_sunday_and_clip(seeded_client):
    s = seeded_client.get("/api/reports/summary", params={"start": "2026-10-07", "end": "2026-10-15", "granularity": "weekly"}).json()["series"]
    assert [(b["start"], b["end"]) for b in s] == [("2026-10-07", "2026-10-10"), ("2026-10-11", "2026-10-15")]


def test_reports_default_period_and_bad_granularity(seeded_client):
    r = seeded_client.get("/api/reports/summary").json()
    assert r["period"]["name"] == "last_30_days" and r["period"]["days"] == 30
    assert seeded_client.get("/api/reports/summary", params={"granularity": "hourly"}).status_code == 422


def test_debt_report(seeded_client):
    r = seeded_client.get("/api/reports/debts").json()
    assert r["total_outstanding"] == 8_470_750 and len(r["customers"]) == 7 and r["credit_terms_days"] == 30
    assert r["customers"][0]["outstanding"] == max(c["outstanding"] for c in r["customers"])
    assert r["total_overdue"] == sum(c["overdue_amount"] for c in r["customers"]) > 0
    assert all(c["outstanding"] > 0 for c in r["customers"])


def test_anomaly_report_has_evidence(seeded_client):
    r = seeded_client.get("/api/reports/anomalies").json()
    assert r["by_code"]["possible_duplicate"] == 1 and r["by_code"]["amount_outlier"] == 1 and r["by_code"]["future_date"] == 1
    assert r["count"] == sum(r["by_code"].values())
    dup = next(i for i in r["items"] if i["code"] == "possible_duplicate")
    assert dup["transaction"]["id"] == 594 and dup["related_ids"] == [593] and dup["severity"] == "high"
    sept = seeded_client.get("/api/reports/anomalies", params={"start": "2026-09-01", "end": "2026-09-30"}).json()
    assert "possible_duplicate" not in sept["by_code"]          # planted in October
    assert all("2026-09-01" <= i["transaction"]["date"] <= "2026-09-30" for i in sept["items"])


def test_cashflow_is_labelled_estimate(seeded_client):
    r = seeded_client.get("/api/reports/cashflow", params={"horizon_days": 30}).json()
    assert r["is_estimate"] is True and "ضماناً" in r["disclaimer_ar"] and r["sufficient_data"] is True
    assert r["low"] <= r["projected_net_change"] <= r["high"] and r["horizon_days"] == 30
    assert seeded_client.get("/api/reports/cashflow", params={"horizon_days": 0}).status_code == 422
    assert seeded_client.get("/api/reports/cashflow", params={"horizon_days": 91}).status_code == 422


def test_cashflow_declines_to_guess_without_history(client):
    client.post("/api/transactions", json={"date": "2026-10-10", "type": "sale", "amount": 1000, "description": "x", "payment_method": "cash"})
    r = client.get("/api/reports/cashflow").json()
    assert r["sufficient_data"] is False and r["projected_net_change"] is None and "غير كافية" in r["note_ar"]


# ---------------------------------------------------------------- settings
def test_settings_read_and_ai_status_without_key(client, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "groq_api_key", None)
    s = client.get("/api/settings").json()
    assert s["ai"]["configured"] is False and "غير مضبوط" in s["ai"]["message_ar"]
    assert s["is_demo_data"] is False and s["demo_notice_ar"] is None and s["currency_display"] == "د.ع"


def test_demo_data_is_clearly_indicated(seeded_client):
    s = seeded_client.get("/api/settings").json()
    assert s["is_demo_data"] is True and "تجريبية" in s["demo_notice_ar"] and s["transactions_count"] == 650
    assert seeded_client.get("/api/health").json()["is_demo_data"] is True


def test_settings_update_and_validation(client):
    r = client.put("/api/settings", json={"business_name": "محل النور", "credit_terms_days": 45, "currency_display": "IQD"})
    assert r.status_code == 200 and r.json()["business_name"] == "محل النور" and r.json()["credit_terms_days"] == 45
    assert client.get("/api/settings").json()["currency_display"] == "IQD"
    for bad in ({"credit_terms_days": 0}, {"credit_terms_days": 400}, {"business_name": ""}, {"currency_display": "USD"}, {"reference_date": "2020-01-01"}):
        assert client.put("/api/settings", json=bad).status_code == 422, bad


def test_credit_terms_setting_changes_overdue(seeded_client):
    before = seeded_client.get("/api/reports/debts").json()["total_overdue"]
    seeded_client.put("/api/settings", json={"credit_terms_days": 365})
    assert seeded_client.get("/api/reports/debts").json()["total_overdue"] == 0 < before


def test_reset_demo_requires_confirmation_and_reloads_data(seeded_client):
    seeded_client.post("/api/transactions", json={"date": "2026-10-10", "type": "sale", "amount": 1, "description": "extra", "payment_method": "cash"})
    for body in ({}, {"confirm": "yes"}):
        assert seeded_client.post("/api/settings/reset-demo", json=body).status_code == 422
    assert seeded_client.get("/api/settings").json()["transactions_count"] == 651           # nothing wiped yet
    r = seeded_client.post("/api/settings/reset-demo", json={"confirm": "RESET"})
    assert r.status_code == 200 and r.json()["transactions_loaded"] == 650
    assert seeded_client.get("/api/settings").json()["transactions_count"] == 650
