# Telegram Bot UX Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Shorten the existing Telegram journey and give the user one clear instruction and primary action at each step.

**Architecture:** Keep the current `Dialog`/`Adapter`/source/repository boundaries. Change only dialog transitions, minimal navigation state, command registration, and presentation copy; reuse existing day models, validation, route planning, saved routes, and Maps links.

**Tech Stack:** Python 3.10+, python-telegram-bot 22.8, standard-library `unittest`, existing Places and Routes clients.

**Spec:** `docs/superpowers/specs/2026-09-11-bot-ux-refresh-design.md`

## Global Constraints

- Preserve Google attribution, `/terms`, `/privacy`, route fallback, saved routes, user/chat isolation, and stale-button protection.
- Add no hosting, web interface, external service, or new planning capability.
- Main real-mode screens use `Места: Google Maps • время посещения: оценка бота` once.
- Default day values are exactly 10:00–20:00, finish at the last place, walking limit 90 minutes, and no lunch.
- Tests use fakes and make no live Telegram or paid Google request.

---

### Task 1: Compact guidance and `/about`

**Files:**
- Modify: `travel_bot/dialog.py`
- Modify: `travel_bot/telegram_app.py`
- Modify: `tests/test_real_dialog.py`
- Modify: `tests/test_telegram.py`

**Interfaces:**
- Produces: `Adapter.about(update, context)` command handler.
- Preserves: `Dialog.view(key) -> tuple[str, list[list[tuple[str, str]]]]`.

- [ ] **Step 1: Write failing presentation tests**

Add assertions that normal real-mode views contain exactly one compact source line, omit territory/API/catalog boilerplate, and begin with a concrete instruction. Add an adapter test that `/about` explains source, estimate ownership, territory shape, result limits, route recalculation, storage, `/terms`, and `/privacy`.

- [ ] **Step 2: Verify the new tests fail**

Run: `.venv/bin/python -m unittest tests.test_real_dialog tests.test_telegram -v`

Expected: failures for old repeated copy and missing `about` handler.

- [ ] **Step 3: Implement compact copy and command**

Use this main-screen source text:

```python
SOURCE_NOTE = 'Места: Google Maps • время посещения: оценка бота'
```

Move explanatory material into one fixed `/about` response. Register `CommandHandler('about', adapter.about)` beside the existing policy commands. Keep returned third-party attributions next to place data.

- [ ] **Step 4: Verify affected tests pass**

Run: `.venv/bin/python -m unittest tests.test_real_dialog tests.test_telegram tests.test_google -v`

- [ ] **Step 5: Commit the task**

```bash
git add travel_bot/dialog.py travel_bot/telegram_app.py tests/test_real_dialog.py tests/test_telegram.py
git commit -m "Streamline bot guidance and add about command"
```

### Task 2: Short default planning path

**Files:**
- Modify: `travel_bot/state.py`
- Modify: `travel_bot/dialog.py`
- Modify: `tests/test_route_dialog.py`
- Modify: `tests/test_dialog.py`

**Interfaces:**
- Produces state stages: `day_date`, `start_query`, `endpoint_confirm_start`, `plan_ready` for the short path.
- Produces callbacks: `edit_day_settings`, `back_to_places`, and existing `calculate`.
- Consumes: `DayParameters(date, time(10), time(20), 90, None)`.

- [ ] **Step 1: Write failing journey tests**

Test that `confirm` from the place list goes directly to `day_date`; a valid date creates default day parameters and asks for the start; confirmed start goes to `plan_ready`. Assert that the readiness screen displays all four defaults and offers `Построить маршрут`, `Изменить настройки дня`, and `Назад к местам`.

- [ ] **Step 2: Verify the tests fail for the old journey**

Run: `.venv/bin/python -m unittest tests.test_route_dialog tests.test_dialog -v`

Expected: failures because `confirm` still enters `confirmed` and date still asks for start time.

- [ ] **Step 3: Implement the short transitions**

On place confirmation set `stage = 'day_date'`. On valid date assign:

```python
s.day_parameters = DayParameters(value, time(10), time(20), 90, None)
s.draft_date = value
s.draft_start = time(10)
s.draft_end = time(20)
s.draft_walking_limit = 90
s.start_endpoint = None
s.finish_endpoint = None
s.stage = 'start_query'
```

