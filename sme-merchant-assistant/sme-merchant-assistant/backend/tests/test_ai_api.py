import httpx
import groq
import pytest

from app.ai.groq_provider import GroqProvider
from app.ai.provider import LLMResponse, ProviderError, ToolCall
from app.api.assistant import get_llm_provider
from app.main import app
from tests.fakes import FakeProvider, call, text_turn, tools_turn


def use(provider):
    app.dependency_overrides[get_llm_provider] = lambda: provider


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.pop(get_llm_provider, None)


def chat(client, **body):
    return client.post("/api/assistant/chat", json={"message": "شكد مبيعاتي هذا الشهر؟", **body})


# ------------------------------------------------------------------ no key: clear message, nothing else breaks
def test_without_key_returns_clear_503_and_rest_of_app_works(seeded_client, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "groq_api_key", None)
    r = chat(seeded_client)
    assert r.status_code == 503 and r.json()["error"]["code"] == "ai_not_configured"
    assert ".env" in r.json()["error"]["message"] and "تعمل بشكل طبيعي" in r.json()["error"]["message"]
    st = seeded_client.get("/api/assistant/status").json()
    assert st["configured"] is False and "غير مضبوط" in st["message_ar"]
    for path in ("/api/dashboard/summary", "/api/transactions", "/api/reports/debts", "/api/health"):
        assert seeded_client.get(path).status_code == 200
    assert seeded_client.get("/api/settings").json()["ai"]["configured"] is False


def test_key_without_model_is_still_not_configured(seeded_client, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "groq_api_key", "k")
    monkeypatch.setattr(get_settings(), "groq_model", None)
    assert chat(seeded_client).status_code == 503


def test_provider_factory_builds_groq_only_when_configured(monkeypatch):
    from app.config import get_settings
    cfg = get_settings()
    monkeypatch.setattr(cfg, "groq_api_key", "test-key-not-real")
    monkeypatch.setattr(cfg, "groq_model", "some-model")
    assert isinstance(get_llm_provider(), GroqProvider)
    monkeypatch.setattr(cfg, "ai_provider", "gemini")          # unsupported provider => treated as not configured
    assert get_llm_provider() is None


# ------------------------------------------------------------------ chat endpoint with a scripted model
def test_chat_returns_answer_with_supporting_evidence(seeded_client):
    use(FakeProvider([tools_turn(call("get_customer_debts", {})), text_turn("عندك 7 زبائن عليهم دين، والمجموع 8,470,750 د.ع.")]))
    r = chat(seeded_client, message="منو بعده ما دايفعلي؟", history=[{"role": "user", "content": "هلا"}, {"role": "assistant", "content": "هلا بيك"}])
    assert r.status_code == 200
    b = r.json()
    assert b["status"] == "ok" and b["kind"] == "answer" and b["verified"] is True and b["tools_used"] == ["get_customer_debts"]
    ev = b["evidence"][0]
    assert ev["tool"] == "get_customer_debts" and len(ev["table"]["rows"]) == 7 and ev["transaction_ids"] and ev["basis_ar"]
    assert ev["figures"][1]["display"] == "8,470,750 د.ع" and ev["transactions"][0]["id"] in ev["transaction_ids"]


def test_chat_fallback_when_model_hallucinates(seeded_client):
    use(FakeProvider([tools_turn(call("get_customer_debts", {})), text_turn("عندك 3 زبائن عليهم 1,000,000 د.ع")]))
    b = chat(seeded_client, message="منو بعده ما دايفعلي؟").json()
    assert b["kind"] == "fallback" and b["unsupported_numbers"] and "8,470,750 د.ع" in b["answer_ar"]


def test_chat_clarification(seeded_client):
    use(FakeProvider([text_turn("تقصد أي فترة؟")]))
    b = chat(seeded_client, message="شكد بعت؟").json()
    assert b["kind"] == "clarification" and b["evidence"] == [] and b["tools_used"] == []


@pytest.mark.parametrize("kind,status,code", [("rate_limit", 502, "ai_rate_limit"), ("timeout", 502, "ai_timeout"), ("auth", 502, "ai_auth"),
                                             ("connection", 502, "ai_connection"), ("server", 502, "ai_server")])
