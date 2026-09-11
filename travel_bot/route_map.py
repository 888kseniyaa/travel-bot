"""Pure Google Maps route-link presentation; performs no network requests."""
from dataclasses import dataclass
from urllib.parse import urlencode

from .day import DayPlan, Endpoint
from .places import Place


BASE_URL = 'https://www.google.com/maps/dir/?'
MAX_URL_LENGTH = 2048
MOBILE_WAYPOINT_LIMIT = 3


class RouteMapError(ValueError):
    pass


@dataclass(frozen=True)
class RouteMapLink:
    url: str
    mobile_waypoint_warning: bool = False


def _endpoint_place_id(endpoint, prefix):
    marker = prefix + ':'
    return endpoint.id[len(marker):] if endpoint.id.startswith(marker) else ''


def _place_text(place):
    if place.coordinate is None:
        raise RouteMapError('Ссылка на карту недоступна: у одного из мест нет координат.')
    return place.address or place.name or f'{place.coordinate.latitude},{place.coordinate.longitude}'


def _build_link(start: Endpoint, finish: Endpoint | None, ordered_ids,
                places: tuple[Place, ...]) -> RouteMapLink:
    by_id = {place.id: place for place in places}
    try:
        visited = tuple(by_id[place_id] for place_id in ordered_ids)
    except KeyError:
        raise RouteMapError('Ссылка на карту недоступна: место отсутствует в текущем подборе.') from None

    if finish is None:
        if not visited:
            raise RouteMapError('Для ссылки на карту требуется не менее двух точек.')
        destination, waypoints = visited[-1], visited[:-1]
        destination_text = _place_text(destination)
        destination_id = destination.id
    else:
        destination, waypoints = finish, visited
        destination_text = finish.label
        destination_id = _endpoint_place_id(finish, 'finish')

    params = {'api': '1', 'origin': start.label, 'destination': destination_text}
    origin_id = _endpoint_place_id(start, 'start')
    if origin_id:
        params['origin_place_id'] = origin_id
    if destination_id:
        params['destination_place_id'] = destination_id
    if waypoints:
        params['waypoints'] = '|'.join(_place_text(place) for place in waypoints)
        params['waypoint_place_ids'] = '|'.join(place.id for place in waypoints)

    url = BASE_URL + urlencode(params)
    if len(url) > MAX_URL_LENGTH:
        raise RouteMapError('Ссылка Google Maps превышает предел 2048 символов.')
    return RouteMapLink(url, len(waypoints) > MOBILE_WAYPOINT_LIMIT)


def build_route_map_link(start: Endpoint, finish: Endpoint | None, plan: DayPlan,
                         places: tuple[Place, ...]) -> RouteMapLink:
    return _build_link(start, finish, (stop.place_id for stop in plan.stops), places)


def build_selected_route_map_link(start: Endpoint, finish: Endpoint | None,
                                  selected_ids, places: tuple[Place, ...]) -> RouteMapLink:
    """Build a best-effort link when Routes API cannot calculate a plan."""
    return _build_link(start, finish, selected_ids, places)
