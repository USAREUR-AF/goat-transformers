# homeassistant-ws-state-changed

A message of the Home Assistant websocket API carrying a `state_changed` event, as
`subscribe_events` sends it: `{"id": <subscription id>, "type": "event", "event": <Event.as_dict()>}`.
The event's `data` holds `entity_id`, `old_state` and `new_state`, each a state object (pack
`homeassistant-state`) or `null`. Licence Apache-2.0.

## Kind

One kind, `state_changed`, selected by `type` = `event` and `event.event_type` = `state_changed`.
Any other event is `no-kind`.

## Shared keys

Those of `homeassistant-state`, read from `event.data.new_state`: `uid`, `lat`, `lon`, `callsign`
and `time_ms` (its `last_updated`). The evidence is the same.

## Raw keys

The message id, the event's entity id, `old_state.state` and `old_state.last_updated` (text), the
new state's raw keys, the event's `origin`, `time_fired` (text) and context ids. The rest of
`old_state` is residue.

## Not mapped

- The compressed state messages of `subscribe_entities` (`a`, `c`, `r` with short member names)
  are a different message; not built.
- `null` members are not carried; arrays inside attributes are not carried.
