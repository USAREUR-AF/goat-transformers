# tasmota-state

The object Tasmota publishes on `tele/<topic>/STATE` at each telemetry period, and as the answer
to the `State` command. Licence Apache-2.0 (a layout restated from GPL-3.0 firmware, no code
copied).

## Message convention

One JSON object. `Time` (local time, ISO 8601 without zone by default), `Uptime` (text, days `T` hh:mm:ss)
and `UptimeSec` (seconds); then, as the device has them, the battery level and supply voltage of
deep-sleep builds, free heap (kB), the sleep mode and sleep time (ms), the loop load average and
the MQTT connection count; one power state per relay, `POWER` when the device has one relay and
`POWER1` to `POWER8` when it has several, each the text `ON` or `OFF`; `FanSpeed` on fan modules;
and a `Wifi` object (access point index, SSID, BSSID, channel, PHY mode, quality in percent,
signal in dBm, connection count, accumulated downtime as text), present while Wi-Fi is up; last,
`Hostname` and `IPAddress` of the connection in use (Wi-Fi, or Ethernet on ESP32 builds that have
it).

## Shared keys

None. `Time` is, with the default settings, the device's local time with no zone
(ResponseAppendTime, `support.ino`; `support_rtc.ino`), so it is not core `time_ms`, which is UTC;
it is the raw key `tasmota.time_local`, kept as text. Settings change it: SetOption52 appends the
zone offset (kept in the same text), TimeStamp 1 adds an `Epoch` member (UTC seconds, residue),
TimeStamp 3 adds milliseconds, and TimeStamp 2 makes `Time` a number of UTC epoch seconds, which
this `string` line does not read.

## Raw keys

Every member named above, under module `tasmota`, with the JSON type the firmware writes.

## Not mapped, and why

- Members that only some builds write (`Berry`, `Dimmer`, `Color`, `HSBColor`, `Channel`, `Fade`,
  `Speed` and others) are residue: they come back after the
  mapped members, in input order.
- Arrays (the `Channel` list of light modules) are not carried; the json wire carries no array
  outside a group.
- Relays beyond 8 (`POWER9` and up, possible on ESP32 builds) are residue.
