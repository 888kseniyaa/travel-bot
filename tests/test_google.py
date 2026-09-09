import json
import unittest
import httpx
from travel_bot.google_places import GoogleSource, Budget, SourceError

VIEWPORT = {'low': {'latitude': 48.8, 'longitude': 2.2},
            'high': {'latitude': 48.9, 'longitude': 2.4}}
GEO = {'id': 'geo1', 'displayName': {'text': 'Paris'}, 'formattedAddress': 'Paris, France',
       'types': ['locality', 'political'], 'viewport': VIEWPORT}

def place(id='a', **extra):
    return {'id': id, 'displayName': {'text': 'Museum'}, 'formattedAddress': 'Street 1',
            'googleMapsUri': 'https://maps.google.com/?cid=1', **extra}

class GoogleTests(unittest.IsolatedAsyncioTestCase):
    def source(self, handler):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(client.aclose)
        return GoogleSource('FAKE_SECRET', client=client, retry_delay=0)

    async def test_geo_and_category_requests_mapping_dedup(self):
        requests = []
        def respond(r):
            body = json.loads(r.content); requests.append((body, r.headers))
            if len(requests) == 1: return httpx.Response(200, json={'places': [GEO]})
            return httpx.Response(200, json={'places': [place(), {'id': 'optional'}, place()]})
        s = self.source(respond); b = Budget()
        geo = (await s.resolve_geo('Paris, France', b))[0]
        result = await s.search_geo(geo, {'museum', 'park', 'architecture'}, b)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].id, 'a')
        self.assertEqual(result[0].categories, ('museum', 'park', 'architecture'))
        self.assertEqual(result[1].address, 'Адрес не указан')
        self.assertEqual(result[1].maps_url, '')
        self.assertEqual(requests[0][0]['textQuery'], 'Paris, France')
        for body, headers in requests[1:]:
            self.assertEqual(body['locationRestriction'], {'rectangle': VIEWPORT})
            self.assertNotIn('locationBias', body)
            self.assertEqual(body['pageSize'], 5)
            self.assertNotIn('*', headers['X-Goog-FieldMask'])
            self.assertNotIn('FAKE_SECRET', str(body))
        self.assertEqual(requests[1][0]['includedType'], 'museum')
        self.assertEqual(requests[2][0]['includedType'], 'park')
        self.assertNotIn('includedType', requests[3][0])
        self.assertEqual(b.used, 4)

    async def test_empty_ambiguous_geo_and_invalid_viewport(self):
        s = self.source(lambda r: httpx.Response(200, json={'places': [GEO, {**GEO, 'id': 'geo2'},
                                                   {**GEO, 'id': 'bad', 'viewport': {}}]}))
        b = Budget()
        with self.assertRaises(SourceError): await s.resolve_geo(' ', b)
        self.assertEqual(b.used, 0)
        self.assertEqual(len(await s.resolve_geo('Paris', b)), 2)
        s2 = self.source(lambda r: httpx.Response(200, json={}))
        self.assertEqual(await s2.resolve_geo('Unknown', Budget()), ())

    async def test_errors_are_sanitized_and_bounded(self):
        for status in (401, 403, 429, 400, 503):
            with self.subTest(status=status):
                s = self.source(lambda r: httpx.Response(status, text='FAKE_SECRET sensitive body'))
                b = Budget()
                with self.assertRaises(SourceError) as caught: await s.resolve_geo('Paris', b)
                self.assertNotIn('FAKE_SECRET', str(caught.exception))
                self.assertEqual(b.used, 2 if status == 503 else 1)
        def timeout(r): raise httpx.ReadTimeout('FAKE_SECRET', request=r)
        s = self.source(timeout); b = Budget()
        with self.assertRaises(SourceError): await s.resolve_geo('Paris', b)
        self.assertEqual(b.used, 2)

    async def test_request_budget_and_attributions(self):
        s = self.source(lambda r: httpx.Response(200, json={'places': [place(attributions=[
            {'provider': 'Provider', 'providerUri': 'https://example.org/credit'}])]}))
        from travel_bot.google_places import Geography
        geo = Geography('g', 'Paris', VIEWPORT)
        result = await s.search_geo(geo, {'museum'}, Budget())
        self.assertIn('Provider', result[0].attributions[0])
        b = Budget(limit=0)
        with self.assertRaises(SourceError): await s.search_geo(geo, {'museum'}, b)
        self.assertEqual(b.used, 0)

    async def test_transient_success_and_malformed_response(self):
        calls = []
        def handler(r):
            calls.append(r)
            return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, json={'places': [GEO]})
        s = self.source(handler)
        self.assertEqual(len(await s.resolve_geo('Paris', Budget())), 1)
        malformed = self.source(lambda r: httpx.Response(200, text='not json FAKE_SECRET'))
        with self.assertRaises(SourceError): await malformed.resolve_geo('Paris', Budget())

    async def test_http_attribution_uri_preserved(self):
        from travel_bot.google_places import credits
        self.assertEqual(credits({'attributions': [{'provider': 'X', 'providerUri': 'http://example.org'}]}),
                         ('X http://example.org',))
