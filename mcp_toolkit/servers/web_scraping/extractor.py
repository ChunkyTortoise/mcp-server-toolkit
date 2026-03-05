"""LLM-based structured data extraction from HTML content."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol


class LLMProvider(Protocol):
    """Protocol for LLM providers used in data extraction."""

    async def generate(self, prompt: str) -> str: ...


class DefaultLLMProvider:
    """Default LLM provider that returns empty JSON."""

    async def generate(self, prompt: str) -> str:
        return "{}"


@dataclass
class ExtractionResult:
    """Result of structured data extraction."""

    data: dict[str, Any] | list[dict[str, Any]]
    source_url: str = ""
    extraction_prompt: str = ""
    raw_response: str = ""
    success: bool = True
    error: str | None = None


class DataExtractor:
    """Extract structured data from text/HTML using an LLM.

    Supports two modes:
    1. Schema-based: Provide a JSON schema, LLM extracts matching data
    2. Free-form: Provide a description, LLM extracts relevant fields
    """

    def __init__(self, llm: LLMProvider | None = None) -> None:
        self._llm = llm or DefaultLLMProvider()

    def _build_schema_prompt(self, text: str, schema: dict[str, Any]) -> str:
        return (
            "Extract structured data from the following text according to the JSON schema.\n"
            "Return ONLY valid JSON matching the schema. No markdown, no explanation.\n\n"
            f"Schema:\n{json.dumps(schema, indent=2)}\n\n"
            f"Text:\n{text[:5000]}\n\n"
            "JSON:"
        )

    def _build_freeform_prompt(self, text: str, description: str) -> str:
        return (
            "Extract structured data from the following text.\n"
            f"What to extract: {description}\n"
            "Return ONLY valid JSON. No markdown, no explanation.\n\n"
            f"Text:\n{text[:5000]}\n\n"
            "JSON:"
        )

    async def extract_with_schema(
        self,
        text: str,
        schema: dict[str, Any],
        source_url: str = "",
    ) -> ExtractionResult:
        """Extract data matching a JSON schema from text."""
        prompt = self._build_schema_prompt(text, schema)
        try:
            raw = await self._llm.generate(prompt)
            data = json.loads(raw)
            return ExtractionResult(
                data=data,
                source_url=source_url,
                extraction_prompt=prompt,
                raw_response=raw,
            )
        except json.JSONDecodeError as e:
            return ExtractionResult(
                data={},
                source_url=source_url,
                extraction_prompt=prompt,
                raw_response=raw if "raw" in dir() else "",
                success=False,
                error=f"Invalid JSON from LLM: {e}",
            )
        except Exception as e:
            return ExtractionResult(
                data={},
                source_url=source_url,
                extraction_prompt=prompt,
                success=False,
                error=str(e),
            )

    async def extract_freeform(
        self,
        text: str,
        description: str,
        source_url: str = "",
    ) -> ExtractionResult:
        """Extract data from text based on a natural language description."""
        prompt = self._build_freeform_prompt(text, description)
        try:
            raw = await self._llm.generate(prompt)
            data = json.loads(raw)
            return ExtractionResult(
                data=data,
                source_url=source_url,
                extraction_prompt=prompt,
                raw_response=raw,
            )
        except json.JSONDecodeError as e:
            return ExtractionResult(
                data={},
                source_url=source_url,
                extraction_prompt=prompt,
                raw_response=raw if "raw" in dir() else "",
                success=False,
                error=f"Invalid JSON from LLM: {e}",
            )
        except Exception as e:
            return ExtractionResult(
                data={},
                source_url=source_url,
                extraction_prompt=prompt,
                success=False,
                error=str(e),
            )


class MockExtractorLLM:
    """Mock LLM for testing data extraction."""

    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self._responses = responses or {}
        self._default = '{"extracted": true}'
        self._calls: list[str] = []

    def add_response(self, keyword: str, json_response: str) -> None:
        self._responses[keyword.lower()] = json_response

    async def generate(self, prompt: str) -> str:
        self._calls.append(prompt)
        prompt_lower = prompt.lower()
        for keyword, response in self._responses.items():
            if keyword in prompt_lower:
                return response
        return self._default
