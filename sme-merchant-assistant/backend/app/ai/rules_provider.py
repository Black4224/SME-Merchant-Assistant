"""Offline "rules mode": keyword intent matching in Iraqi Arabic -> the SAME allowlisted tools -> template wording.

It is NOT a language model and does not pretend to be one. Use it when no API key / no network is available (e.g. a demo),
and as a measurable baseline. Every number still comes from the deterministic tools and passes the same verifier.
Anything it does not recognise gets a polite "I can't answer that" instead of a guess.
"""
import json
import re
from datetime import date, timedelta

from app.ai.answer_templates import compose_answer
from app.ai.provider import LLMProvider, LLMResponse, ToolCall
from app.services.text import normalize_text

RULES_MODE_NOTE_AR = ("وضع القواعد (بدون ذكاء اصطناعي): يفهم أسئلة محددة بصيغ شائعة فقط، والأرقام تُحسب من بياناتك وتُتحقق بنفس الطريقة. "
                      "إن لم يفهم سؤالك سيخبرك بذلك. لفهم أوسع فعّل مفتاح الذكاء الاصطناعي.")
ASK_PERIOD = "أي فترة تقصد؟ اليوم، هذا الأسبوع، هذا الشهر، الشهر الماضي؟"
ASK_CUSTOMER = "أي زبون تقصد؟ اكتب اسمه."
ASK_COMPARE = "شنو تريد أقارن؟ مثلاً: مبيعات هذا الشهر بالشهر الماضي."
READ_ONLY = "أنا أقرأ بياناتك وأحسب منها فقط، وما أقدر أضيف أو أعدّل أو أحذف أي شي. للتعديل استخدم صفحة المعاملات."
UNKNOWN = ("ما فهمت سؤالك. أقدر أجاوب عن مبيعاتك ومصاريفك وربحك التقديري وديون الزبائن وتسديداتهم وأكثر الزبائن شراءً "
           "والمعاملات التي تحتاج مراجعة وتوقع النقد. جرّب مثلاً: «شكد مبيعاتي هذا الشهر؟» أو «منو بعده ما دايفعلي؟».")

_DIALECT = str.maketrans({"گ": "ك", "ڤ": "ف", "چ": "ج", "پ": "ب", "ة": "ه"})
_PUNCT = re.compile(r"[؟?!.,،:;«»\"'()\[\]{}]")
STOP = set("""شكد كم شنو منو متي هل من الي الى في عن مره لو او ما هو هي ان انا مني عندي لي بس مال اللي اللى كل
              اخر الاخيره قائمه اعرضلي اعطيني ممكن تعطيني دينار د.ع ع""".split())
INTENT_WORDS = set("""دفع دفعه دفعات دفعها دفعوا تسديد تسديدات دين ديون الدين الديون زبون زبائن الزبون الزبائن عليه عليهم عليها
                       مبيعات مبيعاتي مصاريف مصاريفي ربح ربحت ربحي بعت بعنا صرفت المتاخر المتاخرين المتاخره""".split())


def norm(text: str) -> str:
    t = normalize_text(text).translate(_DIALECT)
    return re.sub(r"\s+", " ", _PUNCT.sub(" ", t)).strip()


def _ref_date(messages: list[dict]) -> date:
    for m in messages:
        if m["role"] == "system":
            hit = re.search(r"TODAY is (\d{4}-\d{2}-\d{2})", m["content"])
            if hit:
                return date.fromisoformat(hit.group(1))
    return date.today()


def detect_period(t: str, ref: date) -> dict | None:
    """Returns tool arguments for a period, or None when the question names no period."""
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", t)
    if len(dates) >= 2:
        a, b = sorted(dates[:2])
        return {"start_date": a, "end_date": b}
    if len(dates) == 1:
        return {"start_date": dates[0], "end_date": dates[0]}
    year = re.search(r"سنه\s*(20\d{2})", t)
    if year:
        return {"start_date": f"{year.group(1)}-01-01", "end_date": f"{year.group(1)}-12-31"}
    n = re.search(r"اخر\s*(\d+)\s*(?:يوم|ايام)", t)
    if n:
        days = int(n.group(1))
        if days == 7:
            return {"period": "last_7_days"}
        if days == 30:
            return {"period": "last_30_days"}
        if 1 <= days <= 365:
            return {"start_date": (ref - timedelta(days=days - 1)).isoformat(), "end_date": ref.isoformat()}
    for pattern, name in [(r"اخر اسبوع", "last_7_days"), (r"اخر شهر", "last_30_days"),
                          (r"الاسبوع (?:الماضي|اللي فات|اللي مضي)", "last_week"), (r"الشهر (?:الماضي|اللي فات|اللي مضي)", "last_month"),
                          (r"(?:هذا|هالـ?)\s*الاسبوع|هالاسبوع|الاسبوع هذا", "this_week"), (r"هذا الشهر|هالشهر|الشهر هذا", "this_month"),
                          (r"\bامس\b|البارحه", "yesterday"), (r"اليوم", "today")]:
        if re.search(pattern, t):
            return {"period": name}
    return None


def _name_candidate(raw: str) -> str:
    """Whatever is left after removing question words and intent words is taken as a customer name."""
    text = re.sub(r"\bعلى\b", " ", raw)  # the preposition "على" must not be confused with the name "علي" after ى->ي normalisation
    tokens = [w for w in norm(text).split() if w not in STOP and w not in INTENT_WORDS and not w.isdigit()]
    return " ".join(tokens) if 0 < len(tokens) <= 4 else ""


