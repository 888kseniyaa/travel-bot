# Saved Routes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist, list, refresh, rename, and delete owner-isolated routes in local SQLite for up to 30 days.

**Architecture:** A strict versioned domain payload separates permitted persistent data from temporary Google content. A SQLite repository enforces ownership, versions, limits, expiration, and migrations; a service refreshes Google content and validates the saved order; a dedicated saved-route flow integrates it with the existing Telegram adapter without replacing the active selection.

**Tech Stack:** Python 3.10+, standard-library `sqlite3`/`json`, python-telegram-bot 22.8, existing Places/Routes clients, `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-11-saved-routes-design.md`

## Global Constraints

- Store at most 20 records per Telegram user and delete records older than 30 days.
- Store Place IDs and permitted 30-day coordinates, but no Google names, addresses, hours, raw responses, transit steps, or raw route results.
- Every repository operation is owner-scoped; mutations also require the current record version.
- Preserve the active in-memory selection and successfully calculated plan on every storage failure.
- Use parameterized SQL, strict versioned JSON, no pickle, no route/user content in logs.
- Use fake Google clients and temporary databases in tests; perform no live or paid calls.
- Do not commit, push, deploy, or create external resources.

---

### Task 1: Versioned saved-route domain

**Files:**
- Create: `travel_bot/saved_routes.py`
- Create: `tests/test_saved_routes.py`
- Modify: `travel_bot/state.py`
- Modify: `travel_bot/dialog.py`

**Interfaces:**
- Produce `SavedPlace(place_id, category, categories, duration_min)`.
- Produce `SavedEndpoint(place_id, query, coordinate, utc_offset_minutes)`.
- Produce `SavedRoutePayload(format_version, geography_query, day, start, finish, places, order, exclusion_codes)`.
- Produce `SavedRouteSummary(id, version, name, route_date, created_at, updated_at, expires_at)` and `SavedRoute`.
- Produce strict `payload_to_json`, `payload_from_json`, `route_fingerprint`, and `default_route_name`.
- Extend `Selection` with original geography/start/finish query values and non-destructive saved-route browser state.

- [ ] Write tests with literal payload JSON for round-trip, stable fingerprint, title normalization, date-plus-original-query name, at most six places, order membership, positive durations, coordinate validation, 30-day expiration, unknown version, malformed JSON, excessive text, and forbidden extra fields.
- [ ] Run `python -m unittest tests.test_saved_routes -v`; verify failure because the module is absent.
- [ ] Implement immutable domain values and explicit dictionary validation; accept only format version 1 and exact allowed keys.
- [ ] Capture normalized original queries when the current dialog receives geography/start/finish text; do not replace them with Google display values.
- [ ] Run `python -m unittest tests.test_saved_routes tests.test_dialog tests.test_route_dialog -v`; require all affected tests to pass.

### Task 2: SQLite repository and migration

**Files:**
- Create: `travel_bot/route_repository.py`
- Create: `tests/test_route_repository.py`
- Modify: `.gitignore`

**Interfaces:**
- Produce `RouteRepository(path, now_provider)` with `migrate`, `save`, `list`, `get`, `rename`, `delete`, `delete_all`, `count`, and `close`.
- Produce fixed exceptions `RepositoryError`, `RouteLimitError`, `RouteNotFound`, `StaleRoute`.
- `save(owner_user_id, name, geography_query, fingerprint, payload) -> SavedRoute` returns the existing row for a duplicate fingerprint.
- `get/rename/delete` require `owner_user_id`; mutations require `expected_version`.

- [ ] Write temporary-file tests for clean migration, migration metadata, restart persistence, idempotent fingerprint, newest-first pagination, strict owner isolation, cross-owner mutation refusal, rename version increment, stale version rejection, repeated delete, delete-all isolation, cleanup older than 30 days, exact-boundary retention, and refusal of the 21st live record.
- [ ] Run `python -m unittest tests.test_route_repository -v`; verify failure because the repository is absent.
- [ ] Implement migration 1 in one exclusive transaction and refuse schema versions above 1; configure foreign keys, busy timeout, WAL, and row factory.
- [ ] Implement parameterized CRUD transactions, owner/version predicates, cleanup-before-list/save, and safe exception translation without logging SQL values.
- [ ] Ignore `data/*.sqlite3`, `data/*.sqlite3-wal`, and `data/*.sqlite3-shm`.
- [ ] Run `python -m unittest tests.test_route_repository -v`; require all repository tests to pass.

