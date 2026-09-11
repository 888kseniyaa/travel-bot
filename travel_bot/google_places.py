"""Places API (New), Text Search only. No disk cache, photos or reviews."""
import asyncio
import math
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, replace
from urllib.parse import quote, urlparse
import httpx
from .day import Coordinate, Endpoint
from .places import Place

ENDPOINT = 'https://places.googleapis.com/v1/places:searchText'
GEO_FIELDS = 'places.id,places.displayName,places.formattedAddress,places.types,places.viewport,places.attributions'
PLACE_FIELDS = 'places.id,places.displayName,places.formattedAddress,places.googleMapsUri,places.attributions,places.location'
ENDPOINT_FIELDS = ('places.id,places.displayName,places.formattedAddress,places.googleMapsUri,'
                   'places.attributions,places.location,places.utcOffsetMinutes')
DETAIL_FIELDS = ('id,displayName,formattedAddress,location,utcOffsetMinutes,'
                 'currentOpeningHours.periods,googleMapsUri,attributions')
QUERIES = {'museum': ('museums', 'museum'), 'park': ('parks', 'park'),
           'architecture': ('architectural landmarks', None)}
GEO_TYPES = {'locality', 'sublocality', 'neighborhood', 'administrative_area_level_3',
             'administrative_area_level_4', 'sublocality_level_1', 'sublocality_level_2'}

class SourceError(ValueError):
    """Only public, fixed messages may cross this boundary."""

@dataclass
class Budget:
    limit: int = 12
    used: int = 0

    def take(self):
        if self.used >= self.limit:
            raise SourceError('Лимит 12 запросов этого подбора исчерпан. Выбор сохранён. Для нового поиска: /start.')
        self.used += 1

@dataclass(frozen=True)
class Geography:
    id: str
    label: str
    rectangle: dict
    attributions: tuple[str, ...] = ()


def safe_url(value, allow_http=False):
    if not isinstance(value, str): return ''
    try:
        u = urlparse(value)
        return value if u.scheme in (('https', 'http') if allow_http else ('https',)) and u.hostname and not u.username and not u.password else ''
    except ValueError:
        return ''


def credits(raw):
    result = []
    for item in raw.get('attributions', []) or []:
        if not isinstance(item, dict): continue
        name = item.get('provider') or ''
        url = safe_url(item.get('providerUri'), allow_http=True)
        if name or url: result.append(f'{name} {url}'.strip())
    return tuple(result)


def valid_rectangle(value):
    try:
        a, b = value['low'], value['high']
        south, west, north, east = a['latitude'], a['longitude'], b['latitude'], b['longitude']
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (south, west, north, east)):
            return False
        width = (east - west) % 360
        return -90 <= south < north <= 90 and -180 <= west <= 180 and -180 <= east <= 180 and 0 < width <= 180
    except (KeyError, TypeError): return False


def coordinate(raw):
    try:
        return Coordinate(float(raw['latitude']), float(raw['longitude']))
    except (KeyError, TypeError, ValueError):
        return None


def opening_windows(raw, default_offset):
    hours = raw.get('currentOpeningHours')
    if not isinstance(hours, dict):
        return (), False
    result = []
    zone = timezone(timedelta(minutes=int(raw.get('utcOffsetMinutes', default_offset) or 0)))
    for period in hours.get('periods', []) or []:
        try:
            opened, closed = period['open'], period['close']
            od, cd = opened['date'], closed['date']
            start = datetime(od['year'], od['month'], od['day'], opened.get('hour', 0),
                             opened.get('minute', 0), tzinfo=zone)
            end = datetime(cd['year'], cd['month'], cd['day'], closed.get('hour', 0),
                           closed.get('minute', 0), tzinfo=zone)
            if end > start: result.append((start, end))
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(result), True


