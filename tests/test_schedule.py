import datetime as dt
import tempfile
import unittest
from pathlib import Path

from schedule import MeetingSlot, load_slots, occurrence_key, save_slots


class MeetingScheduleTests(unittest.TestCase):
    def slot(self, **changes) -> MeetingSlot:
        values = dict(
            title="Standup",
            start=dt.datetime(2026, 7, 6, 9, 0),
            end=dt.datetime(2026, 7, 6, 9, 30),
            recording_name="standup",
        )
        values.update(changes)
        return MeetingSlot(**values)

    def test_one_time_slot_is_only_active_in_its_window(self) -> None:
        slot = self.slot()
        self.assertIsNotNone(slot.active_occurrence(dt.datetime(2026, 7, 6, 9, 15)))
        self.assertIsNone(slot.active_occurrence(dt.datetime(2026, 7, 7, 9, 15)))

    def test_daily_and_weekly_next_occurrences(self) -> None:
        daily = self.slot(recurrence="daily")
        weekly = self.slot(recurrence="weekly")
        self.assertEqual(daily.next_occurrence(dt.datetime(2026, 7, 8, 10))[0],
                         dt.datetime(2026, 7, 9, 9))
        self.assertEqual(weekly.next_occurrence(dt.datetime(2026, 7, 7, 10))[0],
                         dt.datetime(2026, 7, 13, 9))

    def test_custom_weekdays(self) -> None:
        slot = self.slot(recurrence="custom", custom_days=[1, 3])
        next_start, _ = slot.next_occurrence(dt.datetime(2026, 7, 6, 10))
        self.assertEqual(next_start, dt.datetime(2026, 7, 7, 9))

    def test_cross_midnight_window_is_active_next_day(self) -> None:
        slot = self.slot(end=dt.datetime(2026, 7, 7, 1), recurrence="daily")
        start, end = slot.active_occurrence(dt.datetime(2026, 7, 8, 0, 30))
        self.assertEqual(start, dt.datetime(2026, 7, 7, 9))
        self.assertEqual(end, dt.datetime(2026, 7, 8, 1))

    def test_recurring_slots_include_the_occurrence_date_in_the_name(self) -> None:
        slot = self.slot(recurrence="weekly", recording_name="standup")
        occurrence_start = dt.datetime(2026, 7, 13, 9, 0)

        self.assertEqual(slot.occurrence_name(occurrence_start), "standup-2026/07/13-09:00 AM")

    def test_recurring_slots_can_skip_the_occurrence_date_in_the_name(self) -> None:
        slot = self.slot(recurrence="weekly", recording_name="standup", include_occurrence_stamp=False)
        occurrence_start = dt.datetime(2026, 7, 13, 9, 0)

        self.assertEqual(slot.occurrence_name(occurrence_start), "standup")

    def test_schedule_round_trip_preserves_scheduler_state(self) -> None:
        slot = self.slot(recurrence="custom", custom_days=[0, 4], last_started="2026-07-06T09:00")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.json"
            save_slots([slot], path)
            loaded = load_slots(path)[0]
        self.assertEqual(loaded.to_dict(), slot.to_dict())
        self.assertEqual(occurrence_key(slot.start), "2026-07-06T09:00")

    def test_custom_requires_a_weekday(self) -> None:
        with self.assertRaises(ValueError):
            self.slot(recurrence="custom").validate()


if __name__ == "__main__":
    unittest.main()
