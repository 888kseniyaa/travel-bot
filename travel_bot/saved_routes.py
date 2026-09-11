"""Versioned persistent route data. Contains no Google display content."""
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time

from .day import Coordinate, DayParameters, LunchBreak


FORMAT_VERSION = 1
MAX_ROUTES = 20
RETENTION_DAYS = 30
MONTHS = ('января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
          'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря')


class PayloadError(ValueError):
    pass


def _text(value, limit=200):
    value = ' '.join(value.split()) if isinstance(value, str) else ''
    if not value or len(value) > limit:
        raise PayloadError('Некорректный текст сохранённого маршрута.')
    return value


@dataclass(frozen=True)
class SavedPlace:
    place_id: str
    category: str
    categories: tuple[str, ...]
    duration_min: int

    def __post_init__(self):
        _text(self.place_id, 300); _text(self.category, 40)
        if not self.categories or any(not isinstance(x, str) or not x for x in self.categories):
            raise PayloadError('Некорректные категории места.')
        if not isinstance(self.duration_min, int) or not 1 <= self.duration_min <= 999999:
            raise PayloadError('Некорректная длительность места.')


@dataclass(frozen=True)
class SavedEndpoint:
    place_id: str
    query: str
    coordinate: Coordinate
    utc_offset_minutes: int = 0

    def __post_init__(self):
        if self.place_id: _text(self.place_id, 300)
        _text(self.query, 200)
        if not isinstance(self.coordinate, Coordinate):
            raise PayloadError('Некорректные координаты точки.')
        if not isinstance(self.utc_offset_minutes, int) or not -840 <= self.utc_offset_minutes <= 840:
            raise PayloadError('Некорректный часовой пояс точки.')


@dataclass(frozen=True)
class SavedRoutePayload:
    format_version: int
    geography_query: str
    day: DayParameters
    start: SavedEndpoint
    finish: SavedEndpoint | None
    places: tuple[SavedPlace, ...]
    order: tuple[str, ...]
    exclusion_codes: tuple[str, ...] = ()

    def __post_init__(self):
        if self.format_version != FORMAT_VERSION:
            raise PayloadError('Неподдерживаемая версия сохранённого маршрута.')
        _text(self.geography_query, 200)
        if not isinstance(self.day, DayParameters) or not isinstance(self.start, SavedEndpoint):
            raise PayloadError('Некорректные параметры маршрута.')
        if self.finish is not None and not isinstance(self.finish, SavedEndpoint):
            raise PayloadError('Некорректный финиш маршрута.')
        if not 1 <= len(self.places) <= 6 or len({p.place_id for p in self.places}) != len(self.places):
            raise PayloadError('Сохранённый маршрут должен содержать от одного до шести мест.')
        ids = {p.place_id for p in self.places}
        if not self.order or len(set(self.order)) != len(self.order) or not set(self.order) <= ids:
            raise PayloadError('Некорректный порядок мест.')
        if any(not isinstance(x, str) or len(x) > 300 for x in self.exclusion_codes):
            raise PayloadError('Некорректные причины исключения.')


@dataclass(frozen=True)
class SavedRouteSummary:
    id: str
    version: int
    name: str
    route_date: date
    created_at: datetime
    updated_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class SavedRoute:
    summary: SavedRouteSummary
    geography_query: str
    fingerprint: str
    payload: SavedRoutePayload


def normalize_title(value):
    return _text(value, 80)


def default_route_name(route_date, geography_query):
    query = _text(geography_query, 200)
    return normalize_title(f'{route_date.day} {MONTHS[route_date.month - 1]} — {query}')


def _endpoint_dict(value):
    if value is None: return None
    return {'place_id': value.place_id, 'query': value.query,
            'coordinate': [value.coordinate.latitude, value.coordinate.longitude],
            'utc_offset_minutes': value.utc_offset_minutes}


def payload_to_dict(value):
    lunch = value.day.lunch
    return {
        'format_version': value.format_version,
        'geography_query': value.geography_query,
        'day': {'date': value.day.date.isoformat(), 'start': value.day.start.isoformat(),
                'end': value.day.end.isoformat(),
                'walking_limit_min': value.day.walking_limit_min,
                'lunch': None if lunch is None else
                {'start': lunch.start.isoformat(), 'duration_min': lunch.duration_min}},
        'start': _endpoint_dict(value.start), 'finish': _endpoint_dict(value.finish),
        'places': [{'place_id': p.place_id, 'category': p.category,
                    'categories': list(p.categories), 'duration_min': p.duration_min}
                   for p in value.places],
        'order': list(value.order), 'exclusion_codes': list(value.exclusion_codes),
    }


def payload_to_json(value):
    if not isinstance(value, SavedRoutePayload): raise PayloadError('Некорректный маршрут.')
    return json.dumps(payload_to_dict(value), ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'))


def _exact(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise PayloadError('Некорректная структура сохранённого маршрута.')


def _endpoint_from(value):
    if value is None: return None
    _exact(value, ('place_id', 'query', 'coordinate', 'utc_offset_minutes'))
    coordinate = value['coordinate']
    if not isinstance(coordinate, list) or len(coordinate) != 2:
        raise PayloadError('Некорректные координаты точки.')
    return SavedEndpoint(value['place_id'], value['query'], Coordinate(*coordinate),
                         value['utc_offset_minutes'])


def payload_from_json(encoded):
    try:
        raw = json.loads(encoded)
        _exact(raw, ('format_version', 'geography_query', 'day', 'start', 'finish',
                     'places', 'order', 'exclusion_codes'))
        _exact(raw['day'], ('date', 'start', 'end', 'walking_limit_min', 'lunch'))
        lunch = raw['day']['lunch']
        if lunch is not None: _exact(lunch, ('start', 'duration_min'))
        day = DayParameters(date.fromisoformat(raw['day']['date']),
                            time.fromisoformat(raw['day']['start']),
                            time.fromisoformat(raw['day']['end']),
                            raw['day']['walking_limit_min'],
                            None if lunch is None else LunchBreak(
                                time.fromisoformat(lunch['start']), lunch['duration_min']))
        places = []
        if not isinstance(raw['places'], list): raise PayloadError('Некорректные места.')
        for item in raw['places']:
            _exact(item, ('place_id', 'category', 'categories', 'duration_min'))
            places.append(SavedPlace(item['place_id'], item['category'],
                                     tuple(item['categories']), item['duration_min']))
        return SavedRoutePayload(raw['format_version'], raw['geography_query'], day,
                                 _endpoint_from(raw['start']), _endpoint_from(raw['finish']),
                                 tuple(places), tuple(raw['order']), tuple(raw['exclusion_codes']))
    except PayloadError:
        raise
    except (ValueError, TypeError, KeyError, OverflowError):
        raise PayloadError('Некорректный сохранённый маршрут.') from None


def route_fingerprint(payload):
    return hashlib.sha256(payload_to_json(payload).encode()).hexdigest()
