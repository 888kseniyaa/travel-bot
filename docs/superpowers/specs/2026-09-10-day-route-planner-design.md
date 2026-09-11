# Day Route Planner Design

## Goal

Turn the confirmed set of at most six places into a realistic one-day schedule with visit times, walking or public-transit legs, opening-hour constraints, an optional lunch break, and clear exclusions. Route ordering is computed locally; Google provides place facts and route estimates.

## Agreed user flow

After confirming places, the user enters a date from today through the next seven days, start time, and end time (default 20:00). They enter a start address/place and confirm the Google candidate. The finish is optional: either confirm a separate address/place or finish at the last visit. The walking limit defaults to 90 minutes and can be changed. Lunch is optional and, when enabled, has a fixed start and duration.

The calculation accepts at most six selected places. Known opening hours are hard windows: the complete visit must fit. Unknown hours do not block a visit but create a warning. If all places cannot fit, the planner automatically returns the best feasible subset and names every excluded place with the reason and estimated effect. It never shortens visit durations.

The result shows arrival/departure times, visit duration, each leg's mode and full duration, transfers when available, links, totals, excluded places, unknown-hours warnings, and the fact that routing remains an estimate. Detailed travel steps are shown only when the user requests a leg's details.

The user can return to parameters, selected places, or duration editing and recalculate without starting the whole selection again.

## Travel policy

- If the walking route is at most 15 minutes, choose `WALK`.
- From 15 through 40 walking minutes, compare transit's full origin-to-destination duration with walking. Add a deterministic five-minute comparison penalty per transfer; choose the smaller effective duration.
- Above 40 walking minutes, prefer available `TRANSIT`.
- If transit is unavailable, walking is allowed only when the total walking limit remains satisfied and the result carries a warning.
- A plan exceeding its walking limit is infeasible.

## API strategy and cost limits

`GoogleSource` adds `places.location` to the existing Text Search field mask so selected places already have coordinates. After confirmation, Place Details (New) is called only for the selected places, at most six, to request the fields needed for current opening intervals and timezone interpretation. Start and optional finish candidates are resolved and explicitly confirmed through Places API; no Telegram identifiers are sent to Google.

Routes API calls use coordinates or Google place IDs. The client requests one rectangular `ComputeRouteMatrix` for `WALK` and one for `TRANSIT`. Origins are the start plus selected places; destinations are selected places plus the optional finish. At six places this is at most 7 × 7 = 49 elements per mode, 98 total, and the transit request stays below its 100-element limit. The matrix field mask is exactly `originIndex,destinationIndex,status,condition,distanceMeters,duration`.

The transit matrix uses the day start as an explicit approximation for candidate ordering. The final schedule never presents those approximate transit times as exact. The client validates promising schedules leg by leg with `ComputeRoutes` at each actual planned departure time. It makes at most 12 `ComputeRoutes` calls per calculation. Required summary fields cover duration, distance, warnings, leg steps' travel modes, and transit details needed to count transfers. A user request for detailed directions may make one additional bounded `ComputeRoutes` call for that leg with navigation fields.

The calculation allows at most two matrix calls, six selected-place detail calls, two endpoint-resolution calls, twelve schedule-validation calls, and one user-initiated detail call per leg. Network errors and 500/502/503/504 receive at most one retry; invalid key, permission, quota, invalid input, and incomplete matrix elements do not. No wildcard field masks are used.

Routes content is kept only in the current in-memory session and expires with it. It is not written to disk. Google Maps attribution, third-party attribution, copyright text required for matrix output, API warnings, and walking-route cautions remain visible with the result.

## Components

- `places.py` extends `Place` with a coordinate and opening-window metadata while preserving stable IDs.
- `google_places.py` maps search/detail responses into the internal place and endpoint models. It remains the only Places HTTP boundary.
- `day.py` defines immutable `DayParameters`, `TimeWindow`, `Endpoint`, `LunchBreak`, `TravelOption`, `PlanStop`, and `DayPlan` values. It validates the seven-day horizon and local time ordering.
- `routes.py` implements the async Routes API client, field masks, response streaming/normalization, bounded retries, status handling, per-calculation budget, summary route validation, and optional detail retrieval.
- `planner.py` is a pure deterministic planner with no Telegram, HTTP, or Google dependencies.
- `planning.py` orchestrates selected-place enrichment, matrices, local candidate ranking, time-correct validation, and atomic result commit.
- `state.py` stores day parameters, confirmed endpoints, planning operation identity, plan, exclusions, and route-detail budget within the existing `(chat_id, user_id)` session.
- `dialog.py` adds parameter collection, endpoint confirmation, calculation/recalculation controls, and plan presentation.
- `telegram_app.py` manages cancellable planning tasks using the existing session/revision pattern.
- `settings.py` adds an optional distinct Routes key, explicit planning limits, and validates them without logging secrets.

## Planner algorithm

The planner enumerates every permutation of every non-empty subset of at most six places locally. For each candidate it builds a provisional timeline from the two matrices, visit durations, fixed lunch, known opening windows, day end, and walking limit. It rejects candidates with missing required legs, closed places, over-limit walking, or departure after day end.

Feasible candidates are ordered lexicographically by: more visited places; earlier finish; less total travel; less walking; fewer transfers; stable place-ID sequence. This makes exclusions and tests deterministic. Places absent from the best candidate are classified as closed, outside the available day, unreachable, or incompatible with the walking limit. The displayed time saved is derived from the excluded visit duration plus adjacent provisional travel change and is explicitly labeled an estimate.

The orchestrator validates candidates from best to worse using actual departure times. A validated leg applies the agreed travel policy. Lunch is inserted as a hard blocked interval between activities; no visit or movement may overlap it. If validation changes timing enough to violate a window, the candidate is rejected and the next one is tried while budget remains. If no candidate can be fully validated, no precise schedule is displayed.

## Failures and concurrency

Matrix elements with non-OK status, `ROUTE_NOT_FOUND`, absent duration, or missing indexes are unavailable pairs. Transit may be unavailable while walking remains usable. A partial matrix can produce a plan only if every displayed leg has valid data and then passes final validation.

Timeout, authentication, quota, partial response, and budget errors return fixed messages without response bodies, request URLs, keys, or user identifiers. Existing selections, durations, and day parameters remain intact. The user can retry or edit.

Starting a new calculation creates a unique operation object. Repeated Calculate presses for the same operation do not start another task. `/start`, parameter changes, place changes, and duration changes cancel or invalidate the operation. A response commits only when session identity, revision, parameter fingerprint, and operation identity still match.

## Testing

Pure tests cover ordering, a linear route without backtracking, opening windows, unknown hours, lunch, day end, exclusions, mode selection, transfer penalty, walking limit, unavailable pairs, deterministic ties, and partial matrices. HTTP tests use `httpx.MockTransport` and cover field masks, element limits, statuses, timeouts, authentication, quota, retries, and sanitized output. Dialog and adapter tests cover parameters, endpoint confirmation, recalculation, two-user isolation, repeated presses, cancellation, stale results, details on request, Telegram limits, and the full Places-plus-Routes flow.

The default test suite makes no Google calls. A live check requires separate user approval, configured keys, billing, quotas, policies, and network access.

## Out of scope

No multiday routes, driving, booking, payments, accounts, persistent database, generative AI, deployment, commit, or push. The planner does not claim that Google waypoint optimization solves the mixed-mode/time-window problem.
