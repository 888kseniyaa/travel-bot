import re
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from .places import CATEGORIES, MINUTES, DemoSource, PlaceSource
from .state import Store
from .day import DayParameters, LunchBreak, ValidationError
from .route_map import (
    RouteMapError, build_route_map_link, build_selected_route_map_link,
)

class InputError(ValueError):
    pass

SOURCE_NOTE = 'Места: Google Maps • время посещения: оценка бота'

class Dialog:
    def __init__(self, source: PlaceSource = None, store=None, today_provider=None):
        self.source = source if source is not None else DemoSource()
        self.store = store if store is not None else Store()
        self.today_provider = today_provider or date.today
        self.saved_flow = None

    @property
    def real(self):
        return getattr(self.source, "mode", "demo") == "real"

    def start(self, key):
        self.store.start(key)
        return self.view(key)

    def require(self, key):
        s = self.store.get(key)
        if s is None: raise InputError('Подбор не найден. Начните с /start.')
        return s

    def token(self, key, action):
        s = self.require(key)
        return f'{s.session}:{s.revision}:{action}'

    def text(self, key, text):
        s = self.require(key)
        if s.stage == 'day_date':
            try:
                raw = text.strip()
                value = date.fromisoformat(raw) if '-' in raw else date(*reversed([int(x) for x in raw.split('.')]))
                defaults = DayParameters(value, time(10), time(20), 90, None)
                defaults.validate(self.today_provider())
            except (ValueError, ValidationError):
                raise InputError('Введите дату от сегодня до следующих 7 дней в формате ГГГГ-ММ-ДД.')
            s.day_parameters = defaults
            s.draft_date, s.draft_start, s.draft_end = value, time(10), time(20)
            s.draft_walking_limit = 90
            s.start_endpoint, s.finish_endpoint = None, None
            s.editing_day_settings = False
            s.stage = 'start_query'
        elif s.stage in ('day_start', 'day_end', 'lunch_time'):
            try: value = time.fromisoformat(text.strip())
            except ValueError: raise InputError('Введите время в формате ЧЧ:ММ, например 09:30.')
            if s.stage == 'day_start': s.draft_start, s.stage = value, 'day_end'
            elif s.stage == 'day_end':
                s.draft_end = value
                s.stage = 'finish_choice' if s.editing_day_settings else 'start_query'
            else: s.draft_lunch_start, s.stage = value, 'lunch_duration'
        elif s.stage in ('start_query', 'finish_query'):
            query = ' '.join(text.split())
            if not query or len(query) > 200:
                raise InputError('Введите адрес или название точки (до 200 символов).')
            kind = 'endpoint_start' if s.stage == 'start_query' else 'endpoint_finish'
            if s.stage == 'start_query': s.start_query = query
            else: s.finish_query = query
            s.operation, s.stage = (kind, query, object()), 'searching'
        elif s.stage == 'walking_input':
            raw = text.strip()
            if not re.fullmatch(r'[0-9]{1,3}', raw) or int(raw) == 0:
                raise InputError('Введите положительный лимит ходьбы в минутах, например 90.')
            s.draft_walking_limit, s.stage = int(raw), 'lunch_choice'
        elif s.stage == 'lunch_duration':
            raw = text.strip()
            if not re.fullmatch(r'[0-9]{1,3}', raw) or int(raw) == 0:
                raise InputError('Введите положительную длительность обеда в минутах, например 45.')
            self._finish_day_parameters(s, LunchBreak(s.draft_lunch_start, int(raw)))
        elif s.stage == 'geo' and self.real:
            text = ' '.join(text.split())
            if not text or len(text) > 200:
                raise InputError('Введите город и страну или район, город и страну (до 200 символов).')
            s.geography_query = text
            s.operation = ('geo', text, object())
            s.stage, s.notice = 'searching', ''
        elif s.stage == 'geo':
            try: city, district = self.source.resolve(text)
            except ValueError:
                raise InputError('Эта география пока недоступна. ' + self.source.geography_hint)
            s.city, s.district, s.stage = city, district, 'interests'
        elif s.stage == 'duration':
            raw = text.strip()
            # A generous technical bound avoids huge integers / Telegram message overflow.
            if not re.fullmatch(r'[0-9]{1,6}', raw) or int(raw) == 0:
                raise InputError('Введите целое число минут от 1 до 999999, например 90. Попробуйте ещё раз.')
            s.selected[s.pending] = int(raw)
            s.pending, s.stage, s.plan, s.route_link_fallback = None, 'places', None, False
        else:
            raise InputError('Используйте кнопки ниже. /resume — текущий экран, /start — новый подбор.')
        s.revision += 1
        return self.view(key)

    def _finish_day_parameters(self, s, lunch=None):
        try:
            params = DayParameters(s.draft_date, s.draft_start,
                                   s.draft_end or time(20), s.draft_walking_limit, lunch)
            params.validate(self.today_provider())
        except (TypeError, ValidationError):
            raise InputError('Параметры дня несовместимы. Проверьте начало, конец и обед.')
        s.day_parameters, s.plan, s.stage = params, None, 'plan_ready'
        s.editing_day_settings = False

    def click(self, key, data):
        s = self.require(key)
        if self.saved_flow and s.stage.startswith('saved_'):
            return self.saved_flow.click(self, key, key[1], data)
        prefix = f'{s.session}:{s.revision}:'
        if not isinstance(data, str) or not data.startswith(prefix):
            raise InputError('Эта кнопка устарела или принадлежит другому подбору. Используйте /resume.')
        action = data[len(prefix):]
        op, _, value = action.partition(':')
        if action == 'new': return self.start(key)
        if action == 'routes' and self.saved_flow:
            return self.saved_flow.enter(self, key, key[1])
        if action == 'plan' and s.stage == 'confirmed':
            if len(s.selected) > 6:
                raise InputError('Для одного расчёта выберите не более шести мест.')
            s.stage, s.plan, s.notice = 'day_date', None, ''
        elif action == 'retry_calculate' and s.stage == 'confirmed' and s.route_link_fallback:
            s.stage, s.notice, s.detail_text = 'planning_requested', '', ''
        elif action == 'edit_day_settings' and s.stage == 'plan_ready':
            p = s.day_parameters
            s.draft_date, s.draft_start, s.draft_end = p.date, p.start, p.end
            s.draft_walking_limit = p.walking_limit_min
            s.draft_lunch_start = p.lunch.start if p.lunch else None
            s.editing_day_settings = True
            s.stage, s.plan = 'day_start', None
        elif action == 'keep_day_settings' and s.editing_day_settings and s.stage in (
                'day_start', 'day_end', 'finish_choice', 'finish_query',
                'walking_choice', 'walking_input', 'lunch_choice',
                'lunch_time', 'lunch_duration'):
            s.editing_day_settings = False
            s.stage = 'plan_ready'
        elif action == 'back_to_places' and s.stage in ('day_date', 'start_query', 'plan_ready'):
            s.editing_day_settings = False
            s.stage, s.plan = 'places', None
        elif action == 'edit_plan_parameters' and s.stage == 'planned':
            s.stage, s.plan = 'day_date', None
        elif action == 'edit_plan_places' and s.stage in ('planned', 'confirmed', 'plan_ready'):
            s.stage, s.plan = 'places', None
        elif action == 'end:default' and s.stage == 'day_end':
            s.draft_end = time(20)
            s.stage = 'finish_choice' if s.editing_day_settings else 'start_query'
        elif op == 'endpoint' and s.stage in ('endpoint_confirm_start', 'endpoint_confirm_finish') and value.isdigit() and int(value) < len(s.endpoint_candidates):
            endpoint = s.endpoint_candidates[int(value)]
            if s.stage == 'endpoint_confirm_start':
                s.start_endpoint = replace(endpoint, id='start:' + endpoint.id)
                s.stage = 'plan_ready'
            else:
                s.finish_endpoint = replace(endpoint, id='finish:' + endpoint.id)
                s.stage = 'walking_choice'
            s.endpoint_candidates = ()
        elif action == 'finish:last' and s.stage == 'finish_choice':
            s.finish_endpoint, s.stage = None, 'walking_choice'
        elif action == 'finish:address' and s.stage == 'finish_choice':
            s.stage = 'finish_query'
        elif action == 'walk:90' and s.stage == 'walking_choice':
            s.draft_walking_limit, s.stage = 90, 'lunch_choice'
        elif action == 'walk:custom' and s.stage == 'walking_choice':
            s.stage = 'walking_input'
        elif action == 'lunch:none' and s.stage == 'lunch_choice':
            self._finish_day_parameters(s)
        elif action == 'lunch:yes' and s.stage == 'lunch_choice':
            s.stage = 'lunch_time'
        elif action == 'calculate' and s.stage in ('plan_ready', 'planned'):
            s.stage, s.notice, s.detail_text = 'planning_requested', '', ''
        elif op == 'detail' and s.stage == 'planned' and value.isdigit() and s.plan and int(value) < len(s.plan.legs):
            s.detail_request, s.stage = int(value), 'detail_requested'
        elif action == 'geography' and s.stage != 'searching':
            s.stage, s.places, s.geography, s.candidates = 'geo', (), None, ()
            s.selected.clear()
            s.pending, s.notice = None, ''
        elif op == 'geo' and s.stage == 'geo_confirm' and value.isdigit() and int(value) < len(s.candidates):
            s.geography = s.candidates[int(value)]
            s.city, s.district, s.stage = s.geography.label, None, 'interests'
            s.candidates = ()
        elif op == 'page' and s.stage == 'places' and value.isdigit() and int(value) * 3 < len(s.places):
            s.page = int(value)
        elif action == 'refresh' and self.real and s.stage == 'places':
            s.operation, s.stage, s.notice = ('places', None, object()), 'searching', ''
        elif op == 'category' and s.stage == 'interests' and value in CATEGORIES:
            s.categories.symmetric_difference_update({value})
        elif action == 'show' and s.stage == 'interests':
            if not s.categories: raise InputError('Выберите хотя бы один интерес.')
            if self.real:
                s.operation, s.stage, s.notice = ('places', None, object()), 'searching', ''
            else:
                places = self.source.search(s.city, s.district, s.categories)
                s.places, s.stage = places, 'places'
        elif op in ('toggle', 'duration') and s.stage == 'places':
            if self.real:
                place = s.places[int(value)] if value.isdigit() and int(value) < len(s.places) else None
                value = place.id if place else ''
            else:
                place = next((p for p in s.places if p.id == value), None)
            if place is None: raise InputError('Место недоступно в этом подборе.')
            if op == 'toggle':
                if value in s.selected: del s.selected[value]
                else: s.selected[value] = MINUTES[place.category]
                s.plan = None
                s.route_link_fallback = False
            else:
                if value not in s.selected: raise InputError('Сначала выберите это место.')
                s.pending, s.stage = value, 'duration'
        elif action == 'confirm' and s.stage == 'places':
            if not s.selected: raise InputError('Выберите хотя бы одно место перед подтверждением.')
            s.stage, s.plan, s.notice = 'day_date', None, ''
        elif action == 'edit' and s.stage in ('confirmed', 'duration'):
            s.pending, s.stage = None, 'places'
        elif action == 'interests' and s.stage == 'places':
            if not self.real: s.selected.clear()
            s.stage = 'interests'
        else:
            raise InputError('Эта кнопка сейчас недоступна. Используйте /resume.')
        s.revision += 1
        return self.view(key)

    def view(self, key):
        s = self.require(key)
        if self.saved_flow and s.stage.startswith('saved_'):
            return self.saved_flow.view(self, key, key[1])
        rows = []
        def button(label, action):
            rows.append([(label[:60], self.token(key, action))])
        def link_button(label, url):
            rows.append([(label[:60], url)])
        def attribution(place):
            if place.maps_url: lines.append('Google Maps: ' + place.maps_url)
            lines.extend(place.attributions)
        lines = []
        if s.notice: lines.append(s.notice)
        if s.stage == 'day_date':
            lines += ['Введите дату маршрута в формате ГГГГ-ММ-ДД.', 'Доступны сегодня и следующие 7 дней.']
            button('Назад к местам', 'back_to_places')
        elif s.stage == 'day_start':
            lines += ['Введите время старта в формате ЧЧ:ММ.']
        elif s.stage == 'day_end':
            lines += ['Введите время окончания дня или используйте 20:00.']
            button('Закончить в 20:00', 'end:default')
        elif s.stage == 'start_query':
            lines += ['Введите адрес или название стартовой точки. Результат потребуется подтвердить.']
            button('Назад к местам', 'back_to_places')
        elif s.stage == 'finish_choice':
            lines += ['Где закончить маршрут?']
            button('У последнего места', 'finish:last')
            button('Указать конечную точку', 'finish:address')
        elif s.stage == 'finish_query':
            lines += ['Введите адрес или название конечной точки.']
        elif s.stage in ('endpoint_confirm_start', 'endpoint_confirm_finish'):
            lines += ['Подтвердите точку:']
            for index, endpoint in enumerate(s.endpoint_candidates):
                lines.append(f'{index + 1}. {endpoint.label}')
                button(f'{index + 1}. {endpoint.label}', f'endpoint:{index}')
        elif s.stage == 'walking_choice':
            lines += ['Лимит суммарной ходьбы за день:']
            button('90 минут', 'walk:90')
            button('Другой лимит', 'walk:custom')
        elif s.stage == 'walking_input':
            lines += ['Введите лимит ходьбы в минутах.']
        elif s.stage == 'lunch_choice':
            lines += ['Добавить фиксированный обед?']
            button('Без обеда', 'lunch:none')
            button('Добавить обед', 'lunch:yes')
        elif s.stage == 'lunch_time':
            lines += ['Введите время начала обеда в формате ЧЧ:ММ.']
        elif s.stage == 'lunch_duration':
            lines += ['Введите длительность обеда в минутах.']
        elif s.stage == 'plan_ready':
            p = s.day_parameters
            lines += ['Проверьте настройки и постройте маршрут.',
                      f'День: {p.date:%d.%m.%Y}, {p.start:%H:%M}–{p.end:%H:%M}.',
                      f'Старт: {s.start_endpoint.label}.',
                      'Финиш: ' + (s.finish_endpoint.label if s.finish_endpoint else 'у последнего места') + '.',
                      f'Лимит ходьбы: {p.walking_limit_min} мин.',
                      'Обед: ' + (f'{p.lunch.start:%H:%M}, {p.lunch.duration_min} мин.' if p.lunch else 'нет.')]
            button('Построить маршрут', 'calculate')
            button('Изменить настройки дня', 'edit_day_settings')
            button('Назад к местам', 'back_to_places')
        elif s.stage in ('planning_requested', 'planning', 'detail_requested'):
            lines += ['Рассчитываю маршрут. Повторное нажатие не требуется; выбор и параметры сохранены.']
        elif s.stage == 'planned' and s.plan:
            plan = s.plan
            lines += [f'План дня: {plan.start:%H:%M}–{plan.end:%H:%M}.']
            if s.day_parameters and s.day_parameters.lunch:
                lunch = s.day_parameters.lunch
                lunch_end = (datetime.combine(s.day_parameters.date, lunch.start) +
                             timedelta(minutes=lunch.duration_min)).time()
                lines.append(f'Обед: {lunch.start:%H:%M}–{lunch_end:%H:%M}.')
            for index, leg in enumerate(plan.legs):
                mode = 'пешком' if leg.option.mode == 'WALK' else 'транспорт'
                transfer = f', {leg.option.transfers} пересадка(и)' if leg.option.transfers else ''
                lines.append(f'{leg.departure:%H:%M}–{leg.arrival:%H:%M}: {mode}, {leg.option.duration_min} мин{transfer}.')
                if leg.option.maps_url: lines.append(leg.option.maps_url)
                button(f'Подробности перехода {index + 1}', f'detail:{index}')
                if index < len(plan.stops):
                    stop = plan.stops[index]
                    lines.append(f'{stop.arrival:%H:%M}–{stop.departure:%H:%M}: {stop.name}, {stop.duration_min} мин.')
                    if stop.hours_unknown: lines.append('⚠️ Часы работы неизвестны — проверьте перед поездкой.')
            for exclusion in plan.exclusions:
                lines.append(f'Исключено: {exclusion.name} — {exclusion.reason}; около {exclusion.saved_min} мин освобождено.')
            lines += [f'Переезды: {plan.total_travel_min} мин. Ходьба: {plan.total_walking_min} мин.',
                      *('⚠️ ' + warning for warning in plan.warnings),
                      'Расписание оценочное; проверьте актуальные часы и предупреждения Google Maps.']
            try:
                if not s.start_endpoint:
                    raise RouteMapError('Ссылка на карту недоступна: стартовая точка не определена.')
                route_map = build_route_map_link(s.start_endpoint, s.finish_endpoint,
                                                 plan, s.places)
            except RouteMapError as error:
                lines.append(str(error))
            else:
                lines.append('Google Maps построит собственный вариант по переданным точкам; путь, время и способы перемещения могут отличаться от расчёта бота.')
                if route_map.mobile_waypoint_warning:
                    lines.append('⚠️ На некоторых мобильных устройствах часть промежуточных точек может не открыться.')
                link_button('Открыть маршрут в Google Maps', route_map.url)
            if s.detail_text: lines += ['', 'Подробности перехода:', s.detail_text]
            button('Изменить', 'edit_plan_places')
        elif s.stage == 'searching':
            lines += ['Поиск выполняется. Повторный запрос не нужен. Выбор сохранён.']
        elif s.stage == 'geo_confirm':
            lines += ['Подтвердите найденную территорию. Если район неоднозначен, уточните город и страну.']
            for index, geo in enumerate(s.candidates):
                lines.append(f'{index + 1}. {geo.label}')
                lines.extend(geo.attributions)
                button(f'{index + 1}. {geo.label}', f'geo:{index}')
            button('Уточнить географию', 'geography')
        elif s.stage == 'geo':
            lines += ['Введите город или район.', self.source.geography_hint]
        elif s.stage == 'interests':
            lines += ['Выберите один или несколько интересов.',
                      f'География: {s.district or s.city}.']
            for id, label in CATEGORIES.items():
                button(('✅ ' if id in s.categories else '⬜ ') + label, 'category:' + id)
            button('Показать места', 'show')
            if self.real: button('Другая география (сброс выбора)', 'geography')
        elif s.stage == 'duration':
            p = next(p for p in s.places if p.id == s.pending)
            lines += [f'{p.name}: сейчас {s.selected[s.pending]} мин.',
                      'Введите целое число минут от 1 до 999999.']
            attribution(p)
            button('Отмена изменения', 'edit')
        else:
            if s.stage == 'confirmed':
                lines += ['Расчёт не завершён. Выбранные места сохранены:']
                for p in s.places:
                    if p.id in s.selected:
                        lines.append(f'• {p.name} — {s.selected[p.id]} мин')
                lines += [f'Посещения: {sum(s.selected.values())} мин.']
                if s.route_link_fallback and s.start_endpoint:
                    try:
                        route_map = build_selected_route_map_link(
                            s.start_endpoint, s.finish_endpoint, tuple(s.selected), s.places)
                    except RouteMapError as error:
                        lines.append(str(error))
                    else:
                        lines.append('⚠️ Google Maps получил места в порядке выбора; маршрут и расписание не рассчитаны ботом.')
                        if route_map.mobile_waypoint_warning:
                            lines.append('⚠️ На некоторых мобильных устройствах часть промежуточных точек может не открыться.')
                        link_button('Открыть выбранные места в Google Maps', route_map.url)
                if s.route_link_fallback:
                    button('Повторить расчёт', 'retry_calculate')
                button('Изменить', 'edit_plan_places')
            else:
                lines += ['Выберите места. Повторное нажатие снимает выбор; время можно изменить кнопкой ⏱.']
                if not s.places: lines += ['Мест не найдено. Измените интересы или географию.']
                page_places = s.places[s.page * 3:(s.page + 1) * 3] if self.real else s.places
                for p in page_places:
                    chosen = p.id in s.selected
                    minutes = s.selected.get(p.id, MINUTES[p.category])
                    ref = str(s.places.index(p)) if self.real else p.id
                    lines += [f'\n{"✅" if chosen else "⬜"} {p.name}',
                              p.address or p.district,
                              ', '.join(CATEGORIES[c] for c in (p.categories or (p.category,))),
                              f'Около {minutes} мин.']
                    if p.description: lines.append(p.description)
                    attribution(p)
                    button(('✅ ' if chosen else '⬜ ') + p.name, 'toggle:' + ref)
                    if chosen: button(f'⏱ {p.name}: {minutes} мин', 'duration:' + ref)
                if self.real and s.places:
                    lines.append(f'Страница {s.page + 1}/{(len(s.places) + 2) // 3}. Выбранные места сохраняются.')
                    if s.page: button('← Предыдущая', f'page:{s.page - 1}')
                    if (s.page + 1) * 3 < len(s.places): button('Следующая →', f'page:{s.page + 1}')
                lines += [f'\nВыбрано: {len(s.selected)}. Посещения: {sum(s.selected.values())} мин.']
                button('Подтвердить места', 'confirm')
                button('Изменить интересы' if self.real else 'Изменить интересы (сброс мест)', 'interests')
                if self.real:
                    button('Повторить поиск (выбор сохранится)', 'refresh')
                    button('Другая география (сброс выбора)', 'geography')
        if s.editing_day_settings and s.stage in (
                'day_start', 'day_end', 'finish_choice', 'finish_query',
                'walking_choice', 'walking_input', 'lunch_choice',
                'lunch_time', 'lunch_duration'):
            button('Оставить текущие настройки', 'keep_day_settings')
        if self.saved_flow and s.stage in ('geo', 'planned'):
            button('Мои маршруты', 'routes')
        button('Новый подбор', 'new')
        lines.append(SOURCE_NOTE if self.real else self.source.label)
        return '\n'.join(lines), rows
