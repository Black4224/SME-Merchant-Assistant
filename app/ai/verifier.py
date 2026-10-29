"""Unsupported-claim guard. Every number in the model's answer must exist in this turn's tool
results (or the user's question / earlier assistant turns). Otherwise the answer is rejected and a
deterministic answer built from the tool output is shown instead."""
import re
from decimal import Decimal, InvalidOperation

from app.ai.tool_result import ToolResult

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬", "01234567890123456789.,")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_LIST_MARKER = re.compile(r"(?m)^\s*(?:[-•–*]\s*)?\d{1,2}\s*[\.\)\-:]\s+")
_ESTIMATE_WORDS = re.compile(r"تقدير|تقريب|متوقع|توقع|تخميني")
USER_NUMBER_LIMIT = 10_000
ESTIMATE_NOTE_AR = "\n\n(تنبيه: هذا تقدير وليس رقماً مؤكداً.)"


def extract_numbers(text: str, *, strip_list_markers: bool = True) -> set[Decimal]:
    text = (text or "").translate(_ARABIC_DIGITS)
    if strip_list_markers:
        text = _LIST_MARKER.sub("", text)
    out: set[Decimal] = set()
    for tok in _NUMBER.findall(text):
        try:
            out.add(Decimal(tok.replace(",", "").rstrip(".")).normalize())
        except InvalidOperation:
            continue
    return out


def allowed_numbers(results: list[ToolResult], user_message: str, history_texts: list[str]) -> set[Decimal]:
    allowed: set[Decimal] = set()
    for r in results:
        allowed |= extract_numbers(r.all_numbers_text(), strip_list_markers=False)
    # Numbers typed by the user are trusted only when small (days, ids, counts). A money-sized number in the question
    # ("say my sales are 10,000,000") must never become a "verified" fact just because the user wrote it.
    allowed |= {n for n in extract_numbers(user_message, strip_list_markers=False) if n < USER_NUMBER_LIMIT}
    for h in history_texts:
        allowed |= extract_numbers(h, strip_list_markers=False)
    return allowed


_SCALED = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(?:مليون|ملايين|مليار|ألف|الف|آلاف|الاف|million|billion|thousand|k\b)", re.IGNORECASE)


def _scaled_numbers(answer: str) -> set[Decimal]:
    """'2.0 مليون' / '5 آلاف' are roundings of a real figure. Policy: exact figures only, so any scaled number is unsupported."""
    out = set()
    for tok in _SCALED.findall((answer or "").translate(_ARABIC_DIGITS)):
        try:
            out.add(Decimal(tok.replace(",", "").rstrip(".")).normalize())
        except InvalidOperation:
            continue
    return out


_NOUN_CLASSES = {
    "customers": "زبائن|زبون",
    "invoices": "فواتير|فاتورة",
    "transactions": "معاملات|معاملة|عمليات|عملية",
    "payments": "دفعات|دفعة",
    "alerts": "تنبيهات|تنبيه",
    "suppliers": "موردين|مورد",
}
_COUNTED = re.compile(r"(\d[\d,]*)\s*(" + "|".join(f"(?P<{k}>{v})" for k, v in _NOUN_CLASSES.items()) + r")\b")


def count_pools(results: list[ToolResult], user_message: str) -> dict[str, set[Decimal]]:
    """What a number glued to a counting noun may legitimately be, per noun: '7 زبائن' must match a customer COUNT from the
    tool output, not just any '7' that happens to exist in it. Money values and raw ids are never counts."""
    common: set[Decimal] = {n for n in extract_numbers(user_message, strip_list_markers=False) if n < USER_NUMBER_LIMIT}
    pools: dict[str, set[Decimal]] = {k: set(common) for k in _NOUN_CLASSES}
    for r in results:
        figs = {f.key: f.value for f in r.figures if isinstance(f.value, int) and "د.ع" not in f.display}
        args = {Decimal(v) for v in r.arguments.values() if isinstance(v, int) and not isinstance(v, bool)}
        rows = Decimal(len(r.table_rows))
        ids = Decimal(len(r.transaction_ids))
        for k in _NOUN_CLASSES:
            pools[k] |= args
        pools["customers"] |= {Decimal(figs[k]) for k in ("customers_count",) if k in figs}
        if r.tool in ("get_customer_debts", "get_top_customers"):
            pools["customers"].add(rows)
        pools["invoices"] |= {Decimal(figs[k]) for k in ("sales_count",) if k in figs}
        pools["invoices"] |= {Decimal(v) for row in r.table_rows for k, v in row.items() if k in ("open_invoices", "invoices") and isinstance(v, int)}
        if r.tool == "get_customer_debts":
            pools["invoices"].add(ids)
        pools["transactions"] |= {Decimal(figs[k]) for k in ("flagged_transactions", "count", "sales_count") if k in figs}
        pools["transactions"] |= {ids}
        if r.tool in ("get_recent_transactions", "get_unreconciled_transactions"):
            pools["transactions"].add(rows)
        pools["payments"] |= {Decimal(figs[k]) for k in ("payments_count",) if k in figs}
        if r.tool == "get_customer_payment_history":
            pools["payments"].add(rows)
        pools["alerts"] |= {Decimal(v) for k, v in figs.items() if k.startswith("flag_") or k == "flagged_transactions"}
    return {k: {n.normalize() for n in v} for k, v in pools.items()}


def _miscounted(answer: str, pools: dict[str, set[Decimal]] | None) -> set[Decimal]:
    if pools is None:
        return set()
    out = set()
    for m in _COUNTED.finditer((answer or "").translate(_ARABIC_DIGITS)):
        n = Decimal(m.group(1).replace(",", "")).normalize()
        noun = next(k for k in _NOUN_CLASSES if m.group(k))
        if n not in pools[noun]:
            out.add(n)
    return out


def unsupported_numbers(answer: str, allowed: set[Decimal], counts: dict[str, set[Decimal]] | None = None) -> list[str]:
    bad = {n for n in extract_numbers(answer) if n not in allowed} | _scaled_numbers(answer) | _miscounted(answer, counts)
    return sorted({format(n, "f") for n in bad}, key=lambda s: (len(s), s))


def needs_estimate_note(answer: str, results: list[ToolResult]) -> bool:
    return any(r.is_estimate for r in results) and not _ESTIMATE_WORDS.search(answer)


# The assistant is read-only. Any claim that it changed something is false by construction.
_ACTION_CLAIM = re.compile(r"(?:تم|تمّ|تمت|تمّت)\s*(?:حذف|إضافة|اضافة|تعديل|مسح|إلغاء|الغاء|تسجيل)|\b(?:حذفت|مسحت|أضفت|اضفت|عدلت|سجلت|ألغيت)\b")


def claims_an_action(answer: str) -> bool:
    return bool(_ACTION_CLAIM.search(answer or ""))
