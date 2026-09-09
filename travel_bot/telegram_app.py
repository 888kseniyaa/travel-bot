"""Telegram transport only. Never log updates, exception messages or request URLs."""
import logging
import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters
from .dialog import Dialog, InputError
from .search import complete_search

log = logging.getLogger('travel_bot')

class Adapter:
    def __init__(self, dialog=None, settings=None):
        self.dialog = dialog if dialog is not None else Dialog()
        self.settings = settings
        self.tasks = {}
        self.operations = {}
        self.cleaner = None

    async def close(self):
        pending = list(self.tasks.values())
        if self.cleaner: pending.append(self.cleaner)
        for task in pending: task.cancel()
        if pending: await asyncio.gather(*pending, return_exceptions=True)
        self.tasks.clear()
        self.operations.clear()
        if self.dialog.real and hasattr(self.dialog.source, 'close'):
            await self.dialog.source.close()

    async def cleanup(self):
        while True:
            await asyncio.sleep(60)
            self.dialog.store.purge()
            for key, task in list(self.tasks.items()):
                if self.dialog.store.get(key) is None: task.cancel()

    def cancel_search(self, key):
        self.operations.pop(key, None)
        task = self.tasks.pop(key, None)
        if task: task.cancel()

    def launch_search(self, key, update):
        session = self.dialog.store.get(key)
        if session is None or session.operation is None: return
        if key in self.tasks and not self.tasks[key].done():
            if self.operations.get(key) is session.operation: return
            self.cancel_search(key)
        self.operations[key] = session.operation
        async def run():
            try:
                view = await complete_search(self.dialog, key, session)
                if view is not None and self.dialog.store.get(key) is session:
                    await self.send(update, *view)
            finally:
                if self.tasks.get(key) is asyncio.current_task():
                    self.tasks.pop(key, None)
                    self.operations.pop(key, None)
        self.tasks[key] = asyncio.create_task(run())

    async def policy(self, update, context):
        key = await self.key(update)
        if key is None: return
        if self.settings and self.settings.mode == 'real':
            await self.send(update, 'Условия: ' + self.settings.terms_url + '\nКонфиденциальность: ' + self.settings.privacy_url)
        else:
            await self.send(update, 'Demo: тестовые данные. Состояние хранится в памяти до 30 минут и сбрасывается при перезапуске.')

    async def send(self, update, text, rows=None, edit=False):
        # 1500 Unicode codepoints <= 3000 UTF-16 units; leave room for attribution.
        if len(text) > 1500:
            remaining = text
            parts = []
            while remaining:
                end = remaining.rfind('\n', 0, 1500) if len(remaining) > 1500 else len(remaining)
                if end <= 0: end = min(1500, len(remaining))
                parts.append(remaining[:end]); remaining = remaining[end:].lstrip('\n')
            for index, part in enumerate(parts):
                await self.send(update, part, rows if index == len(parts) - 1 else None, edit and index == 0)
            return
        if self.dialog.real: text = 'Google Maps\n' + text

        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(label, callback_data=data) for label, data in row]
            for row in rows
        ]) if rows else None
        if edit and update.callback_query:
            try:
                await update.callback_query.edit_message_text(text=text, reply_markup=markup, disable_web_page_preview=True)
                return
            except TelegramError:
                # The message may be deleted, inaccessible or already identical.
                pass
        if update.effective_message:
            try:
                await update.effective_message.reply_text(text=text, reply_markup=markup, disable_web_page_preview=True)
            except TelegramError:
                log.warning('Не удалось отправить экран; состояние сохранено. Доступно /resume.')

    async def key(self, update):
        if not update.effective_user or not update.effective_chat:
            return None
        if update.effective_chat.type != 'private':
            await self.send(update, 'Для приватности подбор доступен только в личном чате с ботом. Откройте его и отправьте /start.')
            return None
        return update.effective_chat.id, update.effective_user.id

    async def start(self, update, context):
        key = await self.key(update)
        if key is not None:
            self.cancel_search(key)
            await self.send(update, *self.dialog.start(key))

    async def resume(self, update, context):
        key = await self.key(update)
        if key is None: return
        try: view = self.dialog.view(key)
        except InputError as error:
            await self.send(update, str(error))
            return
        await self.send(update, *view)

    async def text(self, update, context):
        key = await self.key(update)
        if key is None: return
        try:
            view = self.dialog.text(key, update.effective_message.text or '')
        except InputError as error:
            await self.send(update, str(error))
            return
        await self.send(update, *view)
        self.launch_search(key, update)

    async def callback(self, update, context):
        query = update.callback_query
        if query is None: return
        # Do not perform a mutation if Telegram already considers this query expired.
        try: await query.answer()
        except TelegramError:
            await self.send(update, 'Не удалось обработать нажатие. Откройте текущий экран: /resume.')
            return
        key = await self.key(update)
        if key is None: return
        previous = self.dialog.store.get(key)
        try: view = self.dialog.click(key, query.data)
        except InputError as error:
            await self.send(update, str(error))
            return
        if self.dialog.store.get(key) is not previous: self.cancel_search(key)
        await self.send(update, *view, edit=True)
        self.launch_search(key, update)

    async def error(self, update, context):
        # No raw exception/traceback: it can contain the token in a request URL.
        log.error('Ошибка обработки обновления; подробности скрыты для защиты секретов.')
        if update is not None and hasattr(update, 'effective_message'):
            await self.send(update, 'Не удалось выполнить действие. Проверьте текущий подбор: /resume. Новый подбор: /start.')


def build_application(token, dialog=None, settings=None):
    adapter = Adapter(dialog, settings)
    async def initialize(app): adapter.cleaner = asyncio.create_task(adapter.cleanup())
    async def shutdown(app): await adapter.close()
    app = (Application.builder().token(token).concurrent_updates(False)
           .post_init(initialize).post_stop(shutdown).build())
    app.add_handler(CommandHandler('start', adapter.start))
    app.add_handler(CommandHandler('resume', adapter.resume))
    app.add_handler(CommandHandler(['privacy', 'terms'], adapter.policy))
    app.add_handler(CallbackQueryHandler(adapter.callback))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, adapter.text))
    app.add_handler(MessageHandler(filters.COMMAND, adapter.resume))
    app.add_error_handler(adapter.error)
    return app
