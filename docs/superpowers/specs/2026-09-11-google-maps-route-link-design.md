# Google Maps Route Link Design

## Scope

Add a Google Maps Directions URL to a successfully calculated day plan. If Routes API calculation fails, provide a best-effort URL using the user's selection order and explicitly state that the bot did not calculate a route or schedule. Google Maps recalculates the path and may produce travel modes and times that differ from the bot. No web map, hosting, short links, API key in the URL, or additional Google API calls are included.

## Interface and data flow

`travel_bot/route_map.py` is a pure component with no Telegram, network, environment, or Google client dependency. It accepts the confirmed start endpoint, optional finish endpoint, calculated `DayPlan`, and current places. It returns an immutable result containing a URL and optional mobile waypoint warning, or raises a typed presentation error.

The component maps `DayPlan.stops` to `Place` values by stable place ID and preserves stop order. The confirmed start is `origin`. With a separate finish, every visited place is a waypoint and the finish is `destination`; without one, the final visited place is `destination` and preceding places are waypoints. `travelmode` is omitted. Coordinates are the textual location value; supported Google Place IDs are paired using the official `origin_place_id`, `destination_place_id`, and `waypoint_place_ids` parameters.

The dialog invokes this pure component while rendering an existing plan or a confirmed selection after a failed calculation. A successful plan shows `Открыть маршрут в Google Maps`; a failed calculation shows `Открыть выбранные места в Google Maps` and explains that the points follow selection order. Both paths warn when there are more than three waypoints. Generation never mutates or removes the selection or plan.

## Validation, errors, and security

The exporter requires at least two geographically defined points and rejects missing stop mappings or coordinates. The encoded URL must not exceed 2048 characters; it is never truncated. A presentation failure hides the button and explains that the map link is unavailable while leaving the schedule intact.

Only route coordinates and Google Place IDs are exported. API keys, Telegram identifiers, usernames, session IDs, and internal callback values are not inputs. Standard URL encoding is used. No migration or stored data change is required.

## Testing and documentation

Network-free unit tests cover separate/implicit finish, order, Unicode encoding, Place ID pairing, privacy, fewer than two points, 2048-character rejection, and the mobile waypoint warning. Dialog tests cover the button, recalculation notice, and recoverable failure. README documents that Google Maps may recalculate the route and may ignore some waypoints, especially beyond three on mobile clients.
