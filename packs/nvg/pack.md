# Pack: nvg

NVG (NATO Vector Graphics) — NATO's XML format for tactical overlays and the
operational picture. This pack maps an NVG `<point>`: `x` (longitude), `y`
(latitude), `label`, and `symbol` (the APP-6 / MIL-STD-2525 symbol code) to the
shared model, so an NVG point converts to and from CoT and GeoJSON. Public
standard (NVG 1.5, NATO ACT). Only the point's confirmed attributes are mapped;
the other geometry types and attributes are added from the NVG 1.5 schema. The
`symbol` code passes through as the model `type` until an APP-6-to-CoT type map
is added.
