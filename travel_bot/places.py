"""Replace PlaceSource to connect a real provider; minutes remain app estimates."""
from dataclasses import dataclass
from typing import Protocol, Optional
from .day import Coordinate

CATEGORIES = {'museum': 'Музеи', 'park': 'Парки', 'architecture': 'Архитектура'}
MINUTES = {'museum': 120, 'park': 60, 'architecture': 45}

@dataclass(frozen=True)
class Place:
    id: str
    name: str
    district: str
    description: str
    category: str
    address: str = ""
    maps_url: str = ""
    attributions: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    coordinate: Optional[Coordinate] = None
    opening_windows: tuple[tuple[object, object], ...] = ()
    hours_known: bool = False

class PlaceSource(Protocol):
    geography_hint: str
    def resolve(self, text: str) -> tuple[str, Optional[str]]: ...
    def search(self, city: str, district: Optional[str], categories: set[str]) -> tuple[Place, ...]: ...

class DemoSource:
    mode = "demo"
    label = "🧪 Демонстрационные данные — Санкт-Петербург."
    geography_hint = 'Демогород: Санкт-Петербург. Районы: Центральный, Адмиралтейский, Петроградский.'
    places = (
        Place('hermitage', 'Эрмитаж', 'Центральный', 'Коллекции искусства в дворцовом комплексе.', 'museum'),
        Place('russian_museum', 'Русский музей', 'Центральный', 'Знакомство с русским искусством.', 'museum'),
        Place('summer_garden', 'Летний сад', 'Центральный', 'Аллеи, скульптуры и прогулка в саду.', 'park'),
        Place('palace_square', 'Дворцовая площадь', 'Центральный', 'Ансамбль исторической площади.', 'architecture'),
        Place('isaac', 'Исаакиевский собор', 'Адмиралтейский', 'Монументальная архитектура собора.', 'architecture'),
        Place('naval', 'Центральный военно-морской музей', 'Адмиралтейский', 'Экспозиция об истории флота.', 'museum'),
        Place('fortress', 'Петропавловская крепость', 'Петроградский', 'Исторический ансамбль на Заячьем острове.', 'architecture'),
        Place('botanical', 'Ботанический сад', 'Петроградский', 'Прогулка среди растений.', 'park'),
    )

    def resolve(self, text):
        name = ' '.join(text.lower().strip().split()).removesuffix(' район')
        if name in ('санкт-петербург', 'петербург', 'спб'):
            return 'Санкт-Петербург', None
        for district in ('Центральный', 'Адмиралтейский', 'Петроградский'):
            if name == district.lower():
                return 'Санкт-Петербург', district
        raise ValueError(self.geography_hint)

    def search(self, city, district, categories):
        if city != 'Санкт-Петербург': return ()
        return tuple(p for p in self.places if p.category in categories and
                     (district is None or p.district == district))
