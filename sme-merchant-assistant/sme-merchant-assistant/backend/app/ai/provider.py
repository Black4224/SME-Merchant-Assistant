"""LLM provider abstraction. Messages use the OpenAI-style chat format, so adding Gemini or any
other provider means writing one adapter class with a single `chat()` method."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class ProviderError(Exception):
    """Provider call failed. `kind` is a stable, non-sensitive category (never contains keys/URLs)."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind  # not_configured | auth | rate_limit | timeout | connection | bad_request | server | unknown


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON text exactly as produced by the model (validated by the orchestrator)


@dataclass(frozen=True)
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMProvider(ABC):
    name: str = "unknown"

    @abstractmethod
    def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        """One model turn. Raises ProviderError on any failure."""


PROVIDER_ERROR_MESSAGES_AR = {
    "not_configured": "مفتاح الذكاء الاصطناعي غير مضبوط.",
    "auth": "مفتاح الذكاء الاصطناعي غير صالح أو منتهي.",
    "rate_limit": "تم تجاوز حد الطلبات لدى مزوّد الذكاء الاصطناعي. حاول بعد قليل.",
    "timeout": "استغرق مزوّد الذكاء الاصطناعي وقتاً طويلاً. حاول مرة ثانية.",
    "connection": "تعذّر الاتصال بمزوّد الذكاء الاصطناعي.",
    "bad_request": "رفض مزوّد الذكاء الاصطناعي الطلب.",
    "server": "حدث خطأ لدى مزوّد الذكاء الاصطناعي.",
    "unknown": "حدث خطأ غير متوقع في المساعد.",
}
