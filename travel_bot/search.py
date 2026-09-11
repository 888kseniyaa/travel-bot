"""Async provider boundary. A response commits only to its original session."""
import asyncio
from .google_places import SourceError

async def complete_search(dialog, key, session):
    operation = session.operation
    if operation is None: return None
    try:
        if operation[0] == 'geo':
            result = await dialog.source.resolve_geo(operation[1], session.budget)
        elif operation[0] in ('endpoint_start', 'endpoint_finish'):
            result = await dialog.source.resolve_endpoint(operation[1], session.geography, session.budget)
        else:
            result = await dialog.source.search_geo(session.geography, set(session.categories), session.budget)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        if dialog.store.get(key) is not session or session.operation is not operation: return None
        session.notice = str(error) if isinstance(error, SourceError) else 'Поиск временно недоступен. Выбор сохранён.'
        session.stage = ({'geo': 'geo', 'endpoint_start': 'start_query',
                          'endpoint_finish': 'finish_query'}.get(operation[0]) or
                         ('places' if session.places else 'interests'))
    else:
        if dialog.store.get(key) is not session or session.operation is not operation: return None
        if operation[0] == 'geo':
            session.candidates = result
            session.stage = 'geo_confirm' if result else 'geo'
            if not result: session.notice = 'Территория не найдена. Укажите район вместе с городом и страной.'
        elif operation[0] in ('endpoint_start', 'endpoint_finish'):
            session.endpoint_candidates = tuple(result)
            session.stage = ('endpoint_confirm_start' if operation[0] == 'endpoint_start'
                             else 'endpoint_confirm_finish')
            if not result:
                session.stage = 'start_query' if operation[0] == 'endpoint_start' else 'finish_query'
                session.notice = 'Точка не найдена. Уточните адрес или название.'
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
