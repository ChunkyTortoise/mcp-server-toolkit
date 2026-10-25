# Deployment

HTTP bind and credential rules for `mcp-toolkit-gateway` (`mcp_toolkit/gateway/app.py`). Later deployment
notes extend this file. The behavior below is the one exercised by
`tests/test_gateway/test_http_config_security.py` and recorded in
[ADR-0008](adr/ADR-0008-transport-auth.md).

## HTTP bind

`MCP_HOST` defaults to `127.0.0.1`. `MCP_PORT` defaults to `8000`.
`MCP_RESOURCE_URL` is the token audience. On a loopback bind it defaults to
the local `/mcp` URL. Deploy mode, any non-loopback bind, does not use that
default.

A non-loopback bind does not start unless `MCP_BIND_PUBLIC=1`. Deploy mode
also requires `MCP_ISSUER`, `MCP_RESOURCE_URL`, and an exact `MCP_ALLOWED_HOSTS`
list. Wildcard host entries are rejected. `MCP_ALLOWED_ORIGINS` is the Origin
allow list. An empty list rejects every request that sends Origin and accepts
a request that omits Origin. Both lists are passed to the SDK
`transport_security` settings.

Deploy mode has no network-trust or mTLS mode. A gateway that will not forward
the user access token cannot be the client of this process. Only the
Authorization bearer is identity. `X-Forwarded-User` and
`X-Forwarded-Access-Token` are not.

## Credentials

The SDK verifies the inbound bearer and retains it in request/session context.
The tool input schemas omit credentials; trusted tool code can read the SDK
context. This is not a claim of memory erasure. The example has no application
token store and makes no downstream HTTP call. It is not an OAuth proxy.
Backend credentials, such as `DATABASE_URL`, belong in the process environment
of an integrating server, separate from the inbound bearer.

Every loopback spelling receives explicit SDK Host/Origin protection. Public
settings are field-frozen and revalidated before use. Published issuer/resource
URLs cannot contain userinfo or fragments, and configuration errors do not echo
invalid URL or port values. TLS termination remains a deployment responsibility.
