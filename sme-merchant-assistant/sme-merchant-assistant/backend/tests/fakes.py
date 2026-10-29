"""A scripted stand-in for the LLM so every orchestration path is testable offline."""
import json

from app.ai.provider import LLMProvider, LLMResponse, ProviderError, ToolCall


def call(name: str, args: dict | str | None = None, cid: str = "c1") -> ToolCall:
    raw = args if isinstance(args, str) else json.dumps(args or {})
    return ToolCall(id=cid, name=name, arguments=raw)


def tools_turn(*calls: ToolCall) -> LLMResponse:
    return LLMResponse(content=None, tool_calls=list(calls))


def text_turn(text: str | None) -> LLMResponse:
    return LLMResponse(content=text, tool_calls=[])


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[list[dict]] = []

    def chat(self, messages, tools):
        self.calls.append([dict(m) for m in messages])
        if not self.script:
            raise AssertionError("fake provider script exhausted")
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step(messages) if callable(step) else step


class AlwaysCalls(LLMProvider):
    """A model that never stops calling tools."""
    name = "loop"

    def __init__(self):
        self.n = 0

    def chat(self, messages, tools):
        self.n += 1
        return tools_turn(call("get_sales_summary", {"period": "today"}, cid=f"c{self.n}"))
