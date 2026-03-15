"""Gemini Embedding 2 MCP Server — semantic search and vector indexing."""

from mcp_toolkit.servers.gemini_embedding.server import mcp as gemini_embedding_server
from mcp_toolkit.servers.gemini_embedding.vector_store import InMemoryVectorStore

__all__ = ["gemini_embedding_server", "InMemoryVectorStore"]
