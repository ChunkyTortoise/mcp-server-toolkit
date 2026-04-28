"""GmailEmailClient — production Gmail client via Google API (OAuth 2.0).

Requires: pip install mcp-server-toolkit[gmail]
  google-api-python-client>=2.100
  google-auth-httplib2>=0.2
  google-auth-oauthlib>=1.2

OAuth scopes required:
  https://www.googleapis.com/auth/gmail.send
  https://www.googleapis.com/auth/gmail.readonly

Usage:
    from google.oauth2.credentials import Credentials
    from mcp_toolkit.servers.email.gmail_client import GmailEmailClient
    from mcp_toolkit.servers.email import server as email_server

    creds = Credentials.from_authorized_user_file("token.json")
    client = GmailEmailClient(credentials=creds)
    email_server.configure(client=client)
"""

from __future__ import annotations

import base64
import email.mime.multipart
import email.mime.text
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class GmailEmailClient:
    """Production Gmail client using the Gmail REST API.

    Pass a ``google.oauth2.credentials.Credentials`` object obtained via
    the standard Google OAuth 2.0 flow. See examples/oauth_resource_server/
    for a wiring example with Auth0 / Google Identity.
    """

    credentials: Any

    def _build_service(self) -> Any:
        try:
            from googleapiclient.discovery import build  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "Install google-api-python-client: pip install mcp-server-toolkit[gmail]"
            ) from exc
        return build("gmail", "v1", credentials=self.credentials)

    async def send(
        self, to: str, subject: str, body: str, cc: str = "", bcc: str = ""
    ) -> dict:
        msg = email.mime.multipart.MIMEMultipart("alternative")
        msg["To"] = to
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = cc
        if bcc:
            msg["Bcc"] = bcc

        is_html = bool(re.search(r"<[a-z][\s\S]*>", body, re.IGNORECASE))
        msg.attach(email.mime.text.MIMEText(body, "html" if is_html else "plain", "utf-8"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service = self._build_service()
        result = service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {"id": result.get("id", "unknown"), "status": "sent"}

    async def search(
        self, query: str, folder: str = "INBOX", limit: int = 20
    ) -> list[dict]:
        service = self._build_service()
        label = "INBOX" if folder.upper() == "INBOX" else folder
        resp = (
            service.users()
            .messages()
            .list(userId="me", q=query, labelIds=[label], maxResults=limit)
            .execute()
        )
        messages = resp.get("messages", [])
        results: list[dict] = []
        for m in messages:
            detail = (
                service.users()
                .messages()
                .get(userId="me", id=m["id"], format="metadata",
                     metadataHeaders=["Subject", "From"])
                .execute()
            )
            headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
            snippet = detail.get("snippet", "")
            results.append({
                "id": m["id"],
                "subject": headers.get("Subject", ""),
                "from": headers.get("From", ""),
                "preview": snippet[:100],
            })
        return results
