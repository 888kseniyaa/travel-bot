"""Owner-scoped SQLite persistence for saved route definitions."""
import sqlite3
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from .saved_routes import (
    MAX_ROUTES, RETENTION_DAYS, SavedRoute, SavedRouteSummary,
    PayloadError, normalize_title, payload_from_json, payload_to_json,
)


class RepositoryError(RuntimeError): pass
class RouteLimitError(RepositoryError): pass
class RouteNotFound(RepositoryError): pass
class StaleRoute(RepositoryError): pass


class RouteRepository:
    SCHEMA_VERSION = 1

    def __init__(self, path, now_provider):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.now_provider = now_provider
        try:
            self.db = sqlite3.connect(self.path, timeout=5)
            self.db.row_factory = sqlite3.Row
            self.db.execute('PRAGMA foreign_keys=ON')
            self.db.execute('PRAGMA busy_timeout=5000')
            self.db.execute('PRAGMA journal_mode=WAL')
            self.migrate()
        except (sqlite3.Error, OSError) as error:
            if hasattr(self, 'db'): self.db.close()
            raise RepositoryError('Не удалось открыть хранилище маршрутов.') from None

    def close(self):
        db = getattr(self, 'db', None)
        if db is not None:
            db.close(); self.db = None

    def migrate(self):
        try:
            self.db.execute('BEGIN EXCLUSIVE')
            self.db.execute('CREATE TABLE IF NOT EXISTS schema_migrations('
                            'version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)')
            current = self.db.execute('SELECT COALESCE(MAX(version), 0) FROM schema_migrations').fetchone()[0]
            if current > self.SCHEMA_VERSION:
                self.db.rollback()
                raise RepositoryError('Версия базы маршрутов новее версии приложения.')
            if current < 1:
                self.db.execute('CREATE TABLE saved_routes('
                    'id TEXT PRIMARY KEY, owner_user_id INTEGER NOT NULL, version INTEGER NOT NULL, '
                    'name TEXT NOT NULL, geography_query TEXT NOT NULL, fingerprint TEXT NOT NULL, '
                    'payload_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, '
                    'expires_at TEXT NOT NULL)')
                self.db.execute('CREATE UNIQUE INDEX saved_routes_owner_fingerprint '
                                'ON saved_routes(owner_user_id, fingerprint)')
                self.db.execute('CREATE INDEX saved_routes_owner_created '
                                'ON saved_routes(owner_user_id, created_at DESC)')
                self.db.execute('CREATE INDEX saved_routes_expires ON saved_routes(expires_at)')
                self.db.execute('INSERT INTO schema_migrations VALUES(1, ?)',
                                (self._now().isoformat(),))
            self.db.commit()
        except RepositoryError:
            raise
        except sqlite3.Error:
            self.db.rollback()
            raise RepositoryError('Не удалось обновить схему хранилища маршрутов.') from None

    def _now(self):
        return self.now_provider()

    def _purge(self):
        self.db.execute('DELETE FROM saved_routes WHERE expires_at < ?',
                        (self._now().isoformat(),))

    def _summary(self, row):
        from datetime import date, datetime
        payload = self._payload(row)
        return SavedRouteSummary(row['id'], row['version'], row['name'],
                                 date.fromisoformat(payload.day.date.isoformat()),
                                 datetime.fromisoformat(row['created_at']),
                                 datetime.fromisoformat(row['updated_at']),
                                 datetime.fromisoformat(row['expires_at']))

    def _route(self, row):
        return SavedRoute(self._summary(row), row['geography_query'], row['fingerprint'],
                          self._payload(row))

    def _payload(self, row):
        try: return payload_from_json(row['payload_json'])
        except PayloadError:
            raise RepositoryError('Сохранённый маршрут повреждён и не может быть открыт.') from None

    def save(self, owner_user_id, name, geography_query, fingerprint, payload):
        name = normalize_title(name); encoded = payload_to_json(payload)
        try:
            with self.db:
                self._purge()
                old = self.db.execute('SELECT * FROM saved_routes WHERE owner_user_id=? AND fingerprint=?',
                                      (owner_user_id, fingerprint)).fetchone()
                if old: return self._route(old)
                count = self.db.execute('SELECT COUNT(*) FROM saved_routes WHERE owner_user_id=?',
                                        (owner_user_id,)).fetchone()[0]
                if count >= MAX_ROUTES:
                    raise RouteLimitError('Достигнут лимит 20 сохранённых маршрутов.')
                now = self._now(); route_id = uuid4().hex[:16]
                self.db.execute('INSERT INTO saved_routes VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (route_id, owner_user_id, 1, name, geography_query, fingerprint, encoded,
                     now.isoformat(), now.isoformat(),
                     (now + timedelta(days=RETENTION_DAYS)).isoformat()))
                row = self.db.execute('SELECT * FROM saved_routes WHERE id=?', (route_id,)).fetchone()
            return self._route(row)
        except RouteLimitError: raise
        except sqlite3.Error:
            raise RepositoryError('Не удалось сохранить маршрут. Текущий план сохранён в памяти.') from None

    def list(self, owner_user_id, offset=0, limit=5):
        try:
            with self.db: self._purge()
            rows = self.db.execute('SELECT * FROM saved_routes WHERE owner_user_id=? '
                                   'ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?',
                                   (owner_user_id, limit, offset)).fetchall()
            return tuple(self._summary(row) for row in rows)
        except sqlite3.Error:
            raise RepositoryError('Не удалось прочитать сохранённые маршруты.') from None

    def get(self, owner_user_id, route_id):
        try:
            row = self.db.execute('SELECT * FROM saved_routes WHERE id=? AND owner_user_id=?',
                                  (route_id, owner_user_id)).fetchone()
            if not row: raise RouteNotFound('Маршрут не найден или уже удалён.')
            return self._route(row)
        except RouteNotFound: raise
        except sqlite3.Error:
            raise RepositoryError('Не удалось прочитать сохранённый маршрут.') from None

    def rename(self, owner_user_id, route_id, expected_version, name):
        name = normalize_title(name)
        current = self.get(owner_user_id, route_id)
        if current.summary.version != expected_version:
            raise StaleRoute('Маршрут изменился. Откройте актуальную карточку.')
        try:
            with self.db:
                changed = self.db.execute('UPDATE saved_routes SET name=?, version=version+1, updated_at=? '
                    'WHERE id=? AND owner_user_id=? AND version=?',
                    (name, self._now().isoformat(), route_id, owner_user_id, expected_version)).rowcount
            if not changed: raise StaleRoute('Маршрут изменился. Откройте актуальную карточку.')
            return self.get(owner_user_id, route_id)
        except StaleRoute: raise
        except sqlite3.Error:
            raise RepositoryError('Не удалось переименовать маршрут.') from None

    def delete(self, owner_user_id, route_id, expected_version):
        current = self.get(owner_user_id, route_id)
        if current.summary.version != expected_version:
            raise StaleRoute('Маршрут изменился. Откройте актуальную карточку.')
        try:
            with self.db:
                changed = self.db.execute('DELETE FROM saved_routes WHERE id=? AND owner_user_id=? AND version=?',
                                          (route_id, owner_user_id, expected_version)).rowcount
            if not changed: raise RouteNotFound('Маршрут не найден или уже удалён.')
        except RouteNotFound: raise
        except sqlite3.Error:
            raise RepositoryError('Не удалось удалить маршрут.') from None

    def delete_all(self, owner_user_id):
        try:
            with self.db:
                return self.db.execute('DELETE FROM saved_routes WHERE owner_user_id=?',
                                       (owner_user_id,)).rowcount
        except sqlite3.Error:
            raise RepositoryError('Не удалось удалить сохранённые маршруты.') from None

    def count(self, owner_user_id):
        try:
            with self.db: self._purge()
            return self.db.execute('SELECT COUNT(*) FROM saved_routes WHERE owner_user_id=?',
                                   (owner_user_id,)).fetchone()[0]
        except sqlite3.Error:
            raise RepositoryError('Не удалось прочитать сохранённые маршруты.') from None
