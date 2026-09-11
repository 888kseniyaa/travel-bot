import tempfile
import unittest
from datetime import date, datetime, time, timezone
from pathlib import Path

from travel_bot.day import Coordinate, DayParameters
from travel_bot.dialog import Dialog, InputError
from travel_bot.route_repository import RouteRepository
from travel_bot.saved_route_flow import SavedRouteFlow
from travel_bot.saved_route_service import SavedRouteService
from travel_bot.saved_routes import SavedEndpoint, SavedPlace, SavedRoutePayload


class SavedRouteFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        repo = RouteRepository(Path(self.temp.name) / 'routes.sqlite3',
            now_provider=lambda: datetime(2026, 9, 11, tzinfo=timezone.utc))
        self.addCleanup(repo.close)
        self.service = SavedRouteService(repo, None, None)
        payload = SavedRoutePayload(1, 'Paris', DayParameters(date(2026, 9, 12), time(9)),
            SavedEndpoint('s', 'Hotel', Coordinate(1, 2), 0), None,
            (SavedPlace('p', 'museum', ('museum',), 60),), ('p',), ())
        self.saved = repo.save(1, '12 сентября — Paris', 'Paris', 'fp', payload)
        self.dialog = Dialog(); self.key = (1, 1); self.session = self.dialog.store.start(self.key)
        self.session.stage = 'places'; self.session.selected = {'draft': 45}
        self.flow = SavedRouteFlow(self.service); self.dialog.saved_flow = self.flow

    def token(self, action): return self.dialog.token(self.key, action)

    def test_list_card_and_back_preserve_active_selection(self):
        text, rows = self.flow.enter(self.dialog, self.key, 1)
        self.assertIn('12 сентября — Paris', text)
        self.flow.click(self.dialog, self.key, 1, self.token(
            f'saved:card:{self.saved.summary.id}:{self.saved.summary.version}'))
        self.assertEqual(self.session.stage, 'saved_card')
        self.flow.click(self.dialog, self.key, 1, self.token('saved:back_selection'))
        self.assertEqual(self.session.stage, 'places')
        self.assertEqual(self.session.selected, {'draft': 45})

    def test_rename_delete_and_delete_all_confirmations(self):
        self.flow.enter(self.dialog, self.key, 1)
        self.flow.click(self.dialog, self.key, 1, self.token(
            f'saved:rename:{self.saved.summary.id}:{self.saved.summary.version}'))
        with self.assertRaises(InputError): self.flow.text(self.dialog, self.key, 1, ' ')
        self.flow.text(self.dialog, self.key, 1, 'Weekend route')
        renamed = self.service.get(1, self.saved.summary.id)
        self.assertEqual(renamed.summary.name, 'Weekend route')
        self.flow.click(self.dialog, self.key, 1, self.token(
            f'saved:delete:{renamed.summary.id}:{renamed.summary.version}'))
        self.flow.click(self.dialog, self.key, 1, self.token(
            f'saved:delete_yes:{renamed.summary.id}:{renamed.summary.version}'))
        self.assertEqual(self.service.count(1), 0)

        self.flow.enter_delete_all(self.dialog, self.key, 1)
        text, _ = self.flow.view(self.dialog, self.key, 1)
        self.assertIn('Удалить все', text)


if __name__ == '__main__':
    unittest.main()
