## Shared keys

None is bound, on purpose:

- Positions of the source on the sky (`ra`, `dec`, from the core Localization schema) are
  celestial coordinates, not a place on the Earth.
- The spacecraft position of the core GeoLocBase schema (`latitude`, `longitude`) is
  geocentric latitude in degrees; `lat` is geodetic WGS 84. The two differ by up to about
  0.19 degree, and the schema states no ellipsoid. `altitude` is in kilometres above the
  surface with no stated reference.
- `alert_datetime` is when the notice was created and `trigger_time` when the event was
  seen; neither is stated as the time the report is valid, which is what `time_ms` means.
  Both are kept as text in their raw keys.

So no conversion vector to geojson or cot-xml is written.

## Notes

The mission schemas compose the core schemas with `allOf`; the members of every branch
are merged by name. A notice that allows members beyond the named ones carries them as
residue when they are scalars in objects.
