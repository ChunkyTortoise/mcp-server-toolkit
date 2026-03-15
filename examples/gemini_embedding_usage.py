"""Working example: Gemini Embedding server.

Demonstrates text embedding, vector indexing, semantic search, and
cosine similarity using the MockEmbeddingClient (no API key needed).
"""

import asyncio

from mcp_toolkit.framework.testing import MCPTestClient
from mcp_toolkit.servers.gemini_embedding.server import mcp, configure, MockEmbeddingClient
from mcp_toolkit.servers.gemini_embedding.vector_store import InMemoryVectorStore


async def main() -> None:
    # Reset to mock client and fresh store for demo
    configure(client=MockEmbeddingClient(), store=InMemoryVectorStore(), default_dimensions=64)

    client = MCPTestClient(mcp)

    # List available tools
    tools = await client.list_tools()
    print("Gemini Embedding tools:")
    for tool in tools:
        print(f"  - {tool['name']}: {tool.get('description', '')[:60]}")

    # Embed a single text
    print("\n--- embed_text ---")
    result = await client.call_tool("embed_text", {"text": "Python async patterns"})
    print(result)

    # Index several documents
    print("\n--- index_text ---")
    docs = [
        ("doc1", "Python async/await patterns for concurrent programming"),
        ("doc2", "JavaScript promises and event loop explained"),
        ("doc3", "Rust ownership model and memory safety guarantees"),
    ]
    for doc_id, text in docs:
        result = await client.call_tool(
            "index_text",
            {"text": text, "item_id": doc_id, "metadata": f'{{"language": "{text.split()[0].lower()}"}}'},
        )
        print(result)

    # Semantic search
    print("\n--- search ---")
    result = await client.call_tool("search", {"query": "async concurrency", "top_k": 2})
    print(result)

    # Compare similarity between two texts
    print("\n--- similarity ---")
    result = await client.call_tool(
        "similarity",
        {"text_a": "Python async programming", "text_b": "JavaScript promises"},
    )
    print(result)

    # List all indexed items
    print("\n--- list_indexed ---")
    result = await client.call_tool("list_indexed", {})
    print(result)

    # Clear the index
    print("\n--- clear_index ---")
    result = await client.call_tool("clear_index", {})
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
