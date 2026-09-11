import json
import unittest
from datetime import datetime, timezone

import httpx

from travel_bot.day import Coordinate, Endpoint
from travel_bot.routes import PlanningBudget, RoutesClient, RoutesError


class RoutesTests(unittest.IsolatedAsyncioTestCase):
    def client(self, handler):
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(http.aclose)
        return RoutesClient('ROUTES_SECRET', client=http, retry_delay=0)

    def points(self):
        return (Endpoint('start', 'Start', Coordinate(1, 2)),
                Endpoint('a', 'A', Coordinate(3, 4)),
                Endpoint('b', 'B', Coordinate(5, 6)))

    async def test_two_matrices_map_elements_and_departure(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json=[
                {'originIndex': 0, 'destinationIndex': 0, 'status': {},
                 'condition': 'ROUTE_EXISTS', 'duration': '900s', 'distanceMeters': 1200},
                {'originIndex': 0, 'destinationIndex': 1, 'status': {},
                 'condition': 'ROUTE_NOT_FOUND'},
            ])
        client = self.client(handler)
        origins, destinations = self.points()[:2], self.points()[1:]
        departure = datetime(2026, 9, 10, 7, tzinfo=timezone.utc)
        matrix = await client.matrices(origins, destinations, departure, PlanningBudget())
        self.assertEqual(matrix.get('start', 'a', 'WALK').duration_min, 15)
        self.assertIsNone(matrix.get('start', 'b', 'WALK'))
        self.assertEqual(len(requests), 2)
        bodies = [json.loads(r.content) for r in requests]
        self.assertEqual([b['travelMode'] for b in bodies], ['WALK', 'TRANSIT'])
        self.assertNotIn('departureTime', bodies[0])
        self.assertEqual(bodies[1]['departureTime'], '2026-09-10T07:00:00Z')
        self.assertEqual(requests[0].headers['X-Goog-FieldMask'],
                         'originIndex,destinationIndex,status,condition,distanceMeters,duration')
        self.assertNotIn('ROUTES_SECRET', str(bodies))

    async def test_budget_rejects_excess_before_network(self):
        calls = []
        client = self.client(lambda request: calls.append(request) or httpx.Response(200, json=[]))
        points = tuple(Endpoint(str(i), str(i), Coordinate(1, 2)) for i in range(8))
        with self.assertRaises(RoutesError):
            await client.matrices(points[:7], points, datetime.now(timezone.utc), PlanningBudget())
        self.assertEqual(calls, [])

    async def test_validate_transit_counts_transfers_and_details(self):
        def handler(request):
            return httpx.Response(200, json={'routes': [{
                'duration': '1200s', 'distanceMeters': 5000, 'warnings': ['Check schedule'],
                'legs': [{'steps': [
                    {'travelMode': 'WALK'},
                    {'travelMode': 'TRANSIT', 'navigationInstruction': {'instructions': 'Bus 1'},
                     'transitDetails': {'transitLine': {'name': 'Line 1'}}},
                    {'travelMode': 'TRANSIT', 'navigationInstruction': {'instructions': 'Metro 2'},
                     'transitDetails': {'transitLine': {'name': 'Line 2'}}},
                ]}]}]})
        client = self.client(handler)
        start, end = self.points()[:2]
        result = await client.validate_leg(start, end, datetime(2026, 9, 10, 7, tzinfo=timezone.utc),
                                           'TRANSIT', PlanningBudget(), detailed=True)
        self.assertEqual(result.duration_min, 20)
        self.assertEqual(result.transfers, 1)
        self.assertEqual(result.steps, ('Пешком', 'Bus 1', 'Metro 2'))
        self.assertIn('Check schedule', result.warnings)
        self.assertIn('travelmode=transit', result.maps_url)

    async def test_partial_auth_quota_timeout_and_retry_are_safe(self):
        for status in (401, 403, 429):
            with self.subTest(status=status):
                client = self.client(lambda request, s=status: httpx.Response(s, text='ROUTES_SECRET body'))
                with self.assertRaises(RoutesError) as caught:
                    await client.validate_leg(self.points()[0], self.points()[1],
                                              datetime.now(timezone.utc), 'WALK', PlanningBudget())
                self.assertNotIn('ROUTES_SECRET', str(caught.exception))
        attempts = []
        def transient(request):
            attempts.append(request)
            return httpx.Response(503) if len(attempts) == 1 else httpx.Response(200, json={'routes': []})
        client = self.client(transient)
        with self.assertRaises(RoutesError):
            await client.validate_leg(self.points()[0], self.points()[1],
                                      datetime.now(timezone.utc), 'WALK', PlanningBudget())
        self.assertEqual(len(attempts), 2)


if __name__ == '__main__':
    unittest.main()
