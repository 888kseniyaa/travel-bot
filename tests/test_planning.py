import asyncio
import unittest
from datetime import date, datetime, time, timezone

from travel_bot.day import Coordinate, DayParameters, Endpoint, TravelOption
from travel_bot.dialog import Dialog
from travel_bot.places import Place
from travel_bot.planning import PlanningService, calculation_fingerprint
from travel_bot.routes import PlanningBudget, RouteUnavailable, RoutesError, TravelMatrix


class Source:
    async def enrich_selected(self, places, day, budget):
        return places


class Routes:
    def __init__(self):
        self.calls = []
        self.gate = None
    async def matrices(self, origins, destinations, departure, budget):
        options = []
        for a in origins:
            for b in destinations:
                if a.id != b.id:
                    options += [TravelOption(a.id, b.id, 'WALK', 20),
                                TravelOption(a.id, b.id, 'TRANSIT', 10)]
        return TravelMatrix(options)
    async def validate_leg(self, origin, destination, departure, mode, budget, detailed=False):
        self.calls.append((origin.id, destination.id, departure, mode, detailed))
        if self.gate: await self.gate.wait()
        return TravelOption(origin.id, destination.id, mode, 10, transfers=0,
                            steps=('Step',) if detailed else ())


def configured_dialog():
    dialog = Dialog()
    key = (1, 1)
    dialog.start(key)
    session = dialog.require(key)
    session.places = (Place('a', 'A', '', '', 'museum', coordinate=Coordinate(1, 2)),
                      Place('b', 'B', '', '', 'park', coordinate=Coordinate(2, 3)))
    session.selected = {'a': 60, 'b': 30}
    session.day_parameters = DayParameters(date(2026, 9, 10), time(9), time(20))
    session.start_endpoint = Endpoint('s', 'Start', Coordinate(0, 1))
    session.stage = 'confirmed'
    return dialog, key, session


class PlanningTests(unittest.IsolatedAsyncioTestCase):
    async def test_calculation_commits_complete_plan(self):
        dialog, key, session = configured_dialog()
        routes = Routes()
        service = PlanningService(Source(), routes)
        fingerprint = calculation_fingerprint(session)
        outcome = await service.calculate(dialog, key, session, fingerprint)
        self.assertIs(outcome, session.plan)
        self.assertEqual(len(outcome.stops), 2)
        self.assertEqual([x.option.mode for x in outcome.legs], ['TRANSIT', 'TRANSIT'])
        self.assertEqual(routes.calls[0][2], datetime(2026, 9, 10, 9, tzinfo=timezone.utc))
        self.assertIsNone(session.planning_operation)

    async def test_late_result_after_duration_change_does_not_commit(self):
        dialog, key, session = configured_dialog()
        routes = Routes(); routes.gate = asyncio.Event()
        service = PlanningService(Source(), routes)
        fingerprint = calculation_fingerprint(session)
        task = asyncio.create_task(service.calculate(dialog, key, session, fingerprint))
        await asyncio.sleep(0)
        session.selected['a'] = 75
        routes.gate.set()
        self.assertIsNone(await task)
        self.assertIsNone(session.plan)

    async def test_new_session_and_duplicate_operation_are_safe(self):
        dialog, key, session = configured_dialog()
        routes = Routes(); routes.gate = asyncio.Event()
        service = PlanningService(Source(), routes)
        fingerprint = calculation_fingerprint(session)
        first = asyncio.create_task(service.calculate(dialog, key, session, fingerprint))
        await asyncio.sleep(0)
        second = await service.calculate(dialog, key, session, fingerprint)
        self.assertIsNone(second)
        dialog.start(key); routes.gate.set()
        self.assertIsNone(await first)
        self.assertIsNone(dialog.require(key).plan)

    async def test_detail_is_bounded_and_stale_safe(self):
        dialog, key, session = configured_dialog()
        routes = Routes(); service = PlanningService(Source(), routes)
        fingerprint = calculation_fingerprint(session)
        await service.calculate(dialog, key, session, fingerprint)
        detail = await service.detail(dialog, key, session, 0, calculation_fingerprint(session))
        self.assertEqual(detail.steps, ('Step',))
        session.selected['a'] = 75
        self.assertIsNone(await service.detail(dialog, key, session, 0, fingerprint))

    async def test_unavailable_transit_falls_back_to_walk(self):
        class NoTransit(Routes):
            async def validate_leg(self, origin, destination, departure, mode, budget, detailed=False):
                self.calls.append((origin.id, destination.id, departure, mode, detailed))
                if mode == 'TRANSIT':
                    raise RouteUnavailable('no transit')
                return TravelOption(origin.id, destination.id, 'WALK', 20)
        dialog, key, session = configured_dialog()
        routes = NoTransit()
        outcome = await PlanningService(Source(), routes).calculate(
            dialog, key, session, calculation_fingerprint(session))
        self.assertIsNotNone(outcome)
        self.assertEqual([leg.option.mode for leg in outcome.legs], ['WALK', 'WALK'])

    async def test_failed_calculation_enables_selected_order_map_link(self):
        class BrokenRoutes(Routes):
            async def matrices(self, *args):
                raise RoutesError('Routes API unavailable')
        dialog, key, session = configured_dialog()
        outcome = await PlanningService(Source(), BrokenRoutes()).calculate(
            dialog, key, session, calculation_fingerprint(session))
        self.assertIsNone(outcome)
        self.assertTrue(session.route_link_fallback)
        self.assertEqual(session.stage, 'confirmed')


if __name__ == '__main__':
    unittest.main()
