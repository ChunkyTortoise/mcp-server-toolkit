"""A2A bridge client — exercises both streaming and non-streaming task submission.

Run against a live server:
    python examples/a2a_bridge/client.py

Or run end-to-end in a single process (no network):
    python examples/a2a_bridge/client.py --inline
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid

import httpx


BASE_URL = "http://localhost:8080"


async def fetch_agent_card(client: httpx.AsyncClient) -> dict:
    resp = await client.get(f"{BASE_URL}/.well-known/agent.json")
    resp.raise_for_status()
    return resp.json()


async def submit_task(client: httpx.AsyncClient, tool: str, arguments: dict) -> dict:
    """Submit a task and receive the final status synchronously."""
    payload = {"id": str(uuid.uuid4()), "tool": tool, "arguments": arguments}
    resp = await client.post(f"{BASE_URL}/tasks/send", json=payload)
    resp.raise_for_status()
    return resp.json()


async def stream_task(client: httpx.AsyncClient, tool: str, arguments: dict) -> None:
    """Submit a task and print each SSE event as it arrives."""
    payload = {"id": str(uuid.uuid4()), "tool": tool, "arguments": arguments}
    print(f"\n[SSE stream] tool={tool!r} args={arguments}")
    async with client.stream("POST", f"{BASE_URL}/tasks/sendSubscribe", json=payload) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            raw = line[len("data:"):].strip()
            if raw == "[DONE]":
                print("  → [stream complete]")
                break
            event = json.loads(raw)
            state = event.get("status", {}).get("state", "?")
            msg = event.get("status", {}).get("message", {})
            text = msg.get("parts", [{}])[0].get("text", "") if isinstance(msg, dict) else ""
            print(f"  → state={state!r}  message={text!r}")


async def inline_demo() -> None:
    """Run the demo without a live server (directly calls adapter)."""
    from mcp_toolkit import EnhancedMCP
    from mcp_toolkit.framework.a2a_adapter import A2AAdapter

    mcp_server = EnhancedMCP("inline-demo")

    @mcp_server.tool()
    async def echo(message: str) -> str:
        return f"Echo: {message}"

    adapter = A2AAdapter(mcp_server, base_url="http://localhost:8080")

    # Agent card
    card = await adapter.get_agent_card()
    print("=== Agent Card ===")
    print(json.dumps(card, indent=2))

    # Non-streaming task
    print("\n=== Non-streaming task ===")
    status = await adapter.handle_task(str(uuid.uuid4()), "echo", {"message": "hello world"})
    print(json.dumps(status.to_dict(), indent=2))

    # Streaming task
    print("\n=== Streaming task (SSE events) ===")
    async for chunk in adapter.stream_task(str(uuid.uuid4()), "echo", {"message": "streamed!"}):
        if chunk.startswith("data:"):
            raw = chunk[len("data:"):].strip()
            if raw == "[DONE]":
                print("  → [stream complete]")
            else:
                event = json.loads(raw)
                state = event.get("status", {}).get("state", "?")
                print(f"  → state={state!r}")


async def network_demo() -> None:
    """Run the demo against a live server at BASE_URL."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Agent card
        card = await fetch_agent_card(client)
        print("=== Agent Card ===")
        print(f"  name: {card['name']}")
        print(f"  streaming: {card['capabilities']['streaming']}")
        print(f"  pushNotifications: {card['capabilities']['pushNotifications']}")
        print(f"  skills: {[s['id'] for s in card['skills']]}")

        # 2. Non-streaming tasks
        print("\n=== Non-streaming tasks ===")
        for tool, args in [
            ("echo", {"message": "hello from A2A"}),
            ("reverse", {"text": "abcdef"}),
            ("word_count", {"text": "the quick brown fox"}),
        ]:
            result = await submit_task(client, tool, args)
            output = result.get("result", {}).get("output", "")
            print(f"  {tool}: {output!r}")

        # 3. Streaming task
        await stream_task(client, "echo", {"message": "streaming works!"})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inline", action="store_true", help="Run without a live server")
    args = parser.parse_args()

    if args.inline:
        asyncio.run(inline_demo())
    else:
        asyncio.run(network_demo())


if __name__ == "__main__":
    main()
