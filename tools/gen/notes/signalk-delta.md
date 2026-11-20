## Notes

A delta carries `updates`, each with a `values` list of path and value pairs. The value's
type depends on the path (a number, a string, an object such as a position), so the
schema states no type for it: `value` is not mapped, and no shared key is bound. The
position of a vessel in a delta is the value whose path is `navigation.position`; the
pack language cannot select a group item by the value of another member of the item and
bind its members to a shared key. `signalk-vessel` maps the position of the full model.
