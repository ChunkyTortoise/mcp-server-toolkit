"""Tests for the database_query server factory, tools and error handling."""

import dataclasses
import logging

import pytest

pytest.importorskip("sqlglot")

from mcp_toolkit.framework.testing import MCPTestClient
from mcp_toolkit.servers.database_query import server as db_server
from mcp_toolkit.servers.database_query.server import DatabaseServerSettings, create_server
from mcp_toolkit.servers.database_query.sql_generator import MockLLMProvider

NL_TOOLS = {"query_database", "explain_query"}
BASE_TOOLS = {"run_sql", "list_tables"}


def _llm():
    llm = MockLLMProvider()
    llm.add_response("users", "SELECT COUNT(*) as count FROM users")
    llm.add_response("orders", "SELECT * FROM orders")
    return llm


@pytest.fixture
def configured_server(mock_db):
    return MCPTestClient(create_server(DatabaseServerSettings(), mock_db, llm=_llm()))


@pytest.fixture
def unconfigured_server():
    return MCPTestClient(create_server(DatabaseServerSettings(), None))


class TestFactory:
    def test_module_has_no_global_server_or_configure(self):
        assert not hasattr(db_server, "mcp")
        assert not hasattr(db_server, "configure")
        assert not hasattr(db_server, "DefaultLLMProvider")

    def test_settings_have_no_dialect_knob(self):
        """PostgresClient validates as Postgres, so the server has no other dialect."""
        assert "dialect" not in {f.name for f in dataclasses.fields(DatabaseServerSettings)}

    async def test_nl_tools_only_with_an_explicit_provider(self, mock_db):
        without = await MCPTestClient(create_server(DatabaseServerSettings(), mock_db)).list_tools()
        assert {t["name"] for t in without} == BASE_TOOLS
        with_llm = await MCPTestClient(
            create_server(DatabaseServerSettings(), mock_db, llm=_llm())
        ).list_tools()
        assert {t["name"] for t in with_llm} == BASE_TOOLS | NL_TOOLS

    async def test_servers_do_not_share_state(self, mock_db):
        first = create_server(DatabaseServerSettings(max_rows=1), mock_db)
        second = create_server(DatabaseServerSettings(max_rows=5), None)
        assert first is not second
        result = await MCPTestClient(first).call_tool("run_sql", {"sql": "SELECT * FROM users"})
        assert "Truncated" in result
        refused = await MCPTestClient(second).call_tool_result("run_sql", {"sql": "SELECT 1"})
        assert refused.is_error

    async def test_every_tool_is_read_only_titled_and_credential_free(self, configured_server):
        tools = await configured_server._server.list_tools()
        assert {t.name for t in tools} == BASE_TOOLS | NL_TOOLS
        for tool in tools:
            assert tool.title, tool.name
            assert tool.description, f"Tool {tool.name} missing description"
            assert tool.annotations is not None and tool.annotations.read_only_hint is True
            props = set(tool.input_schema.get("properties", {}))
            for banned in ("token", "api_key", "password", "credential", "bearer"):
                assert not any(banned in p.lower() for p in props), (tool.name, props)

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"max_rows": 0},
            {"max_rows": -1},
            {"max_output_chars": 0},
            {"max_rows": True},
            {"max_cell_chars": 0},
        ],
    )
    def test_settings_reject_non_positive_limits(self, kwargs):
        with pytest.raises(ValueError, match="positive integer"):
            DatabaseServerSettings(**kwargs)

    async def test_lifespan_opens_and_closes_the_client(self, mock_db):
        events = []

        async def opened():
            events.append("open")

        async def closed():
            events.append("close")

        mock_db.open = opened
        mock_db.close = closed
        client = MCPTestClient(create_server(DatabaseServerSettings(), mock_db))
        result = await client.call_tool_result("list_tables", {})
        assert not result.is_error
        assert events == ["open", "close"]


