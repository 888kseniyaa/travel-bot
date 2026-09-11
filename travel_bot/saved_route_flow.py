"""Synchronous saved-route navigation; network refresh is launched by Adapter."""
from .dialog import InputError
from .route_repository import RepositoryError
from .route_map import RouteMapError, build_route_map_link


class SavedRouteFlow:
    def __init__(self, service):
        self.service = service

    def _session(self, dialog, key):
        session = dialog.store.get(key)
        if session is None: session = dialog.store.start(key)
        return session

    def _load(self, session, owner, page=0):
        session.saved_page = max(0, page)
        session.saved_summaries = self.service.list(owner, session.saved_page)

    def enter(self, dialog, key, owner):
        session = self._session(dialog, key)
        if not session.stage.startswith('saved_'):
            session.saved_return_stage = session.stage
        try: self._load(session, owner)
        except RepositoryError as error: raise InputError(str(error)) from None
        session.stage = 'saved_routes'; session.revision += 1
        return self.view(dialog, key, owner)

    def enter_delete_all(self, dialog, key, owner):
        session = self._session(dialog, key)
        if not session.stage.startswith('saved_'):
            session.saved_return_stage = session.stage
        try: session.saved_delete_all_count = self.service.count(owner)
        except RepositoryError as error: raise InputError(str(error)) from None
        session.stage = 'saved_delete_all'; session.revision += 1
        return self.view(dialog, key, owner)

    def _parse(self, dialog, key, data):
        session = self._session(dialog, key)
        prefix = f'{session.session}:{session.revision}:'
        if not isinstance(data, str) or not data.startswith(prefix):
            raise InputError('Эта кнопка устарела. Откройте /routes заново.')
        return session, data[len(prefix):].split(':')

    def click(self, dialog, key, owner, data):
        session, parts = self._parse(dialog, key, data)
        try:
            action = parts[1] if parts and parts[0] == 'saved' and len(parts) > 1 else ''
            if action == 'back_selection':
                session.stage = session.saved_return_stage or 'geo'
                session.saved_return_stage = None
            elif action == 'back_list':
                self._load(session, owner, session.saved_page); session.stage = 'saved_routes'
            elif action == 'page' and len(parts) == 3 and parts[2].isdigit():
                self._load(session, owner, int(parts[2])); session.stage = 'saved_routes'
            elif action in ('card', 'open', 'rename', 'delete', 'delete_yes') and len(parts) == 4:
                route_id, raw_version = parts[2], parts[3]
                if not raw_version.isdigit(): raise InputError('Некорректная кнопка маршрута.')
                version = int(raw_version)
                if action == 'card':
                    session.saved_current = self.service.get(owner, route_id)
                    session.saved_opened = None
                    session.stage = 'saved_card'
                elif action == 'open':
                    session.saved_open_request = (route_id, version)
                    session.stage = 'saved_loading'
                elif action == 'rename':
                    current = self.service.get(owner, route_id)
                    if current.summary.version != version: raise InputError('Маршрут изменился. Откройте актуальную карточку.')
                    session.saved_current = current; session.stage = 'saved_rename'
                elif action == 'delete':
                    current = self.service.get(owner, route_id)
                    if current.summary.version != version: raise InputError('Маршрут изменился. Откройте актуальную карточку.')
                    session.saved_current = current; session.stage = 'saved_delete'
                else:
                    self.service.delete(owner, route_id, version)
                    self._load(session, owner, session.saved_page); session.stage = 'saved_routes'
                    session.notice = 'Маршрут удалён.'
            elif action == 'delete_all_yes' and session.stage == 'saved_delete_all':
                count = self.service.delete_all(owner); session.stage = session.saved_return_stage or 'geo'
                session.saved_return_stage = None; session.notice = f'Удалено маршрутов: {count}.'
            else:
                raise InputError('Эта кнопка сейчас недоступна.')
        except RepositoryError as error:
            raise InputError(str(error)) from None
        session.revision += 1
        return self.view(dialog, key, owner) if session.stage.startswith('saved_') else dialog.view(key)

    def text(self, dialog, key, owner, text):
        session = self._session(dialog, key)
        if session.stage != 'saved_rename' or not session.saved_current:
            raise InputError('Используйте кнопки маршрута.')
        try:
            renamed = self.service.rename(owner, session.saved_current.summary.id,
                                          session.saved_current.summary.version, text)
        except (RepositoryError, ValueError) as error:
            raise InputError(str(error)) from None
        session.saved_current = renamed; session.stage = 'saved_card'; session.revision += 1
        return self.view(dialog, key, owner)

    def view(self, dialog, key, owner):
        session = self._session(dialog, key); rows = []
        def button(label, action): rows.append([(label, dialog.token(key, 'saved:' + action))])
        lines = ['Мои маршруты']
        if session.notice: lines.append(session.notice)
        if session.stage == 'saved_routes':
            if not session.saved_summaries: lines.append('Сохранённых маршрутов пока нет.')
            for item in session.saved_summaries:
                lines.append(f'• {item.name} — {item.route_date:%d.%m.%Y}')
                button(item.name, f'card:{item.id}:{item.version}')
            if session.saved_page: button('← Предыдущие', f'page:{session.saved_page - 1}')
            if self.service.count(owner) > (session.saved_page + 1) * 5:
                button('Следующие →', f'page:{session.saved_page + 1}')
            button('Вернуться к подбору', 'back_selection')
        elif session.stage == 'saved_card' and session.saved_current:
            item = session.saved_current
            lines += [item.summary.name, f'Дата: {item.payload.day.date:%d.%m.%Y}.',
                      f'День: {item.payload.day.start:%H:%M}–{item.payload.day.end:%H:%M}.',
                      'При открытии данные Google и переходы обновляются.']
            button('Открыть маршрут', f'open:{item.summary.id}:{item.summary.version}')
            button('Переименовать', f'rename:{item.summary.id}:{item.summary.version}')
            button('Удалить', f'delete:{item.summary.id}:{item.summary.version}')
            button('К списку', 'back_list')
        elif session.stage == 'saved_rename':
            lines.append('Введите новое название длиной от 1 до 80 символов.')
            button('Отмена', 'back_list')
        elif session.stage == 'saved_delete' and session.saved_current:
            item = session.saved_current
            lines.append(f'Удалить маршрут «{item.summary.name}»?')
            button('Да, удалить', f'delete_yes:{item.summary.id}:{item.summary.version}')
            button('Отмена', 'back_list')
        elif session.stage == 'saved_delete_all':
            lines.append(f'Удалить все сохранённые маршруты ({session.saved_delete_all_count})?')
            button('Да, удалить все', 'delete_all_yes')
            button('Отмена', 'back_selection')
        elif session.stage == 'saved_loading':
            lines.append('Обновляю места и переходы по текущим данным Google.')
        elif session.stage == 'saved_opened' and session.saved_opened:
            opened = session.saved_opened; plan = opened.plan
            lines += [opened.saved.summary.name,
                      'Данные Google и переходы обновлены при открытии и могут отличаться от первоначального расчёта.',
                      f'План дня: {plan.start:%H:%M}–{plan.end:%H:%M}.']
            for index, stop in enumerate(plan.stops):
                if index < len(plan.legs):
                    leg = plan.legs[index]
                    mode = 'пешком' if leg.option.mode == 'WALK' else 'транспорт'
                    lines.append(f'{leg.departure:%H:%M}–{leg.arrival:%H:%M}: {mode}, {leg.option.duration_min} мин.')
                lines.append(f'{stop.arrival:%H:%M}–{stop.departure:%H:%M}: {stop.name}, {stop.duration_min} мин.')
                place = next((p for p in opened.places if p.id == stop.place_id), None)
                if place: lines.extend(place.attributions)
            if len(plan.legs) > len(plan.stops):
                leg = plan.legs[-1]
                mode = 'пешком' if leg.option.mode == 'WALK' else 'транспорт'
                lines.append(f'{leg.departure:%H:%M}–{leg.arrival:%H:%M}: до финиша, {mode}, {leg.option.duration_min} мин.')
            for excluded in plan.exclusions:
                lines.append(f'Исключено: {excluded.name} — {excluded.reason}.')
            try:
                link = build_route_map_link(opened.start, opened.finish, plan, opened.places)
            except RouteMapError as error:
                lines.append(str(error))
            else:
                lines.append('Google Maps построит собственный вариант по переданным точкам.')
                if link.mobile_waypoint_warning:
                    lines.append('⚠️ Некоторые мобильные клиенты могут открыть не все промежуточные точки.')
                rows.append([('Открыть маршрут в Google Maps', link.url)])
            item = opened.saved.summary
            button('Переименовать', f'rename:{item.id}:{item.version}')
            button('Удалить', f'delete:{item.id}:{item.version}')
            button('К списку', 'back_list')
        return '\n'.join(lines), rows
