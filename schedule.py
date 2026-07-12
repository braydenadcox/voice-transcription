from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path


SCHEDULE_PATH = Path("schedule.json")
RECURRENCES = {"none", "daily", "weekly", "custom"}


@dataclass
class MeetingSlot:
    title: str
    start: dt.datetime
    end: dt.datetime
    recurrence: str = "none"
    custom_days: list[int] = field(default_factory=list)
    include_mic: bool = True
    recording_name: str = "meeting"
    auto_transcribe: bool = True
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    last_started: str | None = None

    def validate(self) -> None:
        if not self.title.strip():
            raise ValueError("Title is required.")
        if self.end <= self.start:
            raise ValueError("End time must be after start time.")
        if self.recurrence not in RECURRENCES:
            raise ValueError("Unknown recurrence pattern.")
        if self.recurrence == "custom" and not self.custom_days:
            raise ValueError("Choose at least one day for a custom recurrence.")
        if any(day not in range(7) for day in self.custom_days):
            raise ValueError("Custom weekdays must be between Monday and Sunday.")

    @property
    def duration(self) -> dt.timedelta:
        return self.end - self.start

    def occurs_on(self, day: dt.date) -> bool:
        if day < self.start.date():
            return False
        if self.recurrence == "none":
            return day == self.start.date()
        if self.recurrence == "daily":
            return True
        if self.recurrence == "weekly":
            return day.weekday() == self.start.weekday()
        return day.weekday() in self.custom_days

    def occurrence_start(self, day: dt.date) -> dt.datetime:
        return dt.datetime.combine(day, self.start.time())

    def active_occurrence(self, now: dt.datetime) -> tuple[dt.datetime, dt.datetime] | None:
        # Yesterday matters for meeting windows that cross midnight.
        for day in (now.date(), now.date() - dt.timedelta(days=1)):
            if self.occurs_on(day):
                start = self.occurrence_start(day)
                end = start + self.duration
                if start <= now < end:
                    return start, end
        return None

    def next_occurrence(self, now: dt.datetime, days: int = 370) -> tuple[dt.datetime, dt.datetime] | None:
        active = self.active_occurrence(now)
        if active:
            return active
        for offset in range(days + 1):
            day = now.date() + dt.timedelta(days=offset)
            if self.occurs_on(day):
                start = self.occurrence_start(day)
                if start >= now:
                    return start, start + self.duration
        return None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["start"] = self.start.isoformat(timespec="minutes")
        data["end"] = self.end.isoformat(timespec="minutes")
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "MeetingSlot":
        values = dict(data)
        values["start"] = dt.datetime.fromisoformat(values["start"])
        values["end"] = dt.datetime.fromisoformat(values["end"])
        slot = cls(**values)
        slot.validate()
        return slot


def load_slots(path: Path = SCHEDULE_PATH) -> list[MeetingSlot]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [MeetingSlot.from_dict(item) for item in data]
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError(f"Could not read schedule from {path}: {exc}") from exc


def save_slots(slots: list[MeetingSlot], path: Path = SCHEDULE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps([slot.to_dict() for slot in slots], indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def occurrence_key(start: dt.datetime) -> str:
    return start.isoformat(timespec="minutes")
