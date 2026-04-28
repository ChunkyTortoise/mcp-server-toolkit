"""Tests for SMTPEmailClient — unit tests only (no real SMTP connection)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from mcp_toolkit.servers.email.smtp_client import SMTPEmailClient

INTEGRATION = os.environ.get("INTEGRATION") == "1"


class TestSMTPClientUnit:
    def test_from_addr_defaults_to_username(self):
        client = SMTPEmailClient(host="smtp.test.com", username="user@test.com")
        assert client.from_addr == "user@test.com"

    def test_from_addr_explicit(self):
        client = SMTPEmailClient(
            host="smtp.test.com", username="user@test.com", from_addr="alias@test.com"
        )
        assert client.from_addr == "alias@test.com"

    @pytest.mark.asyncio
    async def test_send_uses_starttls_by_default(self):
        client = SMTPEmailClient(
            host="smtp.test.com", username="u@t.com", credential="x", use_tls=True
        )
        mock_smtp = MagicMock()
        mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP", return_value=mock_smtp):
            result = await client.send("to@t.com", "Hello", "Body")

        mock_smtp.starttls.assert_called_once()
        mock_smtp.login.assert_called_once_with("u@t.com", "x")
        mock_smtp.sendmail.assert_called_once()
        assert result["status"] == "sent"

    @pytest.mark.asyncio
    async def test_send_uses_ssl_when_configured(self):
        client = SMTPEmailClient(
            host="smtp.test.com", port=465, username="u@t.com", credential="x",
            use_ssl=True, use_tls=False,
        )
        mock_smtp = MagicMock()
        mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP_SSL", return_value=mock_smtp):
            result = await client.send("to@t.com", "Hi", "Text body")

        mock_smtp.sendmail.assert_called_once()
        assert result["status"] == "sent"

    @pytest.mark.asyncio
    async def test_search_returns_empty_without_imap_host(self):
        client = SMTPEmailClient(host="smtp.test.com")
        results = await client.search("hello")
        assert results == []

    @pytest.mark.asyncio
    async def test_send_returns_dict_with_id_and_status(self):
        client = SMTPEmailClient(host="smtp.test.com", username="u@t.com", use_tls=False)
        mock_smtp = MagicMock()
        mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP", return_value=mock_smtp):
            result = await client.send("r@t.com", "Subject", "body")

        assert "id" in result
        assert result["status"] == "sent"
