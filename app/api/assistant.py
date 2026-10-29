from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.ai import orchestrator
from app.ai.groq_provider import GroqProvider
from app.ai.provider import PROVIDER_ERROR_MESSAGES_AR, LLMProvider, ProviderError
from app.ai.rules_provider import RULES_MODE_NOTE_AR, RulesProvider
from app.config import get_settings
from app.database import get_session
from app.errors import BadGateway, ServiceUnavailable

router = APIRouter(prefix="/api/assistant", tags=["assistant"])
TRANSIENT_KINDS = {"rate_limit", "timeout", "connection", "server"}
DEGRADED_NOTE_AR = "تعذّر الاتصال بمزوّد الذكاء الاصطناعي مؤقتاً، لذلك أُجيب بوضع القواعد (بدون ذكاء اصطناعي). الأرقام نفسها محسوبة من بياناتك."


class HistoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class ChatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(max_length=1000)
    history: list[HistoryItem] = Field(default_factory=list, max_length=20)

    @field_validator("message")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("السؤال فارغ")
        return v


def get_llm_provider() -> LLMProvider | None:
    """None when no key is configured. Overridden in tests with a scripted fake."""
    cfg = get_settings()
    if cfg.ai_provider == "rules":
        return RulesProvider()
    if cfg.ai_provider == "groq" and cfg.ai_configured:
        return GroqProvider(cfg.groq_api_key, cfg.groq_model)
    return None


@router.get("/status")
def status(provider: LLMProvider | None = Depends(get_llm_provider)):
    cfg = get_settings()
    if cfg.ai_provider == "rules":
        return {"provider": "rules", "configured": True, "message_ar": RULES_MODE_NOTE_AR}
    return {"provider": cfg.ai_provider, "configured": provider is not None,
            "message_ar": None if provider else PROVIDER_ERROR_MESSAGES_AR["not_configured"] + " أضف المفتاح في ملف .env ثم أعد تشغيل الخادم. باقي ميزات النظام تعمل بشكل طبيعي."}


@router.post("/chat")
def chat(body: ChatIn, session: Session = Depends(get_session), provider: LLMProvider | None = Depends(get_llm_provider)):
    if provider is None:
        raise ServiceUnavailable(
            "المساعد الذكي غير مفعّل لأن مفتاح الذكاء الاصطناعي غير مضبوط. أضفه في ملف .env. باقي الصفحات (لوحة التحكم، المعاملات، التقارير) تعمل بشكل طبيعي.",
            code="ai_not_configured",
        )
    history = [h.model_dump() for h in body.history]
    try:
        reply = orchestrator.answer_question(session, provider, body.message, history)
    except ProviderError as e:
        if get_settings().ai_fallback_to_rules and e.kind in TRANSIENT_KINDS and not isinstance(provider, RulesProvider):
            reply = orchestrator.answer_question(session, RulesProvider(), body.message, history)
            reply.degraded = True
            reply.warnings = [DEGRADED_NOTE_AR, *reply.warnings]
            return reply.to_dict()
        raise BadGateway(PROVIDER_ERROR_MESSAGES_AR.get(e.kind, PROVIDER_ERROR_MESSAGES_AR["unknown"]), code=f"ai_{e.kind}") from None
    return reply.to_dict()
