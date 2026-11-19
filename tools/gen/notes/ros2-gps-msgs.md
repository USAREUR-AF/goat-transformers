None. `GPSFix.msg` gives latitude and longitude in degrees but names no datum, and
says altitude is "above reference (e.g., sea level)", which is not the WGS 84
ellipsoid. `track` is "degrees from north" with no statement of true or magnetic
north. The `GPSDRaw*` messages mirror gpsd's report structure (`fix_latitude`,
`fix_alt_hae` and the like) with no unit or datum stated in the .msg files. The
instruction is to bind a position only where WGS 84 is stated, so every field is a
raw key of module `ros2gps`. A reader who knows the receiver reports WGS 84 can
pass `lat`/`lon` as context, or bind them in an overlay.
