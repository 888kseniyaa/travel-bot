import unittest
from types import SimpleNamespace as Obj
from unittest.mock import AsyncMock
from telegram.error import BadRequest, NetworkError, Forbidden
from travel_bot.telegram_app import Adapter, build_application

class AdapterTests(unittest.IsolatedAsyncioTestCase):
    def update(self, text=None, data=None, chat_type='private'):
        message = Obj(text=text, reply_text=AsyncMock())
        query = None if data is None else Obj(data=data, answer=AsyncMock(), edit_message_text=AsyncMock())
        return Obj(effective_user=Obj(id=1), effective_chat=Obj(id=10, type=chat_type),
                   effective_message=message, callback_query=query)

    async def test_full_flow_through_handlers(self):
        a = Adapter()
        u = self.update('/start')
        await a.start(u, None)
        await a.text(self.update('Санкт-Петербург'), None)
        async def click(action):
            q = self.update(data=a.dialog.token((10, 1), action))
            await a.callback(q, None)
            return q
        await click('category:museum')
        await click('category:park')
        await click('show')
        await click('toggle:hermitage')
        await click('toggle:summer_garden')
        await click('duration:hermitage')
        await a.text(self.update('75'), None)
        result = await click('confirm')
        text = result.callback_query.edit_message_text.call_args.kwargs['text']
        self.assertIn('135 мин', text)
        self.assertIn('Маршрут пока не рассчитан', text)
        await click('edit')
        await click('new')
        self.assertEqual(a.dialog.store.get((10, 1)).selected, {})

    async def test_expired_callback_answer_does_not_mutate(self):
        a = Adapter()
        a.dialog.start((10, 1))
        u = self.update(data=a.dialog.token((10, 1), 'new'))
        session = a.dialog.store.get((10, 1)).session
        u.callback_query.answer.side_effect = BadRequest('Query is too old')
        await a.callback(u, None)
        self.assertEqual(a.dialog.store.get((10, 1)).session, session)

    async def test_edit_failure_falls_back_and_resume_keeps_selection(self):
        a = Adapter()
        a.dialog.start((10, 1))
        u = self.update(data=a.dialog.token((10, 1), 'new'))
        u.callback_query.edit_message_text.side_effect = BadRequest('Message cannot be edited')
        await a.callback(u, None)
        self.assertIn('Введите город', u.effective_message.reply_text.call_args.kwargs['text'])
        a.dialog.text((10, 1), 'спб')
        token = a.dialog.token((10, 1), 'category:museum')
        r = self.update('/resume')
        await a.resume(r, None)
        self.assertEqual(a.dialog.token((10, 1), 'category:museum'), token)

    async def test_send_failures_and_error_handler_do_not_escape(self):
        a = Adapter()
        u = self.update('/start')
        u.effective_message.reply_text.side_effect = NetworkError('offline')
        with self.assertLogs('travel_bot', level='WARNING'):
            await a.start(u, None)
        self.assertIsNotNone(a.dialog.store.get((10, 1)))
        u.effective_message.reply_text.side_effect = Forbidden('blocked')
        with self.assertLogs('travel_bot', level='WARNING') as logs:
            await a.error(u, Obj(error=RuntimeError('sensitive text')))
        self.assertNotIn('sensitive text', '\n'.join(logs.output))

    async def test_groups_are_rejected(self):
        a = Adapter()
        u = self.update('/start', chat_type='group')
        await a.start(u, None)
        self.assertIsNone(a.dialog.store.get((10, 1)))
        self.assertIn('личном чате', u.effective_message.reply_text.call_args.kwargs['text'])

    def test_application_builds_without_network(self):
        app = build_application('123456:TEST_ONLY_NOT_A_REAL_TOKEN')
        self.assertEqual(app.concurrent_updates, 1)
        self.assertTrue(app.error_handlers)
