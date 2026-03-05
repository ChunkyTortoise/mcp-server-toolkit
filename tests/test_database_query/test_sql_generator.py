"""Tests for SQL generator and validation."""

import pytest

from mcp_toolkit.servers.database_query.schema_inspector import (
    ColumnInfo,
    DatabaseSchema,
    SchemaInspector,
    TableInfo,
)
from mcp_toolkit.servers.database_query.sql_generator import (
    MockLLMProvider,
    SQLGenerator,
)


@pytest.fixture
def sample_schema():
    return DatabaseSchema(
        tables=[
            TableInfo(
                name="users",
                schema="public",
                columns=[
                    ColumnInfo(name="id", data_type="integer", is_primary_key=True),
                    ColumnInfo(name="name", data_type="varchar"),
                    ColumnInfo(name="email", data_type="varchar"),
                ],
                row_count_estimate=1000,
            ),
            TableInfo(
                name="orders",
                schema="public",
                columns=[
                    ColumnInfo(name="id", data_type="integer", is_primary_key=True),
                    ColumnInfo(name="user_id", data_type="integer"),
                    ColumnInfo(name="total", data_type="numeric"),
                ],
            ),
        ]
    )


@pytest.fixture
def mock_llm():
    llm = MockLLMProvider()
    llm.add_response("users", "SELECT COUNT(*) FROM users")
    llm.add_response("orders", "SELECT user_id, SUM(total) FROM orders GROUP BY user_id")
    return llm


class TestSQLGenerator:
    async def test_generate_sql(self, mock_llm, sample_schema):
        gen = SQLGenerator(llm=mock_llm)
        sql = await gen.generate("How many users?", sample_schema)
        assert "SELECT" in sql.upper()
        assert mock_llm.call_count == 1

    async def test_validate_select(self):
        gen = SQLGenerator()
        is_valid, result = gen.validate("SELECT * FROM users")
        assert is_valid is True

    async def test_validate_rejects_insert(self):
        gen = SQLGenerator()
        is_valid, _ = gen.validate("INSERT INTO users VALUES (1, 'a', 'b')")
        assert is_valid is False

    async def test_validate_rejects_delete(self):
        gen = SQLGenerator()
        is_valid, _ = gen.validate("DELETE FROM users")
        assert is_valid is False

    async def test_validate_rejects_drop(self):
        gen = SQLGenerator()
        is_valid, _ = gen.validate("DROP TABLE users")
        assert is_valid is False

    async def test_validate_allows_with_cte(self):
        gen = SQLGenerator()
        is_valid, _ = gen.validate("WITH cte AS (SELECT 1) SELECT * FROM cte")
        assert is_valid is True

    async def test_generate_and_validate(self, mock_llm, sample_schema):
        gen = SQLGenerator(llm=mock_llm)
        sql, is_valid, result = await gen.generate_and_validate("How many users?", sample_schema)
        assert is_valid is True
        assert "SELECT" in result.upper()

    def test_clean_sql_strips_markdown(self):
        raw = "```sql\nSELECT 1;\n```"
        cleaned = SQLGenerator.clean_sql(raw)
        assert cleaned == "SELECT 1"

    def test_clean_sql_removes_trailing_semicolon(self):
        assert SQLGenerator.clean_sql("SELECT 1;") == "SELECT 1"

    def test_build_prompt_includes_schema(self, sample_schema):
        gen = SQLGenerator()
        prompt = gen.build_prompt("How many users?", sample_schema)
        assert "users" in prompt
        assert "orders" in prompt
        assert "How many users?" in prompt


class TestSchemaInspector:
    async def test_inspect_returns_schema(self, mock_db):
        inspector = SchemaInspector()
        schema = await inspector.inspect(mock_db)
        assert len(schema.tables) == 2
        table_names = {t.name for t in schema.tables}
        assert "users" in table_names
        assert "orders" in table_names

    async def test_inspect_caches_result(self, mock_db):
        inspector = SchemaInspector()
        schema1 = await inspector.inspect(mock_db)
        cached = inspector.get_cached_schema()
        assert cached is schema1

    def test_from_ddl(self):
        ddl = [
            "CREATE TABLE public.users (\n  id integer PRIMARY KEY,\n  name varchar NOT NULL\n);"
        ]
        schema = SchemaInspector.from_ddl(ddl)
        assert len(schema.tables) == 1
        assert schema.tables[0].name == "users"
        assert len(schema.tables[0].columns) == 2

    def test_table_to_ddl(self):
        table = TableInfo(
            name="test",
            columns=[
                ColumnInfo(name="id", data_type="integer", is_primary_key=True),
                ColumnInfo(name="name", data_type="varchar", is_nullable=False),
            ],
        )
        ddl = table.to_ddl()
        assert "CREATE TABLE" in ddl
        assert "id integer PRIMARY KEY" in ddl
        assert "NOT NULL" in ddl

    def test_schema_to_context(self, sample_schema):
        context = sample_schema.to_context()
        assert "users" in context
        assert "orders" in context
        assert "Database schema" in context

    async def test_inspect_no_connection_raises(self):
        inspector = SchemaInspector()
        with pytest.raises(ValueError, match="No database connection"):
            await inspector.inspect()


class TestMockLLMProvider:
    async def test_returns_matching_response(self):
        llm = MockLLMProvider()
        llm.add_response("users", "SELECT * FROM users")
        result = await llm.generate("Get all users")
        assert result == "SELECT * FROM users"

    async def test_returns_default_for_unknown(self):
        llm = MockLLMProvider()
        result = await llm.generate("something unknown")
        assert result == "SELECT 1"

    async def test_tracks_call_count(self):
        llm = MockLLMProvider()
        await llm.generate("q1")
        await llm.generate("q2")
        assert llm.call_count == 2
