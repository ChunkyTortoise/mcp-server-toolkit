"""Free slot finder with timezone handling for calendar scheduling."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


@dataclass
class TimeSlot:
    """A time slot representing availability."""

    start: datetime
    end: datetime
    calendar_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_minutes(self) -> int:
        return int((self.end - self.start).total_seconds() / 60)

    def overlaps(self, other: TimeSlot) -> bool:
        return self.start < other.end and other.start < self.end

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "duration_minutes": self.duration_minutes,
            "calendar_id": self.calendar_id,
        }


@dataclass
class BusinessHours:
    """Business hours configuration."""

    start_hour: int = 9
    end_hour: int = 17
    working_days: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])  # Mon-Fri


class AvailabilityFinder:
    """Finds free time slots based on existing events and business hours."""

    def __init__(
        self,
        business_hours: BusinessHours | None = None,
        slot_duration_minutes: int = 30,
    ) -> None:
        self._business_hours = business_hours or BusinessHours()
        self._slot_duration = slot_duration_minutes

    def find_free_slots(
        self,
        start_date: datetime,
        end_date: datetime,
        busy_slots: list[TimeSlot],
        slot_duration_minutes: int | None = None,
    ) -> list[TimeSlot]:
        """Find free time slots within the given date range.

        Args:
            start_date: Start of the search range.
            end_date: End of the search range.
            busy_slots: List of already-booked time slots.
            slot_duration_minutes: Override default slot duration.
        """
        duration = slot_duration_minutes or self._slot_duration
        bh = self._business_hours
        free_slots: list[TimeSlot] = []

        current = start_date.replace(hour=bh.start_hour, minute=0, second=0, microsecond=0)
        if current < start_date:
            current = start_date

        while current < end_date:
            if current.weekday() not in bh.working_days:
                current += timedelta(days=1)
                current = current.replace(hour=bh.start_hour, minute=0, second=0, microsecond=0)
                continue

            if current.hour < bh.start_hour:
                current = current.replace(hour=bh.start_hour, minute=0)

            day_end = current.replace(hour=bh.end_hour, minute=0, second=0)

            while current + timedelta(minutes=duration) <= day_end and current < end_date:
                candidate = TimeSlot(
                    start=current,
                    end=current + timedelta(minutes=duration),
                )
                is_free = not any(candidate.overlaps(busy) for busy in busy_slots)
                if is_free:
                    free_slots.append(candidate)
                current += timedelta(minutes=duration)

            # Move to next day
            current += timedelta(days=1)
            current = current.replace(hour=bh.start_hour, minute=0, second=0, microsecond=0)

        return free_slots

    def next_available(
        self,
        from_time: datetime,
        busy_slots: list[TimeSlot],
    ) -> TimeSlot | None:
        """Find the next available slot from a given time."""
        end = from_time + timedelta(days=14)
        slots = self.find_free_slots(from_time, end, busy_slots)
        return slots[0] if slots else None
