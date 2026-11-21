# shelly-notify-event

A notification a Shelly Gen2 or Gen3 device sends for events that are not status changes: button
pushes of an input, scheduled restarts, OTA progress, script events. Licence
`LicenseRef-unstated`: the documentation states no licence.

## Message convention

One JSON-RPC 2.0 notification frame: `src`, `dst`, `method` `NotifyEvent`, and `params` with
`ts` (Unix seconds, with a fraction) and `events`, an array of event objects. Each event has
`component` (the component key, `input:0`, `sys`), `id` (the instance id; absent for `sys`),
`event` (the event name, for example `single_push`, `double_push`, `long_push`,
`scheduled_restart`) and `ts`. One kind, `notify_event`.

## Shared keys

| Member | Key | Evidence (Shelly API documentation, in this repository's words) |
|---|---|---|
| `params.ts` | `time_ms` | the notification page gives `ts` as a Unix timestamp in UTC, a number; `time_ms` is epoch milliseconds UTC, through `iscale:1000` |

## Raw keys

`src`, `dst`, and the list `shelly.events` with the item keys `shelly.event_component`,
`shelly.event_id`, `shelly.event_name` and `shelly.event_time_ms` (the event's `ts`, epoch
milliseconds through `iscale:1000`; a raw key, as core `time_ms` is a scalar of the entity).

## Not mapped, and why

- Members of an event beyond the four above (`time_ms` of a scheduled restart, `progress_percent`
  of an update, `data` of a script event, `msg`) are dropped: group items carry no residue.
- Frames with another method are not of this format (`no-kind`).
