"""Tests for data extraction module."""

import pytest

from mcp_toolkit.servers.web_scraping.extractor import (
    DataExtractor,
    MockExtractorLLM,
)


@pytest.fixture
def mock_llm():
    llm = MockExtractorLLM()
    llm.add_response(
        "product",
        '{"products": [{"name": "Widget", "price": 9.99}, {"name": "Gadget", "price": 19.99}]}',
    )
    llm.add_response("contact", '{"name": "John Doe", "email": "john@test.com"}')
    return llm


class TestDataExtractor:
    async def test_extract_with_schema(self, mock_llm):
        extractor = DataExtractor(llm=mock_llm)
        schema = {
            "type": "object",
            "properties": {
                "products": {
                    "type": "array",
                    "items": {"type": "object"},
                }
            },
        }
        result = await extractor.extract_with_schema(
            "Product list: Widget $9.99, Gadget $19.99",
            schema,
            source_url="https://shop.com",
        )
        assert result.success is True
        assert "products" in result.data
        assert len(result.data["products"]) == 2

    async def test_extract_freeform(self, mock_llm):
        extractor = DataExtractor(llm=mock_llm)
        result = await extractor.extract_freeform(
            "Contact: John Doe, john@test.com",
            "contact information",
        )
        assert result.success is True
        assert result.data.get("name") == "John Doe"

    async def test_extract_with_invalid_json_response(self):
        class BadLLM:
            async def generate(self, prompt: str) -> str:
                return "not valid json"

        extractor = DataExtractor(llm=BadLLM())
        result = await extractor.extract_freeform("some text", "anything")
        assert result.success is False
        assert "Invalid JSON" in result.error

    async def test_extract_sets_source_url(self, mock_llm):
        extractor = DataExtractor(llm=mock_llm)
        result = await extractor.extract_freeform(
            "Contact data", "contact info", source_url="https://test.com"
        )
        assert result.source_url == "https://test.com"

    async def test_default_llm_returns_empty(self):
        extractor = DataExtractor()
        result = await extractor.extract_freeform("data", "extract it")
        assert result.success is True
        assert result.data == {}


class TestMockExtractorLLM:
    async def test_returns_matching_response(self):
        llm = MockExtractorLLM()
        llm.add_response("hello", '{"greeting": "hi"}')
        response = await llm.generate("say hello")
        assert "greeting" in response

    async def test_returns_default(self):
        llm = MockExtractorLLM()
        response = await llm.generate("unknown")
        assert response == '{"extracted": true}'

    async def test_tracks_calls(self):
        llm = MockExtractorLLM()
        await llm.generate("p1")
        await llm.generate("p2")
        assert len(llm._calls) == 2
