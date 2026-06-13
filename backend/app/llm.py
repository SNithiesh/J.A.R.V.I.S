"""
The brain, as a ROUTER rather than a single model.

Two ideas layered together (this is feedback item #7 made real):

1. TIER SELECTION (before the call): a cheap heuristic classifies the
   turn as "fast" (short conversational) or "smart" (code, planning,
   long input) and picks the model chain for that tier. Phase 5 can
   replace the heuristic with an LLM classifier; the interface
   doesn't change.

2. FAILOVER (during the call): each tier is a CHAIN of providers
   tried in order. A 429 or outage on a free model silently falls
   through to the next provider instead of surfacing an error.
   Ollama, when configured, is the always-available last resort —
   that is offline mode.

Everything speaks the OpenAI wire format, so OpenRouter, Ollama, and
any future provider are interchangeable entries in a chain.
"""
import re
from dataclasses import dataclass, field

from openai import AsyncOpenAI

from .config import settings


@dataclass(frozen=True)
class ModelSpec:
    label: str
    base_url: str
    api_key: str
    model: str


_clients: dict[str, AsyncOpenAI] = {}


def _client(spec: ModelSpec) -> AsyncOpenAI:
    key = f"{spec.base_url}|{spec.api_key[:8]}"
    if key not in _clients:
        _clients[key] = AsyncOpenAI(base_url=spec.base_url, api_key=spec.api_key or "none")
    return _clients[key]


def _spec_openrouter(model: str, label: str) -> ModelSpec:
    return ModelSpec(label, settings.openrouter_base_url, settings.openrouter_api_key, model)


def _spec_ollama() -> ModelSpec | None:
    if not settings.ollama_base_url:
        return None
    return ModelSpec("ollama", settings.ollama_base_url, "ollama", settings.ollama_model)


_SMART_HINTS = re.compile(
    r"\b(code|debug|refactor|plan|architect|analy[sz]e|design|implement|step.by.step|write a)\b",
    re.IGNORECASE,
)


def pick_tier(user_text: str, override: str | None = None) -> str:
    """Cheap, zero-cost routing heuristic. Override wins when a caller knows better."""
    if override in ("fast", "smart"):
        return override
    if len(user_text) > 600 or _SMART_HINTS.search(user_text) or "```" in user_text:
        return "smart"
    return "fast"


def chain_for(tier: str) -> list[ModelSpec]:
    chain: list[ModelSpec] = []
    if tier == "smart" and settings.model_smart != settings.model_fast:
        chain.append(_spec_openrouter(settings.model_smart, "smart"))
    chain.append(_spec_openrouter(settings.model_fast, "fast"))
    if (local := _spec_ollama()) is not None:
        chain.append(local)
    return chain


async def stream_with_failover(chain: list[ModelSpec], messages: list, tools: list):
    """
    Yields (spec, chunk) pairs from the first provider in the chain that
    answers. Failover happens only BEFORE the first chunk arrives — once a
    provider has started streaming, an interruption surfaces as an error
    rather than silently restarting the answer on a different model.
    """
    last_error: Exception | None = None
    for spec in chain:
        try:
            stream = await _client(spec).chat.completions.create(
                model=spec.model,
                max_tokens=settings.max_tokens,
                messages=messages,
                tools=tools or None,
                stream=True,
            )
            iterator = stream.__aiter__()
            first = await iterator.__anext__()        # provider is alive
        except StopAsyncIteration:
            return                                    # empty but successful stream
        except Exception as e:                        # 429, 5xx, timeout, connect
            last_error = e
            continue
        yield spec, first
        async for chunk in iterator:
            yield spec, chunk
        return
    raise RuntimeError(f"All model providers failed. Last error: {last_error}")


async def complete_with_failover(chain: list[ModelSpec], messages: list) -> str:
    """Plain completion with the same failover semantics — for background
    jobs like the memory distiller that don't need streaming or tools."""
    last_error: Exception | None = None
    for spec in chain:
        try:
            resp = await _client(spec).chat.completions.create(
                model=spec.model, max_tokens=512, messages=messages
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            last_error = e
    raise RuntimeError(f"All model providers failed. Last error: {last_error}")


async def call_with_failover(chain: list[ModelSpec], messages: list, tools: list):
    """Non-streaming, tool-capable single call — for background executors,
    where nobody is watching tokens arrive. Returns the response message."""
    last_error: Exception | None = None
    for spec in chain:
        try:
            resp = await _client(spec).chat.completions.create(
                model=spec.model,
                max_tokens=settings.max_tokens,
                messages=messages,
                tools=tools or None,
            )
            return resp.choices[0].message
        except Exception as e:
            last_error = e
    raise RuntimeError(f"All model providers failed. Last error: {last_error}")


# ---------- stream accumulation (pure, unit-tested) ----------
@dataclass
class Accumulated:
    content: str = ""
    tool_calls: dict[int, dict] = field(default_factory=dict)

    def ordered_tool_calls(self) -> list[dict]:
        return [self.tool_calls[i] for i in sorted(self.tool_calls)]


def apply_delta(acc: Accumulated, delta) -> str:
    """
    Merge one streamed delta into the accumulator. Returns any new visible
    text so the caller can forward it immediately. Tool-call arguments
    arrive as string fragments across many chunks; they are concatenated
    here and parsed only once the stream ends.
    """
    text = getattr(delta, "content", None) or ""
    acc.content += text
    for tc in getattr(delta, "tool_calls", None) or []:
        slot = acc.tool_calls.setdefault(
            tc.index, {"id": "", "name": "", "arguments": ""}
        )
        if getattr(tc, "id", None):
            slot["id"] = tc.id
        fn = getattr(tc, "function", None)
        if fn is not None:
            if getattr(fn, "name", None):
                slot["name"] = fn.name
            slot["arguments"] += getattr(fn, "arguments", None) or ""
    return text
