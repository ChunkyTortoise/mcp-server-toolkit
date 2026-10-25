"""Deploy-mode bind rules and SDK Host/Origin transport security."""

import os
import sys
import time
from contextlib import asynccontextmanager

import httpx
import jwt
import pytest

from mcp_toolkit.gateway.app import create_server, http_options, main

ISSUER = "https://idp.example"
OTHER_ISSUER = "https://other.example"
RESOURCE = "https://orders.example/mcp"
ALLOWED_HOST = "app.example:8000"
LOOPBACK_HOST = "127.0.0.1:8000"
ALLOWED_ORIGIN = "https://app.example"
SDK_LOOPBACK_ORIGIN = "http://127.0.0.1:8000"
ACCEPT = {"Accept": "application/json, text/event-stream"}
PROTOCOL = "2025-11-25"
GATEWAY_SENTENCE = (
    "Deploy mode has no network-trust or mTLS mode. A gateway that will not "
    "forward the user access token cannot be the client of this process."
)
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": PROTOCOL,
        "capabilities": {},
        "clientInfo": {"name": "config-security", "version": "1"},
    },
}


def _clear_mcp_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("MCP_"):
            monkeypatch.delenv(key, raising=False)


def _refuse_serve(monkeypatch):
    def fail_if_serving(self, *args, **kwargs):
        raise AssertionError("server started")

    monkeypatch.setattr("mcp_toolkit.gateway.app.EnhancedMCP.run", fail_if_serving)
    monkeypatch.setattr(sys, "argv", ["examples/http_server.py"])


def _resolve(environ=None, **kwargs):
    from mcp_toolkit.framework.http_auth import resolve_http_server_settings

    return resolve_http_server_settings(environ, **kwargs)


def mint(secret, **overrides):
    claims = {
        "sub": "reader@example.test",
        "iss": ISSUER,
        "aud": RESOURCE,
        "exp": time.time() + 300,
        "scope": "orders:read",
    }
    claims.update(overrides)
    return jwt.encode(claims, secret, algorithm="HS256")


@asynccontextmanager
async def served(**server_kwargs):
    secret = "config-security-test-secret-32bytes"
    settings = _resolve(
        port=8000,
        hosts_configured=server_kwargs.get("allowed_hosts") is not None,
        origins_configured=server_kwargs.get("allowed_origins") is not None,
        **server_kwargs,
    )
    server = create_server(secret=secret, settings=settings)
    app = server.streamable_http_app(**http_options(settings))
    async with server.session_manager.run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://app.example:8000"
        ) as allowed:
            async with httpx.AsyncClient(
                transport=transport, base_url="http://127.0.0.1:8000"
            ) as loopback:
                yield {"secret": secret, "allowed": allowed, "loopback": loopback, "server": server}


def auth_headers(bearer, **extra):
    return {**ACCEPT, "Authorization": f"Bearer {bearer}", **extra}


async def initialize(client, bearer, **extra):
    return await client.post("/mcp", headers=auth_headers(bearer, **extra), json=INITIALIZE)


def _public_env(**extra):
    env = {
        "MCP_HOST": "0.0.0.0",
        "MCP_BIND_PUBLIC": "1",
        "MCP_ISSUER": ISSUER,
        "MCP_RESOURCE_URL": RESOURCE,
        "MCP_ALLOWED_HOSTS": "orders.example",
        "MCP_JWT_SECRET": "config-security-test-secret-32bytes",
    }
    env.update(extra)
    return env


def test_ipv4_loopback_range_is_not_deploy_mode():
    settings = _resolve({"MCP_HOST": "127.8.9.10", "MCP_PORT": "8123"})
    assert settings.deploy_mode is False
    assert settings.host == "127.8.9.10"
    assert settings.resource_url == "http://127.8.9.10:8123/mcp"
    assert settings.transport_security.enable_dns_rebinding_protection is True
    assert "127.8.9.10:*" in settings.transport_security.allowed_hosts


def test_default_bind_is_loopback_without_requiring_issuer():
    settings = _resolve({})
    assert settings.host == "127.0.0.1"
    assert settings.deploy_mode is False
    assert settings.issuer == "http://127.0.0.1:9000"
    assert settings.resource_url == "http://127.0.0.1:8000/mcp"


