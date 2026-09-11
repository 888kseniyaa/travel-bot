from dataclasses import dataclass, field
from typing import Optional
from datetime import date, time
from uuid import uuid4
from .places import Place
from .google_places import Budget, Geography
from .day import DayParameters, DayPlan, Endpoint
from time import monotonic

@dataclass
class Selection:
    session: str = field(default_factory=lambda: uuid4().hex[:16])
    revision: int = 0
    stage: str = 'geo'
    city: str = ''
    district: Optional[str] = None
    categories: set[str] = field(default_factory=set)
    places: tuple[Place, ...] = ()
    selected: dict[str, int] = field(default_factory=dict)
    pending: Optional[str] = None
    geography: Optional[Geography] = None
    candidates: tuple[Geography, ...] = ()
    operation: Optional[tuple] = None
    budget: Budget = field(default_factory=Budget)
    page: int = 0
    notice: str = ''
    day_parameters: Optional[DayParameters] = None
    start_endpoint: Optional[Endpoint] = None
    finish_endpoint: Optional[Endpoint] = None
    endpoint_candidates: tuple[Endpoint, ...] = ()
    plan: Optional[DayPlan] = None
    route_link_fallback: bool = False
    planning_operation: Optional[object] = None
    planning_fingerprint: str = ''
    planning_budget: Optional[object] = None
    draft_date: Optional[date] = None
    draft_start: Optional[time] = None
    draft_end: Optional[time] = None
    draft_walking_limit: int = 90
    draft_lunch_start: Optional[time] = None
    detail_text: str = ''
    detail_request: Optional[int] = None
    geography_query: str = ''
    start_query: str = ''
    finish_query: str = ''
    saved_return_stage: Optional[str] = None
    saved_page: int = 0
    saved_summaries: tuple = ()
    saved_current: Optional[object] = None
    saved_opened: Optional[object] = None
    saved_open_request: Optional[tuple] = None
    saved_delete_all_count: int = 0
    expires: float = field(default_factory=lambda: monotonic() + 1800)

class Store:
    """In-memory state scoped to both chat and user. Lost on restart."""
    def __init__(self):
        self._sessions: dict[tuple[int, int], Selection] = {}

    def start(self, key):
        self.purge()
        self._sessions[key] = Selection()
        return self._sessions[key]

    def purge(self):
        for key, value in list(self._sessions.items()):
            if value.expires <= monotonic(): del self._sessions[key]

    def get(self, key):
        self.purge()
        return self._sessions.get(key)
