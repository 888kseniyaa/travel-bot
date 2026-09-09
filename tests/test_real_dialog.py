import asyncio
import unittest
from travel_bot.dialog import Dialog, InputError
from travel_bot.google_places import Geography, SourceError
from travel_bot.places import Place
from travel_bot.search import complete_search

class Source:
    mode = 'real'
    label = 'Google Maps — реальные места.'
    geography_hint = 'Введите город и страну.'
    def __init__(self): self.calls = 0; self.fail = False; self.gate = None
    async def resolve_geo(self, text, budget):
        self.calls += 1
        if self.gate: await self.gate.wait()
        return (Geography('g', 'Paris, France', {}), Geography('g2', 'Paris, USA', {})) if text.strip() else ()
    async def search_geo(self, geo, categories, budget):
        self.calls += 1
        if self.fail: raise SourceError('Квота исчерпана. Выбор сохранён.')
        return tuple(Place('google-long-id-' + str(i) * 100, f'Museum {i}', geo.label, '', 'museum',
                           'Street 1', 'https://maps.google.com/?cid=1', ('Provider https://example.org',)) for i in range(7))

class RealDialogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.source = Source(); self.d = Dialog(self.source); self.k = (1, 1); self.d.start(self.k)
    def click(self, action): return self.d.click(self.k, self.d.token(self.k, action))
    async def finish(self): return await complete_search(self.d, self.k, self.d.require(self.k))
    async def prepare(self):
        self.d.text(self.k, 'Paris'); await self.finish()
        self.assertEqual(self.d.require(self.k).stage, 'geo_confirm')
        self.click('geo:0'); self.click('category:museum'); self.click('show'); await self.finish()
    async def test_full_flow_pages_duration_confirmation_and_failure(self):
        await self.prepare()
        self.click('toggle:0'); self.click('page:1'); self.click('toggle:3')
        self.click('duration:3'); self.d.text(self.k, '75'); self.click('confirm')
        self.assertIn('195 мин', self.d.view(self.k)[0])
        self.assertIn('Дорога не включена', self.d.view(self.k)[0])
        self.click('edit'); self.source.fail = True; self.click('refresh'); await self.finish()
        self.assertEqual(len(self.d.require(self.k).selected), 2)
        self.assertIn('Квота', self.d.view(self.k)[0])
        for row in self.d.view(self.k)[1]:
            for _, data in row: self.assertLessEqual(len(data.encode()), 64)
        self.assertNotIn('Санкт-Петербург', self.d.view(self.k)[0])
    async def test_duplicate_clicks_and_late_response_cannot_override_new_session(self):
        self.source.gate = asyncio.Event()
        self.d.text(self.k, 'Paris'); old = self.d.require(self.k)
        task = asyncio.create_task(complete_search(self.d, self.k, old)); await asyncio.sleep(0)
        with self.assertRaises(InputError): self.d.text(self.k, 'Paris')
        self.d.start(self.k); self.source.gate.set()
        self.assertIsNone(await task)
        self.assertEqual(self.d.require(self.k).stage, 'geo')
        self.assertEqual(self.source.calls, 1)
    async def test_empty_geography_and_reset(self):
        self.d.text(self.k, 'Unknown'); self.source.resolve_geo = self.empty
        await self.finish()
        self.assertEqual(self.d.require(self.k).stage, 'geo')
        self.assertIn('город', self.d.view(self.k)[0])
        self.click('new'); self.assertEqual(self.d.require(self.k).selected, {})
    async def empty(self, *args): return ()
    async def test_selected_places_survive_interest_change_and_failed_search(self):
        await self.prepare(); self.click('toggle:0'); self.click('interests')
        self.click('category:park'); self.source.fail = True
        self.click('show'); await self.finish()
        self.assertEqual(len(self.d.require(self.k).selected), 1)
        self.assertEqual(self.d.require(self.k).stage, 'places')

    async def test_expired_session_rejects_old_buttons(self):
        from unittest.mock import patch
        s = self.d.require(self.k)
        button = self.d.token(self.k, 'new')
        with patch('travel_bot.state.monotonic', return_value=s.expires + 1):
            with self.assertRaises(InputError): self.d.click(self.k, button)
            self.assertIsNone(self.d.store.get(self.k))
