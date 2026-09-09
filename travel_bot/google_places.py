"""Places API (New), Text Search only. No disk cache, photos or reviews."""
import asyncio
import math
from dataclasses import dataclass, replace
from urllib.parse import urlparse
import httpx
from .places import Place

ENDPOINT = 'https://places.googleapis.com/v1/places:searchText'
GEO_FIELDS = 'places.id,places.displayName,places.formattedAddress,places.types,places.viewport,places.attributions'
PLACE_FIELDS = 'places.id,places.displayName,places.formattedAddress,places.googleMapsUri,places.attributions'
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
                                   safe_url(p.get('googleMapsUri')), credits(p), (category,))
        return tuple(result.values())[:15]