def test_resource_url_stays_independent_of_bind_address():
    settings = _resolve(
        {
            "MCP_HOST": "127.0.0.1",
            "MCP_PORT": "8123",
            "MCP_RESOURCE_URL": RESOURCE,
            "MCP_ISSUER": ISSUER,
        }
    )
    assert settings.host == "127.0.0.1"
    assert settings.port == 8123
    assert settings.resource_url == RESOURCE
    assert "8123" not in settings.resource_url


def test_non_loopback_bind_exits_without_public_flag(monkeypatch, capsys):
    _clear_mcp_env(monkeypatch)
    _refuse_serve(monkeypatch)
    for key, value in _public_env(MCP_HOST="10.1.2.3").items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("MCP_BIND_PUBLIC", raising=False)
    with pytest.raises(SystemExit) as caught:
        main()
    assert caught.value.code not in (0, None)
    assert "MCP_BIND_PUBLIC=1" in capsys.readouterr().err


def test_deploy_mode_exits_without_issuer(monkeypatch, capsys):
    _clear_mcp_env(monkeypatch)
    _refuse_serve(monkeypatch)
    for key, value in _public_env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("MCP_ISSUER", raising=False)
    with pytest.raises(SystemExit) as caught:
        main()
    assert caught.value.code not in (0, None)
    assert "MCP_ISSUER" in capsys.readouterr().err


def test_deploy_mode_exits_without_resource_url(monkeypatch, capsys):
    _clear_mcp_env(monkeypatch)
    _refuse_serve(monkeypatch)
    for key, value in _public_env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("MCP_RESOURCE_URL", raising=False)
    with pytest.raises(SystemExit) as caught:
        main()
    assert caught.value.code not in (0, None)
    assert "MCP_RESOURCE_URL" in capsys.readouterr().err


def test_public_bind_exits_without_exact_allowed_hosts(monkeypatch, capsys):
    _clear_mcp_env(monkeypatch)
    _refuse_serve(monkeypatch)
    for key, value in _public_env(MCP_ALLOWED_HOSTS="   ").items():
        monkeypatch.setenv(key, value)
    with pytest.raises(SystemExit) as caught:
        main()
    assert caught.value.code not in (0, None)
    assert "MCP_ALLOWED_HOSTS" in capsys.readouterr().err


def test_public_bind_rejects_wildcard_allowed_hosts(monkeypatch, capsys):
    _clear_mcp_env(monkeypatch)
    _refuse_serve(monkeypatch)
    for key, value in _public_env(MCP_ALLOWED_HOSTS="orders.example:*").items():
        monkeypatch.setenv(key, value)
    with pytest.raises(SystemExit) as caught:
        main()
    assert caught.value.code not in (0, None)
    assert "exact" in capsys.readouterr().err


def test_public_bind_feeds_exact_hosts_and_empty_origins_to_the_sdk():
    settings = _resolve(
        _public_env(
            MCP_ALLOWED_HOSTS=" orders.example , orders.example:443 ", MCP_ALLOWED_ORIGINS=""
        )
    )
    assert settings.deploy_mode is True
    assert settings.transport_security is not None
    assert settings.transport_security.enable_dns_rebinding_protection is True
    assert settings.transport_security.allowed_hosts == ["orders.example", "orders.example:443"]
    assert settings.transport_security.allowed_origins == []


def test_loopback_wildcard_host_pattern_is_passed_through():
    settings = _resolve({"MCP_HOST": "::1", "MCP_ALLOWED_HOSTS": "[::1]:*"})
    assert settings.deploy_mode is False
    assert settings.host == "::1"
    assert settings.transport_security is not None
    assert settings.transport_security.allowed_hosts == ["[::1]:*"]


async def test_wrong_issuer_gets_401():
    async with served(
        host="0.0.0.0",
        bind_public=True,
        issuer=ISSUER,
        resource_url=RESOURCE,
        allowed_hosts=[ALLOWED_HOST],
        allowed_origins=[ALLOWED_ORIGIN],
    ) as server:
        bearer = mint(server["secret"], iss=OTHER_ISSUER)
        response = await initialize(server["allowed"], bearer)
    assert response.status_code == 401


async def test_allowed_host_succeeds():
    async with served(
        host="0.0.0.0",
        bind_public=True,
        issuer=ISSUER,
        resource_url=RESOURCE,
        allowed_hosts=[ALLOWED_HOST],
        allowed_origins=[ALLOWED_ORIGIN],
    ) as server:
        response = await initialize(server["allowed"], mint(server["secret"]))
    assert response.status_code == 200


