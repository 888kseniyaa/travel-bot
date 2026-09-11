import logging
import os
import sys
from telegram.error import TelegramError
from .telegram_app import build_application
from .settings import Settings
from .dialog import Dialog
from .google_places import GoogleSource
from .places import DemoSource
from .routes import RoutesClient
from .planning import PlanningService


def main():
    logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')
    # Third-party logs may include Bot API URLs containing the bot token.
    for name in ('httpx', 'httpcore', 'telegram'):
        logger = logging.getLogger(name)
        logger.handlers = [logging.NullHandler()]
        logger.propagate = False
    try:
        settings = Settings.load(os.environ)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    try:
        source = GoogleSource(settings.google_key) if settings.mode == 'real' else DemoSource()
        planning = (PlanningService(source, RoutesClient(settings.routes_key))
                    if settings.mode == 'real' else None)
        app = build_application(settings.token, Dialog(source), settings, planning)
        app.run_polling(allowed_updates=['message', 'callback_query'], bootstrap_retries=3)
    except (TelegramError, ValueError):
        print('Не удалось запустить бот. Проверьте токен, сеть и отсутствие второго запущенного экземпляра.', file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
