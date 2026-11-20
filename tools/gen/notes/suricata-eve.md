## The form

One message is one EVE JSON record as Suricata writes it to `eve.json`: one JSON object
per line, with `timestamp`, `event_type`, the flow's address tuple and one member object
named after the event type. The pack has one kind per event type it maps (`alert`, `flow`,
`dns`, `http`, `tls`, `fileinfo`, `anomaly`, `stats`), chosen by `event_type`. The kinds
are cut from the one EVE schema by `tools/gen/suricata-eve-schemas.py`: each holds the
top-level scalar members and its own member object (an alert also its `flow` object).
Member objects of other event types inside a record are residue (their scalars) or not
carried (their arrays).

## Shared keys

None.

- `time_ms` is not bound. Suricata writes `timestamp` as an ISO 8601 date and time with
  microseconds and an offset written without a colon (`2023-09-18T06:13:41.532140+0000`,
  the form `doc/userguide/output/eve/eve-json-format.rst` shows), and `iso8601_ms` refuses
  an offset without its colon (ruling 3a of 0.11). The text is the raw key
  `suricataeve.timestamp`.
- `uid` is not bound: `flow_id` is a number, and `community_id` names a flow, not one
  record.
- Addresses and ports are network endpoints, not positions.

## Licence

Suricata and its documentation are GPL-2.0. The pack restates the layout the schema
states, with no code copied, and is Apache-2.0 (rule of the repository's licensing model).