async def test_wrong_host_gets_421():
    async with served(
        host="0.0.0.0",
        bind_public=True,
        issuer=ISSUER,
        resource_url=RESOURCE,
        allowed_hosts=[ALLOWED_HOST],
        allowed_origins=[ALLOWED_ORIGIN],
    ) as server:
        response = await initialize(server["loopback"], mint(server["secret"]))
    assert response.status_code == 421
    assert "Invalid Host" in response.text


async def test_allowed_origin_succeeds():
    async with served(
        host="0.0.0.0",
        bind_public=True,
        issuer=ISSUER,
        resource_url=RESOURCE,
        allowed_hosts=[ALLOWED_HOST],
        allowed_origins=[ALLOWED_ORIGIN],
    ) as server:
        response = await initialize(
            server["allowed"], mint(server["secret"]), Origin=ALLOWED_ORIGIN
        )
    assert response.status_code == 200


async def test_bad_origin_gets_403():
    async with served(
        host="0.0.0.0",
        bind_public=True,
        issuer=ISSUER,
        resource_url=RESOURCE,
        allowed_hosts=[ALLOWED_HOST],
        allowed_origins=[ALLOWED_ORIGIN],
    ) as server:
        response = await initialize(
            server["allowed"], mint(server["secret"]), Origin=SDK_LOOPBACK_ORIGIN
        )
    assert response.status_code == 403
    assert "Invalid Origin" in response.text


async def test_omitted_origin_succeeds():
    async with served(
        host="0.0.0.0",
        bind_public=True,
        issuer=ISSUER,
        resource_url=RESOURCE,
        allowed_hosts=[ALLOWED_HOST],
        allowed_origins=[],
    ) as server:
        response = await initialize(server["allowed"], mint(server["secret"]))
        assert response.status_code == 200
        rejected = await initialize(
            server["allowed"], mint(server["secret"]), Origin=SDK_LOOPBACK_ORIGIN
        )
    assert rejected.status_code == 403
    assert "Invalid Origin" in rejected.text


async def test_forwarded_headers_without_bearer_get_401():
    async with served(issuer=ISSUER, resource_url=RESOURCE) as server:
        bearer = mint(server["secret"])
        cases = (
            {"X-Forwarded-User": "alice"},
            {"X-Forwarded-Access-Token": bearer},
            {"X-Forwarded-User": "alice", "X-Forwarded-Access-Token": bearer},
        )
        for forwarded in cases:
            response = await server["loopback"].post(
                "/mcp",
                headers={**ACCEPT, **forwarded},
                json=INITIALIZE,
            )
            assert response.status_code == 401


def test_gmail_client_docstring_does_not_cite_missing_oauth_example():
    from pathlib import Path

    source = Path("mcp_toolkit/servers/email/gmail_client.py").read_text()
    assert "oauth_resource_server" not in source


def test_docs_require_the_gateway_to_forward_the_access_token():
    from pathlib import Path

    adr = Path("docs/adr/ADR-0008-transport-auth.md").read_text()
    deployment = Path("docs/DEPLOYMENT.md").read_text()
    for text in (adr, deployment):
        assert GATEWAY_SENTENCE in " ".join(text.split())
    assert "DATABASE_URL" in adr
    assert "not an oauth proxy" in adr.lower()
    assert "not an oauth proxy" in deployment.lower()


@pytest.mark.parametrize("host", ["127.0.0.1", "127.8.9.10", "LOCALHOST", "::1", "0:0:0:0:0:0:0:1"])
async def test_every_loopback_bind_rejects_rebinding_host(host):
    async with served(host=host, issuer=ISSUER, resource_url=RESOURCE) as server:
        response = await initialize(
            server["loopback"], mint(server["secret"]), Host="rebind.attacker.example:8000"
        )
        assert response.status_code == 421


@pytest.mark.parametrize("host", ["127.0.0.1", "127.8.9.10", "LOCALHOST", "::1", "0:0:0:0:0:0:0:1"])
async def test_every_loopback_bind_rejects_unlisted_origin(host):
    async with served(host=host, issuer=ISSUER, resource_url=RESOURCE) as server:
        response = await initialize(
            server["loopback"], mint(server["secret"]), Origin="https://attacker.example"
        )
        assert response.status_code == 403


