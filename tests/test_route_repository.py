import sqlite3
import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from travel_bot.day import Coordinate, DayParameters
from travel_bot.route_repository import (
    RepositoryError, RouteLimitError, RouteNotFound, RouteRepository, StaleRoute,
)
from travel_bot.saved_routes import SavedEndpoint, SavedPlace, SavedRoutePayload


class RouteRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'nested' / 'routes.sqlite3'
        self.now = datetime(2026, 9, 11, 12, tzinfo=timezone.utc)
        self.repo = RouteRepository(self.path, now_provider=lambda: self.now)
        self.addCleanup(self.repo.close)

    def payload(self, suffix='1'):
        return SavedRoutePayload(1, 'Paris', DayParameters(date(2026, 9, 12), time(9)),
            SavedEndpoint('start', 'Hotel', Coordinate(1, 2), 0), None,
            (SavedPlace('p' + suffix, 'museum', ('museum',), 60),),
            ('p' + suffix,), ())

    def test_migration_and_restart_persistence(self):
        saved = self.repo.save(10, 'Route', 'Paris', 'fp', self.payload())
        self.repo.close()
        reopened = RouteRepository(self.path, now_provider=lambda: self.now)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.get(10, saved.summary.id).payload, self.payload())
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('select max(version) from schema_migrations').fetchone()[0], 1)

    def test_idempotency_pagination_and_owner_isolation(self):
        first = self.repo.save(10, 'First', 'Paris', 'same', self.payload())
        duplicate = self.repo.save(10, 'Ignored', 'Paris', 'same', self.payload())
        self.assertEqual(first.summary.id, duplicate.summary.id)
        other = self.repo.save(20, 'Other', 'Paris', 'same', self.payload())
        self.assertNotEqual(first.summary.id, other.summary.id)
        with self.assertRaises(RouteNotFound): self.repo.get(20, first.summary.id)
        self.assertEqual([x.name for x in self.repo.list(10, 0, 5)], ['First'])

    def test_versions_rename_delete_and_delete_all_are_owner_scoped(self):
        route = self.repo.save(10, 'First', 'Paris', 'one', self.payload())
        renamed = self.repo.rename(10, route.summary.id, route.summary.version, 'Renamed')
        self.assertEqual(renamed.summary.version, 2)
        with self.assertRaises(StaleRoute):
            self.repo.rename(10, route.summary.id, 1, 'Old')
        with self.assertRaises(RouteNotFound):
            self.repo.delete(20, route.summary.id, 2)
        self.repo.save(20, 'Other', 'Paris', 'other', self.payload('2'))
        self.assertEqual(self.repo.delete_all(10), 1)
        self.assertEqual(self.repo.count(20), 1)
        with self.assertRaises(RouteNotFound): self.repo.delete(10, route.summary.id, 2)

    def test_expiration_and_limit(self):
        for i in range(20):
            self.repo.save(10, str(i), 'Paris', str(i), self.payload(str(i)))
        with self.assertRaises(RouteLimitError):
            self.repo.save(10, '21', 'Paris', '21', self.payload('21'))
        self.now += timedelta(days=30)
        self.assertEqual(self.repo.count(10), 20)
        self.now += timedelta(seconds=1)
        self.assertEqual(self.repo.list(10, 0, 5), ())
        self.repo.save(10, 'Fresh', 'Paris', 'fresh', self.payload('fresh'))
        self.assertEqual(self.repo.count(10), 1)

    def test_newer_schema_is_refused(self):
        self.repo.close()
        with sqlite3.connect(self.path) as db:
            db.execute('insert into schema_migrations values (?, ?)', (99, self.now.isoformat()))
        with self.assertRaisesRegex(Exception, 'новее'):
            RouteRepository(self.path, now_provider=lambda: self.now)

    def test_corrupt_payload_returns_safe_repository_error(self):
        saved = self.repo.save(10, 'Route', 'Paris', 'fp', self.payload())
        with self.repo.db:
            self.repo.db.execute('update saved_routes set payload_json=? where id=?',
                                 ('{"raw_google":"secret"}', saved.summary.id))
        with self.assertRaisesRegex(RepositoryError, 'поврежд'):
            self.repo.get(10, saved.summary.id)


if __name__ == '__main__':
    unittest.main()
