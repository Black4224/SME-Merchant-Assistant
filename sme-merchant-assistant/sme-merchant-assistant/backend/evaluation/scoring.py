"""Scoring helpers shared by the dataset-validation test and the evaluation harness."""
import json
from decimal import Decimal

from app.ai.verifier import extract_numbers
from app.services.text import normalize_text

# Evidence blocks carry money in `figures` and `table`; ids and dates live elsewhere and must not count as "numbers".
def evidence_blob(ev: dict) -> str:
    return json.dumps({"figures": [f["display"] for f in ev["figures"]], "table": ev["table"]["rows"]}, ensure_ascii=False, default=str)


def to_decimals(values) -> set[Decimal]:
    return {Decimal(str(v)).normalize() for v in values}


def numbers_present(expected, text: str) -> bool:
    return to_decimals(expected) <= extract_numbers(text, strip_list_markers=False)


def texts_present(expected, text: str) -> bool:
    n = normalize_text(text)
    return all(normalize_text(t) in n for t in expected)


def evidence_matches(alt: dict, ev: dict) -> list[str]:
    """Returns a list of mismatch descriptions (empty = this evidence satisfies the alternative's structure)."""
    bad = []
    if ev["tool"] != alt["tool"]:
        return [f"tool {ev['tool']} != {alt['tool']}"]
    for key, field in (("range", "date_range"), ("secondary_range", "secondary_range")):
        want = alt.get(key)
        if want:
            got = ev.get(field)
            if not got or (got["start"], got["end"]) != (want["start"], want["end"]):
                bad.append(f"{key} {got and (got['start'], got['end'])} != {(want['start'], want['end'])}")
    for group, ids in (alt.get("ids") or {}).items():
        if ev.get("ids_truncated"):
            continue
        if sorted(ev["id_groups"].get(group, [])) != sorted(ids):
            bad.append(f"ids[{group}] differ ({len(ev['id_groups'].get(group, []))} vs {len(ids)})")
    for group, ids in (alt.get("ids_include") or {}).items():
        if not set(ids) <= set(ev["id_groups"].get(group, [])):
            bad.append(f"ids_include[{group}] missing")
    if "has_data" in alt and ev["has_data"] != alt["has_data"]:
        bad.append(f"has_data {ev['has_data']} != {alt['has_data']}")
    if alt.get("evidence_kind") and ev["evidence_kind"] != alt["evidence_kind"]:
        bad.append("evidence_kind")
    if alt.get("estimate") and not ev["is_estimate"]:
        bad.append("not labelled estimate")
    blob = evidence_blob(ev)
    if not numbers_present(alt.get("numbers", []), blob):
        bad.append(f"numbers {alt.get('numbers')} not in evidence")
    if not texts_present(alt.get("texts", []), blob + " " + ev["title_ar"]):
        bad.append(f"texts {alt.get('texts')} not in evidence")
    return bad
