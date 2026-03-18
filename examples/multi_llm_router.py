"""Multi-LLM Router Server — basic usage example.

This example shows how to configure the multi_llm server with multiple providers
and use the routing tools: query_cheap, query_best, get_second_opinion.

Set at least one of these environment variables before running:
  GEMINI_API_KEY, OPENAI_API_KEY, XAI_API_KEY
"""

import asyncio
import os

from mcp_toolkit.framework.testing import MCPTestClient
from mcp_toolkit.servers.multi_llm import multi_llm_server
from mcp_toolkit.servers.multi_llm.models import ProviderName
from mcp_toolkit.servers.multi_llm.providers import GeminiProvider, OpenAICompatibleProvider
from mcp_toolkit.servers.multi_llm.server import configure


def build_providers() -> dict:
    providers = {}

    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        providers[ProviderName.GEMINI] = GeminiProvider(
            api_key=gemini_key, default_model="gemini-3.1-pro-preview"
        )
        print("Gemini provider configured.")

    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        providers[ProviderName.OPENAI] = OpenAICompatibleProvider(
            api_key=openai_key,
            base_url="https://api.openai.com/v1",
            provider=ProviderName.OPENAI,
            default_model="gpt-5.4",
        )
        print("OpenAI provider configured.")

    xai_key = os.environ.get("XAI_API_KEY")
    if xai_key:
        providers[ProviderName.XAI] = OpenAICompatibleProvider(
            api_key=xai_key,
            base_url="https://api.x.ai/v1",
            provider=ProviderName.XAI,
            default_model="grok-4-0709",
        )
        print("xAI/Grok provider configured.")

    return providers


async def main() -> None:
    providers = build_providers()
    if not providers:
        print("No API keys found. Set GEMINI_API_KEY, OPENAI_API_KEY, or XAI_API_KEY.")
        return

    configure(providers=providers)

    client = MCPTestClient(multi_llm_server)

    # List available providers and their circuit-breaker states
    provider_list = await client.call_tool("list_providers", {})
    print("\nConfigured providers:")
    print(provider_list)

    # Route to the cheapest available model
    cheap_result = await client.call_tool("query_cheap", {"prompt": "What is 2 + 2?"})
    print("\n--- query_cheap ---")
    print(cheap_result)

    # Route to the best available model
    best_result = await client.call_tool("query_best", {"prompt": "Explain async/await in one sentence."})
    print("\n--- query_best ---")
    print(best_result)

    # Query all providers in parallel and compare
    opinion_result = await client.call_tool(
        "get_second_opinion",
        {"prompt": "What is the capital of France?"},
    )
    print("\n--- get_second_opinion ---")
    print(opinion_result)


if __name__ == "__main__":
    asyncio.run(main())
