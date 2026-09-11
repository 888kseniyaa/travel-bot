import asyncio
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx

from .day import TravelOption


MATRIX_URL = 'https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix'
ROUTE_URL = 'https://routes.googleapis.com/directions/v2:computeRoutes'
MATRIX_MASK = 'originIndex,destinationIndex,status,condition,distanceMeters,duration'
SUMMARY_MASK = ('routes.duration,routes.distanceMeters,routes.warnings,'
                'routes.legs.steps.travelMode,routes.legs.steps.transitDetails')
DETAIL_MASK = SUMMARY_MASK + ',routes.legs.steps.navigationInstruction,routes.legs.steps.localizedValues'


class RoutesError(ValueError):
    pass


class RouteUnavailable(RoutesError):
    pass


@dataclass
class PlanningBudget:
    matrix_calls: int = 0
    matrix_elements: int = 0
    route_calls: int = 0
    detailed_legs: set[str] = field(default_factory=set)

    def take_matrix(self, elements):
        if elements > 49 or self.matrix_calls >= 2:
            raise RoutesError('Превышен лимит матрицы маршрута. Уменьшите число мест.')
        self.matrix_calls += 1
        self.matrix_elements += elements

    def take_route(self, detailed=False, leg_key=''):
        if detailed:
            if not leg_key or leg_key in self.detailed_legs:
                raise RoutesError('Подробности этого перехода уже запрашивались.')
            self.detailed_legs.add(leg_key)
        elif self.route_calls >= 12:
            raise RoutesError('Лимит проверок маршрута исчерпан. Измените параметры и повторите расчёт.')
        if not detailed:
            self.route_calls += 1


class TravelMatrix:
    def __init__(self, options=()):
        self._options = {(x.origin_id, x.destination_id, x.mode): x for x in options}

    def get(self, origin_id, destination_id, mode):
        return self._options.get((origin_id, destination_id, mode))

    def options(self):
        return tuple(self._options.values())


def duration_minutes(value):
    if not isinstance(value, str) or not value.endswith('s'):
        raise ValueError('invalid duration')
    seconds = float(value[:-1])
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError('invalid duration')
    return max(1, math.ceil(seconds / 60))


def coordinate_body(point):
    return {'location': {'latLng': {
        'latitude': point.coordinate.latitude,
        'longitude': point.coordinate.longitude,
    }}}


def matrix_waypoint(point):
    return {'waypoint': coordinate_body(point)}


def departure_text(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def directions_url(origin, destination, mode):
    query = urlencode({
        'api': '1',
        'origin': f'{origin.coordinate.latitude},{origin.coordinate.longitude}',
        'destination': f'{destination.coordinate.latitude},{destination.coordinate.longitude}',
        'travelmode': 'transit' if mode == 'TRANSIT' else 'walking',
    })
    return 'https://www.google.com/maps/dir/?' + query


class RoutesClient:
    def __init__(self, api_key, client=None, retry_delay=0.5):
        if not api_key:
            raise RoutesError('Для планирования требуется ключ Routes API.')
        self._key = api_key
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(8, connect=3), follow_redirects=False)
        self.retry_delay = retry_delay

    async def close(self):
        await self._client.aclose()

    async def _post(self, url, body, mask):
        for attempt in range(2):
            try:
                response = await asyncio.wait_for(self._client.post(url, json=body, headers={
                    'X-Goog-Api-Key': self._key,
                    'X-Goog-FieldMask': mask,
                }), timeout=10)
            except (httpx.TransportError, asyncio.TimeoutError):
                if attempt == 0:
                    await asyncio.sleep(self.retry_delay)
                    continue
                raise RoutesError('Google Routes не ответил вовремя. Параметры и выбор сохранены.') from None
            if response.status_code in (500, 502, 503, 504) and attempt == 0:
                await asyncio.sleep(self.retry_delay)
                continue
            if response.status_code in (401, 403):
                raise RoutesError('Google отклонил доступ к Routes API. Проверьте ключ, API и биллинг.')
            if response.status_code == 429:
                raise RoutesError('Квота Google Routes исчерпана. Повторите расчёт позже.')
            if response.status_code != 200:
                raise RoutesError('Маршруты Google сейчас недоступны. Параметры и выбор сохранены.')
            try:
                return response.json()
            except ValueError:
                raise RoutesError('Google Routes вернул неподдерживаемый ответ.') from None

    async def matrices(self, origins, destinations, departure, budget):
        elements = len(origins) * len(destinations)
        if not origins or not destinations or elements > 49:
            raise RoutesError('Для матрицы допускается не более 49 элементов на режим.')
        options = []
        for mode in ('WALK', 'TRANSIT'):
            budget.take_matrix(elements)
            body = {
                'origins': [matrix_waypoint(x) for x in origins],
                'destinations': [matrix_waypoint(x) for x in destinations],
                'travelMode': mode,
                'languageCode': 'ru',
                'units': 'METRIC',
            }
            if mode == 'TRANSIT':
                body['departureTime'] = departure_text(departure)
            payload = await self._post(MATRIX_URL, body, MATRIX_MASK)
            if not isinstance(payload, list):
                raise RoutesError('Google Routes вернул неполную матрицу.')
            for item in payload:
                try:
                    oi, di = item['originIndex'], item['destinationIndex']
                    if item.get('status') or item.get('condition') != 'ROUTE_EXISTS':
                        continue
                    if not (0 <= oi < len(origins) and 0 <= di < len(destinations)):
                        continue
                    minutes = duration_minutes(item['duration'])
                    distance = int(item.get('distanceMeters') or 0)
                    options.append(TravelOption(origins[oi].id, destinations[di].id, mode,
                                                minutes, distance))
                except (KeyError, TypeError, ValueError):
                    continue
        return TravelMatrix(options)

    async def validate_leg(self, origin, destination, departure, mode, budget,
                           detailed=False):
        leg_key = f'{origin.id}:{destination.id}:{mode}'
        budget.take_route(detailed, leg_key)
        body = {
            'origin': coordinate_body(origin),
            'destination': coordinate_body(destination),
            'travelMode': mode,
            'languageCode': 'ru',
            'units': 'METRIC',
        }
        if mode == 'TRANSIT':
            body['departureTime'] = departure_text(departure)
        payload = await self._post(ROUTE_URL, body, DETAIL_MASK if detailed else SUMMARY_MASK)
        routes = payload.get('routes') if isinstance(payload, dict) else None
        if not routes:
            raise RouteUnavailable('Для одного из переходов маршрут не найден.')
        route = routes[0]
        try:
            minutes = duration_minutes(route['duration'])
            distance = int(route.get('distanceMeters') or 0)
        except (KeyError, TypeError, ValueError):
            raise RoutesError('Google Routes вернул неполный переход.') from None
        steps = []
        transit_count = 0
        for leg in route.get('legs', []) or []:
            for step in leg.get('steps', []) or []:
                travel_mode = step.get('travelMode', '')
                if travel_mode == 'TRANSIT': transit_count += 1
                if detailed:
                    instruction = (step.get('navigationInstruction') or {}).get('instructions')
                    if instruction: steps.append(instruction)
                    elif travel_mode == 'WALK': steps.append('Пешком')
                    elif travel_mode == 'TRANSIT':
                        line = (step.get('transitDetails') or {}).get('transitLine') or {}
                        steps.append(line.get('name') or 'Общественный транспорт')
        return TravelOption(origin.id, destination.id, mode, minutes, distance,
                            max(0, transit_count - 1), tuple(route.get('warnings') or ()),
                            directions_url(origin, destination, mode), tuple(steps))