class GoogleSource:
    mode = 'real'
    label = 'Google Maps — реальные места.'
    geography_hint = 'Введите город и страну или район вместе с городом и страной. Найденную территорию нужно подтвердить.'

    def __init__(self, api_key, client=None, retry_delay=0.5):
        if not api_key: raise SourceError('В real-режиме требуется GOOGLE_PLACES_API_KEY.')
        self._key = api_key
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(8, connect=3), follow_redirects=False)
        self.retry_delay = retry_delay

    async def close(self):
        await self._client.aclose()

    async def _request(self, body, fields, budget):
        for attempt in range(2):
            budget.take()
            try:
                response = await asyncio.wait_for(self._client.post(ENDPOINT, json=body, headers={
                    'X-Goog-Api-Key': self._key, 'X-Goog-FieldMask': fields,
                }), timeout=10)
            except (httpx.TransportError, asyncio.TimeoutError):
                if attempt == 0:
                    await asyncio.sleep(self.retry_delay)
                    continue
                raise SourceError('Google не ответил вовремя. Выбор сохранён; попробуйте поиск позже.') from None
            status = response.status_code
            if status in (500, 502, 503, 504) and attempt == 0:
                await asyncio.sleep(self.retry_delay)
                continue
            if status in (401, 403):
                raise SourceError('Google отклонил доступ. Администратору нужно проверить ключ, API и биллинг. Выбор сохранён.')
            if status == 429:
                raise SourceError('Лимит или квота Google исчерпаны. Попробуйте позже; выбор сохранён.')
            if status != 200:
                raise SourceError('Поиск Google сейчас недоступен. Попробуйте позже или уточните географию. Выбор сохранён.')
            try:
                payload = response.json()
                if not isinstance(payload, dict): raise ValueError()
                places = payload.get('places', [])
                if not isinstance(places, list) or any(not isinstance(p, dict) for p in places): raise ValueError()
                return places
            except (ValueError, TypeError):
                raise SourceError('Google вернул неподдерживаемый ответ. Выбор сохранён; попробуйте позже.') from None

    async def _details(self, place_id, budget):
        url = f'https://places.googleapis.com/v1/places/{quote(place_id, safe="")}'
        for attempt in range(2):
            budget.take()
            try:
                response = await asyncio.wait_for(self._client.get(url, headers={
                    'X-Goog-Api-Key': self._key, 'X-Goog-FieldMask': DETAIL_FIELDS,
                }), timeout=10)
            except (httpx.TransportError, asyncio.TimeoutError):
                if attempt == 0:
                    await asyncio.sleep(self.retry_delay)
                    continue
                raise SourceError('Google не ответил вовремя. Выбор сохранён; попробуйте позже.') from None
            if response.status_code in (500, 502, 503, 504) and attempt == 0:
                await asyncio.sleep(self.retry_delay)
                continue
            if response.status_code in (401, 403):
                raise SourceError('Google отклонил доступ. Администратору нужно проверить ключ, API и биллинг. Выбор сохранён.')
            if response.status_code == 429:
                raise SourceError('Лимит или квота Google исчерпаны. Попробуйте позже; выбор сохранён.')
            if response.status_code != 200:
                raise SourceError('Данные выбранного места сейчас недоступны. Выбор сохранён.')
            try:
                payload = response.json()
                if not isinstance(payload, dict): raise ValueError()
                return payload
            except (ValueError, TypeError):
                raise SourceError('Google вернул неподдерживаемый ответ. Выбор сохранён; попробуйте позже.') from None

    async def resolve_geo(self, text, budget):
        text = ' '.join(text.split())
        if not text or len(text) > 200:
            raise SourceError('Введите город и страну или район, город и страну (до 200 символов).')
        rows = await self._request({'textQuery': text, 'languageCode': 'ru', 'pageSize': 5}, GEO_FIELDS, budget)
        candidates = {}
        for p in rows:
            if not p.get('id') or not GEO_TYPES.intersection(p.get('types') or []): continue
            if not valid_rectangle(p.get('viewport')): continue
            label = p.get('formattedAddress') or (p.get('displayName') or {}).get('text')
            if not label: continue
            candidates[p['id']] = Geography(p['id'], label, p['viewport'], credits(p))
        return tuple(candidates.values())[:3]

    async def search_geo(self, geo, categories, budget):
        if not valid_rectangle(geo.rectangle): raise SourceError('Территория поиска недоступна. Уточните город.')
        if not categories or not set(categories) <= QUERIES.keys(): raise SourceError('Выберите доступные интересы.')
        result = {}
        for category, (query, included_type) in QUERIES.items():
            if category not in categories: continue
            body = {'textQuery': query, 'languageCode': 'ru', 'pageSize': 5,
                    'locationRestriction': {'rectangle': geo.rectangle}}
            if included_type:
                body.update(includedType=included_type, strictTypeFiltering=True)
            rows = await self._request(body, PLACE_FIELDS, budget)
            for p in rows[:5]:
                id = p.get('id')
                if not isinstance(id, str) or not id: continue
                if id in result:
                    old = result[id]
                    result[id] = replace(old, categories=tuple(dict.fromkeys((*old.categories, category))),
                                         attributions=tuple(dict.fromkeys((*old.attributions, *credits(p)))))
                    continue
                result[id] = Place(id, (p.get('displayName') or {}).get('text') or 'Название не указано',
                                   geo.label, '', category, p.get('formattedAddress') or 'Адрес не указан',
                                   safe_url(p.get('googleMapsUri')), credits(p), (category,),
                                   coordinate(p.get('location') or {}))
        return tuple(result.values())[:15]

    async def resolve_endpoint(self, text, geo, budget):
        text = ' '.join(text.split())
        if not text or len(text) > 200:
            raise SourceError('Введите адрес или название точки (до 200 символов).')
        body = {'textQuery': text, 'languageCode': 'ru', 'pageSize': 3,
                'locationRestriction': {'rectangle': geo.rectangle}}
        rows = await self._request(body, ENDPOINT_FIELDS, budget)
        result = []
        for item in rows:
            point = coordinate(item.get('location') or {})
            name = (item.get('displayName') or {}).get('text')
            if not item.get('id') or not point or not name: continue
            address = item.get('formattedAddress')
            result.append(Endpoint(item['id'], f'{name} — {address}' if address else name, point,
                                   int(item.get('utcOffsetMinutes') or 0),
                                   safe_url(item.get('googleMapsUri')), credits(item)))
        return tuple(result[:3])

    async def enrich_selected(self, places, day, budget):
        result = []
        for place in places:
            raw = await self._details(place.id, budget)
            windows, known = opening_windows(raw, 0)
            result.append(replace(place,
                                  coordinate=coordinate(raw.get('location') or {}) or place.coordinate,
                                  opening_windows=windows,
                                  hours_known=known,
                                  maps_url=safe_url(raw.get('googleMapsUri')) or place.maps_url,
                                  attributions=tuple(dict.fromkeys((*place.attributions, *credits(raw))))))
        return tuple(result)

    async def refresh_saved_places(self, saved_places, day, budget):
        result = []
        for saved in saved_places:
            raw = await self._details(saved.place_id, budget)
            point = coordinate(raw.get('location') or {})
            if point is None:
                raise SourceError('У одного из сохранённых мест больше нет координат.')
            windows, known = opening_windows(raw, 0)
            result.append(Place(saved.place_id,
                (raw.get('displayName') or {}).get('text') or 'Название не указано', '', '',
                saved.category, raw.get('formattedAddress') or 'Адрес не указан',
                safe_url(raw.get('googleMapsUri')), credits(raw), saved.categories,
                point, windows, known))
        return tuple(result)

    async def refresh_saved_endpoint(self, saved, role, budget):
        raw = await self._details(saved.place_id, budget) if saved.place_id else {}
        point = coordinate(raw.get('location') or {}) or saved.coordinate
        return Endpoint(role + ':' + saved.place_id, saved.query, point,
                        int(raw.get('utcOffsetMinutes', saved.utc_offset_minutes) or 0),
                        safe_url(raw.get('googleMapsUri')), credits(raw))
