from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Optional


class ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Coordinate:
    latitude: float
    longitude: float

    def __post_init__(self):
        if not (-90 <= self.latitude <= 90 and -180 <= self.longitude <= 180):
            raise ValidationError('Некорректные координаты.')


@dataclass(frozen=True)
class TimeWindow:
    start: datetime
    end: datetime

    def __post_init__(self):
        if self.end <= self.start:
            raise ValidationError('Конец временного окна должен быть позже начала.')


@dataclass(frozen=True)
class LunchBreak:
    start: time
    duration_min: int


@dataclass(frozen=True)
class DayParameters:
    date: date
    start: time
    end: time = time(20)
    walking_limit_min: int = 90
    lunch: Optional[LunchBreak] = None

    def validate(self, today: date):
        if not today <= self.date <= today + timedelta(days=7):
            raise ValidationError('Дата должна быть сегодня или в следующие 7 дней.')
        if self.end <= self.start:
            raise ValidationError('Время окончания должно быть позже времени старта.')
        if self.walking_limit_min <= 0:
            raise ValidationError('Лимит ходьбы должен быть положительным.')
        if self.lunch:
            lunch_end = (datetime.combine(self.date, self.lunch.start) +
                         timedelta(minutes=self.lunch.duration_min)).time()
            if (self.lunch.duration_min <= 0 or self.lunch.start < self.start or
                    lunch_end > self.end):
                raise ValidationError('Обед должен полностью помещаться в туристический день.')

    def bounds(self, zone: tzinfo):
        return (datetime.combine(self.date, self.start, zone),
                datetime.combine(self.date, self.end, zone))


@dataclass(frozen=True)
class Endpoint:
    id: str
    label: str
    coordinate: Coordinate
    utc_offset_minutes: int = 0
    maps_url: str = ''
    attributions: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.id or not self.label:
            raise ValidationError('Точка должна иметь идентификатор и название.')


@dataclass(frozen=True)
class TravelOption:
    origin_id: str
    destination_id: str
    mode: str
    duration_min: int
    distance_m: int = 0
    transfers: int = 0
    warnings: tuple[str, ...] = ()
    maps_url: str = ''
    steps: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlanStop:
    place_id: str
    name: str
    arrival: datetime
    departure: datetime
    duration_min: int
    hours_unknown: bool = False


@dataclass(frozen=True)
class PlanLeg:
    option: TravelOption
    departure: datetime
    arrival: datetime


@dataclass(frozen=True)
class Exclusion:
    place_id: str
    name: str
    reason: str
    saved_min: int


@dataclass(frozen=True)
class DayPlan:
    stops: tuple[PlanStop, ...]
    legs: tuple[PlanLeg, ...]
    exclusions: tuple[Exclusion, ...]
    start: datetime
    end: datetime
    total_walking_min: int
    total_travel_min: int
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlanCandidate:
    place_ids: tuple[str, ...]
    stops: tuple[PlanStop, ...]
    legs: tuple[PlanLeg, ...]
    exclusions: tuple[Exclusion, ...]
    finish: datetime
    walking_min: int
    travel_min: int
    transfers: int
    warnings: tuple[str, ...] = ()
