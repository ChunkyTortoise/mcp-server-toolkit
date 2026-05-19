# ADR-0006: OAuth 2.1 Resource-Server Design

**Status:** Accepted  
**Date:** 2026-04-26

## Context

`OAuthAuth` (v0.2.0) stored tokens in an in-memory dict and used HMAC hex strings as the token format. This was documented as "for testing only" but was presented in the README alongside `APIKeyAuth` in a way that implied production readiness. That was misleading.

MCP servers that expose sensitive data (database queries, CRM records, calendar events) need real token validation to be deployed safely. The Anthropic MCP Engineer JD explicitly calls out "guiding partners through OAuth implementations."

## Decision

Introduce `JWTAuth` as the production authentication class. Keep `OAuthAuth` as a test-only class with an explicit docstring saying so.

### `JWTAuth` design

- **HS256 mode** (`secret=`): symmetric HMAC-SHA256. Suitable for single-tenant or internal services. Minimal setup — no external key store required.
- **RS256 / JWKS mode** (`jwks_uri=`): fetches the IdP's public key set via `PyJWT.PyJWKClient`. Keys are cached in process and refreshed automatically when a new `kid` is encountered (automatic key rotation).
- **Scope extraction**: supports `scope` (space-separated string, RFC 6749), `scp` (list, Azure AD style), and `permissions` (list, Auth0 style).
- **Standard claims verified**: `exp` (with configurable leeway), `nbf`, `aud`, `iss`.
- **Bearer prefix stripped** automatically.

### `requires_scope` decorator

Wraps an async tool function, checks the caller's scope, and returns an error
string without executing the tool body if the check fails.

> **Superseded by [ADR-0008](ADR-0008-auth-boundary.md).** As originally
> shipped, this decorator extracted the credential from a `token` / `api_key`
> / `authorization` **tool kwarg** — which placed the credential in the public
> `list_tools()` schema and was wired into no server. ADR-0008 replaces that:
> `requires_scope(scope)` now reads the SDK-verified bearer token from the
> per-request context (`JWTTokenVerifier` + the SDK's bearer-auth middleware);
> the credential is never a tool argument. The kwarg path is fully removed —
> no fallback.

### `auth_tool` on `EnhancedMCP`

Convenience method combining `@mcp.tool()` + `@requires_scope(scope)` in one
decorator. Inherits the ADR-0008 contextvar-based credential model.

### Audit logging

Every auth event (accepted / rejected, including reason) is emitted as structured JSON to the `mcp_toolkit.auth.audit` logger. Operators route this logger to their SIEM or audit sink.

## Consequences

- `JWTAuth` adds `PyJWT[cryptography]` as a dependency (behind the new `[auth]` extra).
- JWKS key fetching is synchronous internally (PyJWT) but wrapped with `run_in_executor` to avoid blocking the async event loop.
- `OAuthAuth` is kept for backward compatibility and for tests that need a simple token issuer without a full IdP.
- Full OAuth 2.1 authorization-server functionality (token issuance, PKCE, refresh) is out of scope — this library is a resource server only.

## Alternatives Rejected

- **Authlib**: more complete but heavier. PyJWT is sufficient for resource-server validation.
- **python-jose**: less maintained; PyJWT is the de-facto standard.
- **Custom JWKS fetch with httpx**: more control but reimplements what `PyJWKClient` already does correctly (caching, rotation, kid matching).
