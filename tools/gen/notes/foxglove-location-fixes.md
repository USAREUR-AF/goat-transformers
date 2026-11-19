## What the message is

The pack's message is one `foxglove.LocationFixes`: a list of `LocationFix` messages (field 1), as
the Foxglove schema of that name groups several fixes in one message on a channel. Each fix is an
item of the list `foxglove.location_fixes_fixes`.

## Everything raw

A key of an item is never a shared key (engine-spec 0.7), so the latitude, longitude and velocity
of each fix are raw keys of module `foxglove` here, and the pack converts to no other format. To
convert one fix, take it out of the list and use `foxglove-location-fix`, which binds `lat`,
`lon` and the velocity (see its `pack.md` for the evidence and the inference about the datum).
The item keys are named by message type, so every list of `LocationFix` in module `foxglove`
holds the same keys. They are not the keys of `foxglove-location-fix`: those name the fields of a
fix that is the whole message, and a module key keeps one meaning, so where that pack's name is
already taken the item key carries the field number (`foxglove.location_fix_latitude_at_1`).
