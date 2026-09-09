"""Async provider boundary. A response commits only to its original session."""
import asyncio
from .google_places import SourceError

async def complete_search(dialog, key, session):
    operation = session.operation
    if operation is None: return None
    try:
        if operation[0] == 'geo':
            result = await dialog.source.resolve_geo(operation[1], session.budget)
        else:
            result = await dialog.source.search_geo(session.geography, set(session.categories), session.budget)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        if dialog.store.get(key) is not session or session.operation is not operation: return None
        session.notice = str(error) if isinstance(error, SourceError) else 'Поиск временно недоступен. Выбор сохранён.'
        session.stage = 'geo' if operation[0] == 'geo' else ('places' if session.places else 'interests')
    else:
        if dialog.store.get(key) is not session or session.operation is not operation: return None
        if operation[0] == 'geo':
            session.candidates = result
            session.stage = 'geo_confirm' if result else 'geo'
            if not result: session.notice = 'Территория не найдена. Укажите район вместе с городом и страной.'
        else:
            # Keep user-chosen places even when absent from a refreshed result set.
            kept = {p.id: p for p in session.places if p.id in session.selected}
            for p in result:
                if p.id in kept or len(kept) < 15: kept[p.id] = p
            session.places, session.page, session.stage = tuple(kept.values()), 0, 'places'
            if not result: session.notice = 'Новых мест не найдено. Измените интересы или географию; выбранные места сохранены.'
    session.operation = None
    session.revision += 1
    return dialog.view(key)
