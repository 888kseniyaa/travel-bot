import asyncio
import unittest
from types import SimpleNamespace as Obj
from unittest.mock import AsyncMock
from test_real_dialog import Source
from travel_bot.dialog import Dialog
from travel_bot.telegram_app import Adapter

class RealAdapterTests(unittest.IsolatedAsyncioTestCase):
    def update(self, text='', data=None):
        return Obj(effective_user=Obj(id=1), effective_chat=Obj(id=1,type='private'),
                   effective_message=Obj(text=text, reply_text=AsyncMock()),
                   callback_query=None if data is None else Obj(data=data,answer=AsyncMock(),edit_message_text=AsyncMock()))
    async def test_background_search_does_not_block_start_or_duplicate(self):
        source = Source(); source.gate = asyncio.Event(); adapter = Adapter(Dialog(source))
        await adapter.start(self.update(), None)
        await adapter.text(self.update('Paris'), None)
        await asyncio.sleep(0)
        self.assertEqual(source.calls, 1)
        await adapter.text(self.update('Paris'), None)
        self.assertEqual(source.calls, 1)
        await adapter.start(self.update(), None)
        source.gate.set(); await asyncio.sleep(0)
        self.assertEqual(adapter.dialog.require((1,1)).stage, 'geo')
        await adapter.close()
    async def test_long_google_content_split_with_attribution_and_keyboard(self):
        adapter = Adapter(Dialog(Source())); u = self.update()
        await adapter.send(u, '😀' * 5000, [[('Next', 'short')]])
        sent = u.effective_message.reply_text.call_args_list
        self.assertGreater(len(sent), 1)
        for call in sent:
            text = call.kwargs['text']
            self.assertLessEqual(len(text.encode('utf-16-le')) // 2, 4096)
            self.assertIn('Google Maps', text)
        self.assertIsNotNone(sent[-1].kwargs['reply_markup'])

    async def test_new_search_while_old_result_is_being_sent(self):
        source = Source(); adapter = Adapter(Dialog(source)); key = (1,1)
        await adapter.start(self.update(), None)
        entered, release = asyncio.Event(), asyncio.Event()
        update = self.update('Paris')
        async def send_result(**kwargs):
            if 'Подтвердите' in kwargs['text']:
                entered.set(); await release.wait()
        update.effective_message.reply_text.side_effect = send_result
        await adapter.text(update, None); await entered.wait()
        adapter.dialog.click(key, adapter.dialog.token(key, 'geography'))
        await adapter.text(self.update('London'), None)
        for _ in range(5): await asyncio.sleep(0)
        release.set()
        self.assertEqual(source.calls, 2)
        await adapter.close()

    async def test_google_fixture_through_telegram_handlers(self):
        import json
        import httpx
        from test_google import GEO, place
        from travel_bot.google_places import GoogleSource
        requests = []
        def respond(request):
            body = json.loads(request.content); requests.append(body)
            if body['textQuery'] == 'Paris, France': return httpx.Response(200, json={'places': [GEO]})
            return httpx.Response(200, json={'places': [place(str(i)) for i in range(5)]})
        source = GoogleSource('TEST_SECRET', client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
        adapter = Adapter(Dialog(source)); self.addAsyncCleanup(adapter.close)
        k = (1,1)
        async def drain():
            task = adapter.tasks.get(k)
            if task: await task
        async def click(action):
            update = self.update(data=adapter.dialog.token(k, action))
            await adapter.callback(update, None); await drain()
            return update
        await adapter.start(self.update(), None)
        await adapter.text(self.update('Paris, France'), None); await drain()
        await click('geo:0'); await click('category:museum'); await click('category:park')
        await click('show'); await click('toggle:0'); await click('page:1'); await click('toggle:3')
        await click('duration:3'); await adapter.text(self.update('75'), None)
        result = await click('confirm')
        text = result.callback_query.edit_message_text.call_args.kwargs['text']
        self.assertIn('195 мин', text)
        self.assertIn('Google Maps', text)
        self.assertNotIn('TEST_SECRET', text)
        self.assertEqual(len(requests), 3)
        self.assertEqual(len(adapter.dialog.require(k).places), 5)