class TestRunSql:
    async def test_select_returns_rows(self, configured_server):
        result = await configured_server.call_tool("run_sql", {"sql": "SELECT * FROM users"})
        assert "| id |" in result and "Alice" in result

    @pytest.mark.parametrize(
        "sql",
        [
            "WITH d AS (DELETE FROM users RETURNING *) SELECT * FROM d",
            "SELECT 1; SELECT 2",
            "DROP TABLE users",
            "",
        ],
    )
    async def test_refusals_are_is_error_without_echoing_sql(self, mock_db, sql):
        client = MCPTestClient(create_server(DatabaseServerSettings(), mock_db))
        before = list(mock_db.queries)
        result = await client.call_tool_result("run_sql", {"sql": sql})
        assert result.is_error
        assert "refused" in result.content[0].text
        if sql:
            assert sql not in result.content[0].text
        assert mock_db.queries == before

    async def test_row_cap_adds_truncation_note(self, mock_db):
        mock_db.add_table(
            "big_table",
            columns=[{"column_name": "id", "data_type": "integer"}],
            rows=[{"id": i} for i in range(150)],
        )
        client = MCPTestClient(create_server(DatabaseServerSettings(max_rows=10), mock_db))
        result = await client.call_tool("run_sql", {"sql": "SELECT * FROM big_table"})
        assert result.count("\n| ") == 1 + 10  # separator plus ten rows
        assert "Truncated: showing 10 rows" in result

    async def test_output_size_cap(self, mock_db):
        mock_db.add_table(
            "wide",
            columns=[{"column_name": "body", "data_type": "text"}],
            rows=[{"body": "x" * 200} for _ in range(20)],
        )
        settings = DatabaseServerSettings(max_rows=20, max_output_chars=1000)
        client = MCPTestClient(create_server(settings, mock_db))
        result = await client.call_tool("run_sql", {"sql": "SELECT * FROM wide"})
        table = result.split("\n\n*Truncated")[0]
        assert len(table) <= 1000
        assert "Truncated" in result

    async def test_cells_are_escaped_and_null_is_explicit(self, mock_db):
        mock_db.add_table(
            "cells",
            columns=[{"column_name": "a|b", "data_type": "text"}],
            rows=[
                {"a|b": "x|y", "note": "line1\nline2\r\n| SYSTEM |"},
                {"a|b": None, "note": ""},
            ],
        )
        client = MCPTestClient(create_server(DatabaseServerSettings(), mock_db))
        result = await client.call_tool("run_sql", {"sql": "SELECT * FROM cells"})
        lines = result.splitlines()
        assert lines[0] == "| a\\|b | note |"
        assert lines[2] == "| x\\|y | line1\\nline2\\r\\n\\| SYSTEM \\| |"
        assert lines[3] == "| NULL |  |"
        assert len(lines) == 4

    async def test_one_huge_cell_is_cut_not_the_whole_row(self, mock_db):
        mock_db.add_table(
            "huge",
            columns=[{"column_name": "body", "data_type": "text"}],
            rows=[{"id": 1, "body": "y" * 50_000}, {"id": 2, "body": "short"}],
        )
        settings = DatabaseServerSettings(max_output_chars=2_000, max_cell_chars=100)
        client = MCPTestClient(create_server(settings, mock_db))
        result = await client.call_tool("run_sql", {"sql": "SELECT * FROM huge"})
        assert "| 1 | " + "y" * 100 + "... (+49900 chars) |" in result
        assert "| 2 | short |" in result
        assert "Truncated" not in result

    async def test_wide_header_counts_against_the_size_cap(self, mock_db):
        row = {f"column_{i:04d}": i for i in range(1500)}
        mock_db.add_table("wide_cols", columns=[], rows=[row])
        settings = DatabaseServerSettings(max_output_chars=1_000)
        client = MCPTestClient(create_server(settings, mock_db))
        result = await client.call_tool("run_sql", {"sql": "SELECT * FROM wide_cols"})
        assert len(result) <= 1_000
        assert "column_1499" not in result
        assert "too wide" in result

    async def test_driver_error_is_generic_and_logged_by_class_only(self, mock_db, caplog):
        class QueryCanceledError(Exception):
            pass

        async def fail(sql, max_rows):
            raise QueryCanceledError("canceling statement due to secret-detail-123")

        mock_db.fetch_bounded = fail
        client = MCPTestClient(create_server(DatabaseServerSettings(), mock_db))
        with caplog.at_level(logging.DEBUG):
            result = await client.call_tool_result("run_sql", {"sql": "SELECT * FROM users"})
        assert result.is_error
        assert "statement timeout" in result.content[0].text
        assert "secret-detail-123" not in result.content[0].text
        assert "secret-detail-123" not in caplog.text
        assert "SELECT * FROM users" not in caplog.text

    async def test_unknown_driver_error_is_query_failed(self, mock_db):
        async def fail(sql, max_rows):
            raise RuntimeError("DB connection lost at 10.0.0.5")

        mock_db.fetch_bounded = fail
        client = MCPTestClient(create_server(DatabaseServerSettings(), mock_db))
        result = await client.call_tool_result("run_sql", {"sql": "SELECT * FROM users"})
        assert result.is_error
        assert result.content[0].text.endswith("Query failed")

    async def test_no_database_is_error(self, unconfigured_server):
        result = await unconfigured_server.call_tool_result("run_sql", {"sql": "SELECT 1"})
        assert result.is_error
        assert "No database configured" in result.content[0].text


