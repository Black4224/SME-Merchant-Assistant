"""CSV import evaluation against the REAL endpoints, with files whose faults are injected at known rows.

    python -m evaluation.csv_eval

Measures: row-level error detection (precision/recall, correct field attribution), zero false positives on tricky-but-valid rows,
exact duplicate handling, format coverage (encodings/separators/Arabic headers), graceful failure on bad files (never a 5xx),
atomic commits, and that previews never write.
"""
import csv
import io
import json
import sys
import logging
import random
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_session
from app.main import app
from app.models import ImportBatch, Transaction

COLS = ["date", "type", "amount", "description", "reference", "payment_method", "customer", "supplier", "category", "status"]


def make_client(raise_exceptions=True):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override():
        with Session(engine, expire_on_commit=False) as s:
            yield s

    app.dependency_overrides[get_session] = override
    return TestClient(app, raise_server_exceptions=raise_exceptions), engine


def count(engine, model=Transaction):
    with Session(engine) as s:
        return s.scalar(select(func.count()).select_from(model))


def to_csv(rows, cols=COLS, sep=",") -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, delimiter=sep, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


def good_rows(n: int, tag: str = "A", start_idx: int = 0) -> list[dict]:
    """Deterministic, valid, mutually distinct rows covering every type and method."""
    rng, rows = random.Random(7), []
    kinds = [("sale", "cash", "", ""), ("sale", "digital", "", ""), ("sale", "credit", "عميل {k}", ""), ("customer_payment", "cash", "عميل {k}", ""),
             ("expense", "cash", "", ""), ("supplier_purchase", "credit", "", "مورد {k}"), ("supplier_purchase", "cash", "", ""), ("supplier_payment", "bank", "", "مورد {k}")]
    for i in range(start_idx, start_idx + n):
        t, m, c, s = kinds[i % len(kinds)]
        k = i % 5
        rows.append({"date": f"2026-10-{1 + i % 28:02d}", "type": t, "amount": str(rng.randrange(10, 900) * 1000 + i), "description": f"{tag} حركة رقم {i}",
                     "reference": f"{tag}-{i}", "payment_method": m, "customer": c.format(k=k), "supplier": s.format(k=k), "category": "", "status": ""})
    return rows


def preview(c, data: bytes, name="t.csv", mapping=None):
    return c.post("/api/import/csv/preview", files={"file": (name, data, "text/csv")}, data={"mapping": json.dumps(mapping)} if mapping else None)


def confirm(c, data: bytes, name="t.csv", **form):
    return c.post("/api/import/csv/confirm", files={"file": (name, data, "text/csv")}, data={k: str(v).lower() if isinstance(v, bool) else v for k, v in form.items()})


# ------------------------------------------------------------------------------------------------ scenarios
FAULTS = [  # (label, mutation, expected error field)
    ("impossible date", {"date": "2026-02-30"}, "date"), ("unparseable date", {"date": "15-Oct"}, "date"),
    ("negative amount", {"amount": "-500"}, "amount"), ("fractional amount", {"amount": "1500.5"}, "amount"), ("zero amount", {"amount": "0"}, "amount"),
    ("text amount", {"amount": "abc"}, "amount"), ("absurd amount", {"amount": "999999999999"}, "amount"),
    ("unknown type", {"type": "gift"}, "type"), ("unknown method", {"payment_method": "bitcoin"}, "payment_method"),
    ("empty description", {"description": ""}, "description"), ("description too long", {"description": "ط" * 300}, "description"),
    ("unknown status", {"status": "maybe"}, "status"),
    ("credit sale without customer", {"type": "sale", "payment_method": "credit", "customer": "", "supplier": ""}, "row"),
    ("customer payment without customer", {"type": "customer_payment", "payment_method": "cash", "customer": "", "supplier": ""}, "row"),
    ("expense on credit", {"type": "expense", "payment_method": "credit", "customer": "", "supplier": ""}, "row"),
]
TRICKY_VALID = [  # look odd but are valid: must NOT be flagged
    {"amount": "1,250,000"}, {"amount": "١٢٥٠٠٠٠"}, {"amount": "1250000.00"}, {"amount": " 75000 "}, {"date": "15/10/2026"}, {"date": "2026/10/15"},
    {"date": "١٥/١٠/٢٠٢٦"}, {"type": "بيع", "payment_method": "نقدي", "customer": "", "supplier": ""}, {"type": "مصروف", "payment_method": "كاش", "customer": "", "supplier": ""},
    {"description": "بيع، مع فاصلة \"واقتباس\""}, {"description": "  مسافات   كثيرة  "}, {"status": "مطابق"}, {"status": "غير مطابق"}, {"description": "ط" * 255},
]