def _has(t: str, *words: str) -> bool:
    return any(w in t for w in words)


def _tok(t: str, *words: str) -> bool:
    """Whole-word match, for short keywords that also occur inside other words (دين inside دينار, بيع inside مبيعات...)."""
    toks = set(t.split())
    return any(w in toks for w in words)


def _name_after_alaa(raw: str) -> str:
    """'شكد على علي الجبوري' / 'شكد عليه مطعم السلام' -> the name that FOLLOWS the preposition; '' if there is none."""
    m = re.search(r"(?:\bعلى|\bعليه)\s+(.+)$", raw.strip())
    if not m:
        return ""
    tokens = [w for w in norm(m.group(1)).split() if w not in STOP and w not in INTENT_WORDS and not w.isdigit()]
    return " ".join(tokens) if 0 < len(tokens) <= 4 else ""


class RulesProvider(LLMProvider):
    name = "rules"

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        last_user = max(i for i, m in enumerate(messages) if m["role"] == "user")
        after = messages[last_user + 1 :]
        tool_msgs = [m for m in after if m["role"] == "tool"]
        if tool_msgs:
            payload = json.loads(tool_msgs[-1]["content"])
            if "error" in payload:
                msg = payload["error"]
                if "غير واضح" in msg:
                    return LLMResponse(f"{msg} أي واحد تقصد؟", [])
                return LLMResponse(ASK_PERIOD if "الفترة" in msg else UNKNOWN, [])
            return LLMResponse(compose_answer(payload), [])
        return self._decide(messages[last_user]["content"], _ref_date(messages))

    # ------------------------------------------------------------------------------------------ intent rules
    def _decide(self, raw: str, ref: date) -> LLMResponse:
        t = norm(raw)
        period = detect_period(t, ref)

        def call(name: str, args: dict) -> LLMResponse:
            return LLMResponse(None, [ToolCall("r1", name, json.dumps(args, ensure_ascii=False))])

        def say(text: str) -> LLMResponse:
            return LLMResponse(text, [])

        def need_period(tool: str, extra: dict | None = None) -> LLMResponse:
            return call(tool, {**period, **(extra or {})}) if period else say(ASK_PERIOD)

        if re.search(r"(?:^| )(?:احذف|امسح|ضيف|اضف|عدل|سجل|ارسل|الغي)", t):
            return say(READ_ONLY)
        if _has(t, "توقع", "التدفق", "تدفق") or (_has(t, "النقد") and _has(t, "الجاي", "القادم", "راح")):
            days = re.search(r"(\d+)\s*يوم", t)
            h = int(days.group(1)) if days and 1 <= int(days.group(1)) <= 90 else 30
            return call("get_cashflow_projection", {} if h == 30 else {"horizon_days": h})
        if _has(t, "قارن", "الفرق بين", "احسن لو", "زادت", "نقصت", "مقابل"):
            cur = "this_week" if re.search(r"(?:هذا|هالـ?)\s*الاسبوع|الاسبوع هذا", t) else "this_month" if (re.search(r"هذا الشهر|هالشهر", t) or "الشهر" in t) else None
            return call("compare_periods", {"current_period": cur}) if cur else say(ASK_COMPARE)
        if _has(t, "مراجع", "مشبوه", "مكرر", "غير مطابق", "مطابق"):
            return call("get_unreconciled_transactions", {})
        recent = re.search(r"اخر\s*(\d+)?\s*(معاملات|معامله|حركات|مصاريف)", t)
        if recent or _has(t, "اخر المعاملات", "اخر الحركات"):
            kind = "expense" if recent and recent.group(2) == "مصاريف" else None
            n = int(recent.group(1)) if recent and recent.group(1) else 10
            return call("get_recent_transactions", {"limit": max(1, min(n, 20)), **({"type": kind} if kind else {})})
        if _has(t, "اكثر زبون", "احسن زبون", "افضل زبون", "اكبر زبون"):
            return call("get_top_customers", period or {"period": "last_30_days"})
        name = _name_candidate(raw)
        if re.search(r"\b(?:دفع|دفعه|دفعات|دفعها|دفعوا|تسديد|تسديدات)\b", t):
            return call("get_customer_payment_history", {"customer_name": name, **(period or {})}) if name else say(ASK_CUSTOMER)
        if _tok(t, "دين", "ديون", "مديون", "عليه", "عليهم") or _has(t, "دايفع", "مادفع", "بعده", "متاخر", "بذمه") or re.match(r"^(?:شكد|كم) على ", raw.strip()):
            args = {"only_overdue": True} if "متاخر" in t else {}
            who = _name_after_alaa(raw)
            if who:
                args["customer_name"] = who
            return call("get_customer_debts", args)
        if _tok(t, "ربح", "ربحت", "ربحي", "الربح", "الارباح") or _has(t, "كسبت", "مكسب", "ارباح"):
            return need_period("get_profit_summary")
        if _has(t, "صرفت", "مصاريف", "مصروف"):
            return need_period("get_expenses_summary")
        if _has(t, "مبيعات", "بعت", "بعنا") or _tok(t, "بيع"):
            return need_period("get_sales_summary")
        return say(UNKNOWN)
