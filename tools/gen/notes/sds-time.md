## `time_ms` in this pack

This standard has a member of its root table that the schema describes as an integer of
Unix milliseconds and as the time the record is valid at, or the time the record (or the
set, snapshot, page or report it is) was produced, generated, serialized or read. That
member is bound to `time_ms` as a plain `int`: the same unit, milliseconds since
1970-01-01 00:00:00 UTC, so no transform is needed. The table "Mapped to shared keys"
quotes the description. This replaces, for this pack, the `time_ms` item under "Not bound"
above, which is about the epochs written as text. Other millisecond members of the record
(creation and update times of an entry, expiry, request and window times) are raw keys.