def s_injected_faults():
    c, engine = make_client()
    rows = good_rows(100, "F")
    fault_at, tricky_at = {}, set()
    for j, (label, mut, field) in enumerate(FAULTS):
        i = 3 + j * 6
        rows[i] = {**rows[i], **mut}
        fault_at[i + 2] = (label, field)  # row_number = list index + header + 1
    for j, mut in enumerate(TRICKY_VALID):
        i = 5 + j * 6 + (1 if (5 + j * 6) in {k - 2 for k in fault_at} else 0)
        rows[i] = {**rows[i], **mut}
        tricky_at.add(i + 2)
    data = to_csv(rows)
    p = preview(c, data).json()
    flagged = {e["row_number"]: e for e in p["errors"]}
    tp = set(flagged) & set(fault_at)
    fp, fn = set(flagged) - set(fault_at), set(fault_at) - set(flagged)
    right_field = sum(1 for r in tp if flagged[r]["errors"][0]["field"] == fault_at[r][1])
    tricky_false_pos = sorted(tricky_at & set(flagged))
    blocked = confirm(c, data)
    after_block = count(engine)
    done = confirm(c, data, skip_invalid="true", expected_sha256=p["file_sha256"])
    ok = done.status_code == 201 and done.json()["imported"] == 100 - len(fault_at) and done.json()["skipped_invalid"] == len(fault_at)
    return {"injected": len(fault_at), "detected": len(tp), "false_positives": sorted(fp), "missed": sorted(fn), "field_correct": right_field,
            "tricky_valid_rows": len(tricky_at), "tricky_false_positives": tricky_false_pos,
            "missed_detail": [fault_at[r][0] for r in sorted(fn)],
            "blocked_without_skip": blocked.status_code == 422 and blocked.json()["error"]["code"] == "invalid_rows" and after_block == 0,
            "imported_exactly_the_valid_rows": ok and count(engine) == 100 - len(fault_at)}, {
        "passed": not fp and not fn and right_field == len(tp) and not tricky_false_pos and ok and blocked.status_code == 422 and after_block == 0}


def s_clean_file_totals():
    c, engine = make_client()
    rows = good_rows(100, "C")
    data = to_csv(rows)
    p = preview(c, data).json()
    before = count(engine)
    r = confirm(c, data)
    expected = {t: sum(int(x["amount"]) for x in rows if x["type"] == t) for t in {x["type"] for x in rows}}
    tot = c.get("/api/reports/summary", params={"start": "2026-10-01", "end": "2026-10-31"}).json()["totals"]
    got = {"sale": tot["sales_total"], "customer_payment": tot["customer_payments"], "expense": tot["expenses_total"],
           "supplier_purchase": tot["purchases_total"], "supplier_payment": tot["supplier_payments"]}
    return {"preview": p["counts"], "preview_wrote_nothing": before == 0, "imported": r.json().get("imported"), "totals_match_source": got == expected,
            "mismatches": {k: (got[k], expected[k]) for k in expected if got[k] != expected[k]}}, {
        "passed": p["counts"] == {"total": 100, "valid": 100, "duplicate": 0, "invalid": 0} and before == 0 and r.status_code == 201 and r.json()["imported"] == 100 and got == expected}


