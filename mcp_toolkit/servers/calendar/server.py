"""Calendar MCP Server — Event management and scheduling."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from mcp_toolkit.framework.base_server import EnhancedMCP
from mcp_toolkit.servers.calendar.availability import AvailabilityFinder, BusinessHours, TimeSlot

mcp = EnhancedMCP("calendar")

_availability_finder = AvailabilityFinder()


@dataclass
class CalendarEvent:
    id: str
    title: str
    start: datetime
    end: datetime
    description: str = ""
    attendees: list[str] = field(default_factory=list)
    calendar_id: str = "default"


class CalendarProvider(Protocol):
    async def list_events(
        self, start: datetime, end: datetime, calendar_id: str
    ) -> list[CalendarEvent]: ...

    async def create_event(self, event: CalendarEvent) -> CalendarEvent: ...

    async def delete_event(self, event_id: str) -> bool: ...


class MockCalendarProvider:
    def __init__(self) -> None:
        self._events: dict[str, CalendarEvent] = {}
        self._counter = 0

    async def list_events(
        self, start: datetime, end: datetime, calendar_id: str = "default"
    ) -> list[CalendarEvent]:
        return [
            e
            for e in self._events.values()
            if e.start >= start and e.end <= end and e.calendar_id == calendar_id
        ]

    async def create_event(self, event: CalendarEvent) -> CalendarEvent:
        self._counter += 1
        event.id = f"evt_{self._counter}"
        self._events[event.id] = event
        return event

    async def delete_event(self, event_id: str) -> bool:
        if event_id in self._events:
            del self._events[event_id]
            return True
        return False


_provider: CalendarProvider = MockCalendarProvider()


def configure(
    provider: CalendarProvider | None = None, business_hours: BusinessHours | None = None
) -> None:
    global _provider, _availability_finder
    if provider:
        _provider = provider
    if business_hours:
        _availability_finder = AvailabilityFinder(business_hours=business_hours)


@mcp.tool()
async def list_events(
    start_date: str,
    end_date: str,
    calendar_id: str = "default",
) -> str:
    """List calendar events in a date range.

    Args:
        start_date: Start date (ISO 8601, e.g., "2026-02-16T00:00:00").
        end_date: End date (ISO 8601).
        calendar_id: Calendar ID (default "default").
    """
    start = datetime.fromisoformat(start_date)
    end = datetime.fromisoformat(end_date)
    events = await _provider.list_events(start, end, calendar_id)

    if not events:
        return f"No events found between {start_date} and {end_date}."

    lines = [f"**{len(events)} events:**"]
    for e in events:
        lines.append(f"- [{e.id}] **{e.title}** | {e.start.isoformat()} - {e.end.isoformat()}")
    return "\n".join(lines)


@mcp.tool()
async def create_event(
    title: str,
    start_time: str,
    end_time: str,
    description: str = "",
    attendees: str = "",
    calendar_id: str = "default",
) -> str:
    """Create a new calendar event.

    Args:
        title: Event title.
        start_time: Start time (ISO 8601).
        end_time: End time (ISO 8601).
        description: Event description.
        attendees: Comma-separated email addresses.
        calendar_id: Calendar ID.
    """
    attendee_list = [a.strip() for a in attendees.split(",") if a.strip()] if attendees else []
    event = CalendarEvent(
        id="",
        title=title,
        start=datetime.fromisoformat(start_time),
        end=datetime.fromisoformat(end_time),
        description=description,
        attendees=attendee_list,
        calendar_id=calendar_id,
    )
    created = await _provider.create_event(event)
    return f"Event created: {created.id} — {title} ({start_time} to {end_time})"


@mcp.tool()
async def find_free_slots(
    start_date: str,
    end_date: str,
    duration_minutes: int = 30,
    calendar_id: str = "default",
) -> str:
    """Find available time slots for scheduling.

    Args:
        start_date: Start of search range (ISO 8601).
        end_date: End of search range (ISO 8601).
        duration_minutes: Required slot duration (default 30).
        calendar_id: Calendar to check.
    """
    start = datetime.fromisoformat(start_date)
    end = datetime.fromisoformat(end_date)
    events = await _provider.list_events(start, end, calendar_id)

    busy_slots = [TimeSlot(start=e.start, end=e.end, calendar_id=e.calendar_id) for e in events]

    free = _availability_finder.find_free_slots(start, end, busy_slots, duration_minutes)

    if not free:
        return "No free slots available in the requested range."

    # Limit to first 20 slots
    display = free[:20]
    lines = [
        f"**{len(free)} free {duration_minutes}-min slots found** (showing first {len(display)}):"
    ]
    for slot in display:
        lines.append(f"- {slot.start.strftime('%Y-%m-%d %H:%M')} - {slot.end.strftime('%H:%M')}")
    return "\n".join(lines)


@mcp.tool()
async def delete_event(event_id: str) -> str:
    """Delete a calendar event by ID.

    Args:
        event_id: The event ID to delete.
    """
    deleted = await _provider.delete_event(event_id)
    if deleted:
        return f"Event {event_id} deleted."
    return f"Event {event_id} not found."
