# shelly-rpc-response

The response frame of a Shelly Gen2 or Gen3 device to an RPC call, with the result as
`Shelly.GetStatus` returns it (one status object per component) or an error. Licence
`LicenseRef-unstated`: the documentation states no licence.

## Message convention

One JSON-RPC 2.0 response frame: `id` (the request's id, a number or text), `src` (the device
id), `dst` (the caller's `src`), and either `result` or `error` (`code`, a negative integer, and
`message`). This pack reads `result` as a status: the component objects, keyed as in a
notification. The result of `<Component>.GetStatus` (one object, not keyed) and of other methods
is residue.

## Components of the result

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

None. A response carries no time.

## Raw keys

`src`, `dst`, the component members above, `error.code` and `error.message`, under module
`shelly`.

## Not mapped, and why

- `id` may be a number or text: one transform cannot read both, so it is residue (kept on a
  round trip, written after the mapped members).

- Other components (`cloud`, `mqtt`, `wifi`, `ble`, `eth`, `ws`, `light:<n>`, `pm1:<n>`, `em:<n>`,
  `script:<n>` and the rest) and higher instance ids are residue: a same-format round trip keeps
  their scalar members after the mapped ones; a conversion does not.
- Arrays are not carried: `aenergy.by_minute`, `counts.by_minute`, `errors`, `flags`. A round
  trip drops them.
- A `null` member (for example `target_pos` while a cover is idle, an input's `state` when it is
  not a switch input, `sys.time` before the clock is set) is absent, and is not written back.
- An object that has no members left (`available_updates` with no update, `ble`) is not written.
- Members whose name contains `.` cannot be addressed and are dropped (none are known).

- The result of a method that is not a status (for example `Switch.Set`, which returns
  `was_on`) is residue.
