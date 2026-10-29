"""Controlled workflow: question -> model picks an allowlisted tool -> validated args ->
deterministic Python -> structured evidence -> model explains in Iraqi Arabic -> verifier checks
every number -> answer + evidence. Anything unsafe degrades to a deterministic answer."""
import json
import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.ai import tools
from app.ai.prompts import build_system_prompt
from app.ai.provider import LLMProvider
from app.ai.tool_result import ToolResult
from app.ai.verifier import ESTIMATE_NOTE_AR, allowed_numbers, claims_an_action, count_pools, needs_estimate_note, unsupported_numbers
from app.errors import AppError
from app.services.money import InvalidAmount
from app.services.periods import InvalidDateRange
from app.services.settings_service import get_reference_date, get_setting

log = logging.getLogger("sme.ai")

MAX_ROUNDS = 4
MAX_CALLS_PER_ROUND = 4
MAX_TOTAL_CALLS = 8
MAX_TOOL_ERRORS = 3
MAX_HISTORY_TURNS = 8

NO_RESULT_FALLBACK_AR = "ما كدرت أجاوب بأرقام مضمونة على هذا السؤال. جرّب تسأل بصيغة ثانية وحدّد الفترة (مثلاً: هذا الأسبوع أو هذا الشهر)."
READ_ONLY_TEXT_AR = "أنا أقرأ بياناتك وأحسب منها فقط، وما أقدر أضيف أو أعدّل أو أحذف أي شي. للتعديل استخدم صفحة المعاملات."
READ_ONLY_NOTE_AR = "حاول النموذج تنفيذ أو ادّعاء إجراء غير مسموح (المساعد للقراءة فقط)، فتم تجاهله."
UNVERIFIED_NOTE_AR = "تنبيه: الصياغة الذكية فيها رقم غير موجود في البيانات، فعرضت لك الأرقام الصحيحة مباشرة من النظام."


@dataclass
class AssistantReply:
    kind: str  # answer | clarification | message | fallback
    answer_ar: str
    evidence: list[ToolResult] = field(default_factory=list)
    verified: bool = True
    tools_used: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unsupported_numbers: list[str] = field(default_factory=list)
    tool_errors: list[str] = field(default_factory=list)
    rounds: int = 0
    degraded: bool = False

    def to_dict(self) -> dict:
        return {
            "status": "ok",
            "kind": self.kind,
            "answer_ar": self.answer_ar,
            "verified": self.verified,
            "tools_used": self.tools_used,
            "evidence": [r.to_ui_dict() for r in self.evidence],
            "warnings": self.warnings,
            "unsupported_numbers": self.unsupported_numbers,
            "degraded": self.degraded,
        }


def _run_tool(session: Session, name: str, raw_args: str) -> tuple[ToolResult | None, str]:
    """Returns (result, tool-message-content). Errors are returned to the model, never raised."""
    try:
        parsed = json.loads(raw_args or "{}")
        if not isinstance(parsed, dict):
            raise tools.ToolArgError("arguments must be a JSON object")
    except json.JSONDecodeError:
        return None, json.dumps({"error": "invalid JSON in tool arguments"}, ensure_ascii=False)
    except tools.ToolArgError as e:
        return None, json.dumps({"error": str(e)}, ensure_ascii=False)
    try:
        result = tools.execute(session, name, parsed)
    except (tools.ToolArgError, InvalidDateRange, InvalidAmount, AppError) as e:
        return None, json.dumps({"error": getattr(e, "message", None) or str(e)}, ensure_ascii=False)
    except Exception:  # noqa: BLE001 - never let a tool bug crash the chat
        log.exception("tool %s crashed", name)
        return None, json.dumps({"error": "internal tool error"}, ensure_ascii=False)
    return result, json.dumps(result.to_model_payload(), ensure_ascii=False, default=str)


def _fallback(results: list[ToolResult], reason_warning: str | None = None, **extra) -> AssistantReply:
    if results:
        text = "\n\n".join(r.render_plain() for r in results)
        warnings = [reason_warning] if reason_warning else []
        return AssistantReply("fallback", text, results, True, [r.tool for r in results], warnings, **extra)
    return AssistantReply("fallback", NO_RESULT_FALLBACK_AR, [], True, [], [reason_warning] if reason_warning else [], **extra)


def _finalize(text: str | None, results: list[ToolResult], user_message: str, history_texts: list[str],
              tool_errors: list[str], rounds: int, attempted_forbidden: bool = False) -> AssistantReply:
    text = (text or "").strip()
    used = [r.tool for r in results]
    if attempted_forbidden or claims_an_action(text):
        return AssistantReply("message", READ_ONLY_TEXT_AR, results, True, used, [READ_ONLY_NOTE_AR], [], tool_errors, rounds)
    if not text:
        return _fallback(results, tool_errors=tool_errors, rounds=rounds)
    bad = unsupported_numbers(text, allowed_numbers(results, user_message, history_texts), count_pools(results, user_message))
    if bad:
        return _fallback(results, UNVERIFIED_NOTE_AR, unsupported_numbers=bad, tool_errors=tool_errors, rounds=rounds)
    if needs_estimate_note(text, results):
        text += ESTIMATE_NOTE_AR
    if results:
        kind = "answer"
    else:
        kind = "clarification" if ("؟" in text or "?" in text) else "message"
    return AssistantReply(kind, text, results, True, used, [], [], tool_errors, rounds)


def answer_question(session: Session, provider: LLMProvider, message: str, history: list[dict] | None = None) -> AssistantReply:
    """Raises ProviderError if the model provider fails (the API layer turns that into a clear 502)."""
    history = [h for h in (history or []) if h.get("role") in ("user", "assistant") and h.get("content")][-MAX_HISTORY_TURNS:]
    messages: list[dict] = [{"role": "system", "content": build_system_prompt(get_reference_date(session), get_setting(session, "business_name"))}]
    messages += [{"role": h["role"], "content": h["content"]} for h in history]
    messages.append({"role": "user", "content": message})
    history_texts = [h["content"] for h in history if h["role"] == "assistant"]

    schemas = tools.tool_schemas()
    results: list[ToolResult] = []
    errors: list[str] = []
    total_calls = 0
    forbidden_attempt = False

    for round_no in range(MAX_ROUNDS + 1):
        resp = provider.chat(messages, schemas)
        if not resp.tool_calls:
            return _finalize(resp.content, results, message, history_texts, errors, round_no, forbidden_attempt)
        if round_no == MAX_ROUNDS:
            break
        messages.append({
            "role": "assistant", "content": resp.content or "",
            "tool_calls": [{"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}} for c in resp.tool_calls],
        })
        for idx, call in enumerate(resp.tool_calls):
            if idx >= MAX_CALLS_PER_ROUND or total_calls >= MAX_TOTAL_CALLS:
                content = json.dumps({"error": "too many tool calls; answer with what you have"}, ensure_ascii=False)
            else:
                total_calls += 1
                if call.name not in tools.REGISTRY:
                    forbidden_attempt = True  # e.g. delete_transaction / run_sql: the model tried to act, not just read
                result, content = _run_tool(session, call.name, call.arguments)
                if result is not None:
                    results.append(result)
                else:
                    errors.append(f"{call.name}: {json.loads(content)['error']}")
            messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
        if len(errors) >= MAX_TOOL_ERRORS and not results:
            return _fallback(results, tool_errors=errors, rounds=round_no + 1)
    return _fallback(results, tool_errors=errors, rounds=MAX_ROUNDS)
