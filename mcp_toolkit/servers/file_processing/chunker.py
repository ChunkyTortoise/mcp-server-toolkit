"""Smart text chunking for RAG ingestion."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Chunk:
    """A text chunk with metadata for RAG ingestion."""

    text: str
    index: int
    start_char: int
    end_char: int
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def word_count(self) -> int:
        return len(self.text.split())


class TextChunker:
    """Smart text chunker with configurable strategies.

    Supports:
    - Fixed-size chunking with overlap
    - Sentence-based chunking
    - Paragraph-based chunking
    - Semantic heading-based chunking (for markdown)
    """

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        strategy: str = "fixed",
    ) -> None:
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._strategy = strategy

    def chunk(
        self,
        text: str,
        source: str = "",
        strategy: str | None = None,
    ) -> list[Chunk]:
        """Split text into chunks using the configured strategy."""
        strat = strategy or self._strategy
        strategies = {
            "fixed": self._chunk_fixed,
            "sentence": self._chunk_sentence,
            "paragraph": self._chunk_paragraph,
            "markdown": self._chunk_markdown,
        }

        chunker = strategies.get(strat, self._chunk_fixed)
        chunks = chunker(text)

        for i, chunk in enumerate(chunks):
            chunk.index = i
            chunk.metadata["source"] = source
            chunk.metadata["strategy"] = strat
            chunk.metadata["total_chunks"] = len(chunks)

        return chunks

    def _chunk_fixed(self, text: str) -> list[Chunk]:
        """Fixed-size chunks with overlap."""
        chunks = []
        pos = 0
        while pos < len(text):
            end = min(pos + self._chunk_size, len(text))
            chunk_text = text[pos:end]

            if end < len(text):
                last_space = chunk_text.rfind(" ")
                if last_space > self._chunk_size * 0.5:
                    end = pos + last_space
                    chunk_text = text[pos:end]

            chunks.append(
                Chunk(
                    text=chunk_text.strip(),
                    index=len(chunks),
                    start_char=pos,
                    end_char=end,
                )
            )
            pos = end - self._chunk_overlap
            if pos <= chunks[-1].start_char:
                pos = end

        return [c for c in chunks if c.text]

    def _chunk_sentence(self, text: str) -> list[Chunk]:
        """Chunk by sentences, grouping to meet target size."""
        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks = []
        current_sentences: list[str] = []
        current_len = 0
        current_start = 0

        for sentence in sentences:
            if current_len + len(sentence) > self._chunk_size and current_sentences:
                chunk_text = " ".join(current_sentences)
                chunks.append(
                    Chunk(
                        text=chunk_text.strip(),
                        index=len(chunks),
                        start_char=current_start,
                        end_char=current_start + len(chunk_text),
                    )
                )
                overlap_text = (
                    " ".join(current_sentences[-2:]) if len(current_sentences) > 1 else ""
                )
                current_start += len(chunk_text) - len(overlap_text)
                current_sentences = current_sentences[-2:] if len(current_sentences) > 1 else []
                current_len = sum(len(s) for s in current_sentences)

            current_sentences.append(sentence)
            current_len += len(sentence)

        if current_sentences:
            chunk_text = " ".join(current_sentences)
            chunks.append(
                Chunk(
                    text=chunk_text.strip(),
                    index=len(chunks),
                    start_char=current_start,
                    end_char=current_start + len(chunk_text),
                )
            )

        return [c for c in chunks if c.text]

    def _chunk_paragraph(self, text: str) -> list[Chunk]:
        """Chunk by paragraphs (double newline), grouping to meet target size."""
        paragraphs = re.split(r"\n\s*\n", text)
        chunks = []
        current_paras: list[str] = []
        current_len = 0
        current_start = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            if current_len + len(para) > self._chunk_size and current_paras:
                chunk_text = "\n\n".join(current_paras)
                chunks.append(
                    Chunk(
                        text=chunk_text,
                        index=len(chunks),
                        start_char=current_start,
                        end_char=current_start + len(chunk_text),
                    )
                )
                current_start += len(chunk_text) + 2
                current_paras = []
                current_len = 0

            current_paras.append(para)
            current_len += len(para)

        if current_paras:
            chunk_text = "\n\n".join(current_paras)
            chunks.append(
                Chunk(
                    text=chunk_text,
                    index=len(chunks),
                    start_char=current_start,
                    end_char=current_start + len(chunk_text),
                )
            )

        return [c for c in chunks if c.text]

    def _chunk_markdown(self, text: str) -> list[Chunk]:
        """Chunk by markdown headings, preserving heading hierarchy."""
        sections = re.split(r"(?=^#{1,3}\s)", text, flags=re.MULTILINE)
        chunks = []
        current_sections: list[str] = []
        current_len = 0
        current_start = 0

        for section in sections:
            section = section.strip()
            if not section:
                continue

            if current_len + len(section) > self._chunk_size and current_sections:
                chunk_text = "\n\n".join(current_sections)
                chunks.append(
                    Chunk(
                        text=chunk_text,
                        index=len(chunks),
                        start_char=current_start,
                        end_char=current_start + len(chunk_text),
                        metadata={"has_heading": True},
                    )
                )
                current_start += len(chunk_text) + 2
                current_sections = []
                current_len = 0

            current_sections.append(section)
            current_len += len(section)

        if current_sections:
            chunk_text = "\n\n".join(current_sections)
            chunks.append(
                Chunk(
                    text=chunk_text,
                    index=len(chunks),
                    start_char=current_start,
                    end_char=current_start + len(chunk_text),
                    metadata={"has_heading": True},
                )
            )

        return [c for c in chunks if c.text]
