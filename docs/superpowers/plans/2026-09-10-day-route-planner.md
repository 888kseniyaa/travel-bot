# Day Route Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, cost-bounded one-day WALK/TRANSIT planner for at most six confirmed places and expose it through the existing Telegram flow.

**Architecture:** Places provides coordinates, selected-place hours, and confirmed endpoints; Routes supplies two bounded matrices and time-correct leg validation. A pure local planner ranks subsets and orders, while an async coordinator applies results only to the unchanged user session.

**Tech Stack:** Python 3.10+, python-telegram-bot 22.8, httpx 0.28.1, unittest, Places API (New), Routes API v2.

**Spec:** `docs/superpowers/specs/2026-09-10-day-route-planner-design.md`

## Global Constraints

- Plan one day, today through seven days ahead, for at most six selected places.
- Use only `WALK` and `TRANSIT`; never shorten visit durations.
- Matrix maximum: 49 elements per mode and two matrix calls per calculation.
- Validation maximum: 12 Compute Routes calls plus one explicit detail call per requested leg.
- No production wildcard field masks, persistent Google-content cache, secrets in logs/messages, live paid calls, commit, push, or deploy.
- Existing demo/real selection, state isolation, stale-button protection, and all current tests must remain functional.

---

### Task 1: Day and place domain models

**Files:**
- Modify: `travel_bot/places.py`
- Create: `travel_bot/day.py`
- Modify: `travel_bot/state.py`
- Test: `tests/test_day.py`

**Interfaces:**
- `Coordinate(latitude: float, longitude: float)` validates geographic ranges.
- `DayParameters(date: date, start: time, end: time, walking_limit_min: int, lunch: LunchBreak | None)` validates horizon through `validate(today)`.
- `TimeWindow(start: datetime, end: datetime)`, `Endpoint(id, label, coordinate)`, and immutable plan/result values are consumed by Routes and planner.

- [ ] Write failing tests for the seven-day horizon, end after start, fixed lunch bounds, coordinate validation, and new fields preserving the existing `Place` constructor defaults.
- [ ] Run `python -m unittest tests.test_day -v`; confirm failure because `travel_bot.day` is absent.
- [ ] Implement the immutable values and extend `Selection` with parameters/endpoints/operation/result fields without changing existing defaults.
- [ ] Run `python -m unittest tests.test_day tests.test_dialog tests.test_real_dialog -v`; expect all tests to pass.

### Task 2: Selected-place details and endpoint resolution

**Files:**
- Modify: `travel_bot/google_places.py`
- Test: `tests/test_google_planning.py`

**Interfaces:**
- `GoogleSource.resolve_endpoint(text: str, geography: Geography, budget: PlanningBudget) -> tuple[Endpoint, ...]`
- `GoogleSource.enrich_selected(places: tuple[Place, ...], day: DayParameters, budget: PlanningBudget) -> tuple[Place, ...]`
- Search mapping fills `Place.coordinate`; enrichment fills `Place.opening_windows` or marks hours unknown.

- [ ] Write failing MockTransport tests for coordinate mapping, ambiguous endpoint confirmation, one Details request per selected place, hours crossing midnight, closed/missing hours, exact field masks, and sanitized failures.
- [ ] Run `python -m unittest tests.test_google_planning -v`; confirm missing interfaces fail.
- [ ] Add endpoint/detail calls with bounded timeouts and retries, requesting only location, display/address data, current opening periods, timezone data, Google Maps URI, and attributions needed by the spec.
- [ ] Run `python -m unittest tests.test_google_planning tests.test_google -v`; expect all tests to pass without network.

### Task 3: Routes client and matrix normalization

**Files:**
- Create: `travel_bot/routes.py`
- Test: `tests/test_routes.py`

**Interfaces:**
- `RoutesClient.matrices(points, departure, budget) -> TravelMatrix` performs one WALK and one TRANSIT matrix request.
- `RoutesClient.validate_leg(origin, destination, departure, mode, budget, detailed=False) -> TravelOption` performs Compute Routes.
- `PlanningBudget` enforces 49 elements per mode, two matrices, twelve validation calls, one user-initiated detail call per leg, and one retry only for transient failures.

- [ ] Write failing MockTransport tests for both travel-mode bodies, departure timestamp on transit, exact matrix mask including status/condition/indexes, streamed elements, unavailable/partial elements, malformed durations, 100-element rejection, retry policy, quota/auth/timeout sanitization, and detail masks.
- [ ] Run `python -m unittest tests.test_routes -v`; confirm failure because `travel_bot.routes` is absent.
- [ ] Implement the client and normalized matrix keyed by stable endpoint IDs; never include chat/user data or secrets in bodies/logs.
- [ ] Run `python -m unittest tests.test_routes -v`; expect all tests to pass without network.

