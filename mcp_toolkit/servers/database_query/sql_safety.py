"""Shared SQL safety checks for the database_query server.

One read-only validator serves every path (PostgresClient.fetch, vector_search and
SQLGenerator.validate), so the same SQL gets the same verdict everywhere.

The validator is a sqlglot AST allowlist: only SELECT, set operations
(UNION/INTERSECT/EXCEPT), VALUES and a non-executing EXPLAIN are accepted. DML/DDL
anywhere in the tree, SELECT ... INTO, COPY, statements sqlglot cannot parse, and a
fixed denylist of functions (file access, large objects, backend control, dblink,
set_config) are rejected.

This is defense in depth, not a security boundary. The function list is a fixed
denylist: a function that is not on it passes the validator. The grants of the
database role are what stop such a function, so also connect with a read-only role
(default_transaction_read_only = on, SELECT-only grants, REVOKE EXECUTE ... FROM
PUBLIC on functions the role must not call). The Postgres integration tests in CI
exercise both layers.

Requires: pip install mcp-server-toolkit[database]
"""

from __future__ import annotations

import re

# SQL statement types that are never allowed in read-only mode.
_WRITE_STATEMENT_TYPES = {
    "Insert",
    "Update",
    "Delete",
    "Drop",
    "Create",
    "Alter",
    "Truncate",
    "TruncateTable",
    "Merge",
    "Replace",
    "Grant",
    "Revoke",
    "Lock",
    "Call",
}

# Top-level statement types accepted in read-only mode (allowlist).
_ALLOWED_STATEMENT_TYPES = {"Select", "Union", "Intersect", "Except", "Values"}

# Node types rejected anywhere in the tree, in addition to the write statements.
# Into: SELECT ... INTO creates a table. Copy: COPY ... TO PROGRAM runs a shell
# command. Command: SQL sqlglot could not parse (SET ROLE, VACUUM, ...).
_DENIED_NODE_TYPES = _WRITE_STATEMENT_TYPES | {"Into", "Copy", "Command", "Set"}

# Functions with side effects or file, large-object or network access that a SELECT
# can call. Audited against pg_proc (schema pg_catalog) on postgres:16, plus the
# dblink and adminpack extensions. Fixed list: the role's grants cover the rest.
_DENIED_FUNCTIONS = {
    # backend and server control
    "pg_terminate_backend",
    "pg_cancel_backend",
    "pg_reload_conf",
    "pg_rotate_logfile",
    "pg_rotate_logfile_old",
    "pg_log_backend_memory_contexts",
    "pg_import_system_collations",
    "pg_switch_wal",
    "pg_create_restore_point",
    "pg_promote",
    "pg_backup_start",
    "pg_backup_stop",
    "pg_wal_replay_pause",
    "pg_wal_replay_resume",
    "pg_notify",
    "pg_stat_reset",
    "pg_stat_reset_shared",
    "pg_stat_reset_slru",
    "pg_stat_reset_single_table_counters",
    "pg_stat_reset_single_function_counters",
    "pg_stat_reset_replication_slot",
    "pg_stat_reset_subscription_stats",
    "set_config",
    "pg_sleep",
    "pg_sleep_for",
    "pg_sleep_until",
    # server file access
    "pg_read_file",
    "pg_read_file_old",
    "pg_read_binary_file",
    "pg_write_file",
    "pg_ls_dir",
    "pg_stat_file",
    "pg_current_logfile",
    "pg_ls_archive_statusdir",
    "pg_ls_logdir",
    "pg_ls_logicalmapdir",
    "pg_ls_logicalsnapdir",
    "pg_ls_replslotdir",
    "pg_ls_tmpdir",
    "pg_ls_waldir",
    "pg_file_write",
    "pg_file_rename",
    "pg_file_unlink",
    "pg_logdir_ls",
    # large objects
    "lo_import",
    "lo_export",
    "lo_unlink",
    "lo_create",
    "lo_creat",
    "lo_put",
    "lo_get",
    "lo_from_bytea",
    "lo_open",
    "lo_close",
    "lo_lseek",
    "lo_lseek64",
    "lo_tell",
    "lo_tell64",
    "lo_truncate",
    "lo_truncate64",
    "loread",
    "lowrite",
    # network (dblink extension)
    "dblink",
    "dblink_exec",
    "dblink_connect",
    "dblink_connect_u",
    "dblink_disconnect",
    "dblink_send_query",
    "dblink_get_result",
    "dblink_open",
    "dblink_fetch",
    "dblink_close",
    "dblink_cancel_query",
    "dblink_get_connections",
    # locks and sequences (state changes visible to other sessions)
    "pg_advisory_lock",
    "pg_advisory_lock_shared",
    "pg_advisory_xact_lock",
    "pg_advisory_xact_lock_shared",
    "pg_try_advisory_lock",
    "pg_try_advisory_lock_shared",
    "pg_try_advisory_xact_lock",
    "pg_try_advisory_xact_lock_shared",
    "pg_advisory_unlock",
    "pg_advisory_unlock_shared",
    "pg_advisory_unlock_all",
    "nextval",
    "setval",
    # replication slots, origins and logical messages
    "pg_create_logical_replication_slot",
    "pg_create_physical_replication_slot",
    "pg_copy_logical_replication_slot",
    "pg_copy_physical_replication_slot",
    "pg_drop_replication_slot",
    "pg_replication_slot_advance",
    "pg_logical_emit_message",
    "pg_logical_slot_get_changes",
    "pg_logical_slot_get_binary_changes",
    "pg_logical_slot_peek_changes",
    "pg_logical_slot_peek_binary_changes",
    "pg_replication_origin_create",
    "pg_replication_origin_drop",
    "pg_replication_origin_advance",
    "pg_replication_origin_session_setup",
    "pg_replication_origin_session_reset",
    "pg_replication_origin_xact_setup",
    "pg_replication_origin_xact_reset",
    # SQL run from a string or whole-database dumps to XML
    "query_to_xml",
    "query_to_xmlschema",
    "query_to_xml_and_xmlschema",
    "cursor_to_xml",
    "cursor_to_xmlschema",
    "table_to_xml",
    "table_to_xmlschema",
    "table_to_xml_and_xmlschema",
    "schema_to_xml",
    "schema_to_xmlschema",
    "schema_to_xml_and_xmlschema",
    "database_to_xml",
    "database_to_xmlschema",
    "database_to_xml_and_xmlschema",
}

