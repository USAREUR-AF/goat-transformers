## The form: Zeek JSON with the scope separator "_"

One message is one record of one Zeek log written as JSON (`LogAscii::use_json`, or
`policy/tuning/json-logs`), with the scope separator set to an underscore:

    redef Log::default_scope_sep = "_";

Zeek flattens a record field into its parent with the scope separator between the names:
the connection's originator address, field `orig_h` of record `id`, is the member `id_orig_h`.

**Zeek's default output does not decode.** By default the separator is `.` and the member is
`id.orig_h`. The `json` wire addresses nested members by a path whose steps are separated by
`.`, and a member name that itself contains `.` cannot be addressed (engine-spec 0.5, the
json wire). Such a member is not even carried back unchanged as residue: residue is keyed by
path, and the path `id.orig_h` is written as a nested object. A record of the default output
therefore decodes with those fields unread and does not round-trip. A pack for the default
needs a way to write a `.` inside one member name in a json path (routed to the pack-language
leads).

Timestamps (`ts`) are epoch seconds as a JSON number with microseconds (the default
`LogAscii::json_timestamps`). Fields that other scripts add to a log by `redef record Info +=`
(for example `community_id`) are not in these packs; their scalars are residue.

## Shared keys
