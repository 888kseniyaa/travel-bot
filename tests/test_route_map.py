import unittest
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from travel_bot.day import Coordinate, DayPlan, Endpoint, PlanStop
from travel_bot.places import Place
from travel_bot.route_map import (
    RouteMapError, build_route_map_link, build_selected_route_map_link,
)


def plan(*ids):
    now = datetime(2026, 9, 11, 9, tzinfo=timezone.utc)
    stops = tuple(PlanStop(value, value, now, now, 60) for value in ids)
    return DayPlan(stops, (), (), now, now, 0, 0)


class RouteMapTests(unittest.TestCase):
    def setUp(self):
        self.start = Endpoint('start:ChIJ-start', 'Отель — Невский проспект, 1',
                              Coordinate(59.93, 30.31))
        self.finish = Endpoint('finish:ChIJ-finish', 'Вокзал', Coordinate(59.92, 30.33))
        self.places = (
            Place('ChIJ-a', 'Музей А', '', '', 'museum', 'Дворцовая площадь, 2',
                  coordinate=Coordinate(59.94, 30.32)),
            Place('ChIJ-b', 'Парк Б', '', '', 'park', 'Садовая улица, 3',
                  coordinate=Coordinate(59.95, 30.34)),
        )

    def query(self, result):
        parsed = urlparse(result.url)
        self.assertEqual((parsed.scheme, parsed.netloc, parsed.path),
                         ('https', 'www.google.com', '/maps/dir/'))
        return parse_qs(parsed.query)

    def test_separate_finish_preserves_order_and_pairs_place_ids(self):
        result = build_route_map_link(self.start, self.finish, plan('ChIJ-b', 'ChIJ-a'), self.places)
        query = self.query(result)
        self.assertEqual(query['api'], ['1'])
        self.assertEqual(query['origin'], ['Отель — Невский проспект, 1'])
        self.assertEqual(query['origin_place_id'], ['ChIJ-start'])
        self.assertEqual(query['waypoints'], ['Садовая улица, 3|Дворцовая площадь, 2'])
        self.assertEqual(query['waypoint_place_ids'], ['ChIJ-b|ChIJ-a'])
        self.assertEqual(query['destination'], ['Вокзал'])
        self.assertEqual(query['destination_place_id'], ['ChIJ-finish'])
        self.assertNotIn('travelmode', query)
        self.assertIn('%D0%9E%D1%82%D0%B5%D0%BB%D1%8C', result.url)

    def test_without_finish_uses_last_stop_as_destination(self):
        query = self.query(build_route_map_link(
            self.start, None, plan('ChIJ-a', 'ChIJ-b'), self.places))
        self.assertEqual(query['waypoints'], ['Дворцовая площадь, 2'])
        self.assertEqual(query['waypoint_place_ids'], ['ChIJ-a'])
        self.assertEqual(query['destination'], ['Садовая улица, 3'])
        self.assertEqual(query['destination_place_id'], ['ChIJ-b'])

    def test_privacy_validation_length_and_mobile_warning(self):
        many = tuple(Place(f'ChIJ-{i}', str(i), '', '', 'park', f'Address {i}',
                           coordinate=Coordinate(50 + i / 100, 30)) for i in range(5))
        result = build_route_map_link(self.start, self.finish,
                                      plan(*(p.id for p in many)), many)
        self.assertTrue(result.mobile_waypoint_warning)
        for forbidden in ('API_SECRET', '123456789', 'session-abcdef'):
            self.assertNotIn(forbidden, result.url)

        with self.assertRaisesRegex(RouteMapError, 'двух'):
            build_route_map_link(self.start, None, plan(), ())
        missing = (Place('x', 'X', '', '', 'park', 'X'),)
        with self.assertRaisesRegex(RouteMapError, 'координат'):
            build_route_map_link(self.start, None, plan('x'), missing)
        huge = (Place('long', 'Long', '', '', 'park', 'Я' * 2100,
                      coordinate=Coordinate(1, 1)),)
        with self.assertRaisesRegex(RouteMapError, '2048'):
            build_route_map_link(self.start, None, plan('long'), huge)

    def test_fallback_link_preserves_user_selection_order(self):
        result = build_selected_route_map_link(
            self.start, self.finish, ('ChIJ-b', 'ChIJ-a'), self.places)
        query = self.query(result)
        self.assertEqual(query['waypoint_place_ids'], ['ChIJ-b|ChIJ-a'])
        self.assertEqual(query['destination_place_id'], ['ChIJ-finish'])


if __name__ == '__main__':
    unittest.main()
