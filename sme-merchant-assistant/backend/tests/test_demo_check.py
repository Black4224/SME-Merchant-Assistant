from scripts.demo_check import EXAMPLE_QUESTIONS, FAIL, PASS, WARN, check_assistant, check_data
from app.ai.rules_provider import RulesProvider
from app.models import Transaction
from sqlalchemy import select


def statuses(rows):
    return {name: status for name, status, _ in rows}


def test_clean_demo_database_passes_every_data_check(seeded):
    rows = check_data(seeded)
    assert all(s == PASS for _, s, _ in rows), rows
    assert len(rows) >= 7


def test_empty_database_is_reported_as_not_ready(engine_session):
    rows = check_data(engine_session)
    assert rows[0][1] == FAIL and "reset_demo" in rows[0][2]


def test_a_tampered_figure_is_caught_against_the_independent_oracle(seeded):
    t = seeded.scalars(select(Transaction).where(Transaction.type == "sale").order_by(Transaction.id)).all()[-2]
    t.amount_iqd += 1000
    seeded.flush()
    bad = [n for n, s, _ in check_data(seeded) if s == FAIL]
    assert any("sales this month" in n for n in bad) or any("estimated profit" in n for n in bad)


def test_non_demo_data_skips_the_documented_figures(seeded):
    from app.services.settings_service import set_setting
    set_setting(seeded, "is_demo_data", "false")
    rows = check_data(seeded)
    assert statuses(rows)["demo-data flag"] == WARN and len(rows) == 2


def test_all_eight_example_questions_work_in_rules_mode(seeded):
    rows = check_assistant(seeded, RulesProvider(), ask=True)
    asked = [r for r in rows if r[0].startswith("ask:")]
    assert len(asked) == len(EXAMPLE_QUESTIONS) == 8
    assert all(s == PASS for _, s, _ in asked), asked


def test_missing_provider_is_a_warning_not_a_crash(seeded):
    assert check_assistant(seeded, None, ask=True)[0][1] == WARN


def test_check_never_modifies_data(seeded):
    from sqlalchemy import func
    before = seeded.scalar(select(func.sum(Transaction.amount_iqd)))
    check_data(seeded); check_assistant(seeded, RulesProvider(), ask=True)
    assert seeded.scalar(select(func.sum(Transaction.amount_iqd))) == before
