import asyncio
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace as Obj
from unittest.mock import AsyncMock

from travel_bot.day import DayPlan, PlanLeg, TravelOption
from travel_bot.dialog import Dialog
from travel_bot.telegram_app import Adapter


class Source:
    mode = 'real'
    label = 'Real'
    geography_hint = 'Введите город.'


class Planning:
    def __init__(self):
        self.calculations = 0
        self.details = 0

    async def calculate(self, dialog, key, session, fingerprint):
        self.calculations += 1
        now = datetime(2026, 9, 10, 9, tzinfo=timezone.utc)
        session.plan = DayPlan((), (), (), now, now, 0, 0, ())
        session.stage = 'planned'
        session.notice = 'Готово'

    async def detail(self, dialog, key, session, index, fingerprint):
        self.details += 1
        return TravelOption('a', 'b', 'WALK', 8, steps=('Идите прямо',))


class Saved:
    repository = None
    def __init__(self): self.calls = 0
    def autosave(self, session, owner):
        self.calls += 1
        return Obj(summary=Obj(name='Saved route'))
    def list(self, owner, page=0): return ()
    def count(self, owner): return 0


class RouteAdapterTests(unittest.IsolatedAsyncioTestCase):
    def update(self, data=None):
        return Obj(effective_user=Obj(id=1), effective_chat=Obj(id=1, type='private'),
                   effective_message=Obj(text='', reply_text=AsyncMock()),
                   callback_query=Obj(data=data, answer=AsyncMock(), edit_message_text=AsyncMock()))

    async def test_calculation_and_detail_are_launched_once(self):
        planning = Planning()
        adapter = Adapter(Dialog(Source()), planning_service=planning)
        self.addAsyncCleanup(adapter.close)
        session = adapter.dialog.store.start((1, 1))
        session.stage = 'plan_ready'
        update = self.update(adapter.dialog.token((1, 1), 'calculate'))
        await adapter.callback(update, None)
        await adapter.planning_tasks[(1, 1)]
        self.assertEqual(planning.calculations, 1)
        self.assertEqual(session.stage, 'planned')

        option = TravelOption('a', 'b', 'WALK', 8)
        session.plan = DayPlan((), (PlanLeg(option, session.plan.start, session.plan.end),),
                               (), session.plan.start, session.plan.end, 8, 8, ())
        update = self.update(adapter.dialog.token((1, 1), 'detail:0'))
        await adapter.callback(update, None)
        await adapter.planning_tasks[(1, 1)]
        self.assertEqual(planning.details, 1)
        self.assertIn('Идите прямо', session.detail_text)

    async def test_new_selection_cancels_background_planning(self):
        gate = asyncio.Event()
        class Slow(Planning):
            async def calculate(self, *args):
                await gate.wait()
        adapter = Adapter(Dialog(Source()), planning_service=Slow())
        self.addAsyncCleanup(adapter.close)
        session = adapter.dialog.store.start((1, 1)); session.stage = 'plan_ready'
        await adapter.callback(self.update(adapter.dialog.token((1, 1), 'calculate')), None)
        await adapter.start(self.update(), None)
        self.assertNotIn((1, 1), adapter.planning_tasks)

    async def test_successful_calculation_is_autosaved_once(self):
        planning, saved = Planning(), Saved()
        adapter = Adapter(Dialog(Source()), planning_service=planning, saved_service=saved)
        self.addAsyncCleanup(adapter.close)
        session = adapter.dialog.store.start((1, 1)); session.stage = 'plan_ready'
        await adapter.callback(self.update(adapter.dialog.token((1, 1), 'calculate')), None)
        await adapter.planning_tasks[(1, 1)]
        self.assertEqual(saved.calls, 1)
        self.assertIn('Saved route', session.notice)


if __name__ == '__main__':
    unittest.main()
