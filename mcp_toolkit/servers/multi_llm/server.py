"""Multi-LLM MCP Server — query Gemini, OpenAI, and xAI/Grok as tools."""

from __future__ import annotations

import asyncio
import os

from mcp_toolkit.framework.base_server import EnhancedMCP
from mcp_toolkit.servers.multi_llm.models import LLMResponse, ProviderName
from mcp_toolkit.servers.multi_llm.providers import (
    GeminiProvider,
    LLMProvider,
    OpenAICompatibleProvider,
)
from mcp_toolkit.servers.multi_llm.router import BEST_PRIORITY, CHEAP_PRIORITY

mcp = EnhancedMCP("multi-llm")

_providers: dict[ProviderName, LLMProvider] = {}


def configure(providers: dict[ProviderName, LLMProvider] | None = None) -> None:
    global _providers
    if providers is not None:
        _providers = providers


def _get_provider(name: ProviderName) -> LLMProvider | None:
    return _providers.get(name)


def _format_response(resp: LLMResponse) -> str:
    return (
        f"**{resp.provider.value}** / {resp.model}\n"
        f"{resp.content}\n\n"
        f"---\n"
        f"tokens: {resp.input_tokens} in / {resp.output_tokens} out | "
        f"cost: ${resp.cost_usd:.6f} | latency: {resp.latency_ms:.0f}ms"
    )


@mcp.rate_limited_tool(max_calls=30, window_seconds=60)
async def query_model(
    provider: str,
    model: str,
    prompt: str,
    system_prompt: str = "",
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> str:
    """Query a specific LLM provider and model directly.

    Args:
        provider: Provider name: "gemini", "openai", or "xai".
        model: Model ID (e.g. "gemini-3.1-pro-preview", "gpt-5.4", "grok-4-0709").
        prompt: The user prompt.
        system_prompt: Optional system instructions.
        temperature: Sampling temperature 0.0–1.0.
        max_tokens: Maximum output tokens.
    """
    try:
        pname = ProviderName(provider)
    except ValueError:
        return f"Error: Unknown provider '{provider}'. Valid: gemini, openai, xai."

    p = _get_provider(pname)
    if p is None:
        return f"Error: Provider '{provider}' not configured (API key missing)."

    if p.circuit_breaker.is_open():
        return f"Error: Provider '{provider}' circuit breaker is open. Retry in 60s."

    if not prompt or not prompt.strip():
        return "Error: prompt cannot be empty."

    temperature = max(0.0, min(2.0, temperature))
    max_tokens = max(1, min(128_000, max_tokens))

    try:
        async with mcp.telemetry.span(
            f"provider.{provider}",
            attributes={"model": model, "provider": provider},
        ):
            resp = await p.query(
                prompt=prompt,
                model=model,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        return _format_response(resp)
    except Exception as e:
        return f"Error querying {provider}: {e}"


@mcp.rate_limited_tool(max_calls=10, window_seconds=60)
async def get_second_opinion(prompt: str, context: str = "") -> str:
    """Query all available providers in parallel and return a side-by-side comparison.

    Args:
        prompt: The question or prompt to send to all providers.
        context: Optional context passed as system prompt to each provider.
    """
    available = [
        (pn, p) for pn, p in _providers.items() if not p.circuit_breaker.is_open()
    ]

    if not available:
        return "Error: No providers available. Check API keys and circuit breaker status."

    async def _query_one(pn: ProviderName, p: LLMProvider) -> str:
        try:
            async with mcp.telemetry.span(
                f"provider.{pn.value}",
                attributes={"model": p.default_model, "provider": pn.value},
            ):
                resp = await p.query(
                    prompt=prompt,
                    model=p.default_model,
                    system_prompt=context,
                )
            return (
                f"### {pn.value.upper()}\n"
                f"{resp.content}\n\n"
                f"tokens: {resp.input_tokens}+{resp.output_tokens} | "
                f"cost: ${resp.cost_usd:.6f} | latency: {resp.latency_ms:.0f}ms"
            )
        except Exception as e:
            return f"### {pn.value.upper()}\nError: {e}"

    try:
        results = await asyncio.wait_for(
            asyncio.gather(*[_query_one(pn, p) for pn, p in available]),
            timeout=45.0,
        )
    except asyncio.TimeoutError:
        return "Error: Second opinion request timed out after 45s."

    return f"## Second Opinion: {prompt[:80]}\n\n" + "\n\n---\n\n".join(results)


@mcp.cached_tool(ttl=300)
async def query_cheap(prompt: str) -> str:
    """Route to cheapest available model (Gemini 3.1 Flash-Lite > GPT-5.4-nano > Grok-4.1 Fast).

    Args:
        prompt: The prompt to send to the cheapest available model.
    """
    for pn, model in CHEAP_PRIORITY:
        p = _providers.get(pn)
        if p is not None and not p.circuit_breaker.is_open():
            try:
                async with mcp.telemetry.span(
                    f"provider.{pn.value}",
                    attributes={"model": model, "provider": pn.value},
                ):
                    resp = await p.query(prompt=prompt, model=model)
                return _format_response(resp)
            except Exception:
                continue
    return "Error: No cheap providers available."


@mcp.rate_limited_tool(max_calls=15, window_seconds=60)
async def query_best(prompt: str) -> str:
    """Route to best available model (GPT-5.4 > Gemini 3.1 Pro > Grok-4).

    Args:
        prompt: The prompt to send to the best available model.
    """
    for pn, model in BEST_PRIORITY:
        p = _providers.get(pn)
        if p is not None and not p.circuit_breaker.is_open():
            try:
                async with mcp.telemetry.span(
                    f"provider.{pn.value}",
                    attributes={"model": model, "provider": pn.value},
                ):
                    resp = await p.query(prompt=prompt, model=model)
                return _format_response(resp)
            except Exception:
                continue
    return "Error: No premium providers available."


@mcp.tool()
async def list_providers() -> str:
    """List configured LLM providers with status and circuit breaker state."""
    if not _providers:
        return "No providers configured."
    lines = []
    for pn, p in _providers.items():
        cb = p.circuit_breaker
        cb_status = "OPEN" if cb.is_open() else "CLOSED"
        lines.append(
            f"- **{pn.value}** | model: {p.default_model} | "
            f"circuit: {cb_status} | failures: {cb._failures}"
        )
    return "\n".join(lines)


def main() -> None:
    providers: dict[ProviderName, LLMProvider] = {}

    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        providers[ProviderName.GEMINI] = GeminiProvider(
            api_key=gemini_key, default_model="gemini-3.1-pro-preview"
        )

    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        providers[ProviderName.OPENAI] = OpenAICompatibleProvider(
            api_key=openai_key,
            base_url="https://api.openai.com/v1",
            provider=ProviderName.OPENAI,
            default_model="gpt-5.4",
        )

    xai_key = os.environ.get("XAI_API_KEY")
    if xai_key:
        providers[ProviderName.XAI] = OpenAICompatibleProvider(
            api_key=xai_key,
            base_url="https://api.x.ai/v1",
            provider=ProviderName.XAI,
            default_model="grok-4-0709",
        )

    configure(providers=providers)
    mcp.run()


if __name__ == "__main__":
    main()
