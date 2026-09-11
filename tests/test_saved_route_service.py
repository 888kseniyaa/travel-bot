import tempfile
import unittest
from datetime import date, datetime, time, timezone
from pathlib import Path

from travel_bot.day import Coordinate, DayParameters, DayPlan, Endpoint, PlanStop
from travel_bot.dialog import Dialog
from travel_bot.places import Place
from travel_bot.route_repository import RouteRepository
from travel_bot.saved_route_service import SavedRouteService


class Places:
    async def refresh_saved_places(self, saved, day, budget):
        return tuple(Place(x.place_id, 'Current ' + x.place_id, '', '', x.category,
                           coordinate=Coordinate(1, 2)) for x in saved)
    async def refresh_saved_endpoint(self, saved, role, budget):
        return Endpoint(role + ':' + saved.place_id, saved.query, saved.coordinate,
                        saved.utc_offset_minutes)


class Planning:
    def __init__(self): self.order = None
    async def validate_fixed_order(self, parameters, start, finish, places, durations, all_places=None):
        self.order = tuple(x.id for x in places)
        now = datetime(2026, 9, 12, 9, tzinfo=timezone.utc)
        return DayPlan(tuple(PlanStop(x.id, x.name, now, now, durations[x.id])
                             for x in places), (), (), now, now, 0, 0)


class SavedRouteServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = RouteRepository(Path(self.temp.name) / 'routes.sqlite3',
            now_provider=lambda: datetime(2026, 9, 11, tzinfo=timezone.utc))
        self.planning = Planning()
        self.service = SavedRouteService(self.repo, Places(), self.planning)

    async def asyncTearDown(self):
        self.repo.close(); self.temp.cleanup()

    def session(self):
        dialog = Dialog(); session = dialog.store.start((1, 1))
        session.geography_query = 'Адмиралтейский район'
        session.start_query = 'Мой отель'
        session.day_parameters = DayParameters(date(2026, 9, 12), time(9))
        session.start_endpoint = Endpoint('start:hotel', 'Google Hotel', Coordinate(1, 2), 180)
        session.places = (Place('a', 'Google A', '', '', 'museum', 'Google address',
                                coordinate=Coordinate(2, 3)),
                          Place('b', 'Google B', '', '', 'park', 'Google address',
                                coordinate=Coordinate(3, 4)))
        session.selected = {'a': 60, 'b': 30}
        now = datetime(2026, 9, 12, 9, tzinfo=timezone.utc)
        session.plan = DayPlan((PlanStop('b', 'Google B', now, now, 30),
                                PlanStop('a', 'Google A', now, now, 60)), (), (), now, now, 0, 0)
        return session

    async def test_autosave_is_idempotent_and_omits_google_display_content(self):
        session = self.session()
        first = self.service.autosave(session, 10)
        second = self.service.autosave(session, 10)
        self.assertEqual(first.summary.id, second.summary.id)
        raw = self.repo.db.execute('select payload_json from saved_routes').fetchone()[0]
        self.assertNotIn('Google A', raw); self.assertNotIn('Google address', raw)
        self.assertEqual(first.summary.name, '12 сентября — Адмиралтейский район')

    async def test_open_refreshes_current_content_in_saved_order_without_mutation(self):
        saved = self.service.autosave(self.session(), 10)
        before = self.repo.db.execute('select payload_json from saved_routes').fetchone()[0]
        opened = await self.service.open_current(10, saved.summary.id, saved.summary.version)
        self.assertEqual(self.planning.order, ('b', 'a'))
        self.assertEqual({x.id: x.name for x in opened.places},
                         {'a': 'Current a', 'b': 'Current b'})
        after = self.repo.db.execute('select payload_json from saved_routes').fetchone()[0]
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
