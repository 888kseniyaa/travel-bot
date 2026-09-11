# Saved Routes Design

## Scope and agreed behavior

Stage 4 persists successfully calculated routes across bot restarts. Users open them through a `Мои маршруты` button on the start and final screens or `/routes`. The current in-memory selection remains intact while browsing saved routes. A saved route is read-only; a later calculation creates a separate record.

Routes are saved automatically and idempotently after a successful calculation. Each user may keep at most 20 records. Records older than 30 days are deleted before list and save operations. The initial title is the route date plus the original geography text supplied by the user; users can rename it. MVP actions are open, rename, and delete. There is no sharing or export beyond the existing Google Maps button. `/delete_my_data` deletes all saved routes after confirmation.

## Policy boundary and persisted data

Current Google policies generally prohibit storing Places and Routes content except documented allowances. Place IDs may be stored; Places/Routes latitude and longitude may be cached for up to 30 consecutive days. The implementation therefore does not persist Google place names, formatted addresses, opening hours, raw API responses, transit steps, or raw route results. References:

- https://developers.google.com/maps/documentation/places/web-service/policies
- https://developers.google.com/maps/documentation/routes/policies
- https://cloud.google.com/maps-platform/terms/maps-service-terms

The record stores only a random route ID, Telegram owner user ID, format/version metadata, user-owned title and original queries, user-entered day parameters and visit durations, place IDs, categories needed by the app, final place ordering, application exclusion reason codes, and start/finish Place IDs. Coordinates required to re-open the route may be cached only until the record expires at 30 days. No username, token, API key, callback payload, full Google response, or unrelated personal data is stored.

Opening a record retrieves current Google place names, addresses, hours, and coordinates by Place ID, then revalidates transitions in the saved order. It does not optimize a new order or overwrite the stored record. The refreshed display may differ from the original calculation and states this explicitly. If refresh fails, the title and user-owned parameters remain visible and the record remains retryable.

## Architecture

`saved_routes.py` contains immutable versioned payload and summary models, strict JSON conversion, title normalization, stable calculation fingerprints, and expiration constants. It has no SQLite, Telegram, or network dependency.

`route_repository.py` owns SQLite connections, schema migrations, transactions, owner-scoped CRUD, idempotent insert, pagination, the 20-record limit, and 30-day cleanup. SQL always binds values. Repository methods require `owner_user_id`; update/delete also require record version for optimistic concurrency.

`saved_route_service.py` converts a completed selection to the permitted payload, coordinates repository operations, refreshes current Google content, and asks the existing planning layer to validate the fixed saved order. Database errors are converted to fixed user-safe errors and never invalidate the in-memory plan.

`saved_route_flow.py` owns saved-route Telegram state transitions and presentation. The existing `Dialog` remains responsible for trip selection and planning. The adapter adds `/routes` and `/delete_my_data`, one cancellable saved-route refresh task per `(chat_id, user_id)`, and automatic save after calculation. Opening and closing the saved-route browser preserves the previous selection stage and values.

`Settings` adds `ROUTES_DB_PATH`, defaulting to `data/routes.sqlite3`. Startup creates the parent directory and runs migrations before polling. Shutdown closes repository resources. The database, WAL, and shared-memory files are ignored by Git.

## Schema and migrations

Migration 1 creates:

- `schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)`;
- `saved_routes(id TEXT PRIMARY KEY, owner_user_id INTEGER NOT NULL, version INTEGER NOT NULL, name TEXT NOT NULL, geography_query TEXT NOT NULL, fingerprint TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, expires_at TEXT NOT NULL)`;
- a unique index on `(owner_user_id, fingerprint)`;
- indexes on `(owner_user_id, created_at DESC)` and `expires_at`.

Migrations run inside an exclusive transaction. A database with a schema version newer than the application fails startup with a safe message. Payload format version 1 is independently validated so future payload migrations do not require destructive SQL changes.

SQLite uses `foreign_keys=ON`, `busy_timeout`, and WAL. The database path is local configuration, not derived from user input. JSON parsing rejects unknown versions, malformed types, invalid dates/times, excessive strings, invalid coordinates, more than six selected places, and mismatched order IDs. `pickle` is prohibited.

## User flow and failure behavior

The list shows five records per page, newest first. A card shows the user-owned title, route date, parameters, and last refresh time. Opening starts a background refresh and produces the current schedule plus the existing Google Maps URL when successful. A back action returns to the unchanged in-memory selection.

Rename accepts 1–80 characters after whitespace normalization. Delete and `/delete_my_data` require explicit confirmation. Repeated automatic save returns the original record. A repeated delete reports that the record is already absent. Old callbacks include short route ID and record version; the repository checks owner and version again.

At the 20-record limit, auto-save leaves the completed plan in memory and asks the user to delete an old record. It does not evict a non-expired record silently. SQLite failure behaves the same way: planning remains successful, a safe notice is shown, and the user can retry. Google refresh failure never deletes or alters the saved record.

## Security, privacy, and operations

Logs omit route payloads, user-entered text, coordinates, Telegram IDs, SQL arguments, and raw exception text. Telegram user ID is used only as the ownership key and is never sent to Google. Callback values contain only session/revision, random route ID, record version, and action.

Before pilot launch, the owner must update the privacy policy to cover Telegram user ID, user-entered geography/start/finish queries, route parameters, SQLite persistence for up to 30 days, Google refresh on open, and user deletion controls. Stage 5 must provide a persistent disk or migrate the repository implementation to a managed database.

## Testing

Unit tests use temporary SQLite databases and no network. They cover strict payload round-trips, invalid content, clean migration, newer-schema refusal, persistence across repository instances, owner isolation, forbidden cross-owner read/update/delete, 20-record limit, 30-day cleanup, idempotent save, optimistic versions, repeated delete, and database failures.

Service and Telegram tests use fake Places/Routes clients. They cover automatic save after a successful calculation, save failure preserving the plan, `/routes`, button access, pagination, open/current-data refresh in fixed order, rename validation, delete confirmation, `/delete_my_data`, stale callbacks, preservation of the active selection, and no real network. Final verification runs the full suite once, `pip check`, migration smoke tests, and a secret scan excluding the ignored `.env`.
