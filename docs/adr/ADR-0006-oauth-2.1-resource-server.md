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

Wraps an async tool function. Extracts credential from `token`, `api_key`, or `authorization` kwargs, validates it, checks the required scope, and returns an error string without executing the tool body if either check fails.

### `auth_tool` on `EnhancedMCP`

Convenience method combining `@mcp.tool()` + `@requires_scope(auth, scope)` in one decorator.

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
