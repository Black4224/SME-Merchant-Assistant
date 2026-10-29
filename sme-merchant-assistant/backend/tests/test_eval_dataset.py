"""The evaluation questions' expected answers come from an independent oracle. Here we check that the real tools, run on
the seeded database, agree with every expected figure, range, evidence id and name. If this fails, either the oracle or
the application is wrong."""
import json
from pathlib import Path

import pytest

from app.ai.tools import execute
from evaluation import oracle
from evaluation.build_dataset import OUT, build
from evaluation.scoring import evidence_matches

from evaluation.build_dataset import HELDOUT_OUT

DATA = json.loads(OUT.read_text(encoding="utf-8"))
HELD = json.loads(HELDOUT_OUT.read_text(encoding="utf-8"))
QUESTIONS = DATA["questions"]
CASES = [(q["id"], i, a) for q in QUESTIONS + HELD["questions"] if q["kind"] == "answer" for i, a in enumerate(q["alternatives"]) if a["tool"]]


def test_committed_dataset_is_up_to_date(tmp_path):
    """questions.json must be exactly what the builder produces from the current CSV."""
    fresh = json.loads(json.dumps(build(), ensure_ascii=False))
    assert fresh == DATA
    assert json.loads(HELDOUT_OUT.read_text(encoding="utf-8")) == HELD            # build() rewrote it; it must be unchanged


def test_dataset_shape_and_coverage():
    assert DATA["meta"]["count"] == len(QUESTIONS) >= 70
    assert len({q["id"] for q in QUESTIONS}) == len(QUESTIONS)
    cats = {q["category"] for q in QUESTIONS}
    assert {"sales", "profit", "expenses", "debts", "top_customers", "payments", "compare", "review", "cashflow", "recent",
            "custom_range", "no_data", "clarification", "refusal", "adversarial"} <= cats
    for q in QUESTIONS:
        assert q["question"].strip()
        if q["kind"] == "answer":
            assert q["alternatives"], q["id"]
        else:
            assert not q["alternatives"], q["id"]
    assert len({q["question"] for q in QUESTIONS}) == len(QUESTIONS)          # no accidental duplicates


def test_heldout_set_is_separate_and_does_not_share_questions_with_the_main_set():
    main = {q["question"] for q in QUESTIONS}
    assert HELD["meta"]["count"] == len(HELD["questions"]) >= 20
    assert not main & {q["question"] for q in HELD["questions"]}
    assert all(q["id"].startswith("H") for q in HELD["questions"])


def test_the_example_questions_from_the_brief_are_covered():
    texts = {q["question"] for q in QUESTIONS}
    for t in ["شكد ربحت هذا الأسبوع؟", "شكد مبيعاتي اليوم؟", "منو بعده ما دايفعلي؟", "شكد ديون الزبائن عليه؟", "منو أكثر زبون يشتري مني؟",
              "قارنلي مبيعات هذا الشهر بالشهر الماضي.", "شنو المدفوعات اللي تحتاج مراجعة؟", "توقعلي التدفق النقدي للـ30 يوم الجاية."]:
        assert t in texts


@pytest.mark.parametrize("qid,idx,alt", CASES, ids=[f"{c[0]}#{c[1]}" for c in CASES])
def test_application_agrees_with_the_independent_oracle(seeded, qid, idx, alt):
    result = execute(seeded, alt["tool"], alt["call"])
    problems = evidence_matches(alt, result.to_ui_dict())
    assert problems == [], f"{qid} alt {idx}: {problems}"


def test_oracle_row_ids_match_database_ids(seeded):
    from sqlalchemy import select
    from app.models import Transaction
    rows = oracle.load()
    db = {t.id: t for t in seeded.scalars(select(Transaction))}
    assert len(rows) == len(db) == 650
    for r in (rows[0], rows[593], rows[594], rows[649]):
        assert db[r["id"]].amount_iqd == r["amount"] and db[r["id"]].txn_date == r["date"] and db[r["id"]].type.value == r["type"]
