"""Tests for SchemaInspector SQL injection prevention."""

import pytest

from mcp_toolkit.servers.database_query.schema_inspector import (
    SchemaInspector,
    _validate_identifier,
)


class TestValidateIdentifier:
    def test_valid_identifiers(self):
        for name in ["users", "table_name", "_private", "Col1", "a123"]:
            _validate_identifier(name, "table_name")  # should not raise

    def test_sql_injection_raises(self):
        with pytest.raises(ValueError, match="Invalid table_name"):
            _validate_identifier("'; DROP TABLE users; --", "table_name")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="Invalid table_name"):
            _validate_identifier("", "table_name")

    def test_spaces_raise(self):
        with pytest.raises(ValueError, match="Invalid table_name"):
            _validate_identifier("my table", "table_name")

    def test_dash_raises(self):
        with pytest.raises(ValueError, match="Invalid table_name"):
            _validate_identifier("my-table", "table_name")

    def test_dot_raises(self):
        with pytest.raises(ValueError, match="Invalid table_schema"):
            _validate_identifier("public.users", "table_schema")

    def test_starts_with_number_raises(self):
        with pytest.raises(ValueError, match="Invalid table_name"):
            _validate_identifier("1table", "table_name")
