import re
from .places import CATEGORIES, MINUTES, DemoSource, PlaceSource
from .state import Store

class InputError(ValueError):
    pass

class Dialog:
    def __init__(self, source: PlaceSource = None, store=None):
        self.source = source if source is not None else DemoSource()
        self.store = store if store is not None else Store()

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
        if s.stage == 'geo' and self.real:
            text = ' '.join(text.split())
            if not text or len(text) > 200:
                raise InputError('Введите город и страну или район, город и страну (до 200 символов).')
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
            s.pending, s.stage = None, 'places'
        else:
            raise InputError('Используйте кнопки ниже. /resume — текущий экран, /start — новый подбор.')
        s.revision += 1
        return self.view(key)

    def click(self, key, data):
        s = self.require(key)
        prefix = f'{s.session}:{s.revision}:'
        if not isinstance(data, str) or not data.startswith(prefix):
            raise InputError('Эта кнопка устарела или принадлежит другому подбору. Используйте /resume.')
        action = data[len(prefix):]
        op, _, value = action.partition(':')
        if action == 'new': return self.start(key)
        if action == 'geography' and s.stage != 'searching':
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
            else:
                if value not in s.selected: raise InputError('Сначала выберите это место.')
                s.pending, s.stage = value, 'duration'
        elif action == 'confirm' and s.stage == 'places':
            if not s.selected: raise InputError('Выберите хотя бы одно место перед подтверждением.')
            s.stage = 'confirmed'
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
        rows = []
        def button(label, action):
            rows.append([(label[:60], self.token(key, action))])
        def attribution(place):
            if place.maps_url: lines.append('Google Maps: ' + place.maps_url)
            lines.extend(place.attributions)
        lines = [self.source.label]
        if self.real:
            lines.append('Данные мест: Google Maps. Оценки времени: бот.')
            if s.geography:
                lines += ['Поиск: ' + s.geography.label,
                          'Территория — прямоугольник Google, не точная административная граница.']
                lines.extend(s.geography.attributions)
            lines.append('Выдача ограничена: до 15 мест; не полный каталог. /terms /privacy')
        if s.notice: lines.append(s.notice)
        if s.stage == 'searching':
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
            lines += [f'География: {s.district or s.city}.', 'Выберите интересы (можно несколько):']
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
            lines += ['Время — приблизительная оценка приложения по категории, не статистика Google.']
            if s.stage == 'confirmed':
                lines += ['Список подтверждён:']
                for p in s.places:
                    if p.id in s.selected:
                        lines.append(f'• {p.name} — {s.selected[p.id]} мин')
                        attribution(p)
                lines += [f'Итого посещения: {sum(s.selected.values())} мин.',
                          'Дорога не включена в сумму. Маршрут пока не рассчитан.']
                button('Вернуться к редактированию', 'edit')
            else:
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
                button('Подтвердить список', 'confirm')
                button('Изменить интересы' if self.real else 'Изменить интересы (сброс мест)', 'interests')
                if self.real:
                    button('Повторить поиск (выбор сохранится)', 'refresh')
                    button('Другая география (сброс выбора)', 'geography')
        button('Новый подбор', 'new')
        return '\n'.join(lines), rows
