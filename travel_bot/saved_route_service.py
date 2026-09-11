"""Application service for permitted saved-route persistence and refresh."""
from dataclasses import dataclass

from .google_places import Budget
from .route_repository import StaleRoute
from .saved_routes import (
    SavedEndpoint, SavedPlace, SavedRoutePayload, default_route_name,
    route_fingerprint,
)


class SavedRouteError(ValueError): pass


@dataclass(frozen=True)
class OpenedSavedRoute:
    saved: object
    places: tuple
    start: object
    finish: object
    plan: object


def _google_id(value, role):
    marker = role + ':'
    return value.id[len(marker):] if value.id.startswith(marker) else value.id


class SavedRouteService:
    def __init__(self, repository, place_source, planning_service):
        self.repository = repository
        self.place_source = place_source
        self.planning_service = planning_service

    def _endpoint(self, value, query, role):
        if value is None: return None
        return SavedEndpoint(_google_id(value, role), query or f'{role} маршрута',
                             value.coordinate, value.utc_offset_minutes)

    def payload_from_session(self, session):
        if not session.plan or not session.day_parameters or not session.start_endpoint:
            raise SavedRouteError('Сначала рассчитайте маршрут.')
        places = tuple(SavedPlace(p.id, p.category, p.categories or (p.category,),
                                  session.selected[p.id])
                       for p in session.places if p.id in session.selected)
        return SavedRoutePayload(
            1, session.geography_query or session.city or 'Маршрут', session.day_parameters,
            self._endpoint(session.start_endpoint, session.start_query, 'start'),
            self._endpoint(session.finish_endpoint, session.finish_query, 'finish'),
            places, tuple(stop.place_id for stop in session.plan.stops),
            tuple('excluded:' + x.place_id for x in session.plan.exclusions))

    def autosave(self, session, owner_user_id):
        payload = self.payload_from_session(session)
        return self.repository.save(owner_user_id,
            default_route_name(payload.day.date, payload.geography_query),
            payload.geography_query, route_fingerprint(payload), payload)

    def list(self, owner_user_id, page=0):
        return self.repository.list(owner_user_id, page * 5, 5)

    def get(self, owner_user_id, route_id): return self.repository.get(owner_user_id, route_id)
    def count(self, owner_user_id): return self.repository.count(owner_user_id)
    def rename(self, owner_user_id, route_id, version, name):
        return self.repository.rename(owner_user_id, route_id, version, name)
    def delete(self, owner_user_id, route_id, version):
        return self.repository.delete(owner_user_id, route_id, version)
    def delete_all(self, owner_user_id): return self.repository.delete_all(owner_user_id)

    async def open_current(self, owner_user_id, route_id, expected_version):
        saved = self.repository.get(owner_user_id, route_id)
        if saved.summary.version != expected_version:
            raise StaleRoute('Маршрут изменился. Откройте актуальную карточку.')
        budget = Budget()
        places = await self.place_source.refresh_saved_places(saved.payload.places,
                                                               saved.payload.day, budget)
        by_id = {p.id: p for p in places}
        try: ordered = tuple(by_id[x] for x in saved.payload.order)
        except KeyError:
            raise SavedRouteError('Одно из сохранённых мест больше недоступно.') from None
        start = await self.place_source.refresh_saved_endpoint(saved.payload.start, 'start', budget)
        finish = (await self.place_source.refresh_saved_endpoint(saved.payload.finish, 'finish', budget)
                  if saved.payload.finish else None)
        durations = {x.place_id: x.duration_min for x in saved.payload.places}
        plan = await self.planning_service.validate_fixed_order(
            saved.payload.day, start, finish, ordered, durations, all_places=places)
        return OpenedSavedRoute(saved, places, start, finish, plan)
