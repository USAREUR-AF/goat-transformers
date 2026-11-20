## The form, and which types are packs

EVerest modules talk over a message bus. An interface (`interfaces/<name>.yaml` of
everest-core) publishes `vars`, each a value of one data type from `types/<file>.yaml`;
an object-typed var is sent as one JSON object. One pack is one such published type, so a
message is one var's JSON value. The types used only as command arguments or results, or
only inside other types, are not packs of their own (they appear nested where they are
used). The bus topic and its envelope are not part of the pack.

`tools/gen/everest2pack.py` reads the types files with the generators' YAML reader. On
every types and interface file of this release it gives the same structure as a full YAML
parser; the two differ only in how line breaks inside some `description` texts are folded,
and no description text reaches a pack. It then points their references (`/<file>#/<Type>`) at the converted documents and
passes the type to `tools/gen/jsonschema2pack.py`.

## Evidence for the shared keys

Bound only where the type's own description gives the meaning (the table above):

- `time_ms`: `Powermeter.timestamp` (the time of the measurement), `EventData.timestamp`
  and `SecurityEvent.timestamp` (the moment the report or event was generated), each a
  `date-time`; `iso8601_ms` converts an offset to UTC.
- `uid`: `Powermeter.meter_id` (the meter's identifier), `SessionEvent.uuid` (the UUID of
  the charging session), `Limits.uuid` (the module's UUID), and in `EnergyFlowRequest` and
  `EnforcedLimits` the UUID of the node of the energy tree.

Not bound: `SessionEvent.timestamp` is described as the session's start time, not the time
of the event; the many other times (departure and full-charge estimates, schedule times)
are forecasts or intervals; EVerest types carry no geographic position.