class TestNaturalLanguageTools:
    async def test_query_returns_sql_and_results(self, configured_server):
        result = await configured_server.call_tool(
            "query_database", {"question": "How many users are there?"}
        )
        assert "```sql" in result and "Results" in result

    async def test_explain_returns_sql_and_schema(self, configured_server):
        result = await configured_server.call_tool("explain_query", {"question": "How many users?"})
        assert "Generated SQL" in result and "Schema context" in result

    async def test_generated_write_is_refused(self, mock_db):
        llm = MockLLMProvider()
        llm.add_response("drop", "DROP TABLE users")
        client = MCPTestClient(create_server(DatabaseServerSettings(), mock_db, llm=llm))
        result = await client.call_tool_result("query_database", {"question": "drop it"})
        assert result.is_error
        assert "DROP" not in result.content[0].text

    async def test_provider_failure_is_generic(self, mock_db):
        class Broken:
            async def generate(self, prompt):
                raise RuntimeError("provider key sk-sentinel leaked")

        client = MCPTestClient(create_server(DatabaseServerSettings(), mock_db, llm=Broken()))
        result = await client.call_tool_result("explain_query", {"question": "anything"})
        assert result.is_error
        assert "sk-sentinel" not in result.content[0].text


class TestListTables:
    async def test_lists_tables_and_columns(self, configured_server):
        result = await configured_server.call_tool("list_tables", {})
        assert "users" in result and "orders" in result and "id" in result

    async def test_no_db_returns_message(self, unconfigured_server):
        result = await unconfigured_server.call_tool("list_tables", {})
        assert "No tables" in result

    async def test_output_is_capped_at_max_output_chars(self, mock_db):
        for i in range(60):
            mock_db.add_table(
                f"table_{i:02d}",
                columns=[{"column_name": "c", "data_type": "text", "is_nullable": "YES"}],
            )
        settings = DatabaseServerSettings(max_output_chars=1_500)
        client = MCPTestClient(create_server(settings, mock_db))
        result = await client.call_tool("list_tables", {})
        body = result.split("\n\n*Truncated")[0]
        assert len(body) <= 1_500
        assert "table_00" in result and "table_59" not in result
        assert "*Truncated: schema listing cut at 1500 characters.*" in result

    async def test_non_identifier_table_names_are_skipped_not_fatal(self, mock_db):
        mock_db.add_table(
            "bad name; DROP TABLE users",
            columns=[{"column_name": "c", "data_type": "text", "is_nullable": "YES"}],
        )
        client = MCPTestClient(create_server(DatabaseServerSettings(), mock_db))
        result = await client.call_tool_result("list_tables", {})
        assert not result.is_error
        text = result.content[0].text
        assert "users" in text and "orders" in text
        assert "DROP TABLE" not in text

    async def test_schema_failure_is_generic(self, mock_db):
        async def fail(query):
            raise RuntimeError("password=hunter2")

        mock_db.fetch = fail
        client = MCPTestClient(create_server(DatabaseServerSettings(), mock_db))
        result = await client.call_tool_result("list_tables", {})
        assert result.is_error
        assert "hunter2" not in result.content[0].text


