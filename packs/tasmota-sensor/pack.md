# tasmota-sensor

The object Tasmota publishes on `tele/<topic>/SENSOR` at each telemetry period: one member per
sensor, named by the sensor type, and the units. This pack maps the energy monitor and four common
climate sensors. Licence Apache-2.0 (a layout restated from GPL-3.0 firmware, no code copied).

## Message convention

One JSON object: `Time` (local time, ISO 8601 without zone by default), then one object per attached sensor,
named by its type, then, when a pressure sensor is attached, `PressureUnit` (`hPa` or `mmHg`),
then `TempUnit` (`C` or `F`), in the order MqttAppendSensorUnits writes them.

- `ENERGY` (energy monitoring builds): the start of the total counter (local time text), total
  energy, yesterday's and today's energy (kWh), energy in the last telemetry period (Wh), active,
  apparent and reactive power (W, VA, var), power factor, frequency (Hz, only from meters that
  measure it), voltage (V), current (A).
- `DS18B20`: one sensor; `DS18B20-1` to `DS18B20-4` when several are on the bus (the firmware
  numbers them from 1, with `-` as the separator unless an option sets `_`; another option names
  them by address instead). Each has `Id` (the ROM address in hexadecimal text) and `Temperature`.
- `BME280`: temperature, humidity (percent), dew point, pressure and, when an altitude is set,
  pressure at sea level. `BMP280`: the same without humidity and dew point.
- `AM2301`: the name Tasmota gives a DHT21, DHT22, AM2301, AM2302 or AM2321 on the DHT22 GPIO
  type; temperature, humidity, dew point (heat index only in builds with USE_HEAT_INDEX). With
  more than one DHT the name gains a separator and the pin, which this pack does not read.

Temperatures and dew points are in `TempUnit`; pressures in `PressureUnit`.

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

- Members are named by sensor type, and Tasmota supports well over a hundred sensors. The pack
  language addresses a member by a fixed name; it has no locator for "every member whose name
  matches", so every sensor type needs its own lines. Only the types above are mapped; any other
  sensor object (for example `SHT3X`, `SI7021`, `DS18B20-5` and up, `DS18B20_1` under the `_` separator,
  `BME280-77` when two BME280 share a bus and are named by address) is residue and comes back after the mapped members. This is a gap of the pack
  language, reported as a candidate addition (a field whose member name is a pattern).
- Multi-phase energy meters write `Voltage`, `Current`, `Power` and the other per-phase values as
  arrays, one element per phase. A float field cannot read an array, so such a message fails with
  `transform-decode`; a path cannot be a scalar in one message and a group in another. Reported as
  a candidate addition.
- `ENERGY.Today` and the others are as the device computes them over its local day.
