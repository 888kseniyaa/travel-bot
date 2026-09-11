import unittest
from datetime import date, datetime, time, timedelta, timezone

from travel_bot.day import (
    Coordinate, DayParameters, Endpoint, LunchBreak, TimeWindow, ValidationError,
)
from travel_bot.places import Place


class DayModelTests(unittest.TestCase):
    def test_date_horizon_and_day_bounds(self):
        today = date(2026, 9, 10)
        params = DayParameters(today + timedelta(days=7), time(9), time(20))
        params.validate(today)
        start, end = params.bounds(timezone(timedelta(hours=2)))
        self.assertEqual(start.isoformat(), '2026-09-17T09:00:00+02:00')
        self.assertEqual(end.isoformat(), '2026-09-17T20:00:00+02:00')
        for invalid in (today - timedelta(days=1), today + timedelta(days=8)):
            with self.assertRaises(ValidationError):
                DayParameters(invalid, time(9), time(20)).validate(today)

    def test_end_lunch_and_walking_limit_are_validated(self):
        today = date(2026, 9, 10)
        invalid = (
            DayParameters(today, time(20), time(20)),
            DayParameters(today, time(9), time(20), walking_limit_min=0),
            DayParameters(today, time(9), time(20), lunch=LunchBreak(time(8), 30)),
            DayParameters(today, time(9), time(20), lunch=LunchBreak(time(19, 45), 30)),
        )
        for params in invalid:
            with self.assertRaises(ValidationError): params.validate(today)

    def test_coordinate_and_window_validation(self):
        Coordinate(59.9, 30.3)
        for lat, lon in ((91, 0), (0, 181)):
            with self.assertRaises(ValidationError): Coordinate(lat, lon)
        now = datetime(2026, 9, 10, 9, tzinfo=timezone.utc)
        with self.assertRaises(ValidationError): TimeWindow(now, now)

    def test_place_defaults_remain_compatible_and_support_planning(self):
        old = Place('id', 'Name', 'District', 'Description', 'museum')
        self.assertIsNone(old.coordinate)
        self.assertFalse(old.hours_known)
        planned = Place('id', 'Name', 'District', '', 'museum', coordinate=Coordinate(1, 2),
                        opening_windows=((datetime(2026, 9, 10, 9), datetime(2026, 9, 10, 18)),),
                        hours_known=True)
        self.assertEqual(planned.coordinate.longitude, 2)

    def test_endpoint_requires_stable_id_and_coordinate(self):
        endpoint = Endpoint('p1', 'Hotel', Coordinate(1, 2), 120)
        self.assertEqual(endpoint.utc_offset_minutes, 120)
        with self.assertRaises(ValidationError): Endpoint('', 'Hotel', Coordinate(1, 2), 0)


if __name__ == '__main__':
    unittest.main()
