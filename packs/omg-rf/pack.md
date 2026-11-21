# omg-rf

The object OpenMQTTGateway publishes on its RFtoMQTT topic for
one code its RCSwitch receiver decoded. Licence Apache-2.0 (a layout restated from GPL-3.0
firmware, no code copied).

## Message convention

One JSON object: `value` (the code as an unsigned integer), `protocol` (the RCSwitch protocol
number), `length` (bits), `delay` (pulse length in microseconds), `tre_state` (the code as
tri-state text, two bits per character), `binary` (the code as binary text), `raw` (the pulse
timings as comma-separated text, when raw output is on) and `frequency` (MHz, on CC1101
receivers).

## Shared keys

None.

## Raw keys

Every member named above, under module `omg`.

## Not mapped, and why

- `value` is read as a signed 64-bit integer; an RCSwitch code of 64 bits with the top bit set
  does not fit and fails with `transform-decode` (RCSwitch codes are at most 64 bits, usually 24
  to 32).
- Payloads of the other RF decoders the gateway can run (RTL_433, Pilight, RF2) have different
  members; they are not this format.
- `origin`, which the gateway adds before queueing (the topic subject the payload goes to), is
  residue.
