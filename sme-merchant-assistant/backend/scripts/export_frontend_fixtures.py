"""Export REAL API responses as JSON fixtures for the frontend tests.

    python -m scripts.export_frontend_fixtures

Runs the actual FastAPI app against an in-memory demo database. The assistant replies come from the real
orchestrator + tools, driven by a scripted stand-in for the LLM (no API key needed).
Re-run this whenever the API changes so the frontend tests keep matching reality.
"""
import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.assistant import get_llm_provider
from app.config import DATA_DIR, PROJECT_ROOT
from app.database import Base, get_session
from app.main import app
from scripts.seed_demo import seed_database
from tests.fakes import FakeProvider, call, text_turn, tools_turn

OUT = PROJECT_ROOT / "frontend" / "src" / "test" / "fixtures"
HEADER = "date,type,amount,description,reference,payment_method,customer,supplier,category,status\n"


def last_tool_figures(messages):
    payload = json.loads([m for m in messages if m["role"] == "tool"][-1]["content"])
    return [f["value"] for f in payload["figures"]]


def main(out: Path = OUT) -> None:
    out.mkdir(parents=True, exist_ok=True)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as s:
        seed_database(s)

    def override():
        with Session(engine, expire_on_commit=False) as s:
            yield s

    app.dependency_overrides[get_session] = override
    c = TestClient(app)

    def save(name, data):
        (out / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def get(path, **params):
        r = c.get(path, params=params)
        assert r.status_code == 200, (path, r.text)
        return r.json()

    save("settings", get("/api/settings"))
    save("dashboard", get("/api/dashboard/summary"))
    save("transactions", get("/api/transactions", page_size=25))
    save("customers", get("/api/customers", page_size=100))
    save("suppliers", get("/api/suppliers"))
    save("categories", get("/api/categories"))
    cid = next(x["customer_id"] for x in get("/api/customers")["items"] if "الجبوري" in x["name"])
    save("customer_debts", get(f"/api/customers/{cid}/debts"))
    save("reports_summary", get("/api/reports/summary", granularity="weekly"))
    save("reports_debts", get("/api/reports/debts"))
    save("reports_anomalies", get("/api/reports/anomalies"))
    save("reports_cashflow", get("/api/reports/cashflow"))
    empty_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(empty_engine)

    # ---- CSV previews (real importer output) ----
    sample_rows = (DATA_DIR / "sample_transactions.csv").read_text(encoding="utf-8-sig").splitlines()[1:]
    mixed = HEADER + "\n".join([
        "2026-10-16,sale,125000,بيع نقدي جديد,INV-X1,cash,,,مبيعات,",
        "2026-10-16,sale,300000,بيع آجل جديد,INV-X2,credit,زبون جديد للاختبار,,مبيعات,",
        "2026-10-16,sale,abc,مبلغ خاطئ,,cash,,,,",
        sample_rows[0],
    ]) + "\n"
    clean = HEADER + "2026-10-16,sale,125000,بيع نقدي جديد,INV-X1,cash,,,مبيعات,\n"
    odd = "when,kind,iqd,memo,how\n2026-10-16,sale,5000,test,cash\n"
    for name, text in (("import_preview_mixed", mixed), ("import_preview_clean", clean), ("import_preview_mapping", odd)):
        r = c.post("/api/import/csv/preview", files={"file": (f"{name}.csv", text.encode("utf-8"), "text/csv")})
        assert r.status_code == 200, r.text
        save(name, r.json())
    r = c.post("/api/import/csv/confirm", files={"file": ("clean.csv", clean.encode(), "text/csv")}, data={"skip_invalid": "false"})
    assert r.status_code == 201, r.text
    save("import_result", r.json())

    # ---- assistant replies through the REAL orchestrator (scripted model, real tools) ----
    def chat(script, message):
        app.dependency_overrides[get_llm_provider] = lambda: FakeProvider(script)
        r = c.post("/api/assistant/chat", json={"message": message})
        assert r.status_code == 200, r.text
        return r.json()

    save("assistant_debts", chat([
        tools_turn(call("get_customer_debts", {"limit": 10})),
        lambda m: text_turn(f"عندك {last_tool_figures(m)[0]} زبائن عليهم دين، والمجموع {last_tool_figures(m)[1]}.")], "منو بعده ما دايفعلي؟"))
    save("assistant_compare", chat([
        tools_turn(call("compare_periods", {"current_period": "this_month"})),
        lambda m: text_turn(f"مبيعات هذا الشهر {last_tool_figures(m)[0]} مقابل {last_tool_figures(m)[1]} لنفس المدة من الشهر الماضي.")],
        "قارنلي مبيعات هذا الشهر بالشهر الماضي."))
    save("assistant_cashflow", chat([
        tools_turn(call("get_cashflow_projection", {})),
        lambda m: text_turn(f"التقدير للتغير في النقد خلال 30 يوم هو {last_tool_figures(m)[0]}.")], "توقعلي التدفق النقدي للـ30 يوم الجاية."))
    save("assistant_fallback", chat([
        tools_turn(call("get_sales_summary", {"period": "this_month"})),
        text_turn("مبيعاتك 25,000,000 د.ع هذا الشهر")], "شكد مبيعاتي هذا الشهر؟"))
    save("assistant_clarification", chat([text_turn("أي فترة تقصد؟ اليوم لو هذا الأسبوع؟")], "شكد بعت؟"))
    app.dependency_overrides.clear()
    print(f"wrote {len(list(out.glob('*.json')))} fixtures -> {out}")


if __name__ == "__main__":
    main()
