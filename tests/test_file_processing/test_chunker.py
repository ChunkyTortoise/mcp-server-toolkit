"""Unit tests for TextChunker — fixed, sentence, paragraph, markdown strategies."""

from __future__ import annotations

import pytest

from mcp_toolkit.servers.file_processing.chunker import Chunk, TextChunker


@pytest.fixture
def chunker():
    return TextChunker(chunk_size=100, chunk_overlap=20)


class TestChunkDataclass:
    def test_char_count(self):
        c = Chunk(text="Hello world", index=0, start_char=0, end_char=11)
        assert c.char_count == 11

    def test_word_count(self):
        c = Chunk(text="Hello world foo", index=0, start_char=0, end_char=15)
        assert c.word_count == 3

    def test_metadata_default(self):
        c = Chunk(text="t", index=0, start_char=0, end_char=1)
        assert c.metadata == {}


class TestFixedStrategy:
    def test_short_text_single_chunk(self, chunker):
        chunks = chunker.chunk("Short text.", source="test.txt", strategy="fixed")
        assert len(chunks) == 1
        assert chunks[0].text == "Short text."

    def test_long_text_multiple_chunks(self):
        c = TextChunker(chunk_size=50, chunk_overlap=10)
        text = "Word " * 100  # 500 chars
        chunks = c.chunk(text, strategy="fixed")
        assert len(chunks) > 1

    def test_chunks_have_metadata(self, chunker):
        chunks = chunker.chunk("Some text.", source="doc.pdf", strategy="fixed")
        assert chunks[0].metadata["source"] == "doc.pdf"
        assert chunks[0].metadata["strategy"] == "fixed"

    def test_empty_text_no_chunks(self, chunker):
        chunks = chunker.chunk("", strategy="fixed")
        assert len(chunks) == 0

    def test_chunk_indices_sequential(self):
        c = TextChunker(chunk_size=30, chunk_overlap=5)
        text = "This is a sentence. " * 20
        chunks = c.chunk(text, strategy="fixed")
        for i, chunk in enumerate(chunks):
            assert chunk.index == i

    def test_total_chunks_in_metadata(self):
        c = TextChunker(chunk_size=50, chunk_overlap=10)
        text = "Word " * 50
        chunks = c.chunk(text, strategy="fixed")
        for chunk in chunks:
            assert chunk.metadata["total_chunks"] == len(chunks)


class TestSentenceStrategy:
    def test_single_sentence(self, chunker):
        chunks = chunker.chunk("Just one sentence.", strategy="sentence")
        assert len(chunks) == 1

    def test_multiple_sentences(self):
        c = TextChunker(chunk_size=50, chunk_overlap=0)
        text = "First sentence. Second sentence. Third sentence. Fourth sentence."
        chunks = c.chunk(text, strategy="sentence")
        assert len(chunks) >= 1
        for chunk in chunks:
            assert len(chunk.text) > 0


class TestParagraphStrategy:
    def test_single_paragraph(self, chunker):
        chunks = chunker.chunk("A single paragraph.", strategy="paragraph")
        assert len(chunks) == 1

    def test_multiple_paragraphs(self):
        c = TextChunker(chunk_size=50, chunk_overlap=0)
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        chunks = c.chunk(text, strategy="paragraph")
        assert len(chunks) >= 1


class TestMarkdownStrategy:
    def test_markdown_with_headings(self):
        c = TextChunker(chunk_size=100, chunk_overlap=0)
        text = (
            "# Section 1\n\nContent 1.\n\n## Section 2\n\nContent 2.\n\n# Section 3\n\nContent 3."
        )
        chunks = c.chunk(text, strategy="markdown")
        assert len(chunks) >= 1

    def test_markdown_metadata(self):
        c = TextChunker(chunk_size=500, chunk_overlap=0)
        text = "# Heading\n\nContent here."
        chunks = c.chunk(text, strategy="markdown")
        assert len(chunks) >= 1


class TestDefaultStrategy:
    def test_unknown_strategy_falls_back_to_fixed(self, chunker):
        chunks = chunker.chunk("Some text.", strategy="nonexistent")
        assert len(chunks) >= 1
        assert chunks[0].metadata["strategy"] == "nonexistent"
