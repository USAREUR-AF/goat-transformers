# Pack: nvg

NVG (NATO Vector Graphics) — NATO's XML format for tactical overlays and the
operational picture. This pack maps an NVG `<point>`: `x` (longitude), `y`
(latitude), `label`, and `symbol` (the APP-6 / MIL-STD-2525 symbol code, kept raw) to the
shared model, so an NVG point converts to and from CoT and GeoJSON. Public
standard (NVG 1.5, NATO ACT). Only the point's confirmed attributes are mapped;
the other geometry types and attributes are added from the NVG 1.5 schema. The
`symbol` code is the raw key `nvg.symbol` (model/nvg.def). It is not the shared
`type`, which is a CoT type token (model/core.def): an APP-6 code there would reach
CoT as an event type no CoT reader knows. Converted to CoT, an NVG point gets the
cot-xml default type `a-u-X`; an APP-6-to-CoT type map would be a derive, not yet
written.
