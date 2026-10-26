# ADR-0008: JWT bearer authentication at the HTTP transport

Status: Accepted

This extends [ADR-0006](ADR-0006-oauth-2.1-resource-server.md). Tool-argument
credentials remain a local and test pattern. The HTTP example validates a bearer
in the Authorization header through the MCP SDK TokenVerifier interface; neither
of its tools has a token or credential input property. This process is a resource
server. It is not an authorization server and not an OAuth proxy. It implements
neither login nor dynamic client registration.

## Decision

[http_auth.py](../../mcp_toolkit/framework/http_auth.py) adapts JWTAuth to the SDK
AccessToken. A canonical resource audience is required. Verification checks the
signature, configured issuer, matching audience and a finite numeric expiry that
has not passed. It rejects malformed identity and scope values. The verified
subject and issuer are retained for SDK session ownership. JWTAuth writes the
auth audit event; the adapter does not add a duplicate success event. A
transport-specific claim-shape rejection follows JWTAuth's accepted event with
jwt.rejected (invalid_transport_claims); both events carry the same client_hash.
The accepted event describes JWTAuth validation, not final transport admission.
Issuer verification is optional for library callers and enforced when configured;
the executable example always supplies an issuer.

[mcp_toolkit/gateway/app.py](../../mcp_toolkit/gateway/app.py) (`mcp-toolkit-gateway`,
or `examples/http_server.py` from a checkout) runs streamable HTTP on
127.0.0.1:8000 by default. MCP_HOST and MCP_PORT control the bind address.
MCP_RESOURCE_URL is the canonical audience and protected-resource identifier.
On a loopback bind it defaults to the local /mcp URL. It is not derived from a
non-loopback bind. MCP_ISSUER identifies the expected issuer. On a loopback bind
it defaults to the loopback demo issuer. A non-loopback address is deploy mode.
Deploy mode does not start unless MCP_BIND_PUBLIC=1, and it requires MCP_ISSUER
and MCP_RESOURCE_URL. MCP_ALLOWED_HOSTS and MCP_ALLOWED_ORIGINS are passed to
the SDK transport_security settings. A public bind requires an exact host list,
with no wildcard entries. An empty origin list rejects every supplied Origin
and accepts a request that omits Origin. Every recognized loopback bind receives
explicit SDK Host/Origin protection, including the 127/8 range, uppercase
localhost and expanded IPv6 loopback spellings. Unset lists keep the SDK's
loopback aliases and add the actual bind address. Setting one list preserves
those defaults for the unset side.
Deploy mode has no network-trust or mTLS mode. A gateway that will not forward
the user access token cannot be the client of this process. Only Authorization
is identity. X-Forwarded-User and X-Forwarded-Access-Token are not.

The resolved settings have frozen fields and validate their invariants at
construction. The example revalidates before using a settings object, including
nested SDK protection and allow-list consistency. Published issuer/resource
URLs must be valid HTTP(S) URLs without userinfo or fragments. Invalid URL/port
configuration produces a generic configuration error without echoing the value.
These checks do not add TLS termination or change the SDK's Origin-pattern rules.

MCP_JWKS_URI selects RS256 verification using keys supplied by an issuer.
Alternatively, MCP_JWT_SECRET selects HS256 for a local demo. Exactly one key
source is required. The --print-demo-token SCOPES flag works only in HS256 mode
and prints a five-minute demo token with the configured audience and issuer.

## Credential flow

| Hop | Credential | What this example does |
| --- | --- | --- |
| Inbound | Authorization bearer | Verified by the SDK TokenVerifier and retained in SDK request/session context. Neither tool has a token input argument. |
| Downstream | Service credentials such as DATABASE_URL | Not used by this synthetic orders example; backend credentials belong in the process environment of an integrating server. No bearer is forwarded. |

The SDK retains an AccessToken for authentication context; this is not a claim
that the bearer is erased from process memory. The example does not exchange it,
persist it in an application token store or forward it downstream. The server
is not an OAuth proxy.

