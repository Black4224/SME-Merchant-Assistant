"""Groq adapter (OpenAI-compatible chat completions with tool calling)."""
import groq

from app.ai.provider import LLMProvider, LLMResponse, ProviderError, ToolCall


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(self, api_key: str | None, model: str | None, *, timeout: float = 30.0, client=None):
        if not api_key or not model:
            raise ProviderError("not_configured")
        self.model = model
        self._client = client or groq.Groq(api_key=api_key, timeout=timeout, max_retries=1)

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0,
                max_tokens=900,
            )
            msg = resp.choices[0].message
        except groq.AuthenticationError:
            raise ProviderError("auth") from None
        except groq.PermissionDeniedError:
            raise ProviderError("auth") from None
        except groq.RateLimitError:
            raise ProviderError("rate_limit") from None
        except groq.APITimeoutError:
            raise ProviderError("timeout") from None
        except groq.APIConnectionError:
            raise ProviderError("connection") from None
        except (groq.BadRequestError, groq.UnprocessableEntityError, groq.NotFoundError):
            raise ProviderError("bad_request") from None
        except groq.InternalServerError:
            raise ProviderError("server") from None
        except (groq.GroqError, IndexError, AttributeError):
            raise ProviderError("unknown") from None
        calls = [
            ToolCall(id=tc.id, name=tc.function.name, arguments=tc.function.arguments or "{}")
            for tc in (msg.tool_calls or [])
        ]
        return LLMResponse(content=msg.content, tool_calls=calls)