def s_duplicates():
    c, engine = make_client()
    a = good_rows(50, "D")
    da = to_csv(a)
    first = confirm(c, da)
    again = confirm(c, da)
    n1 = count(engine)
    b = to_csv(a + good_rows(10, "D", 50))
    pb = preview(c, b).json()
    cb = confirm(c, b)
    n2 = count(engine)
    variants = [{**r, "description": r["description"].replace("حركة", "حركه").replace("رقم", "رقم ")} for r in a]   # alef/taa-marbuta-free spelling + spacing
    variants = [{**r, "description": r["description"].replace("حركة", "حركة")} for r in a]
    arabic = to_csv([{**r, "amount": "".join("٠١٢٣٤٥٦٧٨٩"[int(ch)] for ch in r["amount"])} for r in a])        # same rows, Arabic-Indic digits
    pv = preview(c, arabic).json()
    rep = [{**good_rows(1, "R")[0]}] * 3
    c2, e2 = make_client()
    r1 = confirm(c2, to_csv(rep))
    r2 = confirm(c2, to_csv(rep + [rep[0]]))
    return {"first_import": first.json().get("imported"), "same_file_again": again.status_code, "rows_after_reimport": n1,
            "overlap_preview": pb["counts"], "overlap_added": cb.json().get("imported"), "rows_after_overlap": n2,
            "arabic_digits_variant_duplicates": pv["counts"]["duplicate"], "repeats_in_one_file_kept": r1.json().get("imported"),
            "one_new_repeat_added": r2.json().get("imported")}, {
        "passed": first.json()["imported"] == 50 and again.status_code == 409 and n1 == 50 and pb["counts"]["duplicate"] == 50 and pb["counts"]["valid"] == 10
                  and cb.json()["imported"] == 10 and n2 == 60 and pv["counts"]["duplicate"] == 50 and r1.json()["imported"] == 3 and r2.json()["imported"] == 1}


def s_formats():
    rows = good_rows(20, "E")
    ar_rows = [{**r, "date": r["date"][8:] + "/10/2026", "type": {"sale": "بيع", "expense": "مصروف", "customer_payment": "تسديد زبون", "supplier_purchase": "شراء بضاعة", "supplier_payment": "دفع مورد"}[r["type"]],
                "payment_method": {"cash": "نقدي", "digital": "محفظة", "bank": "بنك", "credit": "آجل"}[r["payment_method"]]} for r in rows]
    ar_headers = dict(zip(COLS, ["التاريخ", "النوع", "المبلغ", "البيان", "المرجع", "طريقة الدفع", "الزبون", "المورد", "التصنيف", "الحالة"]))
    ar_csv = to_csv([{ar_headers[k]: v for k, v in r.items()} for r in ar_rows], cols=list(ar_headers.values()))
    variants = {"utf-8": to_csv(rows), "utf-8-bom": b"\xef\xbb\xbf" + to_csv(rows), "windows-1256": to_csv(rows).decode("utf-8").encode("cp1256", errors="replace"),
                "semicolon": to_csv(rows, sep=";"), "tab": to_csv(rows, sep="\t"), "arabic headers+values+day-first dates": ar_csv}
    out, ok_all = {}, True
    for name, data in variants.items():
        c, engine = make_client()
        p = preview(c, data).json()
        parsed = {r["row_number"]: r["data"] for r in p.get("rows", [])}
        amounts_ok = all(parsed[i + 2]["amount_iqd"] == int(rows[i]["amount"]) for i in range(20)) if p.get("rows") else False
        dates_ok = all(parsed[i + 2]["date"] == rows[i]["date"] for i in range(20)) if p.get("rows") else False
        ok = p.get("counts") == {"total": 20, "valid": 20, "duplicate": 0, "invalid": 0} and amounts_ok and dates_ok
        out[name] = ok
        ok_all &= ok
    return out, {"passed": ok_all}


def s_mapping():
    c, _ = make_client()
    rows = good_rows(5, "M")
    odd = to_csv([{"when": r["date"], "kind": r["type"], "iqd": r["amount"], "memo": r["description"], "how": r["payment_method"], "who": r["customer"], "vendor": r["supplier"]} for r in rows],
                 cols=["when", "kind", "iqd", "memo", "how", "who", "vendor"])
    p = preview(c, odd).json()
    good_map = {"date": "when", "type": "kind", "amount": "iqd", "description": "memo", "payment_method": "how", "customer": "who", "supplier": "vendor"}
    p2 = preview(c, odd, mapping=good_map).json()
    bad = [preview(c, odd, mapping={**good_map, "amount": "nope"}), preview(c, odd, mapping={**good_map, "type": "when"}), preview(c, odd, mapping={**good_map, "bogus": "when"})]
    done = confirm(c, odd, mapping=json.dumps(good_map))
    return {"needs_mapping": p["needs_mapping"], "after_mapping": p2["counts"], "bad_mappings_rejected": [b.status_code for b in bad], "imported": done.json().get("imported")}, {
        "passed": p["needs_mapping"] and p2["counts"]["valid"] == 5 and all(b.status_code == 422 for b in bad) and done.json()["imported"] == 5}