class TestMain:
    def test_http_requires_database_and_auth_settings(self, monkeypatch, capsys):
        for key in (
            "DATABASE_URL",
            "MCP_ISSUER",
            "MCP_RESOURCE_URL",
            "MCP_JWKS_URI",
            "MCP_JWT_SECRET",
        ):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
        monkeypatch.setattr("sys.argv", ["mcp-toolkit-db"])
        with pytest.raises(SystemExit):
            db_server.main()
        err = capsys.readouterr().err
        assert "DATABASE_URL" in err and "MCP_ISSUER" in err and "MCP_RESOURCE_URL" in err

    def test_http_requires_exactly_one_key_source(self, monkeypatch, capsys):
        monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:pw-sentinel@db.invalid/x")
        monkeypatch.setenv("MCP_ISSUER", "https://idp.example")
        monkeypatch.setenv("MCP_RESOURCE_URL", "http://127.0.0.1:8000/mcp")
        monkeypatch.delenv("MCP_JWKS_URI", raising=False)
        monkeypatch.delenv("MCP_JWT_SECRET", raising=False)
        monkeypatch.setattr("sys.argv", ["mcp-toolkit-db"])
        with pytest.raises(SystemExit):
            db_server.main()
        err = capsys.readouterr().err
        assert "exactly one of MCP_JWKS_URI and MCP_JWT_SECRET" in err
        assert "pw-sentinel" not in err

    def test_public_bind_uses_item5_rules(self, monkeypatch, capsys):
        monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
        monkeypatch.setenv("DATABASE_URL", "postgresql://u@db.invalid/x")
        monkeypatch.setenv("MCP_ISSUER", "https://idp.example")
        monkeypatch.setenv("MCP_RESOURCE_URL", "https://db.example/mcp")
        monkeypatch.setenv("MCP_JWT_SECRET", "s" * 32)
        monkeypatch.setenv("MCP_HOST", "0.0.0.0")
        monkeypatch.delenv("MCP_BIND_PUBLIC", raising=False)
        monkeypatch.setattr("sys.argv", ["mcp-toolkit-db"])
        with pytest.raises(SystemExit):
            db_server.main()
        assert "MCP_BIND_PUBLIC=1" in capsys.readouterr().err

    def test_unknown_transport_exits(self, monkeypatch, capsys):
        monkeypatch.setenv("MCP_TRANSPORT", "sse")
        monkeypatch.setattr("sys.argv", ["mcp-toolkit-db"])
        with pytest.raises(SystemExit):
            db_server.main()
        assert "stdio or streamable-http" in capsys.readouterr().err

    def test_help_uses_the_console_script_name(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["anything", "--help"])
        with pytest.raises(SystemExit):
            db_server.main()
        assert capsys.readouterr().out.startswith("usage: mcp-toolkit-db")