### Task 3: Save and fixed-order refresh service

**Files:**
- Create: `travel_bot/saved_route_service.py`
- Modify: `travel_bot/google_places.py`
- Modify: `travel_bot/planning.py`
- Create: `tests/test_saved_route_service.py`

**Interfaces:**
- Produce `SavedRouteService(repository, place_source, planning_service)` with synchronous CRUD wrappers, `autosave(session, owner_user_id)`, and async `open_current(dialog, key, session, route_id, expected_version)`.
- Add `GoogleSource.refresh_saved_places(place_ids, day, budget)` and `refresh_saved_endpoint(place_id, query, cached_coordinate, budget)` with bounded current-data requests.
- Add `PlanningService.validate_fixed_order(...)` that validates the persisted order and never calls `rank_candidates`.

- [ ] Write service tests proving only permitted fields enter `payload_json`, duplicate calculation saves once, limit/database failure preserves `session.plan`, owner isolation is forwarded, Google refresh obtains current names/hours, the exact saved order reaches fixed validation, successful open does not update the stored payload, and Google/Routes failure leaves the record retryable.
- [ ] Run `python -m unittest tests.test_saved_route_service -v`; verify missing interfaces fail.
- [ ] Implement conversion from completed `Selection` to format-1 payload, including selected IDs/durations and final stop order; use original user queries for persisted text.
- [ ] Extend Place Details masks only with display name/formatted address needed at open; reuse existing retry, budget, attribution, and safe-error behavior.
- [ ] Extract fixed-order validation from the existing planner orchestration without changing normal optimization behavior.
- [ ] Run `python -m unittest tests.test_saved_route_service tests.test_google_planning tests.test_planning -v`; require all affected tests to pass.

### Task 4: Saved-route Telegram flow

**Files:**
- Create: `travel_bot/saved_route_flow.py`
- Modify: `travel_bot/dialog.py`
- Modify: `travel_bot/telegram_app.py`
- Modify: `travel_bot/settings.py`
- Modify: `travel_bot/__main__.py`
- Create: `tests/test_saved_route_flow.py`
- Modify: `tests/test_settings.py`
- Modify: `tests/test_telegram.py`

**Interfaces:**
- Add `ROUTES_DB_PATH`, default `data/routes.sqlite3`, to `Settings` without exposing it or secrets in repr.
- Register `/routes` and `/delete_my_data` handlers.
- Produce five-row pagination, route card, rename input, delete confirmation, delete-all confirmation, retry refresh, and return-to-selection actions using session/revision plus route ID/version callbacks.
- Maintain one cancellable refresh task per `(chat_id, user_id)` and call `autosave` once after successful calculation.

- [ ] Write dialog/adapter tests for both entry points, five-item pages, active-selection preservation, current-data refresh, route map button, 1–80-character rename, delete confirmation, repeated delete, delete-all confirmation, stale callbacks, owner isolation, automatic save success/failure, and task cancellation on `/start` or a newer open.
- [ ] Run `python -m unittest tests.test_saved_route_flow tests.test_telegram tests.test_settings -v`; verify new behavior fails before production changes.
- [ ] Implement saved-route browser state separately from the underlying selection stage and values; return restores the exact prior view.
- [ ] Integrate repository migration before polling, automatic save after planning, background refresh, commands, and safe shutdown.
- [ ] Run `python -m unittest tests.test_saved_route_flow tests.test_telegram tests.test_real_adapter tests.test_route_dialog tests.test_settings -v`; require all affected tests to pass.

### Task 5: Documentation and final verification

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

**Interfaces:**
- Document `ROUTES_DB_PATH`, migration/startup behavior, 20-route and 30-day policies, permitted persisted fields, current-data refresh, deletion controls, backup of a stopped SQLite database, persistent-disk requirement, and privacy-policy changes.

- [ ] Update configuration and manual scenarios without secret values or claims that Google route snapshots are stored.
- [ ] Run `python -m unittest discover -s tests -v` once; require zero failures.
- [ ] Run `python -m pip check`; require `No broken requirements found`.
- [ ] Open a temporary database twice and verify migration/restart persistence, then run `git diff --check`.
- [ ] Scan project files excluding ignored `.env` and SQLite files for token-shaped secrets without printing file contents.
- [ ] Report automatic results, no live API calls, and a concrete manual scenario; stop before stage 5 until explicit acceptance.
