"""Tests for file processing MCP server."""

import base64
import json

import pytest

from mcp_toolkit.framework.testing import MCPTestClient
from mcp_toolkit.servers.file_processing.chunker import TextChunker
from mcp_toolkit.servers.file_processing.server import mcp as fp_mcp


@pytest.fixture
def client():
    return MCPTestClient(fp_mcp)


class TestProcessFileTool:
    async def test_process_csv(self, client):
        csv_data = b"name,score\nAlice,95\nBob,87"
        encoded = base64.b64encode(csv_data).decode()
        result = await client.call_tool(
            "process_file",
            {"file_content_base64": encoded, "filename": "scores.csv"},
        )
        assert "Alice" in result
        assert "csv" in result.lower()

    async def test_process_text(self, client):
        text_data = b"Hello, this is a test file.\nWith multiple lines."
        encoded = base64.b64encode(text_data).decode()
        result = await client.call_tool(
            "process_file",
            {"file_content_base64": encoded, "filename": "test.txt"},
        )
        assert "Hello" in result
        assert "text" in result.lower()

    async def test_process_json(self, client):
        json_data = json.dumps({"key": "value"}).encode()
        encoded = base64.b64encode(json_data).decode()
        result = await client.call_tool(
            "process_file",
            {"file_content_base64": encoded, "filename": "data.json"},
        )
        assert "key" in result

    async def test_process_invalid_base64(self, client):
        result = await client.call_tool(
            "process_file",
            {"file_content_base64": "not-valid-base64!!!", "filename": "test.txt"},
        )
        assert "Error" in result

    async def test_process_unsupported_type(self, client):
        encoded = base64.b64encode(b"binary").decode()
        result = await client.call_tool(
            "process_file",
            {"file_content_base64": encoded, "filename": "image.png"},
        )
        assert "Error" in result or "Unsupported" in result


class TestChunkTextTool:
    async def test_chunk_short_text(self, client):
        result = await client.call_tool(
            "chunk_text",
            {"text": "Short text.", "chunk_size": 100},
        )
        chunks = json.loads(result)
        assert len(chunks) == 1
        assert chunks[0]["text"] == "Short text."

    async def test_chunk_long_text(self, client):
        text = "Word " * 500  # ~2500 chars
        result = await client.call_tool(
            "chunk_text",
            {"text": text, "chunk_size": 500, "chunk_overlap": 50},
        )
        chunks = json.loads(result)
        assert len(chunks) > 1

    async def test_chunk_sentence_strategy(self, client):
        text = "First sentence. Second sentence. Third sentence. Fourth sentence."
        result = await client.call_tool(
            "chunk_text",
            {"text": text, "chunk_size": 50, "strategy": "sentence"},
        )
        chunks = json.loads(result)
        assert len(chunks) >= 1

    async def test_chunk_includes_metadata(self, client):
        result = await client.call_tool(
            "chunk_text",
            {"text": "Test content", "source": "test.txt"},
        )
        chunks = json.loads(result)
        assert chunks[0]["metadata"]["source"] == "test.txt"


class TestDetectFileTypeTool:
    async def test_detect_pdf(self, client):
        result = await client.call_tool("detect_file_type", {"filename": "report.pdf"})
        data = json.loads(result)
        assert data["file_type"] == "pdf"
        assert data["supported"] is True

    async def test_detect_unknown(self, client):
        result = await client.call_tool("detect_file_type", {"filename": "image.bmp"})
        data = json.loads(result)
        assert data["file_type"] == "unknown"
        assert data["supported"] is False


class TestTextChunker:
    def test_fixed_chunking(self):
        chunker = TextChunker(chunk_size=50, chunk_overlap=10)
        text = "A" * 120
        chunks = chunker.chunk(text, strategy="fixed")
        assert len(chunks) >= 2
        assert all(c.char_count <= 55 for c in chunks)  # slight variance ok

    def test_paragraph_chunking(self):
        text = "Para one content.\n\nPara two content.\n\nPara three content."
        chunker = TextChunker(chunk_size=30)
        chunks = chunker.chunk(text, strategy="paragraph")
        assert len(chunks) >= 2

    def test_markdown_chunking(self):
        text = (
            "# Section 1\nContent one.\n\n# Section 2\nContent two.\n\n# Section 3\nContent three."
        )
        chunker = TextChunker(chunk_size=40)
        chunks = chunker.chunk(text, strategy="markdown")
        assert len(chunks) >= 2

    def test_chunk_metadata(self):
        chunker = TextChunker(chunk_size=100)
        chunks = chunker.chunk("Hello world", source="test.md")
        assert chunks[0].metadata["source"] == "test.md"
        assert chunks[0].metadata["total_chunks"] == 1

    def test_empty_text(self):
        chunker = TextChunker()
        chunks = chunker.chunk("")
        assert len(chunks) == 0

    def test_chunk_word_count(self):
        chunker = TextChunker(chunk_size=1000)
        chunks = chunker.chunk("Hello beautiful world")
        assert chunks[0].word_count == 3


class TestToolListing:
    async def test_has_expected_tools(self, client):
        tools = await client.list_tools()
        names = {t["name"] for t in tools}
        assert "process_file" in names
        assert "chunk_text" in names
        assert "detect_file_type" in names
