# Google Maps Route Link Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one safe Google Maps Directions URL for the ordered points in a completed day plan.

**Architecture:** A pure exporter converts the existing route domain values into an encoded Maps URL and typed presentation result. The Telegram dialog renders its button, warnings, or recoverable error without changing the planner.

**Tech Stack:** Python 3.10+, standard-library `urllib.parse`, `unittest`, python-telegram-bot 22.8.

**Spec:** `docs/superpowers/specs/2026-09-11-google-maps-route-link-design.md`

## Global Constraints

- Use `https://www.google.com/maps/dir/?api=1` and omit `travelmode`.
- Preserve the final `DayPlan.stops` order and perform no network request or optimization.
- Do not expose secrets, Telegram data, session IDs, or callbacks.
- Reject URLs longer than 2048 characters rather than truncating them.
- Warn above three waypoints and explain that Google Maps recalculates the route.
- Do not commit, push, deploy, or call live APIs.

---

### Task 1: Pure route-map exporter

**Files:**
- Create: `travel_bot/route_map.py`
- Create: `tests/test_route_map.py`

**Interfaces:**
- Produce `RouteMapLink(url: str, mobile_waypoint_warning: bool)`.
- Produce `RouteMapError(ValueError)`.
- Produce `build_route_map_link(start: Endpoint, finish: Endpoint | None, plan: DayPlan, places: tuple[Place, ...]) -> RouteMapLink`.

- [ ] Write tests asserting official base URL, omitted `travelmode`, separate and implicit destinations, exact stop order, Unicode URL encoding, matching Place ID parameters, no internal data, fewer than two points, missing coordinates, length over 2048, and warning above three waypoints.
- [ ] Run `python -m unittest tests.test_route_map -v`; verify failure because `travel_bot.route_map` is absent.
- [ ] Implement immutable result/error types and URL generation with `urllib.parse.urlencode`; validate all inputs and final length without network access.
- [ ] Run `python -m unittest tests.test_route_map -v`; require all tests to pass.

### Task 2: Telegram presentation and documentation

**Files:**
- Modify: `travel_bot/dialog.py`
- Modify: `tests/test_route_dialog.py`
- Modify: `README.md`

**Interfaces:**
- Consume `build_route_map_link(...)` only in the `planned` view.
- Render an external URL button without callback data.

- [ ] Add dialog tests for the button label/URL, Google recalculation notice, waypoint warning, and recoverable map-link error that preserves the plan.
- [ ] Run `python -m unittest tests.test_route_dialog -v`; verify the new assertions fail before production changes.
- [ ] Extend the dialog button representation and Telegram adapter to support an external URL button while preserving existing callback buttons.
- [ ] Render the route link and explanatory copy from the planned view; catch only `RouteMapError` and leave state unchanged.
- [ ] Update README with link purpose, omitted unified mode, independent Google recalculation, 2048 limit, and mobile waypoint limit.
- [ ] Run `python -m unittest tests.test_route_map tests.test_route_dialog tests.test_telegram -v`; require all affected tests to pass.

### Task 3: Final verification

**Files:**
- Verify only; no expected production edits.

- [ ] Run `python -m unittest discover -s tests -v` once and require zero failures.
- [ ] Run `python -m pip check` and require `No broken requirements found`.
- [ ] Scan project files excluding the ignored local `.env` for token-shaped secrets without printing content.
- [ ] Report results and provide a mobile/browser manual test scenario; stop before stage 4.