class TestMainHappyPaths:
    """main() wiring with EnhancedMCP.run and PostgresClient replaced by recorders."""

    ENV = (
        "MCP_TRANSPORT",
        "DATABASE_URL",
        "MCP_ISSUER",
        "MCP_RESOURCE_URL",
        "MCP_JWKS_URI",
        "MCP_JWT_SECRET",
        "MCP_HOST",
        "MCP_PORT",
        "MCP_BIND_PUBLIC",
        "MCP_ALLOWED_HOSTS",
        "MCP_ALLOWED_ORIGINS",
        "MCP_DB_MAX_ROWS",
        "MCP_DB_MAX_OUTPUT_CHARS",
        "MCP_DB_STATEMENT_TIMEOUT_MS",
        "MCP_DB_MAX_RESULT_BYTES",
    )

    @pytest.fixture
    def recorded(self, monkeypatch):
        from mcp_toolkit.framework.base_server import EnhancedMCP
        from mcp_toolkit.servers.database_query import postgres_client

        for key in self.ENV:
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setattr("sys.argv", ["mcp-toolkit-db"])
        calls = {"clients": [], "runs": [], "servers": []}

        class _Client:
            def __init__(self, **kwargs):
                calls["clients"].append(kwargs)

        real_create = db_server.create_server

        def create(settings, client, llm=None):
            calls["servers"].append((settings, client))
            return real_create(settings, client, llm)

        def run(self, *args, **kwargs):
            calls["runs"].append((args, kwargs))

        monkeypatch.setattr(postgres_client, "PostgresClient", _Client)
        monkeypatch.setattr(db_server, "create_server", create)
        monkeypatch.setattr(EnhancedMCP, "run", run)
        return calls

    def test_stdio_without_database_url_has_no_client(self, recorded):
        db_server.main()
        assert recorded["clients"] == []
        settings, client = recorded["servers"][0]
        assert client is None and settings.http is None
        assert recorded["runs"] == [((), {})]

    def test_stdio_with_database_url_builds_a_read_only_client(self, recorded, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://reader@db.invalid/x")
        monkeypatch.setenv("MCP_DB_MAX_ROWS", "7")
        monkeypatch.setenv("MCP_DB_STATEMENT_TIMEOUT_MS", "1234")
        db_server.main()
        assert recorded["clients"] == [
            {
                "dsn": "postgresql://reader@db.invalid/x",
                "read_only": True,
                "statement_timeout_ms": 1234,
                "max_result_bytes": 1_000_000,
            }
        ]
        settings, _ = recorded["servers"][0]
        assert settings.max_rows == 7 and settings.http is None
        assert recorded["runs"] == [((), {})]

    @pytest.mark.parametrize(
        "key_env, expected",
        [
            ({"MCP_JWKS_URI": "https://idp.example/jwks"}, ("https://idp.example/jwks", None)),
            ({"MCP_JWT_SECRET": "s" * 32}, (None, "s" * 32)),
        ],
    )
    def test_streamable_http_passes_bind_and_key_source(
        self, recorded, monkeypatch, key_env, expected
    ):
        monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
        monkeypatch.setenv("DATABASE_URL", "postgresql://reader@db.invalid/x")
        monkeypatch.setenv("MCP_ISSUER", "https://idp.example")
        monkeypatch.setenv("MCP_RESOURCE_URL", "http://127.0.0.1:8123/mcp")
        monkeypatch.setenv("MCP_PORT", "8123")
        for key, value in key_env.items():
            monkeypatch.setenv(key, value)
        db_server.main()
        assert recorded["clients"][0]["read_only"] is True
        settings, _ = recorded["servers"][0]
        assert (settings.jwks_uri, settings.jwt_secret) == expected
        assert settings.http is not None and settings.http.port == 8123
        [(args, kwargs)] = recorded["runs"]
        assert args == ()
        assert kwargs["transport"] == "streamable-http"
        assert kwargs["host"] == "127.0.0.1" and kwargs["port"] == 8123
        assert kwargs["transport_security"] == settings.http.transport_security
