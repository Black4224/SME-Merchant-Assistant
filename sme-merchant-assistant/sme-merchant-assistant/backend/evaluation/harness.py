"""Runs the question set through the REAL orchestrator, tools and verifier and scores every answer."""
import json
import re
import time
from collections import defaultdict
from statistics import mean

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.ai import orchestrator
from app.ai.provider import ProviderError
from app.ai.verifier import extract_numbers
from app.database import Base
from app.models import Transaction
from evaluation.build_dataset import HELDOUT_OUT, OUT as QUESTIONS_PATH
from evaluation.scoring import evidence_matches, numbers_present, texts_present, to_decimals
from scripts.seed_demo import seed_database

NO_DATA_PHRASES = re.compile(r"ما كو|لا توجد|لا يوجد|ما لقيت|غير كافية|لا بيانات|0")


def load_questions(limit: int | None = None, categories: set[str] | None = None, heldout: bool = False) -> list[dict]:
    qs = json.loads((HELDOUT_OUT if heldout else QUESTIONS_PATH).read_text(encoding="utf-8"))["questions"]
    if categories:
        qs = [q for q in qs if q["category"] in categories]
    return qs[:limit] if limit else qs


def seeded_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as s:
        seed_database(s)
    return engine


def db_fingerprint(session: Session) -> tuple:
    session.expire_all()
    return (session.scalar(select(func.count()).select_from(Transaction)), session.scalar(select(func.sum(Transaction.amount_iqd))))


def leaked_numbers(reply_dict: dict, question: str) -> list[str]:
    """Numbers in the FINAL answer that appear nowhere in the evidence (figures, tables, ids, dates) or the user's small numbers."""
    allowed = extract_numbers(json.dumps(reply_dict["evidence"], ensure_ascii=False, default=str), strip_list_markers=False)
    allowed |= {n for n in extract_numbers(question, strip_list_markers=False) if n < 10_000}
    allowed |= {to_decimals([i]).pop() for i in range(1, 40)}  # list positions / small counts the templates may use
    return sorted({format(n, "f") for n in extract_numbers(reply_dict["answer_ar"]) if n not in allowed})


def score_question(q: dict, reply, db_before: tuple, db_after: tuple, question_text: str) -> dict:
    d = reply.to_dict()
    ev = d["evidence"]
    rec = {"id": q["id"], "category": q["category"], "question": q["question"], "expected_kind": q["kind"], "kind": d["kind"],
           "tools_used": d["tools_used"], "answer_ar": d["answer_ar"], "unsupported_raw": d["unsupported_numbers"],
           "tool_errors": reply.tool_errors, "leaked": leaked_numbers(d, question_text),
           "side_effect": db_before != db_after, "forbidden_hit": [n for n in q["forbidden_numbers"] if to_decimals([n]) <= extract_numbers(d["answer_ar"], strip_list_markers=False)],
           "matched_alt": None, "answered": True, "tool_ok": False, "evidence_ok": None, "numeric_ok": None, "traceable_ok": None, "behaviour_ok": None, "problems": []}

    if q["kind"] in ("clarification", "refusal"):
        if q["kind"] == "clarification":
            ok = d["kind"] == "clarification" and not d["tools_used"] and not rec["leaked"]
        else:
            ok = not d["tools_used"] and not ev and d["kind"] in ("message", "fallback", "clarification") and not rec["leaked"] and not rec["side_effect"]
        rec.update(tool_ok=not d["tools_used"], behaviour_ok=ok)
        if not ok:
            rec["problems"].append(f"expected {q['kind']}, got kind={d['kind']} tools={d['tools_used']}")
        rec["passed"] = ok
        return rec

    best = None  # (alt_index, evidence_ok, problems)
    for idx, alt in enumerate(q["alternatives"]):
        if alt.get("tool") is None:  # the "asking is also acceptable" alternative
            if d["kind"] == "clarification" and not d["tools_used"]:
                best = (idx, True, [], None)
                break
            continue
        for e in (x for x in ev if x["tool"] == alt["tool"]):
            probs = evidence_matches(alt, e)
            if best is None or len(probs) < len(best[2]) or (not probs and not best[1]):
                best = (idx, not probs, probs, e)
            if not probs:
                break
        if best and best[1]:
            break
    if best is None:
        # Not answering is a MISS, not an exclusion: the set-level accuracy targets count every question.
        rec["problems"].append(f"none of the expected tools {q['tools']} was used (used {d['tools_used']})")
        rec["answered"] = False
        rec["evidence_ok"] = False
        if any(a.get("numbers") or a.get("texts") or a.get("has_data") is False for a in q["alternatives"] if a.get("tool")):
            rec["numeric_ok"] = False
        if q["requires_evidence"]:
            rec["traceable_ok"] = False
        rec["passed"] = False
        return rec

    idx, ev_ok, probs, e = best
    alt = q["alternatives"][idx]
    rec["matched_alt"] = idx
    if alt.get("tool") is None:  # accepted a clarification
        rec.update(tool_ok=True, evidence_ok=True, numeric_ok=True, traceable_ok=True, behaviour_ok=True)
        rec["passed"] = not rec["leaked"]
        return rec
    rec.update(tool_ok=True, evidence_ok=ev_ok)
    rec["problems"] += probs
    if q["requires_evidence"]:
        id_problem = any(p.startswith(("ids", "tool")) for p in probs)
        has_ids = bool(e and (e["transaction_ids"] or alt.get("has_data") is False))
        rec["traceable_ok"] = bool(e) and has_ids and not id_problem
    if alt.get("numbers") or alt.get("texts"):
        rec["numeric_ok"] = numbers_present(alt.get("numbers", []), d["answer_ar"]) and texts_present(alt.get("texts", []), d["answer_ar"])
        if not rec["numeric_ok"]:
            rec["problems"].append(f"answer does not state {alt.get('numbers')} {alt.get('texts') or ''}")
    if alt.get("has_data") is False:  # "no data" must be said plainly
        said = bool(NO_DATA_PHRASES.search(d["answer_ar"]))
        rec["numeric_ok"] = said and not rec["leaked"]
        if not said:
            rec["problems"].append("did not say there is no data")
    forbidden = bool(rec["forbidden_hit"])
    if forbidden:
        rec["problems"].append(f"stated forbidden number(s) {rec['forbidden_hit']}")
    rec["passed"] = bool(ev_ok and rec["numeric_ok"] in (None, True) and rec["traceable_ok"] in (None, True)
                         and not rec["leaked"] and not rec["side_effect"] and not forbidden)
    return rec


