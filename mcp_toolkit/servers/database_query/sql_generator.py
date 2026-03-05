"""LLM-based SQL generation with schema context and sqlglot validation."""

from __future__ import annotations

from typing import Protocol

import sqlglot

from mcp_toolkit.servers.database_query.schema_inspector import DatabaseSchema


class LLMProvider(Protocol):
    """Protocol for LLM providers used in SQL generation."""

    async def generate(self, prompt: str) -> str: ...


class DefaultLLMProvider:
    """Default LLM provider that returns a placeholder. Override in production."""

    async def generate(self, prompt: str) -> str:
        return "SELECT 1"


class SQLGenerator:
    """Generates SQL from natural language questions using an LLM and schema context."""

    def __init__(self, llm: LLMProvider | None = None, dialect: str = "postgres") -> None:
        self._llm = llm or DefaultLLMProvider()
        self._dialect = dialect

    def build_prompt(self, question: str, schema: DatabaseSchema) -> str:
        """Build the LLM prompt with schema context."""
        return (
            "You are a SQL expert. Generate a single SELECT query to answer the user's question.\n"
            "Only output the SQL query, nothing else. No markdown, no explanation.\n"
            "Only use SELECT statements. Never use INSERT, UPDATE, DELETE, DROP, etc.\n\n"
            f"Database schema:\n{schema.to_context()}\n\n"
            f"Question: {question}\n\n"
            "SQL:"
        )

    async def generate(self, question: str, schema: DatabaseSchema) -> str:
        """Generate SQL from a natural language question."""
        prompt = self.build_prompt(question, schema)
        raw_sql = await self._llm.generate(prompt)
        return self.clean_sql(raw_sql)

    @staticmethod
    def clean_sql(raw: str) -> str:
        """Clean up LLM-generated SQL output."""
        sql = raw.strip()
        if sql.startswith("```"):
            lines = sql.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            sql = "\n".join(lines).strip()
        if sql.endswith(";"):
            sql = sql[:-1].strip()
        return sql

    def validate(self, sql: str) -> tuple[bool, str]:
        """Validate SQL using sqlglot. Returns (is_valid, error_or_transpiled)."""
        try:
            parsed = sqlglot.transpile(sql, read=self._dialect, write=self._dialect)
            if not parsed:
                return False, "Empty SQL after parsing"

            for stmt in parsed:
                upper = stmt.strip().upper()
                if not upper.startswith("SELECT") and not upper.startswith("WITH"):
                    return False, f"Only SELECT/WITH queries allowed, got: {upper[:20]}"

            return True, parsed[0]
        except sqlglot.errors.ErrorLevel:
            return False, f"SQL parsing error: {sql[:100]}"
        except Exception as e:
            return False, f"Validation error: {e}"

    async def generate_and_validate(
        self, question: str, schema: DatabaseSchema
    ) -> tuple[str, bool, str]:
        """Generate SQL and validate it. Returns (sql, is_valid, error_or_clean_sql)."""
        sql = await self.generate(question, schema)
        is_valid, result = self.validate(sql)
        return sql, is_valid, result


class MockLLMProvider:
    """Mock LLM provider for testing. Returns predefined SQL for known questions."""

    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self._responses = responses or {}
        self._default = "SELECT 1"
        self._calls: list[str] = []

    def add_response(self, keyword: str, sql: str) -> None:
        self._responses[keyword.lower()] = sql

    async def generate(self, prompt: str) -> str:
        self._calls.append(prompt)
        prompt_lower = prompt.lower()
        for keyword, sql in self._responses.items():
            if keyword in prompt_lower:
                return sql
        return self._default

    @property
    def call_count(self) -> int:
        return len(self._calls)
