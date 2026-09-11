import unittest
from datetime import date, datetime, time, timedelta, timezone

from travel_bot.day import Coordinate, DayParameters, Endpoint, LunchBreak, TravelOption
from travel_bot.places import Place
from travel_bot.planner import choose_mode, rank_candidates
from travel_bot.routes import TravelMatrix


ZONE = timezone.utc
DAY = date(2026, 9, 10)


def endpoint(id):
    return Endpoint(id, id.upper(), Coordinate(1, 2))


def place(id, known=False, windows=()):
    return Place(id, id.upper(), '', '', 'museum', coordinate=Coordinate(1, 2),
                 opening_windows=windows, hours_known=known)


def option(a, b, mode, minutes, transfers=0):
    return TravelOption(a, b, mode, minutes, transfers=transfers)


class PlannerTests(unittest.TestCase):
    def test_mode_boundaries_and_transfer_penalty(self):
        self.assertEqual(choose_mode(option('a', 'b', 'WALK', 15), option('a', 'b', 'TRANSIT', 5)).mode, 'WALK')
        self.assertEqual(choose_mode(option('a', 'b', 'WALK', 30), option('a', 'b', 'TRANSIT', 20, 1)).mode, 'TRANSIT')
        self.assertEqual(choose_mode(option('a', 'b', 'WALK', 30), option('a', 'b', 'TRANSIT', 26, 1)).mode, 'WALK')
        self.assertEqual(choose_mode(option('a', 'b', 'WALK', 41), option('a', 'b', 'TRANSIT', 39, 3)).mode, 'TRANSIT')
        fallback = choose_mode(option('a', 'b', 'WALK', 45), None)
        self.assertEqual(fallback.mode, 'WALK')
        self.assertTrue(fallback.warnings)

    def test_linear_places_do_not_backtrack(self):
        points = ['s', 'a', 'b', 'c']
        options = []
        positions = {'s': 0, 'a': 1, 'b': 2, 'c': 3}
        for a in points:
            for b in points[1:]:
                if a != b:
                    options.append(option(a, b, 'WALK', abs(positions[a] - positions[b]) * 5))
        params = DayParameters(DAY, time(9), time(20))
        result = rank_candidates(params, endpoint('s'), None,
                                 (place('a'), place('b'), place('c')),
                                 {'a': 30, 'b': 30, 'c': 30}, TravelMatrix(options))
        self.assertEqual(result[0].place_ids, ('a', 'b', 'c'))
        self.assertEqual(result[0].travel_min, 15)

    def test_windows_lunch_unknown_hours_and_exclusion(self):
        open_window = ((datetime(2026, 9, 10, 10, tzinfo=ZONE),
                        datetime(2026, 9, 10, 12, tzinfo=ZONE)),)
        places = (place('open', True, open_window), place('closed', True, ()), place('unknown'))
        options = [option('s', p.id, 'WALK', 10) for p in places]
        options += [option(a.id, b.id, 'WALK', 10) for a in places for b in places if a != b]
        params = DayParameters(DAY, time(9), time(13), lunch=LunchBreak(time(11), 30))
        result = rank_candidates(params, endpoint('s'), None, places,
                                 {'open': 60, 'closed': 30, 'unknown': 30}, TravelMatrix(options))[0]
        self.assertEqual(set(result.place_ids), {'open', 'unknown'})
        open_stop = next(stop for stop in result.stops if stop.place_id == 'open')
        self.assertGreaterEqual(open_stop.arrival.time(), time(10))
        self.assertLessEqual(open_stop.departure.time(), time(12))
        lunch_start = datetime(2026, 9, 10, 11, tzinfo=ZONE)
        lunch_end = datetime(2026, 9, 10, 11, 30, tzinfo=ZONE)
        activities = [(x.arrival, x.departure) for x in result.stops]
        activities += [(x.departure, x.arrival) for x in result.legs]
        self.assertTrue(all(end <= lunch_start or start >= lunch_end for start, end in activities))
        self.assertIn('Часы работы неизвестны: UNKNOWN', result.warnings)
        self.assertEqual(result.exclusions[0].reason, 'место закрыто в выбранный день')

    def test_walking_limit_and_day_end_remove_least_convenient(self):
        places = (place('near'), place('far'))
        matrix = TravelMatrix((option('s', 'near', 'WALK', 10), option('s', 'far', 'WALK', 50),
                               option('near', 'far', 'WALK', 50), option('far', 'near', 'WALK', 50)))
        params = DayParameters(DAY, time(9), time(10, 20), walking_limit_min=30)
        result = rank_candidates(params, endpoint('s'), None, places,
                                 {'near': 60, 'far': 60}, matrix)[0]
        self.assertEqual(result.place_ids, ('near',))
        self.assertEqual(result.exclusions[0].name, 'FAR')

    def test_finish_leg_is_required(self):
        p = place('a')
        params = DayParameters(DAY, time(9), time(11))
        without = rank_candidates(params, endpoint('s'), endpoint('f'), (p,), {'a': 30},
                                  TravelMatrix((option('s', 'a', 'WALK', 10),)))
        self.assertEqual(without, ())


if __name__ == '__main__':
    unittest.main()
