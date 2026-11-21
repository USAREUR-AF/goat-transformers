# tasmota-result

The object Tasmota publishes on `stat/<topic>/RESULT` as the answer to a command. This pack maps
the power states, the answer to `Power`, `Power<n>` and the button and rule actions that switch a
relay. Licence Apache-2.0 (a layout restated from GPL-3.0 firmware, no code copied).

## Message convention

One JSON object whose members are those of the command answered. After a power command, the relay
states: `POWER` on a one-relay device, `POWER<n>` on others, each `ON` or `OFF`.

## Shared keys

None.

## Raw keys

`POWER` and `POWER1` to `POWER8` under module `tasmota` (the same keys tasmota-state maps, so a
RESULT converts to a STATE carrying the relay states).

## Not mapped, and why

- The answers of other commands (hundreds of commands, each with its own members) are residue: a
  same-format round trip keeps them; a conversion does not.
