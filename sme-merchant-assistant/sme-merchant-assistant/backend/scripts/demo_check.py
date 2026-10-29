"""Pre-flight check before a demo. Read-only: it never changes data.

    python -m scripts.demo_check                      # checks the database + the configured assistant
    python -m scripts.demo_check --api http://localhost:8000     # also checks a RUNNING server
    python -m scripts.demo_check --no-ask             # skip asking the 8 example questions (no AI quota used)

Exit code 0 = ready, 1 = something needs fixing.
"""
import argparse
import sys
import time
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import orchestrator
from app.ai.provider import ProviderError
from app.models import Transaction
from app.services.customers import total_outstanding
from app.services.metrics import summarize_period
from app.services.periods import named_period
from app.services.settings_service import get_reference_date, get_setting
from evaluation import oracle

EXAMPLE_QUESTIONS = ["شكد ربحت هذا الأسبوع؟", "شكد مبيعاتي اليوم؟", "منو بعده ما دايفعلي؟", "شكد ديون الزبائن عليه؟", "منو أكثر زبون يشتري مني؟",
                     "قارنلي مبيعات هذا الشهر بالشهر الماضي.", "شنو المدفوعات اللي تحتاج مراجعة؟", "توقعلي التدفق النقدي للـ30 يوم الجاية."]
PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


def check_data(session: Session) -> list[tuple[str, str, str]]:
    out = []
    n = session.scalar(select(func.count()).select_from(Transaction)) or 0
    if n == 0:
        return [("database has data", FAIL, "no transactions. Run: python -m scripts.reset_demo")]
    out.append(("database has data", PASS, f"{n} transactions"))
    demo = get_setting(session, "is_demo_data") == "true"
    out.append(("demo-data flag", PASS if demo else WARN, "synthetic demo data" if demo else "NOT demo data: the documented demo figures are skipped"))
    if not demo:
        return out
    ref = get_reference_date(session)
    out.append(("reference date pinned", PASS if ref == oracle.REF else FAIL, f"{ref}" + ("" if ref == oracle.REF else f" (expected {oracle.REF})")))
    try:
        rows = oracle.load()
    except FileNotFoundError:
        return out + [("independent oracle", WARN, "data/sample_transactions.csv not found; figures not cross-checked")]
    s = oracle.summarize(rows, *oracle.period("this_month", ref))
    got = summarize_period(session, named_period("this_month", ref), include_ids=False)
    debts = sum(v["outstanding"] for v in oracle.debts(rows, ref).values() if v["outstanding"] > 0)
    checks = [("sales this month", got.sales_total, s["sales"]), ("estimated profit this month", got.estimated_profit, s["profit"]),
              ("outstanding customer debts", total_outstanding(session, ref), debts), ("transaction count", n, len(rows))]
    for name, app_v, truth in checks:
        out.append((f"{name} = independent oracle", PASS if app_v == truth else FAIL, f"{app_v:,}" if app_v == truth else f"app {app_v:,} != oracle {truth:,}"))
    return out


def check_assistant(session: Session, provider, ask: bool) -> list[tuple[str, str, str]]:
    if provider is None:
        return [("assistant provider", WARN, "not configured (no key). Set AI_PROVIDER=rules for the offline mode, or add GROQ_API_KEY/GROQ_MODEL")]
    out = [("assistant provider", PASS, provider.name)]
    if not ask:
        return out
    for q in EXAMPLE_QUESTIONS:
        t0 = time.time()
        try:
            r = orchestrator.answer_question(session, provider, q)
        except ProviderError as e:
            out.append((f"ask: {q}", FAIL, f"provider error: {e.kind}"))
            continue
        dt = time.time() - t0
        ok = r.kind == "answer" and r.verified and bool(r.evidence)
        out.append((f"ask: {q}", PASS if ok else WARN, f"{r.kind}, tools={r.tools_used}, {dt:.1f}s" + ("" if ok else f" | {r.answer_ar[:60]}")))
    return out


def check_api(url: str) -> list[tuple[str, str, str]]:
    import httpx
    try:
        h = httpx.get(f"{url}/api/health", timeout=5).json()
        d = httpx.get(f"{url}/api/dashboard/summary", timeout=10)
        return [("running server", PASS if h.get("status") == "ok" and d.status_code == 200 else FAIL, f"{url} -> health={h.get('status')} dashboard={d.status_code}")]
    except Exception as e:  # noqa: BLE001
        return [("running server", FAIL, f"cannot reach {url}: {type(e).__name__}")]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Arabic output on Windows consoles
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api")
    ap.add_argument("--no-ask", action="store_true")
    a = ap.parse_args()
    from app.api.assistant import get_llm_provider
    from app.database import SessionLocal, init_db

    init_db()
    results = []
    with SessionLocal() as session:
        results += check_data(session)
        results += check_assistant(session, get_llm_provider(), not a.no_ask)
    if a.api:
        results += check_api(a.api.rstrip("/"))
    width = max(len(n) for n, _, _ in results)
    for name, status, detail in results:
        print(f"[{status}] {name:<{width}}  {detail}")
    fails, warns = sum(s == FAIL for _, s, _ in results), sum(s == WARN for _, s, _ in results)
    print(f"\n{'READY' if not fails else 'NOT READY'}: {len(results) - fails - warns} passed, {warns} warnings, {fails} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
