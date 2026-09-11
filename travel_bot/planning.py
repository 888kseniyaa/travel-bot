import hashlib
from datetime import timedelta, timezone

from .day import DayPlan
from .planner import evaluate_order, rank_candidates
from .routes import PlanningBudget, RouteUnavailable, RoutesError, TravelMatrix


def calculation_fingerprint(session):
    data = (
        tuple(sorted(session.selected.items())),
        session.day_parameters,
        session.start_endpoint,
        session.finish_endpoint,
        tuple(p.id for p in session.places),
    )
    return hashlib.sha256(repr(data).encode()).hexdigest()


def _still_current(dialog, key, session, operation, fingerprint):
    return (dialog.store.get(key) is session and
            session.planning_operation is operation and
            calculation_fingerprint(session) == fingerprint)


def _point_map(session, places):
    result = {session.start_endpoint.id: session.start_endpoint}
    result.update({p.id: p for p in places})
    if session.finish_endpoint:
        result[session.finish_endpoint.id] = session.finish_endpoint
    return result


class PlanningService:
    def __init__(self, place_source, routes):
        self.place_source = place_source
        self.routes = routes

    async def calculate(self, dialog, key, session, fingerprint):
        if session.planning_operation is not None:
            return None
        operation = object()
        session.planning_operation = operation
        session.stage = 'planning'
        session.notice = ''
        try:
            if calculation_fingerprint(session) != fingerprint:
                return None
            selected = tuple(p for p in session.places if p.id in session.selected)
            if not 1 <= len(selected) <= 6:
                raise RoutesError('Для расчёта выберите от одного до шести мест.')
            if not session.day_parameters or not session.start_endpoint:
                raise RoutesError('Сначала заполните параметры дня и подтвердите стартовую точку.')
            enriched = await self.place_source.enrich_selected(selected, session.day_parameters,
                                                               session.budget)
            if any(p.coordinate is None for p in enriched):
                raise RoutesError('Для одного из мест отсутствуют координаты. Измените список мест.')
            if not _still_current(dialog, key, session, operation, fingerprint):
                return None
            zone = timezone(timedelta(minutes=session.start_endpoint.utc_offset_minutes))
            departure = session.day_parameters.bounds(zone)[0]
            origins = (session.start_endpoint, *enriched)
            destinations = (*enriched,) + ((session.finish_endpoint,) if session.finish_endpoint else ())
            budget = PlanningBudget()
            matrix = await self.routes.matrices(origins, destinations, departure, budget)
            if not _still_current(dialog, key, session, operation, fingerprint):
                return None
            durations = {p.id: session.selected[p.id] for p in enriched}
            candidates = rank_candidates(session.day_parameters, session.start_endpoint,
                                         session.finish_endpoint, enriched, durations, matrix)
            if not candidates:
                raise RoutesError('Ни один выбранный вариант не помещается в день или содержит недоступные переходы.')
            points = _point_map(session, enriched)
            final = None
            for candidate in candidates:
                working = {(x.origin_id, x.destination_id, x.mode): x for x in matrix.options()}
                current = candidate
                try:
                    for index in range(len(current.legs)):
                        leg = current.legs[index]
                        origin = points[leg.option.origin_id]
                        destination = points[leg.option.destination_id]
                        walk = working.get((origin.id, destination.id, 'WALK'))
                        transit = working.get((origin.id, destination.id, 'TRANSIT'))
                        mode = 'TRANSIT' if transit and (walk is None or walk.duration_min > 15) else 'WALK'
                        try:
                            exact = await self.routes.validate_leg(origin, destination, leg.departure,
                                                                   mode, budget)
                        except RouteUnavailable:
                            if mode != 'TRANSIT' or walk is None:
                                raise
                            working.pop((origin.id, destination.id, 'TRANSIT'), None)
                            exact = await self.routes.validate_leg(origin, destination, leg.departure,
                                                                   'WALK', budget)
                            mode = 'WALK'
                        working[(origin.id, destination.id, mode)] = exact
                        current = evaluate_order(tuple(points[x] for x in candidate.place_ids),
                                                 session.day_parameters, session.start_endpoint,
                                                 session.finish_endpoint, enriched, durations,
                                                 TravelMatrix(working.values()))
                        if current is None:
                            raise RouteUnavailable('Уточнённый вариант нарушает ограничения дня.')
                    final = current
                    break
                except RouteUnavailable:
                    continue
            if final is None:
                raise RoutesError('Не удалось подтвердить реалистичное расписание для выбранных мест.')
            if not _still_current(dialog, key, session, operation, fingerprint):
                return None
            day_start = session.day_parameters.bounds(zone)[0]
            session.plan = DayPlan(final.stops, final.legs, final.exclusions, day_start,
                                   final.finish, final.walking_min, final.travel_min,
                                   final.warnings)
            session.planning_budget = budget
            session.stage = 'planned'
            session.notice = ''
            return session.plan
        except RoutesError as error:
            if _still_current(dialog, key, session, operation, fingerprint):
                session.notice = str(error)
                session.stage = 'confirmed'
            return None
        except Exception:
            if _still_current(dialog, key, session, operation, fingerprint):
                session.notice = 'Расчёт временно недоступен. Выбор и параметры сохранены.'
                session.stage = 'confirmed'
            return None
        finally:
            if dialog.store.get(key) is session and session.planning_operation is operation:
                session.planning_operation = None
                session.revision += 1

    async def detail(self, dialog, key, session, leg_index, fingerprint):
        if calculation_fingerprint(session) != fingerprint or not session.plan:
            return None
        if not 0 <= leg_index < len(session.plan.legs):
            return None
        leg = session.plan.legs[leg_index]
        selected = tuple(p for p in session.places if p.id in session.selected)
        points = _point_map(session, selected)
        result = await self.routes.validate_leg(points[leg.option.origin_id],
                                                points[leg.option.destination_id],
                                                leg.departure, leg.option.mode,
                                                session.planning_budget or PlanningBudget(),
                                                detailed=True)
        return result if dialog.store.get(key) is session and calculation_fingerprint(session) == fingerprint else None