def test_provider_failures_become_clear_502s(seeded_client, kind, status, code):
    use(FakeProvider([ProviderError(kind)]))
    r = chat(seeded_client)
    assert r.status_code == status and r.json()["error"]["code"] == code and r.json()["error"]["message"]
    assert "Traceback" not in r.text


def test_unexpected_crash_is_generic_500(api_engine):
    from tests.conftest import _make_client
    use(FakeProvider([RuntimeError("secret-key-abc123")]))
    c = _make_client(api_engine, raise_exceptions=False)
    r = chat(c)
    assert r.status_code == 500 and "secret" not in r.text and r.json()["error"]["code"] == "internal_error"


@pytest.mark.parametrize("body", [
    {"message": ""}, {"message": "   "}, {"message": "x" * 1001}, {"message": "hi", "history": [{"role": "system", "content": "x"}]},
    {"message": "hi", "history": [{"role": "user", "content": ""}]}, {"message": "hi", "history": [{"role": "user", "content": "x" * 2001}]},
    {"message": "hi", "history": [{"role": "user", "content": "a"}] * 21}, {"message": "hi", "extra": 1}, {"history": []}, {"message": 5},
])
def test_chat_input_validation(seeded_client, body):
    use(FakeProvider([text_turn("x")]))
    r = seeded_client.post("/api/assistant/chat", json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_chat_cannot_change_data(seeded_client):
    use(FakeProvider([tools_turn(call("delete_transaction", {"id": 1})), text_turn("ما أقدر أحذف. استخدم صفحة المعاملات.")]))
    b = chat(seeded_client, message="احذف المعاملة 1").json()
    assert b["evidence"] == [] and seeded_client.get("/api/transactions/1").status_code == 200


# ------------------------------------------------------------------ Groq adapter (no network)
def _req():
    return httpx.Request("POST", "https://api.groq.com/x")


def _resp(status):
    return httpx.Response(status, request=_req(), json={"error": {"message": "secret-details"}})


class _Msg:
    def __init__(self, content=None, tool_calls=None):
        self.content, self.tool_calls = content, tool_calls


class _Fn:
    def __init__(self, name, arguments):
        self.name, self.arguments = name, arguments


class _TC:
    def __init__(self, id, name, arguments):
        self.id, self.function = id, _Fn(name, arguments)


class _Client:
    def __init__(self, outcome):
        self.outcome, self.kwargs = outcome, None
        self.chat = type("C", (), {"completions": self})()

    def create(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return type("R", (), {"choices": [type("Ch", (), {"message": self.outcome})()]})()


def test_groq_adapter_translates_tool_calls_and_sends_deterministic_request():
    client = _Client(_Msg(None, [_TC("t1", "get_sales_summary", '{"period":"today"}'), _TC("t2", "get_customer_debts", None)]))
    out = GroqProvider("k", "m", client=client).chat([{"role": "user", "content": "x"}], [{"type": "function"}])
    assert out == LLMResponse(None, [ToolCall("t1", "get_sales_summary", '{"period":"today"}'), ToolCall("t2", "get_customer_debts", "{}")])
    assert client.kwargs["temperature"] == 0 and client.kwargs["model"] == "m" and client.kwargs["tool_choice"] == "auto"


def test_groq_adapter_plain_text():
    out = GroqProvider("k", "m", client=_Client(_Msg("أهلاً"))).chat([], [])
    assert out.content == "أهلاً" and out.tool_calls == []


@pytest.mark.parametrize("exc,kind", [
    (groq.AuthenticationError("x", response=_resp(401), body=None), "auth"),
    (groq.PermissionDeniedError("x", response=_resp(403), body=None), "auth"),
    (groq.RateLimitError("x", response=_resp(429), body=None), "rate_limit"),
    (groq.APITimeoutError(request=_req()), "timeout"),
    (groq.APIConnectionError(request=_req()), "connection"),
    (groq.BadRequestError("x", response=_resp(400), body=None), "bad_request"),
    (groq.InternalServerError("x", response=_resp(500), body=None), "server"),
])
def test_groq_errors_map_to_safe_kinds_without_leaking(exc, kind):
    with pytest.raises(ProviderError) as e:
        GroqProvider("sk-very-secret", "m", client=_Client(exc)).chat([], [])
    assert e.value.kind == kind and "secret" not in str(e.value) and "secret" not in repr(e.value.__cause__)


def test_groq_adapter_requires_key_and_model():
    for args in ((None, "m"), ("k", None), ("", "")):
        with pytest.raises(ProviderError) as e:
            GroqProvider(*args)
        assert e.value.kind == "not_configured"


# ------------------------------------------------------------------ opt-in graceful degradation to the offline rules mode
@pytest.mark.parametrize("kind", ["rate_limit", "timeout", "connection", "server"])
def test_transient_failure_falls_back_to_rules_only_when_enabled_and_says_so(seeded_client, monkeypatch, kind):
    from app.config import get_settings
    use(FakeProvider([ProviderError(kind)]))
    off = chat(seeded_client, message="منو بعده ما دايفعلي؟")
    assert off.status_code == 502 and off.json()["error"]["code"] == f"ai_{kind}"                       # default: explicit error
    monkeypatch.setattr(get_settings(), "ai_fallback_to_rules", True)
    use(FakeProvider([ProviderError(kind)]))
    on = chat(seeded_client, message="منو بعده ما دايفعلي؟")
    b = on.json()
    assert on.status_code == 200 and b["degraded"] is True and b["kind"] == "answer" and b["verified"] is True
    assert "بوضع القواعد" in b["warnings"][0] and "8,470,750 د.ع" in b["answer_ar"] and b["evidence"][0]["transaction_ids"]


@pytest.mark.parametrize("kind", ["auth", "bad_request", "unknown"])
def test_non_transient_failures_are_never_masked(seeded_client, monkeypatch, kind):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "ai_fallback_to_rules", True)
    use(FakeProvider([ProviderError(kind)]))
    assert chat(seeded_client).status_code == 502          # a bad key must be fixed, not hidden


def test_degraded_mode_still_declines_what_it_cannot_understand(seeded_client, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "ai_fallback_to_rules", True)
    use(FakeProvider([ProviderError("timeout")]))
    b = chat(seeded_client, message="منو رئيس وزراء العراق؟").json()
    assert b["degraded"] is True and b["evidence"] == [] and "ما فهمت" in b["answer_ar"]


def test_normal_replies_are_not_marked_degraded(seeded_client):
    use(FakeProvider([text_turn("تقصد أي فترة؟")]))
    assert chat(seeded_client, message="شكد بعت؟").json()["degraded"] is False


# ------------------------------------------------------------------ the shipped .env.example must be harmless if copied unchanged
@pytest.mark.parametrize("key,model", [("your_groq_api_key_here", "your_groq_model_name_here"), ("", ""), ("  ", "m"), ("k", ""), ("sk-real", "your_model_here")])
def test_placeholder_or_blank_values_count_as_not_configured(monkeypatch, key, model):
    from app.config import get_settings
    cfg = get_settings()
    monkeypatch.setattr(cfg, "ai_provider", "groq")
    monkeypatch.setattr(cfg, "groq_api_key", key)
    monkeypatch.setattr(cfg, "groq_model", model)
    assert cfg.ai_configured is False and get_llm_provider() is None


def test_real_looking_values_count_as_configured(monkeypatch):
    from app.config import get_settings
    cfg = get_settings()
    monkeypatch.setattr(cfg, "ai_provider", "groq")
    monkeypatch.setattr(cfg, "groq_api_key", "gsk_abc123")
    monkeypatch.setattr(cfg, "groq_model", "llama-3.3-70b-versatile")
    assert cfg.ai_configured is True


def test_env_example_loads_as_unconfigured(tmp_path):
    from pydantic_settings import SettingsConfigDict
    from app.config import PROJECT_ROOT, Settings
    class FromExample(Settings):
        model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env.example", extra="ignore")
    cfg = FromExample()
    assert cfg.ai_provider == "groq" and cfg.ai_configured is False and cfg.ai_fallback_to_rules is False
