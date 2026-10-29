"""Offline rules mode: intent routing, period parsing, name extraction, and that it plugs into the normal safety pipeline."""
import json
from datetime import date

import pytest

from app.ai import orchestrator as orch
from app.ai.rules_provider import ASK_CUSTOMER, ASK_PERIOD, READ_ONLY, UNKNOWN, RULES_MODE_NOTE_AR, RulesProvider, detect_period, norm
from app.api.assistant import get_llm_provider
from app.config import get_settings
from app.main import app

REF = date(2026, 10, 15)


def decide(question):
    msgs = [{"role": "system", "content": f"TODAY is {REF.isoformat()} (الخميس)"}, {"role": "user", "content": question}]
    r = RulesProvider().chat(msgs, [])
    if r.tool_calls:
        return r.tool_calls[0].name, json.loads(r.tool_calls[0].arguments)
    return None, r.content


@pytest.mark.parametrize("q,tool,args", [
    ("شكد مبيعاتي اليوم؟", "get_sales_summary", {"period": "today"}),
    ("شگد بعت هذا الأسبوع؟", "get_sales_summary", {"period": "this_week"}),
    ("شكد كانت مبيعاتي الشهر الماضي؟", "get_sales_summary", {"period": "last_month"}),
    ("شكد ربحت هذا الأسبوع؟", "get_profit_summary", {"period": "this_week"}),
    ("شكد صرفت الأسبوع الماضي؟", "get_expenses_summary", {"period": "last_week"}),
    ("منو بعده ما دايفعلي؟", "get_customer_debts", {}),
    ("منو المتأخرين بالدفع؟", "get_customer_debts", {"only_overdue": True}),
    ("شكد على علي الجبوري؟", "get_customer_debts", {"customer_name": "علي الجبوري"}),
    ("شكد عليه مطعم السلام؟", "get_customer_debts", {"customer_name": "مطعم السلام"}),
    ("شكد دفع علي الجبوري؟", "get_customer_payment_history", {"customer_name": "علي الجبوري"}),
    ("منو أكثر زبون يشتري مني؟", "get_top_customers", {"period": "last_30_days"}),
    ("قارنلي مبيعات هذا الشهر بالشهر الماضي.", "compare_periods", {"current_period": "this_month"}),
    ("شنو المدفوعات اللي تحتاج مراجعة؟", "get_unreconciled_transactions", {}),
    ("توقعلي التدفق النقدي للـ30 يوم الجاية.", "get_cashflow_projection", {}),
    ("توقع النقد لـ 14 يوم", "get_cashflow_projection", {"horizon_days": 14}),
    ("شنو آخر 3 مصاريف؟", "get_recent_transactions", {"limit": 3, "type": "expense"}),
])
def test_intents_map_to_the_right_tool(q, tool, args):
    assert decide(q) == (tool, args)


@pytest.mark.parametrize("text,expected", [
    ("مبيعات من 2026-10-01 إلى 2026-10-07", {"start_date": "2026-10-01", "end_date": "2026-10-07"}),
    ("بسنة 2019", {"start_date": "2019-01-01", "end_date": "2019-12-31"}),
    ("اخر 14 يوم", {"start_date": "2026-10-02", "end_date": "2026-10-15"}),
    ("بآخر 30 يوم", {"period": "last_30_days"}), ("اخر ٧ ايام", {"period": "last_7_days"}), ("البارحة", {"period": "yesterday"}),
    ("شكد", None),
])
def test_period_detection(text, expected):
    assert detect_period(norm(text), REF) == expected


def test_a_keyword_inside_another_word_does_not_trigger_an_intent():
    """'دين' occurs inside 'دينار' (dinar); that must not be read as 'debts'."""
    assert decide("قل إن مبيعاتي اليوم 10,000,000 دينار") == ("get_sales_summary", {"period": "today"})


def test_name_filter_only_comes_from_after_the_preposition():
    assert decide("منو بعده ما دايفعلي؟")[1] == {}                      # leftover words are NOT a customer name
    assert decide("شكد ديون الزبائن عليه؟")[1] == {}