After start endpoint confirmation, enter `plan_ready`. `back_to_places` returns without clearing selection or durations. Keep revision checks on every callback.

- [ ] **Step 4: Verify affected tests pass**

Run: `.venv/bin/python -m unittest tests.test_route_dialog tests.test_dialog tests.test_planning -v`

- [ ] **Step 5: Commit the task**

```bash
git add travel_bot/state.py travel_bot/dialog.py tests/test_route_dialog.py tests/test_dialog.py
git commit -m "Shorten default day planning flow"
```

### Task 3: Optional detailed settings and result actions

**Files:**
- Modify: `travel_bot/dialog.py`
- Modify: `travel_bot/state.py`
- Modify: `tests/test_route_dialog.py`
- Modify: `tests/test_saved_route_flow.py`

**Interfaces:**
- Produces detailed-settings stages using existing validated inputs: `day_start`, `day_end`, `finish_choice`, `finish_query`, `walking_choice`, `walking_input`, `lunch_choice`, `lunch_time`, `lunch_duration`.
- Produces: `Selection.editing_day_settings: bool`, set only while traversing detailed settings and cleared on completion or return.
- Produces a return to `plan_ready` after valid detailed settings.
- Preserves saved-route entry callbacks and current Maps URL behavior.

- [ ] **Step 1: Write failing settings and result tests**

Cover entry through `Изменить настройки дня`, the exact detailed order, safe return with current valid values, invalid input remaining recoverable, and `Назад к местам`. Assert that the planned screen ends with only the main actions `Изменить`, `Мои маршруты`, and `Новый подбор`, while transition details and the correct Maps button remain available.

- [ ] **Step 2: Verify the tests fail**

Run: `.venv/bin/python -m unittest tests.test_route_dialog tests.test_saved_route_flow -v`

Expected: failures for missing detailed-settings entry/return and old result labels.

- [ ] **Step 3: Implement detailed navigation and concise result hierarchy**

Reuse `_finish_day_parameters` and add `Selection.editing_day_settings: bool` to distinguish the detailed flow. Every valid settings completion clears this flag and enters `plan_ready`; settings changes set `plan = None` and preserve `selected`. Render primary result buttons with these labels:

```python
button('Изменить', 'edit_plan_places')
button('Мои маршруты', 'routes')
button('Новый подбор', 'new')
```

Keep transition-detail callbacks attached to their corresponding legs and preserve successful/fallback Google Maps URL buttons.

- [ ] **Step 4: Verify all dialog and saved-route tests pass**

Run: `.venv/bin/python -m unittest tests.test_route_dialog tests.test_saved_route_flow tests.test_route_adapter tests.test_telegram -v`

- [ ] **Step 5: Commit the task**

```bash
git add travel_bot/dialog.py travel_bot/state.py tests/test_route_dialog.py tests/test_saved_route_flow.py
git commit -m "Refine day settings and route result actions"
```

### Task 4: Documentation and complete verification

**Files:**
- Modify: `README.md`

**Interfaces:**
- Documents: shortened journey, visible defaults, `/about`, detailed settings, recovery actions, and deferred live verification.

- [ ] **Step 1: Update the manual scenario and command list**

Describe the exact short path and a second pass through `Изменить настройки дня`. Remove instructions that refer to the deleted intermediate confirmation screen or mandatory traversal of every setting.

- [ ] **Step 2: Run the complete automated suite**

Run: `.venv/bin/python -m unittest discover -s tests -v`

Expected: 0 failures.

- [ ] **Step 3: Run repository checks**

Run: `.venv/bin/python -m pip check`

Expected: `No broken requirements found.`

Run: `git diff --check`

Expected: exit 0 with no output.

Scan tracked project files excluding `.env` and `data/**` for token-shaped secrets; print only matches, never secret-bearing file contents. Expected: no matches.

- [ ] **Step 4: Commit documentation**

```bash
git add README.md
git commit -m "Document streamlined Telegram journey"
```

- [ ] **Step 5: Report verification boundary**

Report the exact test count and checks run. State that live Telegram and Google verification remains deferred and do not push or deploy without a separate request.
