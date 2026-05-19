# ADR-0008 — Auth Boundary: Credential Source and the stdio Limit

**Status:** Accepted
**Date:** 2026-05-19
**Authors:** mcp-server-toolkit maintainers
**Supersedes:** the credential-source portion of [ADR-0006](ADR-0006-oauth-2.1-resource-server.md)

---

## Context

`requires_scope` — the decorator the README markets as the toolkit's scope
RBAC — read the caller's credential from the tool's own arguments:

```python
credential = kwargs.get("token") or kwargs.get("api_key") or kwargs.get("authorization") or ""
```

Two things are wrong with that, and the second is worse than the first.

1. **The credential was public input.** A tool shaped like
   `async def query_database(sql: str, token: str = "")` publishes `token` as a
   parameter in its MCP `inputSchema`. `list_tools()` hands that schema to every
   client. The "credential" was therefore an ordinary, client-supplied,
   discoverable tool argument — not a transport credential. Anything the client
   can read from the schema and set at will is not an authentication boundary.

2. **It was wired into nothing.** No server in the toolkit applied
   `requires_scope`. It was dead code that nonetheless appeared in the
   capability table and an ADR — the gap between the claim and the wiring was
   the actual finding.

This ADR records how auth was made real and schema-clean, and one honest limit
that fell out of doing it correctly.

---

## Decision

### 1. The credential comes from the transport, never from a tool argument

The MCP SDK (developed against `mcp` 1.26.0, whose bundled `FastMCP` this
toolkit already extends) ships the correct mechanism. When a server is constructed with a
`token_verifier`, `streamable_http_app()` / `sse_app()` install
`BearerAuthBackend` → `AuthContextMiddleware` → `RequireAuthMiddleware`. That
stack parses the request's `Authorization` header, validates the bearer token,
and places the verified token in a per-request `contextvar`.

`requires_scope` was rewritten to **shrink** to that model:

```python
def requires_scope(scope: str):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            token = get_access_token()                 # SDK per-request contextvar
            if token is None:
                return "Error: Unauthorized — authentication required"
            if scope and scope not in token.scopes:
                return f"Error: Forbidden — scope '{scope}' required, have {token.scopes}"
            return await func(*args, **kwargs)
        return wrapper
    return decorator
```

The signature dropped its `auth` parameter; the body dropped every
`kwargs.get(...)` path. **There is no kwarg fallback** — a fallback would
re-introduce exactly the public-input failure above. A `JWTTokenVerifier`
adapter bridges the toolkit's existing `JWTAuth` / `APIKeyAuth`
(`authenticate(credential) -> AuthResult`, unchanged) to the SDK's
`TokenVerifier.verify_token(token) -> AccessToken | None`. The validation logic
is reused verbatim — only its entry point moved from a tool kwarg to the
transport.

### 2. Hand-rolling the contextvar/middleware was rejected

The obvious alternative — write our own request-scoped credential store and
auth middleware — was rejected. The SDK already implements
`BearerAuthBackend`, `AuthContextMiddleware`, `RequireAuthMiddleware` and
RFC 6750/9728 error semantics. Re-implementing shipped, tested protocol
plumbing to validate a token is not engineering judgment; it is a maintenance
liability and, in a library that *is* an MCP toolkit, a credibility tell.
`EnhancedMCP.__init__` already forwarded `**kwargs` to `FastMCP`, so
`token_verifier` and `auth` pass through with **no base-class change** —
the right amount of code here was none.

### 3. RFC-compliant rejection over HTTP

With a verifier wired, the SDK enforces, before any tool runs:

- no / invalid token → **401** with a `WWW-Authenticate: Bearer` challenge
- token valid, required scope absent → **403** `insufficient_scope`
- token valid, scope present → tool executes

The pre-built `database_query` and `crm_ghl` servers are wired this way, with
per-tool scopes (`db:read`; `crm:read` / `crm:write`).

The apparent double scope check is deliberate: `AuthSettings.required_scopes`
(enforced server-wide by `RequireAuthMiddleware` at the transport) gates
admission to the server, while `@requires_scope` adds the per-tool granularity
the single server-wide setting cannot express — e.g. `crm:read` for reads vs.
`crm:write` for mutations on the same server.

### 4. The stdio limit — stated, not papered over

stdio has no `Authorization` channel. There is no place for a bearer token to
live, so `get_access_token()` is always `None` under stdio. This is a real
boundary of the transport, not a defect of the design, and it forces a choice
for the toolkit's default (stdio: Claude Desktop, IDE plugins).

**Decision: under stdio, an `@requires_scope` tool hard-rejects** (returns
`Unauthorized`) rather than soft-skipping the check.

The alternative — "no auth context, so skip the check and run" — was rejected.
Soft-skip makes authentication *optional in practice*: the same decorated tool
silently runs unauthenticated under the default transport and authenticated
only over HTTP. That is precisely the class of gap this ADR exists to close,
and it would make the RBAC claim true only in a configuration nobody runs by
default. A loud, uniform rejection is the honest behaviour: auth is enforced,
or the tool refuses.

Real authentication therefore requires the **opt-in HTTP transport**. The
servers keep stdio as the default (so `python -m …server` is unchanged) and
expose one switch, `MCP_HTTP_PORT`, which runs
`mcp.run(transport="streamable-http")`. HTTP mode **refuses to start** if
`MCP_JWT_SECRET` is unset, so auth cannot silently no-op through
misconfiguration — the failure is at boot, not at request time.

---

## Consequences

**Positive:**

- The credential is never in `list_tools()`. A schema test asserts no
  auth-wired tool exposes a `token` / `api_key` / `authorization` property;
  this is the regression gate for the original finding.
- Auth is exercised end-to-end against the real SDK middleware (no mocking):
  `TestClient(mcp.streamable_http_app())` proves 401 / 403 / 200.
- One credential model, reusing the SDK's RFC-compliant implementation; the
  toolkit's `JWTAuth`/`APIKeyAuth` are unchanged.

**Negative / Trade-offs:**

- Auth is **HTTP-only**. Under the default stdio transport every
  `@requires_scope` tool returns `Unauthorized`. This is intended (§4) and is
  documented in the README and each server's `main()` docstring, but it does
  mean scope RBAC and the stdio default are mutually exclusive — an HTTP
  deployment is required to use auth at all.
- This toolkit is an OAuth 2.1 **resource server** only — it validates tokens
  (signature, `exp`, `iss`, `aud`, scopes). Token issuance, PKCE, and refresh
  remain out of scope (also stated in ADR-0006).

---

## Alternatives Considered

**Keep the kwarg credential, just document it.** Rejected — a credential a
client reads from the public schema and sets freely is not an auth boundary;
no amount of documentation changes that.

**Hand-roll contextvar + auth middleware.** Rejected — duplicates shipped,
tested SDK plumbing; higher maintenance surface; a poor signal in an MCP
library.

**Soft-skip the scope check when no auth context exists (stdio).** Rejected —
makes auth optional in practice and would make the RBAC claim true only in a
non-default configuration. See §4.

**Add an auth shim to stdio.** Rejected — stdio has no header channel;
inventing an out-of-band credential path would be a bespoke, non-standard
mechanism contradicting the "use the SDK's standard auth" decision. The honest
answer is that authenticated transport means HTTP.
