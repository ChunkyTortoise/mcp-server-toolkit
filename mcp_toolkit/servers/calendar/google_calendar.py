"""GoogleCalendarProvider — production Google Calendar client via REST API.

Requires: pip install mcp-server-toolkit[gcal]
  google-api-python-client>=2.100
  google-auth-httplib2>=0.2
  google-auth-oauthlib>=1.2

OAuth scopes required:
  https://www.googleapis.com/auth/calendar
  https://www.googleapis.com/auth/calendar.readonly

Usage:
    from google.oauth2.credentials import Credentials
    from mcp_toolkit.servers.calendar.google_calendar import GoogleCalendarProvider
    from mcp_toolkit.servers.calendar import server as cal_server

    creds = Credentials.from_authorized_user_file("token.json")
    provider = GoogleCalendarProvider(credentials=creds, calendar_id="primary")
    cal_server.configure(provider=provider)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from mcp_toolkit.servers.calendar.server import CalendarEvent


@dataclass
class GoogleCalendarProvider:
    """Production CalendarProvider backed by the Google Calendar REST API."""

    credentials: Any
    calendar_id: str = "primary"
    _service: Any = field(default=None, init=False, repr=False)

    def _build(self) -> Any:
        if self._service is None:
            try:
                from googleapiclient.discovery import build  # type: ignore[import-untyped]
            except ImportError as exc:
                raise ImportError(
                    "Install google-api-python-client: pip install mcp-server-toolkit[gcal]"
                ) from exc
            self._service = build("calendar", "v3", credentials=self.credentials)
        return self._service

    async def list_events(
        self, start: datetime, end: datetime, calendar_id: str = "primary"
    ) -> list[CalendarEvent]:
        cal_id = calendar_id or self.calendar_id
        svc = self._build()
        result = (
            svc.events()
            .list(
                calendarId=cal_id,
                timeMin=start.isoformat() + "Z",
                timeMax=end.isoformat() + "Z",
                singleEvents=True,
                orderBy="startTime",
                maxResults=250,
            )
            .execute()
        )
        events: list[CalendarEvent] = []
        for item in result.get("items", []):
            start_raw = item["start"].get("dateTime") or item["start"].get("date") + "T00:00:00"
            end_raw = item["end"].get("dateTime") or item["end"].get("date") + "T23:59:59"
            events.append(
                CalendarEvent(
                    id=item["id"],
                    title=item.get("summary", "(No title)"),
                    start=datetime.fromisoformat(start_raw.rstrip("Z")),
                    end=datetime.fromisoformat(end_raw.rstrip("Z")),
                    description=item.get("description", ""),
                    attendees=[
                        a.get("email", "") for a in item.get("attendees", [])
                    ],
                    calendar_id=cal_id,
                )
            )
        return events

    async def create_event(self, event: CalendarEvent) -> CalendarEvent:
        svc = self._build()
        body: dict[str, Any] = {
            "summary": event.title,
            "description": event.description,
            "start": {"dateTime": event.start.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": event.end.isoformat(), "timeZone": "UTC"},
        }
        if event.attendees:
            body["attendees"] = [{"email": a} for a in event.attendees]

        result = (
            svc.events()
            .insert(calendarId=event.calendar_id or self.calendar_id, body=body)
            .execute()
        )
        event.id = result["id"]
        return event

    async def delete_event(self, event_id: str) -> bool:
        svc = self._build()
        try:
            svc.events().delete(calendarId=self.calendar_id, eventId=event_id).execute()
            return True
        except Exception:
            return False
