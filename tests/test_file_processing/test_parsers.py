"""Tests for file parsers."""

import json

import pytest

from mcp_toolkit.servers.file_processing.parsers import FileParser


@pytest.fixture
def parser():
    return FileParser()


class TestFileTypeDetection:
    def test_detect_pdf(self, parser):
        assert parser.detect_type("report.pdf") == "pdf"

    def test_detect_csv(self, parser):
        assert parser.detect_type("data.csv") == "csv"

    def test_detect_excel_xlsx(self, parser):
        assert parser.detect_type("sheet.xlsx") == "excel"

    def test_detect_excel_xls(self, parser):
        assert parser.detect_type("sheet.xls") == "excel"

    def test_detect_text(self, parser):
        assert parser.detect_type("readme.txt") == "text"

    def test_detect_json(self, parser):
        assert parser.detect_type("config.json") == "json"

    def test_detect_markdown(self, parser):
        assert parser.detect_type("notes.md") == "markdown"

    def test_detect_unknown(self, parser):
        assert parser.detect_type("image.png") == "unknown"

    def test_case_insensitive(self, parser):
        assert parser.detect_type("DATA.CSV") == "csv"


class TestCSVParser:
    async def test_parse_csv(self, parser):
        content = b"name,age,city\nAlice,30,NYC\nBob,25,LA"
        result = await parser.parse(content, "data.csv")
        assert result.is_success
        assert result.file_type == "csv"
        assert result.rows == 2
        assert "Alice" in result.text
        assert "Bob" in result.text

    async def test_csv_metadata(self, parser):
        content = b"col1,col2\n1,2"
        result = await parser.parse(content, "test.csv")
        assert result.metadata["headers"] == ["col1", "col2"]
        assert result.metadata["row_count"] == 1


class TestTextParser:
    async def test_parse_text(self, parser):
        content = b"Hello, World!\nLine 2\nLine 3"
        result = await parser.parse(content, "test.txt")
        assert result.is_success
        assert result.file_type == "text"
        assert "Hello, World!" in result.text
        assert result.metadata["line_count"] == 3

    async def test_parse_markdown(self, parser):
        content = b"# Title\n\nSome content here."
        result = await parser.parse(content, "readme.md")
        assert result.is_success
        assert result.file_type == "markdown"
        assert "Title" in result.text


class TestJSONParser:
    async def test_parse_json_object(self, parser):
        data = {"key": "value", "number": 42}
        content = json.dumps(data).encode()
        result = await parser.parse(content, "config.json")
        assert result.is_success
        assert result.file_type == "json"
        assert "key" in result.metadata.get("keys", [])

    async def test_parse_json_array(self, parser):
        data = [{"id": 1}, {"id": 2}]
        content = json.dumps(data).encode()
        result = await parser.parse(content, "list.json")
        assert result.is_success
        assert result.rows == 2

    async def test_parse_invalid_json(self, parser):
        content = b"not valid json{"
        result = await parser.parse(content, "bad.json")
        assert not result.is_success
        assert result.error is not None


class TestUnsupportedFile:
    async def test_unsupported_extension(self, parser):
        result = await parser.parse(b"binary data", "image.png")
        assert not result.is_success
        assert "Unsupported" in result.error
