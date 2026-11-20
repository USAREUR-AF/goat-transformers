# signalk-delta

The Signal K delta message: how a server streams changes over WebSocket, and how a source sends
them to a server. Licence: CC-BY-SA-2.0 (share-alike), profile `open+copyleft`; see
PROVENANCE.md.

## Message convention

The message is one delta object: a `context` (the path of the object the updates belong to, for
example `vessels.urn:mrn:signalk:uuid:...`) and an array `updates`. Each update has either a
`$source` reference or a `source` object, a `timestamp`, and a `values` array of path/value pairs
and/or a `meta` array of path/meta pairs.

## What is mapped

All raw keys of module `signalk`: the context; for each update its `$source`, the `label`,
`type`, `src`, `pgn`, `sentence` and `talker` of its `source` object and its timestamp (raw text);
for each value and meta entry its path. No member binds a shared key.

## Not mapped, and why

- **The value of a pair.** Its JSON type depends on its path: a number for
  `navigation.speedOverGround`, an object for `navigation.position`, a string for
  `navigation.state`. A `json` transform reads one JSON type and fails the whole decode on
  another, so `value` has no line, and items carry no residue (engine-spec 0.7): a round trip keeps
  the paths and drops the values.
- **Binding a pair to a shared key** (the position of a `navigation.position` pair to `lat` and
  `lon`, `navigation.speedOverGround` to `speed_ms`) needs an item to be selected by the value of
  a sibling member (`path`), which the language has no way to state.

Both are named as missing pack-language features: a `json` value that keeps any scalar or object
as it is, and a group whose items are selected, or bound to keys, by the text of a member. Until
then the `signalk-vessel` pack is the one that carries positions.
