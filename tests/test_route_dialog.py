import unittest
from datetime import date, datetime, time, timedelta, timezone

from travel_bot.day import (
    Coordinate, DayPlan, Endpoint, Exclusion, PlanLeg, PlanStop, TravelOption,
)
from travel_bot.dialog import Dialog, InputError
from travel_bot.places import Place


class RealSource:
    mode = 'real'
    label = 'Google Maps — реальные места.'
    geography_hint = 'Geo'


class RouteDialogTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 9, 10)
        self.dialog = Dialog(RealSource(), today_provider=lambda: self.today)
        self.key = (1, 1)
        self.dialog.start(self.key)
        self.session = self.dialog.require(self.key)
        self.session.stage = 'confirmed'
        self.session.geography = object()
        self.session.places = tuple(
            Place(str(i), f'Place {i}', '', '', 'museum', coordinate=Coordinate(i, i))
            for i in range(1, 3))
        self.session.selected = {'1': 60, '2': 30}

    def click(self, action):
        return self.dialog.click(self.key, self.dialog.token(self.key, action))

    def test_parameter_flow_defaults_and_endpoint_confirmation(self):
        self.click('plan')
        self.dialog.text(self.key, '2026-09-12')
        self.dialog.text(self.key, '09:30')
        self.click('end:default')
        self.dialog.text(self.key, 'Hotel')
        self.assertEqual(self.session.operation[0], 'endpoint_start')
        self.session.operation = None
        self.session.endpoint_candidates = (Endpoint('hotel', 'Hotel', Coordinate(1, 2), 120),)
        self.session.stage = 'endpoint_confirm_start'
        self.click('endpoint:0')
        self.assertEqual(self.session.start_endpoint.id, 'start:hotel')
        self.click('finish:last')
        self.click('walk:90')
        self.click('lunch:none')
        self.assertEqual(self.session.stage, 'plan_ready')
        self.assertEqual(self.session.day_parameters.end, time(20))
        self.assertEqual(self.session.day_parameters.walking_limit_min, 90)
        self.click('calculate')
        self.assertEqual(self.session.stage, 'planning_requested')

    def test_custom_end_walk_lunch_and_invalid_values(self):
        self.click('plan')
        for bad in ('yesterday', '2026-09-19'):
            with self.assertRaises(InputError): self.dialog.text(self.key, bad)
        self.dialog.text(self.key, '2026-09-10')
        with self.assertRaises(InputError): self.dialog.text(self.key, '25:00')
        self.dialog.text(self.key, '08:00')
        self.dialog.text(self.key, '18:00')
        self.dialog.text(self.key, 'Hotel')
        self.session.operation = None
        self.session.endpoint_candidates = (Endpoint('h', 'H', Coordinate(1, 2)),)
        self.session.stage = 'endpoint_confirm_start'; self.click('endpoint:0')
        self.click('finish:last'); self.click('walk:custom')
        with self.assertRaises(InputError): self.dialog.text(self.key, '0')
        self.dialog.text(self.key, '45'); self.click('lunch:yes')
        self.dialog.text(self.key, '13:00'); self.dialog.text(self.key, '30')
        self.assertEqual(self.session.day_parameters.walking_limit_min, 45)
        self.assertEqual(self.session.day_parameters.lunch.duration_min, 30)

    def test_more_than_six_places_cannot_plan(self):
        self.session.selected = {str(i): 30 for i in range(7)}
        with self.assertRaisesRegex(InputError, 'шести'): self.click('plan')

    def test_plan_view_exclusions_details_and_edit(self):
        start = datetime(2026, 9, 10, 9, tzinfo=timezone.utc)
        option = TravelOption('start:h', '1', 'TRANSIT', 15, transfers=1,
                              maps_url='https://www.google.com/maps/dir/?api=1')
        self.session.plan = DayPlan(
            (PlanStop('1', 'Museum', start + timedelta(minutes=15), start + timedelta(minutes=75), 60, True),),
            (PlanLeg(option, start, start + timedelta(minutes=15)),),
            (Exclusion('2', 'Park', 'не помещается в доступное время', 30),),
            start, start + timedelta(minutes=75), 0, 15, ('Check schedule',))
        self.session.start_endpoint = Endpoint('start:hotel', 'Hotel', Coordinate(0, 0))
        self.session.stage = 'planned'
        text, rows = self.dialog.view(self.key)
        self.assertIn('09:15–10:15', text)
        self.assertIn('1 пересад', text)
        self.assertIn('Исключено: Park', text)
        self.assertIn('Часы работы неизвестны', text)
        self.assertTrue(any('detail:0' in data for row in rows for _, data in row))
        map_urls = [data for row in rows for label, data in row
                    if label == 'Открыть маршрут в Google Maps']
        self.assertEqual(len(map_urls), 1)
        self.assertTrue(map_urls[0].startswith('https://www.google.com/maps/dir/?api=1'))
        self.assertIn('Google Maps построит собственный вариант', text)
        self.click('edit_plan_parameters')
        self.assertEqual(self.session.stage, 'day_date')
        self.assertEqual(self.session.selected, {'1': 60, '2': 30})

    def test_map_link_error_keeps_plan_and_warns_for_many_waypoints(self):
        start = datetime(2026, 9, 10, 9, tzinfo=timezone.utc)
        self.session.start_endpoint = Endpoint('start:h', 'Hotel', Coordinate(0, 0))
        original = DayPlan((PlanStop('missing', 'Missing', start, start, 1),), (), (),
                           start, start, 0, 0)
        self.session.plan, self.session.stage = original, 'planned'
        text, rows = self.dialog.view(self.key)
        self.assertIn('Ссылка на карту недоступна', text)
        self.assertFalse(any(label == 'Открыть маршрут в Google Maps'
                             for row in rows for label, _ in row))
        self.assertIs(self.session.plan, original)

        self.session.places = tuple(
            Place(str(i), str(i), '', '', 'museum', f'Address {i}',
                  coordinate=Coordinate(i, i)) for i in range(5))
        self.session.plan = DayPlan(
            tuple(PlanStop(str(i), str(i), start, start, 1) for i in range(5)),
            (), (), start, start, 0, 0)
        self.session.finish_endpoint = Endpoint('finish:f', 'Finish', Coordinate(6, 6))
        text, _ = self.dialog.view(self.key)
        self.assertIn('часть промежуточных точек', text)

    def test_failed_planning_view_links_places_in_user_order(self):
        self.session.start_endpoint = Endpoint('start:h', 'Hotel', Coordinate(0, 0))
        self.session.finish_endpoint = Endpoint('finish:f', 'Finish', Coordinate(3, 3))
        self.session.selected = {'2': 30, '1': 60}
        self.session.route_link_fallback = True
        self.session.stage = 'confirmed'
        text, rows = self.dialog.view(self.key)
        links = [data for row in rows for label, data in row
                 if label == 'Открыть выбранные места в Google Maps']
        self.assertEqual(len(links), 1)
        self.assertIn('порядке выбора', text)
        self.assertIn('маршрут и расписание не рассчитаны', text)


if __name__ == '__main__':
    unittest.main()
