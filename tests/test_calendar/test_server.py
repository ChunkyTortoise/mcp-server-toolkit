"""Tests for Calendar MCP server."""

from datetime import datetime

import pytest

from mcp_toolkit.framework.testing import MCPTestClient
from mcp_toolkit.servers.calendar.availability import AvailabilityFinder, TimeSlot
from mcp_toolkit.servers.calendar.server import MockCalendarProvider, configure
from mcp_toolkit.servers.calendar.server import mcp as cal_mcp


@pytest.fixture
def client():
    configure(provider=MockCalendarProvider())
    return MCPTestClient(cal_mcp)


class TestCreateEvent:
    async def test_create_basic_event(self, client):
        result = await client.call_tool(
            "create_event",
            {
                "title": "Team Meeting",
                "start_time": "2026-02-17T10:00:00",
                "end_time": "2026-02-17T11:00:00",
            },
        )
        assert "Event created" in result
        assert "Team Meeting" in result

    async def test_create_with_attendees(self, client):
        result = await client.call_tool(
            "create_event",
            {
                "title": "Review",
                "start_time": "2026-02-17T14:00:00",
                "end_time": "2026-02-17T15:00:00",
                "attendees": "alice@test.com, bob@test.com",
            },
        )
        assert "Event created" in result


class TestListEvents:
    async def test_list_no_events(self, client):
        result = await client.call_tool(
            "list_events",
            {
                "start_date": "2026-02-17T00:00:00",
                "end_date": "2026-02-17T23:59:00",
            },
        )
        assert "No events" in result

    async def test_list_after_create(self, client):
        await client.call_tool(
            "create_event",
            {
                "title": "Standup",
                "start_time": "2026-02-17T09:00:00",
                "end_time": "2026-02-17T09:30:00",
            },
        )
        result = await client.call_tool(
            "list_events",
            {
                "start_date": "2026-02-17T00:00:00",
                "end_date": "2026-02-17T23:59:00",
            },
        )
        assert "Standup" in result


class TestDeleteEvent:
    async def test_delete_nonexistent(self, client):
        result = await client.call_tool("delete_event", {"event_id": "xxx"})
        assert "not found" in result

    async def test_delete_existing(self, client):
        await client.call_tool(
            "create_event",
            {
                "title": "Delete Me",
                "start_time": "2026-02-17T10:00:00",
                "end_time": "2026-02-17T11:00:00",
            },
        )
        result = await client.call_tool("delete_event", {"event_id": "evt_1"})
        assert "deleted" in result


class TestFindFreeSlots:
    async def test_find_slots_empty_calendar(self, client):
        # Monday Feb 17 2026 is a weekday
        result = await client.call_tool(
            "find_free_slots",
            {
                "start_date": "2026-02-17T00:00:00",
                "end_date": "2026-02-17T23:59:00",
                "duration_minutes": 30,
            },
        )
        assert "free" in result.lower()


class TestAvailabilityFinder:
    def test_find_free_slots_no_busy(self):
        finder = AvailabilityFinder(slot_duration_minutes=60)
        start = datetime(2026, 2, 17, 0, 0)  # Monday
        end = datetime(2026, 2, 17, 23, 59)
        slots = finder.find_free_slots(start, end, busy_slots=[])
        assert len(slots) > 0
        # 9-17 = 8 hours = 8 one-hour slots
        assert len(slots) == 8

    def test_find_free_slots_with_busy(self):
        finder = AvailabilityFinder(slot_duration_minutes=60)
        start = datetime(2026, 2, 17, 0, 0)
        end = datetime(2026, 2, 17, 23, 59)
        busy = [TimeSlot(start=datetime(2026, 2, 17, 10, 0), end=datetime(2026, 2, 17, 11, 0))]
        slots = finder.find_free_slots(start, end, busy_slots=busy)
        # 8 possible minus 1 busy = 7
        assert len(slots) == 7

    def test_skips_weekends(self):
        finder = AvailabilityFinder(slot_duration_minutes=60)
        # Saturday Feb 21, 2026
        start = datetime(2026, 2, 21, 0, 0)
        end = datetime(2026, 2, 21, 23, 59)
        slots = finder.find_free_slots(start, end, busy_slots=[])
        assert len(slots) == 0

    def test_next_available(self):
        finder = AvailabilityFinder(slot_duration_minutes=30)
        now = datetime(2026, 2, 17, 9, 0)
        slot = finder.next_available(now, busy_slots=[])
        assert slot is not None
        assert slot.duration_minutes == 30

    def test_time_slot_overlaps(self):
        a = TimeSlot(start=datetime(2026, 1, 1, 10, 0), end=datetime(2026, 1, 1, 11, 0))
        b = TimeSlot(start=datetime(2026, 1, 1, 10, 30), end=datetime(2026, 1, 1, 11, 30))
        c = TimeSlot(start=datetime(2026, 1, 1, 11, 0), end=datetime(2026, 1, 1, 12, 0))
        assert a.overlaps(b) is True
        assert a.overlaps(c) is False

    def test_time_slot_to_dict(self):
        slot = TimeSlot(start=datetime(2026, 1, 1, 10, 0), end=datetime(2026, 1, 1, 10, 30))
        d = slot.to_dict()
        assert "start" in d
        assert d["duration_minutes"] == 30


class TestToolListing:
    async def test_has_expected_tools(self, client):
        tools = await client.list_tools()
        names = {t["name"] for t in tools}
        assert "list_events" in names
        assert "create_event" in names
        assert "find_free_slots" in names
        assert "delete_event" in names