async def test_unset_deploy_origin_list_rejects_supplied_origin():
    async with served(
        host="0.0.0.0",
        bind_public=True,
        issuer=ISSUER,
        resource_url=RESOURCE,
        allowed_hosts=[ALLOWED_HOST],
    ) as server:
        no_origin = await initialize(server["allowed"], mint(server["secret"]))
        assert no_origin.status_code == 200
        with_origin = await initialize(
            server["allowed"], mint(server["secret"]), Origin=ALLOWED_ORIGIN
        )
        assert with_origin.status_code == 403


@pytest.mark.parametrize("deploy_mode", [False, True])
def test_hand_built_public_settings_cannot_skip_explicit_opt_in(deploy_mode):
    from mcp.server.transport_security import TransportSecuritySettings
    from mcp_toolkit.framework.http_auth import HttpConfigError, HttpServerSettings

    with pytest.raises(HttpConfigError):
        settings = HttpServerSettings(
            host="0.0.0.0",
            port=8000,
            resource_url=RESOURCE,
            issuer=ISSUER,
            deploy_mode=deploy_mode,
            allowed_hosts=[ALLOWED_HOST],
            allowed_origins=[],
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=[ALLOWED_HOST],
                allowed_origins=[],
            ),
        )
        create_server(settings=settings, secret="settings-probe-secret-at-least-32bytes")


def test_resolved_settings_fields_cannot_be_mutated_to_a_public_bind():
    from dataclasses import FrozenInstanceError

    settings = _resolve({})
    with pytest.raises(FrozenInstanceError):
        settings.host = "0.0.0.0"


def test_factory_revalidates_mutated_nested_transport_settings():
    from mcp_toolkit.framework.http_auth import HttpConfigError

    settings = _resolve(_public_env())
    settings.transport_security.enable_dns_rebinding_protection = False
    with pytest.raises(HttpConfigError):
        create_server(settings=settings, secret="settings-probe-secret-at-least-32bytes")


@pytest.mark.parametrize("name", ["MCP_ISSUER", "MCP_RESOURCE_URL"])
@pytest.mark.parametrize(
    "value",
    [
        "not-a-url-sentinel",
        "ftp://api.example/mcp",
        "https://user:sentinel-uri-password@api.example/mcp",
        "https://api.example/mcp#fragment",
    ],
)
def test_invalid_or_credential_bearing_config_urls_fail_with_generic_errors(name, value):
    from mcp_toolkit.framework.http_auth import HttpConfigError

    env = _public_env(**{name: value})
    with pytest.raises(HttpConfigError) as error:
        _resolve(env)
    assert name in str(error.value)
    assert "sentinel" not in str(error.value)


def test_invalid_port_error_does_not_echo_its_value_or_cause():
    import traceback
    from mcp_toolkit.framework.http_auth import HttpConfigError

    sensitive_value = "sentinel-port-secret"
    with pytest.raises(HttpConfigError) as error:
        _resolve({"MCP_PORT": sensitive_value})
    rendered = "".join(
        traceback.format_exception(type(error.value), error.value, error.value.__traceback__)
    )
    assert "MCP_PORT" in rendered
    assert sensitive_value not in rendered


@pytest.mark.parametrize("flag", ["true", "yes", "0", ""])
def test_public_bind_requires_exact_opt_in_value(monkeypatch, capsys, flag):
    _clear_mcp_env(monkeypatch)
    _refuse_serve(monkeypatch)
    for key, value in _public_env(MCP_BIND_PUBLIC=flag).items():
        monkeypatch.setenv(key, value)
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "MCP_BIND_PUBLIC" in capsys.readouterr().err


def test_cli_does_not_publish_or_echo_credential_bearing_resource_url(monkeypatch, capsys):
    _clear_mcp_env(monkeypatch)
    _refuse_serve(monkeypatch)
    value = "https://user:sentinel-uri-password@orders.example/mcp"
    for key, setting in _public_env(MCP_RESOURCE_URL=value).items():
        monkeypatch.setenv(key, setting)
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    output = capsys.readouterr()
    assert "MCP_RESOURCE_URL" in output.err
    assert "sentinel-uri-password" not in output.err + output.out


@pytest.mark.parametrize("public", [False, True])
def test_factory_rejects_nested_origin_list_drift(public):
    from mcp_toolkit.framework.http_auth import HttpConfigError

    env = _public_env(MCP_ALLOWED_ORIGINS=ALLOWED_ORIGIN) if public else {}
    settings = _resolve(env)
    settings.transport_security.allowed_origins.append("https://attacker.example")
    with pytest.raises(HttpConfigError):
        create_server(settings=settings, secret="settings-probe-secret-at-least-32bytes")
