"""File Processing MCP Server — PDF/CSV/Excel/TXT file processing and chunking."""

from __future__ import annotations

import base64
import json
from pathlib import Path

from mcp_toolkit.framework.base_server import EnhancedMCP
from mcp_toolkit.servers.file_processing.chunker import TextChunker
from mcp_toolkit.servers.file_processing.parsers import FileParser

mcp = EnhancedMCP("file-processing")

_parser = FileParser()
_chunker = TextChunker()


def configure(
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    default_strategy: str = "fixed",
) -> None:
    """Configure the file processing server."""
    global _chunker
    _chunker = TextChunker(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        strategy=default_strategy,
    )


@mcp.tool()
async def process_file(
    file_content_base64: str,
    filename: str,
) -> str:
    """Process a file and extract its text content.

    Args:
        file_content_base64: Base64-encoded file content.
        filename: Original filename (used for type detection, e.g., "report.pdf").

    Returns:
        Extracted text content with file metadata.
    """
    try:
        content = base64.b64decode(file_content_base64)
    except Exception as e:
        return f"Error decoding file: {e}"

    result = await _parser.parse(content, filename)

    if not result.is_success:
        return f"Error processing {filename}: {result.error}"

    parts = [
        f"**File:** {result.filename}",
        f"**Type:** {result.file_type}",
    ]

    if result.pages > 1:
        parts.append(f"**Pages:** {result.pages}")
    if result.rows > 0:
        parts.append(f"**Rows:** {result.rows}")

    if result.metadata:
        meta_str = json.dumps(result.metadata, indent=2, default=str)
        parts.append(f"**Metadata:**\n```json\n{meta_str}\n```")

    text_preview = result.text[:10000]
    parts.append(f"\n**Content:**\n{text_preview}")

    if len(result.text) > 10000:
        parts.append(f"\n*Content truncated. Total: {len(result.text)} chars.*")

    return "\n".join(parts)


@mcp.tool()
async def chunk_text(
    text: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    strategy: str = "fixed",
    source: str = "",
) -> str:
    """Split text into chunks for RAG ingestion.

    Args:
        text: The text to chunk.
        chunk_size: Target size of each chunk in characters (default 1000).
        chunk_overlap: Number of overlapping characters between chunks (default 200).
        strategy: Chunking strategy — "fixed", "sentence", "paragraph", or "markdown".
        source: Optional source identifier for chunk metadata.

    Returns:
        JSON array of chunks with text, index, and metadata.
    """
    chunker = TextChunker(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        strategy=strategy,
    )
    chunks = chunker.chunk(text, source=source, strategy=strategy)

    result = [
        {
            "index": c.index,
            "text": c.text,
            "char_count": c.char_count,
            "word_count": c.word_count,
            "metadata": c.metadata,
        }
        for c in chunks
    ]

    return json.dumps(result, indent=2)


@mcp.tool()
async def detect_file_type(filename: str) -> str:
    """Detect the file type from a filename.

    Args:
        filename: The filename to check (e.g., "report.pdf", "data.csv").

    Returns:
        Detected file type and whether it's supported.
    """
    file_type = _parser.detect_type(filename)
    supported = file_type != "unknown"
    return json.dumps(
        {
            "filename": filename,
            "file_type": file_type,
            "supported": supported,
            "extension": Path(filename).suffix.lower(),
        }
    )
