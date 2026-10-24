-- Setup for the Postgres integration tests (run as the superuser by the CI
-- `integration` job and by the local Docker recipe in the same job step).
--
-- Client-side rules this file demonstrates. The AST validator is defense in depth and
-- its function list is a fixed denylist; these database rules are what hold:
--   1. One role per tenant, with grants only on that tenant's tables. There is no row
--      predicate: a role that can SELECT a table reads every row in it.
--   2. REVOKE EXECUTE ... FROM PUBLIC on every function the role must not call. New
--      functions are executable by PUBLIC by default, and a function missing from the
--      denylist passes the validator.
--   3. Never GRANT EXECUTE on a SECURITY DEFINER function to the read-only role: it
--      runs with its owner's privileges and can read tables the role cannot.
--   4. Set default_transaction_read_only = on and a statement_timeout on the role.
--
-- The password below is a throwaway CI literal, not a secret.

CREATE TABLE items (id int PRIMARY KEY, name text NOT NULL);
INSERT INTO items VALUES (1, 'alpha'), (2, 'beta'), (3, 'gamma');

-- Two tenants in one table the reader can SELECT (rule 1: not blocked by this role).
CREATE TABLE tenant_rows (tenant text NOT NULL, note text NOT NULL);
INSERT INTO tenant_rows VALUES ('tenant_a', 'a-row-1'), ('tenant_b', 'b-row-1');

-- Synthetic sensitive rows. mcp_reader gets no grant on this table.
CREATE TABLE forbidden_secrets (id int PRIMARY KEY, secret text NOT NULL);
INSERT INTO forbidden_secrets VALUES (1, 'synthetic-secret-1'), (2, 'synthetic-secret-2');

-- Reader can INSERT here, so only default_transaction_read_only stops a write.
CREATE TABLE write_probe (id int);

CREATE ROLE mcp_reader LOGIN PASSWORD 'ci-throwaway-password';
GRANT CONNECT ON DATABASE mcp_test TO mcp_reader;
GRANT USAGE ON SCHEMA public TO mcp_reader;
GRANT SELECT ON items, tenant_rows TO mcp_reader;
GRANT INSERT ON write_probe TO mcp_reader;
ALTER ROLE mcp_reader SET default_transaction_read_only = on;
ALTER ROLE mcp_reader SET statement_timeout = '1500ms';

-- Not on the validator denylist, reads the forbidden table with owner privileges.
CREATE FUNCTION leak() RETURNS text LANGUAGE sql SECURITY DEFINER
AS $$ SELECT secret FROM forbidden_secrets WHERE id = 1 $$;
REVOKE EXECUTE ON FUNCTION leak() FROM PUBLIC;
