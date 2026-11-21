# shelly-notify-status

A notification a Shelly Gen2 or Gen3 device sends when a component's status changes
(`NotifyStatus`, the changed members only) or on connection (`NotifyFullStatus`, every
component). Licence `LicenseRef-unstated`: the documentation states no licence.

## Message convention

One JSON-RPC 2.0 notification frame (no `id`): `src` (the sender, for a device its device id),
`dst` (the client the frame goes to), `method`, and `params`, which holds `ts` (the time of the
notification as Unix seconds, a number with a fraction) and one status object per component.
Two kinds, selected by `method`: `notify_status` and `notify_full_status`. The same frame comes
over WebSocket, outbound WebSocket and MQTT (topic `<device id>/events/rpc`), and from sleeping
battery devices also over outbound UDP.

## Components

A status object is keyed by its component key, the type and the instance id joined by `:`. Mapped:

| Key | Members |
|---|---|
| `switch:0` to `switch:3` | `id`; `source` and `tag` of the last change; `output` (boolean); the timer (`timer_started_at`, Unix seconds; `timer_duration`, s; `timer_type`); on metering models `apower` (W), `voltage` (V), `current` (A), `pf`, `freq` (Hz), `aenergy.total` and `ret_aenergy.total` (Wh) with their `minute_ts` (Unix seconds); `temperature.tC` and `.tF` |
| `cover:0`, `cover:1` | `id`, `source`, `tag`, `state` (text: open, closed, opening, closing, stopped, calibrating), the metering members as for a switch, `current_pos` and `target_pos` (percent open), `move_timeout` (s), `move_started_at` (Unix seconds), `pos_control` (boolean), `last_direction`, `temperature`, `slat_pos` (percent) |
| `input:0` to `input:3` | `id`; `state` (boolean, switch and button inputs); `percent` and `xpercent` (analog inputs); `counts.total`, `counts.xtotal`, `counts.minute_ts`, `freq`, `xfreq` (count inputs) |
| `temperature:0`, `temperature:100` to `temperature:104` | `id`, `tC`, `tF` (the add-on sensors are numbered from 100) |
| `sys` | `mac`; `restart_required`; `time` (local HH:MM); `unixtime`, `last_sync_ts` (Unix seconds); `uptime` (s); RAM and file system size and free (bytes); the configuration, KVS, schedule and webhook revisions; `available_updates.stable.version` and `.beta.version`; on battery devices `wakeup_reason.boot`, `.cause` and `wakeup_period` (s); `utc_offset` (s) |

Keys are `shelly.<type><id>_<member>`, with `.` in a member path written `_` and in lower case
(`shelly.switch0_aenergy_total`, `shelly.temperature100_tc`).

## Shared keys

| Member | Key | Evidence (Shelly API documentation, in this repository's words) |
|---|---|---|
| `params.ts` | `time_ms` | the notification page gives `ts` as a Unix timestamp in UTC, a number; `time_ms` is epoch milliseconds UTC. Bound through `iscale:1000`: decode rounds to the millisecond (half away from zero), encode writes the exact seconds with no trailing zero |

## Raw keys

`src`, `dst` and the component members above, under module `shelly`.

## Not mapped, and why

- Other components (`cloud`, `mqtt`, `wifi`, `ble`, `eth`, `ws`, `light:<n>`, `pm1:<n>`, `em:<n>`,
  `script:<n>` and the rest) and higher instance ids are residue: a same-format round trip keeps
  their scalar members after the mapped ones; a conversion does not.
- Arrays are not carried: `aenergy.by_minute`, `counts.by_minute`, `errors`, `flags`. A round
  trip drops them.
- A `null` member (for example `target_pos` while a cover is idle, an input's `state` when it is
  not a switch input, `sys.time` before the clock is set) is absent, and is not written back.
- An object that has no members left (`available_updates` with no update, `ble`) is not written.
- Members whose name contains `.` cannot be addressed and are dropped (none are known).

- `src` is not bound to core `uid`: it is the device id here, but in a request it is the client's
  name, and a stable identity of a tracked entity is not what a home device is.