### Task 4: Pure deterministic planner

**Files:**
- Create: `travel_bot/planner.py`
- Test: `tests/test_planner.py`

**Interfaces:**
- `rank_candidates(parameters, start, finish, places, matrix) -> tuple[PlanCandidate, ...]`
- `finalize_candidate(candidate, validated_legs) -> DayPlan`
- Candidate ranking uses visited count, finish time, travel, walking, transfers, then stable ID sequence.

- [ ] Write failing table-driven tests for linear ordering without return trips, every permutation/subset, visit durations, known/unknown hours, lunch blocking, day end, 15/40-minute boundaries, five-minute transfer penalties, unavailable transit/walk, walking cap, automatic exclusions, and deterministic ties.
- [ ] Run `python -m unittest tests.test_planner -v`; confirm failure because `travel_bot.planner` is absent.
- [ ] Implement local enumeration and timeline evaluation with no network, Telegram, or Google imports.
- [ ] Run `python -m unittest tests.test_planner -v`; expect all tests to pass.

### Task 5: Async calculation and stale-result protection

**Files:**
- Create: `travel_bot/planning.py`
- Modify: `travel_bot/state.py`
- Test: `tests/test_planning.py`

**Interfaces:**
- `PlanningService.calculate(dialog, key, session, fingerprint) -> PlanningOutcome | None`
- `PlanningService.detail(dialog, key, session, leg_index, fingerprint) -> RouteDetail | None`
- Result commits require unchanged session, revision, fingerprint, and operation identity.

- [ ] Write failing async tests for enrichment → matrices → ranking → time-correct validation, candidate fallback, partial matrix refusal, preserving edits after failure, duplicate Calculate, cancellation, `/start`, and late results after parameter/duration/place changes.
- [ ] Run `python -m unittest tests.test_planning -v`; confirm missing service failures.
- [ ] Implement orchestration with explicit budgets and fixed safe error messages; return no exact schedule unless every displayed leg validates.
- [ ] Run `python -m unittest tests.test_planning -v`; expect all tests to pass.

### Task 6: Telegram parameter and result flow

**Files:**
- Modify: `travel_bot/dialog.py`
- Modify: `travel_bot/telegram_app.py`
- Modify: `travel_bot/settings.py`
- Modify: `travel_bot/__main__.py`
- Test: `tests/test_route_dialog.py`
- Test: `tests/test_route_adapter.py`

**Interfaces:**
- Confirmed selection exposes `plan`, `edit parameters`, and `edit places/durations` actions.
- Adapter maintains one cancellable planning task per `(chat_id, user_id)` and short session-index callbacks.
- Settings accept `GOOGLE_ROUTES_API_KEY`, defaulting to the Places key only when explicitly documented, plus immutable limits matching the spec.

- [ ] Write failing dialog tests for date/start/end, default 20:00, endpoint candidates, optional finish, 90/custom walking limit, optional lunch, six-place rejection, recalculation, exclusions, warnings, summary transitions, and detail buttons.
- [ ] Write failing adapter tests for the complete fake Places+Routes Telegram flow, isolation, duplicate presses, cancellation/stale result, Telegram message/callback limits, and secret-free logs/messages.
- [ ] Run `python -m unittest tests.test_route_dialog tests.test_route_adapter -v`; confirm missing actions fail.
- [ ] Implement state transitions and task lifecycle while preserving existing selection/edit behavior.
- [ ] Run `python -m unittest tests.test_route_dialog tests.test_route_adapter tests.test_telegram tests.test_real_adapter -v`; expect all tests to pass.

### Task 7: Documentation and final verification

**Files:**
- Modify: `.env.example`
- Modify: `.gitignore`
- Modify: `README.md`

**Interfaces:**
- README documents Routes API enablement, field masks, matrix-element math, quotas, mode policy, walking warnings, hours behavior, date horizon, live-test boundary, and manual Telegram scenario.

- [ ] Update configuration examples without secrets; document key/API restrictions, two matrices and their maximum 98 elements, detail-call budgets, billing per matrix element, policies, attribution, and in-memory storage limits.
- [ ] Add a manual scenario covering endpoint confirmation, six-place cap, lunch, exclusion, unknown/closed hours, recalculation, stale Calculate, and on-demand details.
- [ ] Run `python -m unittest discover -s tests -v` once; require zero failures.
- [ ] Run `python -m pip check`; require `No broken requirements found`.
- [ ] Inspect the final diff and scan tracked/project files for token-shaped values without printing matches; report that no live Google/Telegram call, commit, push, or deploy was performed.
