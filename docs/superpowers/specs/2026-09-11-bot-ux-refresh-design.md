# Telegram Bot UX Refresh Design

## Goal and scope

Stage 5 makes the existing Telegram journey shorter, clearer, and easier for a first-time traveler. It changes dialog order, button hierarchy, and user-facing copy while preserving place search, visit-duration editing, day planning, Google Maps links, saved routes, privacy controls, isolation, and stale-button protection. It adds no hosting, web interface, external service, or new trip-planning capability.

## Main journey

`/start` opens a new selection and asks for a city or district immediately. Each view starts with one short instruction describing the required action.

After geography confirmation, the user selects one or more interests and opens the place list. Place cards retain the name, address or district, categories, short description, estimated visit duration, selection state, and required attribution. Controls use action-oriented labels and show only actions valid for the current step.

`Подтвердить места` validates a non-empty selection and moves directly to the trip-date prompt. The separate confirmed-summary screen is removed. `Назад к местам` remains available during day setup so the selection and edited durations can be reviewed without starting over.

After the date, the bot asks for a start location and requires confirmation of the matched Google place. The user then reaches one readiness screen with visible defaults:

- day time: 10:00–20:00;
- finish: at the last visited place;
- total walking limit: 90 minutes;
- lunch: none.

The primary action is `Построить маршрут`. `Изменить настройки дня` opens the existing detailed controls for start/end time, finish, walking limit, and lunch. Returning from detailed settings restores the readiness screen with the chosen values. The user can also return to the place list.

The result prioritizes the ordered schedule, visit and travel totals, important warnings, and the Google Maps button. Secondary technical detail is available through transition-detail buttons. Main actions are `Изменить`, `Мои маршруты`, and `Новый подбор`. A failed Routes calculation keeps the approved stage 3.1 fallback link in selection order and explains that Google Maps, rather than the bot, will calculate that route.

## Copy and information hierarchy

Real-mode screens use one compact source line: `Места: Google Maps • время посещения: оценка бота`. Required third-party attributions and links remain adjacent to the corresponding place data. Repeated descriptions of the rectangular search area, result limits, policy links, API behavior, and implementation details are removed from the main journey.

A new `/about` command explains the Google Maps data source, application-owned duration estimates, rectangular search area, result limit, route recalculation, storage behavior, and points users to `/terms` and `/privacy`. Legal commands and Google attribution remain accessible; the shorter journey does not weaken required disclosure.

Instructions and validation errors use direct language: what to enter, accepted format where needed, and the next available recovery action. Waiting states state that the request is in progress and repeated input is unnecessary. User-facing text does not mention internal sessions, fingerprints, budgets, databases, or APIs unless the API failure itself affects the next action.

## Dialog and state changes

The dialog keeps the same transport/source/repository boundaries. State gains only the minimum navigation data needed to distinguish the compact default path from detailed settings. Default day parameters are created after date selection. Start confirmation leads to readiness instead of forcing finish, walking, and lunch questions.

Detailed settings reuse existing validation and domain models. Their order is start time, end time, finish, walking limit, and optional lunch. Every detailed-settings screen offers a safe return where the current values are valid. Changes invalidate an existing plan but do not clear selected places or visit durations.

Old callback tokens remain revision-scoped. `/start` still creates a fresh selection; `/resume` renders the current step; `/routes` and saved-route browsing preserve the active selection. Group-chat rejection and per-chat/per-user isolation remain unchanged.

## Error handling

Invalid text keeps the user on the same step and provides one concrete example. An empty interest or place selection cannot advance. Search and planning failures preserve completed input and show the relevant retry, edit, or Google Maps fallback action. A stale button produces a short prompt to use the current screen through `/resume`. Telegram edit/send failures continue to fall back safely without exposing exception content.

## Testing and acceptance

Tests are updated before production changes. They cover the shortened happy path, immediate transition from place confirmation to date, 10:00–20:00 defaults, readiness after start confirmation, detailed-setting edits, back navigation, concise source copy, `/about`, action hierarchy, successful and fallback map links, invalid input recovery, stale buttons, restart behavior, and user/chat isolation.

Existing place, planner, repository, saved-route, privacy, and transport tests remain green. Final verification runs the complete unit suite, dependency check, diff check, and secret scan without live Telegram or paid Google requests. Manual Telegram verification remains a separate later activity.
