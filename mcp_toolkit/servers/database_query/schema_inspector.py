"""Auto-detect database schema for SQL generation context."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from mcp_toolkit.servers.database_query.sql_safety import validate_identifier

logger = logging.getLogger(__name__)

# Kept so existing imports of the private name keep working.
_validate_identifier = validate_identifier

_SYSTEM_SCHEMAS = "('pg_catalog', 'information_schema')"


def _is_identifier(name: Any) -> bool:
    try:
        validate_identifier(name, "name")
    except ValueError:
        return False
    return True


class DatabaseConnection(Protocol):
    """Protocol for database connections."""

    async def fetch(self, query: str, /) -> list[dict[str, Any]]: ...


@dataclass
class ColumnInfo:
    name: str
    data_type: str
    is_nullable: bool = True
    is_primary_key: bool = False
    default_value: str | None = None
    foreign_key: str | None = None


@dataclass
class TableInfo:
    name: str
    schema: str = "public"
    columns: list[ColumnInfo] = field(default_factory=list)
    row_count_estimate: int = 0

    def to_ddl(self) -> str:
        """Generate a CREATE TABLE DDL string for LLM context."""
        cols = []
        for c in self.columns:
            parts = [f"  {c.name} {c.data_type}"]
            if c.is_primary_key:
                parts.append("PRIMARY KEY")
            if not c.is_nullable:
                parts.append("NOT NULL")
            if c.foreign_key:
                parts.append(f"REFERENCES {c.foreign_key}")
            cols.append(" ".join(parts))
        col_str = ",\n".join(cols)
        return f"CREATE TABLE {self.schema}.{self.name} (\n{col_str}\n);"


@dataclass
class DatabaseSchema:
    tables: list[TableInfo] = field(default_factory=list)

    def to_context(self) -> str:
        """Generate a full schema context string for LLM prompts."""
        parts = [f"-- Database schema ({len(self.tables)} tables)\n"]
        for table in self.tables:
            parts.append(table.to_ddl())
            parts.append(f"-- Estimated rows: {table.row_count_estimate}\n")
        return "\n".join(parts)


class SchemaInspector:
    """Inspects database schema via information_schema queries."""

    def __init__(self, db: DatabaseConnection | None = None) -> None:
        self._db = db
        self._cached_schema: DatabaseSchema | None = None

    async def inspect(self, db: DatabaseConnection | None = None) -> DatabaseSchema:
        """Inspect the database and return schema information.

        Two fixed queries, no interpolated names. Tables or schemas whose names are
        not plain identifiers are skipped: their names would reach the LLM prompt
        unquoted, and one odd name must not make the whole schema unavailable.
        """
        conn = db or self._db
        if conn is None:
            raise ValueError("No database connection provided")

        tables_rows = await conn.fetch(
            "SELECT table_name, table_schema FROM information_schema.tables "
            f"WHERE table_schema NOT IN {_SYSTEM_SCHEMAS} "
            "ORDER BY table_name"
        )
        columns_rows = await conn.fetch(
            "SELECT table_schema, table_name, column_name, data_type, is_nullable, "
            "column_default FROM information_schema.columns "
            f"WHERE table_schema NOT IN {_SYSTEM_SCHEMAS} "
            "ORDER BY table_schema, table_name, ordinal_position"
        )

        tables: dict[tuple[str, str], TableInfo] = {}
        skipped = 0
        for row in tables_rows:
            name, schema = row["table_name"], row.get("table_schema", "public")
            if not (_is_identifier(name) and _is_identifier(schema)):
                skipped += 1
                continue
            tables[(schema, name)] = TableInfo(name=name, schema=schema)
        for c in columns_rows:
            table = tables.get((c.get("table_schema", "public"), c["table_name"]))
            if table is None:
                continue
            table.columns.append(
                ColumnInfo(
                    name=c["column_name"],
                    data_type=c["data_type"],
                    is_nullable=c.get("is_nullable", "YES") == "YES",
                    default_value=c.get("column_default"),
                )
            )
        if skipped:
            logger.info("schema inspection skipped %d non-identifier table names", skipped)

        schema = DatabaseSchema(tables=list(tables.values()))
        self._cached_schema = schema
        return schema

    def get_cached_schema(self) -> DatabaseSchema | None:
        return self._cached_schema

    @staticmethod
    def from_ddl(ddl_strings: list[str]) -> DatabaseSchema:
        """Create a DatabaseSchema from a list of DDL strings (for testing)."""
        tables = []
        for ddl in ddl_strings:
            lines = ddl.strip().split("\n")
            header = lines[0]
            table_name = header.split("(")[0].replace("CREATE TABLE", "").strip()
            schema = "public"
            if "." in table_name:
                schema, table_name = table_name.rsplit(".", 1)

            columns = []
            for line in lines[1:]:
                line = line.strip().rstrip(",").rstrip(")")
                if not line or line.startswith(")"):
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    columns.append(
                        ColumnInfo(
                            name=parts[0],
                            data_type=parts[1],
                            is_primary_key="PRIMARY" in line.upper(),
                            is_nullable="NOT NULL" not in line.upper(),
                        )
                    )
            tables.append(TableInfo(name=table_name, schema=schema, columns=columns))
        return DatabaseSchema(tables=tables)
