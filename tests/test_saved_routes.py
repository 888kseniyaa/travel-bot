import json
import unittest
from datetime import date, datetime, time, timezone

from travel_bot.day import Coordinate, DayParameters, LunchBreak
from travel_bot.saved_routes import (
    PayloadError, SavedEndpoint, SavedPlace, SavedRoutePayload,
    default_route_name, payload_from_json, payload_to_json, route_fingerprint,
)


class SavedRoutePayloadTests(unittest.TestCase):
    def payload(self):
        return SavedRoutePayload(
            1, 'Адмиралтейский район',
            DayParameters(date(2026, 9, 12), time(9), time(20), 90,
                          LunchBreak(time(13), 45)),
            SavedEndpoint('hotel-id', 'Мой отель', Coordinate(59.9, 30.3), 180),
            None,
            (SavedPlace('p1', 'museum', ('museum',), 120),
             SavedPlace('p2', 'park', ('park',), 60)),
            ('p2', 'p1'), ('not_fit:p3',))

    def test_strict_round_trip_and_stable_fingerprint(self):
        payload = self.payload()
        encoded = payload_to_json(payload)
        self.assertEqual(payload_from_json(encoded), payload)
        self.assertEqual(route_fingerprint(payload), route_fingerprint(payload))
        self.assertNotIn('Эрмитаж', encoded)
        self.assertNotIn('formattedAddress', encoded)

    def test_name_uses_date_and_normalized_user_query(self):
        self.assertEqual(default_route_name(date(2026, 9, 12), '  Адмиралтейский   район  '),
                         '12 сентября — Адмиралтейский район')

    def test_rejects_unknown_or_extra_content_and_invalid_order(self):
        raw = json.loads(payload_to_json(self.payload()))
        raw['format_version'] = 2
        with self.assertRaises(PayloadError): payload_from_json(json.dumps(raw))
        raw['format_version'] = 1; raw['google_name'] = 'Forbidden'
        with self.assertRaises(PayloadError): payload_from_json(json.dumps(raw))
        raw.pop('google_name'); raw['order'] = ['missing']
        with self.assertRaises(PayloadError): payload_from_json(json.dumps(raw))

    def test_rejects_bad_limits_and_coordinates(self):
        with self.assertRaises(PayloadError):
            SavedPlace('p', 'park', ('park',), 0)
        with self.assertRaises(PayloadError):
            SavedRoutePayload(1, 'x' * 201, DayParameters(date.today(), time(9)),
                              SavedEndpoint('s', 'q', Coordinate(0, 0), 0), None,
                              tuple(SavedPlace(str(i), 'park', ('park',), 10)
                                    for i in range(7)), (), ())


if __name__ == '__main__':
    unittest.main()