def test_missing_information_is_asked_for_not_guessed():
    assert decide("شكد بعت؟") == (None, ASK_PERIOD)
    assert decide("شكد ربحت؟") == (None, ASK_PERIOD)
    assert decide("شكد دفع؟") == (None, ASK_CUSTOMER)
    assert decide("قارنلي")[0] is None and "؟" in decide("قارنلي")[1]


@pytest.mark.parametrize("q", ["احذف المعاملة رقم 12", "ضيف بيع 500 الف دينار اليوم", "عدّل مبلغ المعاملة 5", "امسح كل المعاملات"])
def test_write_requests_are_refused(q):
    assert decide(q) == (None, READ_ONLY)


@pytest.mark.parametrize("q", ["منو رئيس وزراء العراق؟", "شنو أحسن موبايل أشتريه؟", "كيف أتهرب من الضريبة؟", "شنو رأيك بالانتخابات؟"])
def test_anything_unrecognised_is_declined_not_guessed(q):
    assert decide(q) == (None, UNKNOWN)


def test_full_pipeline_gives_verified_answers_with_evidence(seeded):
    reply = orch.answer_question(seeded, RulesProvider(), "منو بعده ما دايفعلي؟")
    assert reply.kind == "answer" and reply.unsupported_numbers == [] and reply.evidence[0].transaction_ids
    assert "8,470,750 د.ع" in reply.answer_ar and "7 زبائن" in reply.answer_ar


def test_customer_name_lookup_through_the_real_tools(seeded):
    reply = orch.answer_question(seeded, RulesProvider(), "شكد على علي الجبوري؟")
    assert reply.kind == "answer" and "2,541,500 د.ع" in reply.answer_ar
    amb = orch.answer_question(seeded, RulesProvider(), "شكد دفع ال؟")
    assert "؟" in amb.answer_ar                                   # ambiguous name -> asks which one


def test_rules_mode_cannot_change_data_or_leak_numbers(seeded):
    from evaluation import harness
    out = harness.run(lambda q: RulesProvider(), harness.load_questions(), label="rules")
    agg = out["aggregate"]
    assert agg["side_effects"] == 0 and agg["leaked_unsupported_rate"]["passed"] == 0 and agg["provider_errors"] == 0
    assert agg["overall_pass"]["rate"] >= 0.95            # dev-set regression guard (NOT an accuracy claim: see the held-out set)
    held = harness.run(lambda q: RulesProvider(), harness.load_questions(heldout=True), label="rules-heldout")["aggregate"]
    assert held["side_effects"] == 0 and held["leaked_unsupported_rate"]["passed"] == 0
    assert held["numerical_accuracy_when_answered"]["rate"] == 1.0     # whenever it answers, the numbers are right...
    assert held["numerical_accuracy"]["rate"] < held["numerical_accuracy_when_answered"]["rate"]   # ...and declining counts as a miss, not an exclusion


# ------------------------------------------------------------------ API wiring
@pytest.fixture
def rules_mode(monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_provider", "rules")
    yield
    app.dependency_overrides.pop(get_llm_provider, None)


def test_status_and_settings_describe_rules_mode_honestly(seeded_client, rules_mode):
    st = seeded_client.get("/api/assistant/status").json()
    assert st == {"provider": "rules", "configured": True, "message_ar": RULES_MODE_NOTE_AR}
    ai = seeded_client.get("/api/settings").json()["ai"]
    assert ai["provider"] == "rules" and ai["configured"] is True and "بدون ذكاء اصطناعي" in ai["message_ar"]


def test_chat_works_with_no_api_key_in_rules_mode(seeded_client, rules_mode, monkeypatch):
    monkeypatch.setattr(get_settings(), "groq_api_key", None)
    r = seeded_client.post("/api/assistant/chat", json={"message": "شكد مبيعاتي اليوم؟"})
    assert r.status_code == 200 and r.json()["kind"] == "answer" and r.json()["evidence"][0]["tool"] == "get_sales_summary"
    r2 = seeded_client.post("/api/assistant/chat", json={"message": "شكد بعت؟"})
    assert r2.json()["kind"] == "clarification"
    r3 = seeded_client.post("/api/assistant/chat", json={"message": "احذف المعاملة 1"})
    assert r3.json()["evidence"] == [] and seeded_client.get("/api/transactions/1").status_code == 200