def s_bad_files():
    c, engine = make_client(raise_exceptions=False)
    cases = {"empty": b"", "whitespace": b"  \n \n", "header only": (",".join(COLS) + "\n").encode(), "ragged": b"a,b\n1,2,3,4\n",
             "binary garbage": bytes(random.Random(1).randrange(256) for _ in range(5000)), "html page": b"<html><body>404</body></html>",
             "oversize (>5MB)": b"date,type\n" + b"x" * (5 * 1024 * 1024 + 10)}
    out, ok_all = {}, True
    for name, data in cases.items():
        r = preview(c, data)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        graceful = r.status_code in (200, 413, 422) and r.status_code < 500
        # a 200 is acceptable only if nothing would be imported (e.g. html parsed as a one-column file needing a mapping)
        if r.status_code == 200:
            graceful = body.get("needs_mapping") is True or body["counts"]["valid"] == 0
        out[name] = {"status": r.status_code, "code": body.get("error", {}).get("code"), "graceful": graceful}
        ok_all &= graceful
    return out, {"passed": ok_all and count(engine) == 0}


def s_atomic_commit():
    c, engine = make_client(raise_exceptions=False)
    data = to_csv(good_rows(10, "T"))
    import app.services.importer as imp
    real, calls = imp.add_transaction, {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 6:
            raise RuntimeError("disk full")
        return real(*a, **k)

    logging.disable(logging.CRITICAL)  # the injected failure is logged as an unhandled error; that is expected here
    try:
        with mock.patch.object(imp, "add_transaction", flaky):
            r = confirm(c, data)
    finally:
        logging.disable(logging.NOTSET)
    rolled_back = count(engine) == 0 and count(engine, ImportBatch) == 0
    retry = confirm(c, data)
    return {"status_during_failure": r.status_code, "rolled_back_completely": rolled_back, "retry_succeeds": retry.status_code == 201 and retry.json()["imported"] == 10}, {
        "passed": r.status_code == 500 and rolled_back and retry.status_code == 201}


def s_expected_sha_pin():
    c, _ = make_client()
    data = to_csv(good_rows(5, "P"))
    p = preview(c, data).json()
    tampered = confirm(c, data + b"2026-10-09,sale,1,x,,cash,,,,\n", expected_sha256=p["file_sha256"])
    ok = confirm(c, data, expected_sha256=p["file_sha256"])
    return {"tampered_file": tampered.status_code, "pinned_file": ok.status_code}, {"passed": tampered.status_code == 409 and ok.status_code == 201}


SCENARIOS = [("injected faults at known rows", s_injected_faults), ("clean file: totals equal the source", s_clean_file_totals),
             ("duplicates & re-imports", s_duplicates), ("formats & encodings", s_formats), ("column mapping", s_mapping),
             ("bad files fail gracefully (no 5xx)", s_bad_files), ("atomic commit under failure", s_atomic_commit), ("preview pinned to confirmed file", s_expected_sha_pin)]


def run_csv_eval() -> dict:
    results = []
    try:
        for name, fn in SCENARIOS:
            detail, verdict = fn()
            results.append({"scenario": name, "passed": bool(verdict["passed"]), "detail": detail})
    finally:
        app.dependency_overrides.clear()
    inj = next(r for r in results if r["scenario"].startswith("injected"))["detail"]
    tp, fp, fn = inj["detected"], len(inj["false_positives"]) + len(inj["tricky_false_positives"]), len(inj["missed"])
    return {"scenarios": results, "passed": sum(r["passed"] for r in results), "total": len(results),
            "row_detection": {"injected_faults": inj["injected"], "true_positives": tp, "false_negatives": fn, "false_positives": fp,
                              "precision": round(tp / (tp + fp), 4) if tp + fp else None, "recall": round(tp / (tp + fn), 4) if tp + fn else None,
                              "field_attribution_correct": f"{inj['field_correct']}/{tp}", "tricky_valid_rows_tested": inj["tricky_valid_rows"]}}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Arabic output on Windows consoles / redirected output
    from evaluation.run import RESULTS
    out = run_csv_eval()
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "csv.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"CSV import evaluation: {out['passed']}/{out['total']} scenarios passed")
    for r in out["scenarios"]:
        print(f"  {'PASS' if r['passed'] else 'FAIL'}  {r['scenario']}")
    print("  row detection:", json.dumps(out["row_detection"], ensure_ascii=False))
    for r in out["scenarios"]:
        if not r["passed"]:
            print("  detail:", r["scenario"], json.dumps(r["detail"], ensure_ascii=False, default=str)[:600])


if __name__ == "__main__":
    main()