def run(provider_for, questions: list[dict], *, label: str, pause: float = 0.0) -> dict:
    """`provider_for(question) -> LLMProvider`."""
    engine = seeded_engine()
    results, started = [], time.time()
    for q in questions:
        with Session(engine, expire_on_commit=False) as session:
            before = db_fingerprint(session)
            t0 = time.time()
            try:
                reply = orchestrator.answer_question(session, provider_for(q), q["question"])
                rec = score_question(q, reply, before, db_fingerprint(session), q["question"])
            except ProviderError as e:
                rec = {"id": q["id"], "category": q["category"], "question": q["question"], "expected_kind": q["kind"], "kind": "provider_error",
                       "provider_error": e.kind, "passed": False, "problems": [f"provider error: {e.kind}"], "tool_ok": False, "leaked": [], "side_effect": False,
                       "unsupported_raw": [], "tools_used": [], "answer_ar": "", "evidence_ok": None, "numeric_ok": None, "traceable_ok": None,
                       "behaviour_ok": None, "matched_alt": None, "tool_errors": [], "forbidden_hit": []}
            rec["seconds"] = round(time.time() - t0, 3)
            results.append(rec)
        if pause:
            time.sleep(pause)
    return {"label": label, "seconds": round(time.time() - started, 2), "aggregate": aggregate(results, questions), "results": results}


def _rate(vals):
    vals = [v for v in vals if v is not None]
    return {"passed": sum(bool(v) for v in vals), "total": len(vals), "rate": round(sum(bool(v) for v in vals) / len(vals), 4) if vals else None}


def aggregate(results: list[dict], questions: list[dict]) -> dict:
    by_id = {q["id"]: q for q in questions}
    answers = [r for r in results if r["expected_kind"] == "answer"]
    tool_answers = [r for r in answers if by_id[r["id"]]["tools"] and any(a.get("tool") for a in by_id[r["id"]]["alternatives"])]
    agg = {
        "questions": len(results),
        "overall_pass": _rate(r["passed"] for r in results),
        "numerical_accuracy": _rate(r["numeric_ok"] for r in answers),                       # every question counts; declining = miss
        "numerical_accuracy_when_answered": _rate(r["numeric_ok"] for r in answers if r.get("answered", True)),
        "answer_coverage": _rate(r.get("answered", True) and r["kind"] != "provider_error" for r in answers),
        "evidence_accuracy": _rate(r["evidence_ok"] for r in tool_answers),
        "tool_selection": _rate(r["tool_ok"] for r in results),
        "traceability": _rate(r["traceable_ok"] for r in answers),
        "clarification_accuracy": _rate(r["behaviour_ok"] for r in results if r["expected_kind"] == "clarification"),
        "refusal_accuracy": _rate(r["behaviour_ok"] for r in results if r["expected_kind"] == "refusal"),
        "raw_unsupported_claim_rate": _rate(bool(r["unsupported_raw"]) for r in results),   # model's own wording rejected by the verifier
        "leaked_unsupported_rate": _rate(bool(r["leaked"]) for r in results),               # numbers in the FINAL answer with no evidence
        "side_effects": sum(r["side_effect"] for r in results),
        "provider_errors": sum(r["kind"] == "provider_error" for r in results),
        "mean_seconds": round(mean(r["seconds"] for r in results), 3) if results else None,
    }
    cats = defaultdict(list)
    for r in results:
        cats[r["category"]].append(r["passed"])
    agg["by_category"] = {c: {"passed": sum(v), "total": len(v)} for c, v in cats.items()}
    return agg
