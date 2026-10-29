"""Deterministic Iraqi-Arabic wording for tool results. Uses ONLY values present in the tool payload,
so every number it writes passes the verifier. Used by the offline rules mode and by the evaluation baselines."""


def _fig(payload: dict, prefix: str, default: str = "") -> str:
    for f in payload.get("figures", []):
        if f["label"].startswith(prefix):
            return str(f["value"])
    return default


def _span(r: dict | None) -> str:
    if not r:
        return ""
    return f"بتاريخ {r['start']}" if r["start"] == r["end"] else f"من {r['start']} إلى {r['end']}"


def compose_answer(p: dict) -> str:
    """`p` is ToolResult.to_model_payload()."""
    if "error" in p:
        return "ما كدرت أنفذ هذا الطلب. وضّح سؤالك أكثر (الفترة أو اسم الزبون)."
    tool, span = p["tool"], _span(p.get("date_range"))
    if not p.get("has_data") and tool != "get_customer_debts":
        warn = f" {p['warnings'][0]}" if p.get("warnings") else ""
        return f"ما كو بيانات مسجلة لهذا السؤال{(' ' + span) if span else ''}.{warn}"

    if tool == "get_sales_summary":
        return (f"مبيعاتك {span} هي {_fig(p, 'إجمالي المبيعات')}، منها {_fig(p, 'مبيعات مقبوضة')} مقبوضة وقت البيع "
                f"و{_fig(p, 'مبيعات آجلة')} آجلة (لم تُقبض بعد)، من {_fig(p, 'عدد فواتير')} فاتورة.")
    if tool == "get_profit_summary":
        return (f"الربح التقديري {span} هو {_fig(p, 'الربح التقديري')} (هذا تقدير). المبيعات {_fig(p, 'المبيعات')} "
                f"ومشتريات البضاعة {_fig(p, 'مشتريات البضاعة')} والمصاريف التشغيلية {_fig(p, 'المصاريف التشغيلية')}. "
                f"صافي النقد {_fig(p, 'صافي النقد')}.")
    if tool == "get_expenses_summary":
        return (f"مصاريفك التشغيلية {span} هي {_fig(p, 'المصاريف التشغيلية')}، ومشتريات البضاعة {_fig(p, 'مشتريات البضاعة')}، "
                f"والمدفوع للموردين {_fig(p, 'المدفوع للموردين')}.")
    if tool == "get_customer_debts":
        n = _fig(p, "عدد الزبائن")
        if n in ("", "0"):
            return "ما كو زبائن عليهم دين بهذا الطلب."
        top = "، ".join(f"{r['customer']} ({r['outstanding']})" for r in p.get("rows", [])[:3])
        return (f"عندك {n} زبائن عليهم دين، والمجموع {_fig(p, 'إجمالي الديون')}، منها متأخر {_fig(p, 'منها متأخر')}. "
                f"الأكبر: {top}.")
    if tool == "get_customer_payment_history":
        last = _fig(p, "تاريخ آخر دفعة")
        return (f"{p['title']}: مجموع التسديدات {_fig(p, 'مجموع التسديدات')} على {_fig(p, 'عدد الدفعات')} دفعات، آخر دفعة بتاريخ {last}. "
                f"الدين الحالي على الزبون {_fig(p, 'الدين الحالي')}.")
    if tool == "get_top_customers":
        r = p["rows"][0]
        return f"أكثر زبون اشترى {span} هو {r['customer']} بمجموع {r['total']} على {r['invoices']} فواتير."
    if tool == "compare_periods":
        return (f"مبيعاتك {span} هي {_fig(p, 'المبيعات (الحالية)')} مقابل {_fig(p, 'المبيعات (السابقة)')} للفترة {_span(p.get('compared_with'))}. "
                f"الفرق {_fig(p, 'التغير في المبيعات')} ({_fig(p, 'نسبة التغير في المبيعات')}). "
                f"الربح التقديري (تقدير) {_fig(p, 'الربح التقديري (الحالية)')} مقابل {_fig(p, 'الربح التقديري (السابقة)')}.")
    if tool == "get_unreconciled_transactions":
        kinds = "، ".join(f"{f['label']}: {f['value']}" for f in p["figures"][1:])
        return f"عندك {_fig(p, 'عدد المعاملات')} معاملات تحتاج مراجعة. {kinds}. هذه تنبيهات للمراجعة وليست حكماً نهائياً."
    if tool == "get_recent_transactions":
        lines = "؛ ".join(f"#{r['id']} {r['date']} {r['type']} {r['amount']}" for r in p["rows"][:10])
        return f"آخر {len(p['rows'])} معاملات: {lines}."
    if tool == "get_cashflow_projection":
        return (f"تقدير التغير في النقد خلال الفترة القادمة هو {_fig(p, 'التغير المتوقع')} (المدى من {_fig(p, 'الحد الأدنى')} إلى {_fig(p, 'الحد الأعلى')}). "
                f"هذا تقدير مبني على نشاط الأسابيع الماضية وليس ضماناً.")
    return "\n".join(f"{f['label']}: {f['value']}" for f in p.get("figures", []))