_EXPLAIN_OPTIONS = re.compile(
    r"^\s*(?:\([^)]*\)|(?:VERBOSE|COSTS|BUFFERS|FORMAT\s+\w+)\s+)*", re.IGNORECASE
)
_EXPLAIN_ANALYZE = re.compile(r"\bANALY[SZ]E\b", re.IGNORECASE)

_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def validate_identifier(name: str, label: str) -> None:
    """Reject identifiers that don't match safe SQL identifier pattern."""
    if not isinstance(name, str) or not _IDENTIFIER_RE.match(name):
        raise ValueError(f"Invalid {label}: {name!r}. Must match ^[a-zA-Z_][a-zA-Z0-9_]*$")


def _reject(reason: str) -> None:
    raise ValueError(f"Read-only mode: {reason} is not allowed.")


def _validate_explain(rest: str, dialect: str) -> None:
    """EXPLAIN is allowed only without ANALYZE (which executes the statement)."""
    if _EXPLAIN_ANALYZE.search(rest):
        _reject("EXPLAIN ANALYZE")
    validate_read_only(_EXPLAIN_OPTIONS.sub("", rest, count=1), dialect)


def validate_read_only(sql: str, dialect: str = "postgres") -> None:
    """Raise ValueError unless every statement in sql is a plain read."""
    try:
        import sqlglot
        from sqlglot import exp
    except ImportError as exc:
        raise ImportError("Install sqlglot: pip install mcp-server-toolkit[database]") from exc

    statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    if not statements:
        _reject("an empty statement")
    for statement in statements:
        stmt_type = type(statement).__name__
        if isinstance(statement, exp.Command) and str(statement.this).upper() == "EXPLAIN":
            rest = statement.expression
            _validate_explain(str(getattr(rest, "name", rest) or ""), dialect)
            continue
        if stmt_type not in _ALLOWED_STATEMENT_TYPES:
            _reject(f"statement type '{stmt_type}'")
        for node in statement.walk():
            node_type = type(node).__name__
            if node_type in _DENIED_NODE_TYPES:
                _reject(f"nested '{node_type}'")
            if isinstance(node, exp.Func):
                name = node.name if isinstance(node, exp.Anonymous) else node.sql_name()
                if name and name.lower() in _DENIED_FUNCTIONS:
                    _reject(f"function '{name.lower()}'")
