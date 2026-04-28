"""SMTPEmailClient — production email client using Python stdlib (smtplib + imaplib).

Requires no extra dependencies beyond the Python standard library.

Usage:
    import os
    from mcp_toolkit.servers.email.smtp_client import SMTPEmailClient
    from mcp_toolkit.servers.email import server as email_server

    client = SMTPEmailClient(
        host="smtp.gmail.com",
        port=587,
        username=os.environ["SMTP_USER"],
        credential=os.environ["SMTP_PASS"],  # Gmail: use an App Password
        use_tls=True,
        imap_host="imap.gmail.com",
    )
    email_server.configure(client=client)
"""

from __future__ import annotations

import email.message
import email.mime.multipart
import email.mime.text
import imaplib
import re
import smtplib
import ssl
from dataclasses import dataclass, field


@dataclass
class SMTPEmailClient:
    """Production SMTP/IMAP email client.

    Set use_tls=True for port 587 (STARTTLS).
    Set use_ssl=True  for port 465 (implicit SSL).
    Set imap_host to enable the search() method.
    """

    host: str
    port: int = 587
    username: str = ""
    credential: str = field(default="", repr=False)
    use_tls: bool = True
    use_ssl: bool = False
    from_addr: str = ""
    imap_host: str = ""
    imap_port: int = 993

    def __post_init__(self) -> None:
        if not self.from_addr:
            self.from_addr = self.username

    async def send(
        self, to: str, subject: str, body: str, cc: str = "", bcc: str = ""
    ) -> dict:
        msg = email.mime.multipart.MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.from_addr
        msg["To"] = to
        if cc:
            msg["Cc"] = cc
        if bcc:
            msg["Bcc"] = bcc

        is_html = bool(re.search(r"<[a-z][\s\S]*>", body, re.IGNORECASE))
        msg.attach(email.mime.text.MIMEText(body, "html" if is_html else "plain", "utf-8"))

        recipients = [a.strip() for a in f"{to},{cc},{bcc}".split(",") if a.strip()]
        ctx = ssl.create_default_context()

        if self.use_ssl:
            with smtplib.SMTP_SSL(self.host, self.port, context=ctx) as smtp:
                if self.credential:
                    smtp.login(self.username, self.credential)
                smtp.sendmail(self.from_addr, recipients, msg.as_string())
        else:
            with smtplib.SMTP(self.host, self.port) as smtp:
                if self.use_tls:
                    smtp.starttls(context=ctx)
                if self.credential:
                    smtp.login(self.username, self.credential)
                smtp.sendmail(self.from_addr, recipients, msg.as_string())

        return {"id": f"smtp-{hash(subject) & 0xFFFFFF:06x}", "status": "sent"}

    async def search(
        self, query: str, folder: str = "INBOX", limit: int = 20
    ) -> list[dict]:
        """Search emails via IMAP. Requires imap_host to be set."""
        if not self.imap_host:
            return []
        results: list[dict] = []
        try:
            with imaplib.IMAP4_SSL(self.imap_host, self.imap_port) as imap:
                imap.login(self.username, self.credential)
                imap.select(folder)
                _, data = imap.search(None, "TEXT", f'"{query}"')
                ids = data[0].split() if data and data[0] else []
                for uid in reversed(ids[-limit:]):
                    _, msg_data = imap.fetch(uid, "(RFC822.HEADER)")
                    if not msg_data or not msg_data[0]:
                        continue
                    parsed = email.message_from_bytes(msg_data[0][1])  # type: ignore[arg-type]
                    results.append(
                        {
                            "id": uid.decode(),
                            "subject": parsed.get("Subject", ""),
                            "from": parsed.get("From", ""),
                            "preview": "",
                        }
                    )
        except Exception:
            pass
        return results
