import json
import unittest
from datetime import date, time

import httpx

from travel_bot.day import Coordinate, DayParameters
from travel_bot.google_places import Budget, Geography, GoogleSource, SourceError
from travel_bot.places import Place


RECTANGLE = {'low': {'latitude': 48.8, 'longitude': 2.2},
             'high': {'latitude': 48.9, 'longitude': 2.4}}


class GooglePlanningTests(unittest.IsolatedAsyncioTestCase):
    def source(self, handler):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(client.aclose)
        return GoogleSource('SECRET', client=client, retry_delay=0)

    async def test_endpoint_candidates_are_restricted_and_mapped(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={'places': [
                {'id': 'hotel', 'displayName': {'text': 'Hotel'},
                 'formattedAddress': '1 Street', 'location': {'latitude': 48.85, 'longitude': 2.3},
                 'utcOffsetMinutes': 120, 'googleMapsUri': 'https://maps.google.com/hotel'},
                {'id': 'station', 'displayName': {'text': 'Station'},
                 'location': {'latitude': 48.86, 'longitude': 2.31}},
            ]})
        source = self.source(handler)
        geo = Geography('paris', 'Paris', RECTANGLE)
        result = await source.resolve_endpoint('Hotel', geo, Budget())
        self.assertEqual([x.id for x in result], ['hotel', 'station'])
        self.assertEqual(result[0].coordinate, Coordinate(48.85, 2.3))
        self.assertEqual(result[0].utc_offset_minutes, 120)
        body = json.loads(requests[0].content)
        self.assertEqual(body['locationRestriction'], {'rectangle': RECTANGLE})
        self.assertEqual(body['textQuery'], 'Hotel')
        self.assertNotIn('SECRET', str(body))

    async def test_search_result_maps_coordinate_without_breaking_missing_location(self):
        def handler(request):
            return httpx.Response(200, json={'places': [
                {'id': 'a', 'displayName': {'text': 'A'},
                 'location': {'latitude': 1.0, 'longitude': 2.0}},
                {'id': 'b', 'displayName': {'text': 'B'}},
            ]})
        source = self.source(handler)
        result = await source.search_geo(Geography('g', 'City', RECTANGLE), {'museum'}, Budget())
        self.assertEqual(result[0].coordinate, Coordinate(1, 2))
        self.assertIsNone(result[1].coordinate)

    async def test_selected_details_map_hours_and_unknown_hours(self):
        requests = []
        def handler(request):
            requests.append(request)
            if request.url.path.endswith('/open'):
                return httpx.Response(200, json={
                    'id': 'open', 'location': {'latitude': 1, 'longitude': 2},
                    'utcOffsetMinutes': 120,
                    'currentOpeningHours': {'periods': [{
                        'open': {'date': {'year': 2026, 'month': 9, 'day': 10}, 'hour': 9},
                        'close': {'date': {'year': 2026, 'month': 9, 'day': 10}, 'hour': 18},
                    }]}})
            return httpx.Response(200, json={'id': 'unknown', 'location': {'latitude': 3, 'longitude': 4}})
        source = self.source(handler)
        places = (Place('open', 'Open', '', '', 'museum'), Place('unknown', 'Unknown', '', '', 'park'))
        day = DayParameters(date(2026, 9, 10), time(9), time(20))
        result = await source.enrich_selected(places, day, Budget())
        self.assertTrue(result[0].hours_known)
        self.assertEqual(result[0].opening_windows[0][0].isoformat(), '2026-09-10T09:00:00+02:00')
        self.assertFalse(result[1].hours_known)
        self.assertEqual(result[1].coordinate, Coordinate(3, 4))
        self.assertEqual(len(requests), 2)
        self.assertNotIn('*', requests[0].headers['X-Goog-FieldMask'])

    async def test_missing_coordinate_and_secret_response_are_safe(self):
        source = self.source(lambda request: httpx.Response(403, text='SECRET private'))
        with self.assertRaises(SourceError) as caught:
            await source.resolve_endpoint('Hotel', Geography('g', 'City', RECTANGLE), Budget())
        self.assertNotIn('SECRET', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