The endpoint requires orders:read through AuthSettings.required_scopes. The SDK
RequireAuthMiddleware returns HTTP 401 for missing or invalid bearer credentials,
with a protected-resource metadata pointer, and HTTP 403 insufficient_scope for
an authenticated token without the endpoint scope, before tool dispatch.
get_order reads synthetic data. cancel_order additionally calls require_scope
for orders:write, raising Forbidden as an MCP isError result before its demo
operation. The read tool carries readOnlyHint and the cancel tool carries
destructiveHint; these annotations describe effects and do not enforce access.

Both tools use the toolkit rate limiter. Scope checks and rate limits read the
verified token from the current per-message HTTP Request. They do not rely on
the initialize request's inherited auth context, which remains stale inside an
SDK 1.29.1 stateful handler task. This allows scope reductions and increases on
a refreshed credential to take effect on the next call.

The local cached_tool decorator refuses authenticated HTTP calls. Its shared
cache can skip handler-level authorization on a hit and is not tenant-scoped.
HTTP tools needing caching must supply a separate design that authorizes each
call before returning identity-scoped data.

Both example tools use the toolkit rate limiter. For authenticated HTTP calls the limiter
uses the verified subject (or client identity when no subject exists), with an
issuer-specific bucket. Subject and client identity occupy separate rate-key
namespaces, so a client id equal to a user's subject cannot share its bucket.
Caller-supplied tool arguments cannot change that bucket.
Local calls retain the argument-based fallback described in
[ADR-0005](ADR-0005-rate-limit-distribution.md). Audit identities and span
mcp.subject contain SHA256 prefixes of 16 hex characters, never raw subject.
The bearer and tool arguments are not recorded in the toolkit call spans.

## Session behavior

The example leaves stateless_http unset. SDK 1.29.1 creates a stateful session and
returns Mcp-Session-Id at initialize. The SDK binds that session to the verified
principal (subject, or client identity when no subject is supplied) and issuer.
The current adapter maps AccessToken.client_id to that principal; a separate
client_id claim does not add a distinct client boundary when sub is present.
Reusing the session as another subject returns HTTP 404, with
no handler call. Reusing it without Authorization returns HTTP 401. A refreshed
token for the same principal can reuse the session, but each tool checks that
request's current scopes, including after the creator token has expired. This is not the stateless
transport described by the 2026-07-28 protocol revision.

## Evidence and limits

[test_transport_auth.py](../../tests/test_gateway/test_transport_auth.py) boots the packaged
gateway on a local port and uses the non-deprecated streamable_http_client with
an httpx.AsyncClient carrying Authorization. It tests missing, forged,
wrong-audience, missing-expiry and expired tokens, protected-resource metadata,
authorized reads, per-tool refusals, annotations and credential-free schemas.
An in-process RSA key and localhost JWKS exercise the RS256 path with
MCP_JWT_SECRET absent and a wrong-audience rejection. The same file exercises
real SDK HTTP middleware with handler counters for endpoint-scope and session
refusals, refreshed-token session reuse, and caller-argument rate-limit evasion.
It also checks both directions of scope replacement, denies reuse of an expired
creator token's write authority, refuses authenticated HTTP cache access, checks
demo-token expiry and refuses demo minting in JWKS-only mode.

[test_http_auth.py](../../tests/test_framework/test_http_auth.py) covers strict
expiry types, audience lists, issuer rejection, identity and scope formats,
per-tool scope checks, hashed subjects, separate issuer/client rate buckets,
correlated transport rejection events and one audit event for successful auth.

The tests use local keys, not a live identity provider. They do not demonstrate
TLS termination, login, or revocation at a remote issuer.
[test_gateway/test_http_config_security.py](../../tests/test_gateway/test_http_config_security.py) covers
deploy-mode refusal, the separation of MCP_RESOURCE_URL from the bind address,
wrong issuer, allowed and rejected Host and Origin values, an omitted Origin,
and forwarded identity headers with no bearer.
Rate-limit counters and sessions live in one process. Shared limits and sessions
across replicas require a separate deployment design.
