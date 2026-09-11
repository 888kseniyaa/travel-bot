from dataclasses import replace
from datetime import datetime, timedelta, timezone
from itertools import permutations

from .day import Exclusion, PlanCandidate, PlanLeg, PlanStop


def choose_mode(walk, transit):
    if walk is None:
        return transit
    if transit is None:
        if walk.duration_min > 40:
            return replace(walk, warnings=(*walk.warnings,
                           'Общественный транспорт недоступен; выбран длинный пеший переход.'))
        return walk
    if walk.duration_min <= 15:
        return walk
    if walk.duration_min <= 40:
        return transit if transit.duration_min + transit.transfers * 5 < walk.duration_min else walk
    return transit


def _after_break(current, duration, lunch):
    if lunch is None:
        return current
    start, end = lunch
    finish = current + timedelta(minutes=duration)
    if current < end and finish > start:
        return end
    return current


def _visit_start(place, current, duration, lunch):
    current = _after_break(current, duration, lunch)
    if not place.hours_known:
        return current
    for start, end in place.opening_windows:
        candidate = max(current, start)
        candidate = _after_break(candidate, duration, lunch)
        if candidate + timedelta(minutes=duration) <= end:
            return candidate
    return None


def _exclusions(all_places, included, durations):
    result = []
    included = set(included)
    for place in all_places:
        if place.id in included:
            continue
        reason = ('место закрыто в выбранный день'
                  if place.hours_known and not place.opening_windows
                  else 'не помещается в доступное время или лимит ходьбы')
        result.append(Exclusion(place.id, place.name, reason, durations[place.id]))
    return tuple(result)


def evaluate_order(order, parameters, start, finish, all_places, durations, matrix):
    zone = timezone(timedelta(minutes=start.utc_offset_minutes))
    day_start, day_end = parameters.bounds(zone)
    lunch = None
    if parameters.lunch:
        lunch_start = datetime.combine(parameters.date, parameters.lunch.start, zone)
        lunch = (lunch_start, lunch_start + timedelta(minutes=parameters.lunch.duration_min))
    current = day_start
    previous = start
    legs, stops, warnings = [], [], []
    walking = travel = transfers = 0
    for place in order:
        chosen = choose_mode(matrix.get(previous.id, place.id, 'WALK'),
                             matrix.get(previous.id, place.id, 'TRANSIT'))
        if chosen is None:
            return None
        leg_start = _after_break(current, chosen.duration_min, lunch)
        leg_end = leg_start + timedelta(minutes=chosen.duration_min)
        visit_start = _visit_start(place, leg_end, durations[place.id], lunch)
        if visit_start is None:
            return None
        visit_end = visit_start + timedelta(minutes=durations[place.id])
        if visit_end > day_end:
            return None
        legs.append(PlanLeg(chosen, leg_start, leg_end))
        stops.append(PlanStop(place.id, place.name, visit_start, visit_end,
                              durations[place.id], not place.hours_known))
        if not place.hours_known:
            warnings.append(f'Часы работы неизвестны: {place.name}')
        warnings.extend(chosen.warnings)
        walking += chosen.duration_min if chosen.mode == 'WALK' else 0
        travel += chosen.duration_min
        transfers += chosen.transfers
        if walking > parameters.walking_limit_min:
            return None
        current, previous = visit_end, place
    if finish:
        chosen = choose_mode(matrix.get(previous.id, finish.id, 'WALK'),
                             matrix.get(previous.id, finish.id, 'TRANSIT'))
        if chosen is None:
            return None
        leg_start = _after_break(current, chosen.duration_min, lunch)
        leg_end = leg_start + timedelta(minutes=chosen.duration_min)
        if leg_end > day_end:
            return None
        legs.append(PlanLeg(chosen, leg_start, leg_end))
        walking += chosen.duration_min if chosen.mode == 'WALK' else 0
        travel += chosen.duration_min
        transfers += chosen.transfers
        warnings.extend(chosen.warnings)
        current = leg_end
        if walking > parameters.walking_limit_min:
            return None
    return PlanCandidate(tuple(p.id for p in order), tuple(stops), tuple(legs),
                         _exclusions(all_places, (p.id for p in order), durations),
                         current, walking, travel, transfers,
                         tuple(dict.fromkeys(warnings)))


def rank_candidates(parameters, start, finish, places, durations, matrix):
    candidates = []
    for size in range(len(places), 0, -1):
        for order in permutations(places, size):
            candidate = evaluate_order(order, parameters, start, finish, places, durations, matrix)
            if candidate:
                candidates.append(candidate)
    candidates.sort(key=lambda c: (-len(c.place_ids), c.finish, c.travel_min,
                                   c.walking_min, c.transfers, c.place_ids))
    return tuple(candidates)
