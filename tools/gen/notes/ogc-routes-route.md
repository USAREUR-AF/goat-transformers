## What is not carried

A route of the Route Exchange Model: a GeoJSON feature collection whose features are the
overview (a LineString), the start, the end, intermediate waypoints and segments. It is read
on the json wire, where the three feature schemas are merged into one item shape; no shared
key is bound (a route is many positions). The coordinates (numbers for a Point, arrays for
the overview LineString) and `id` (number or string) are not mapped. Read one start, end or
waypoint with `ogc-routes-waypoint`, one segment with `ogc-routes-segment`.
