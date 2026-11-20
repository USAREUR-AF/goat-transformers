None. `Gpgga` and `Gprmc` give latitude and longitude in decimal degrees, but the
.msg files name no datum, and `Gpgga`'s `alt` and `undulation` state no reference
surface. Without a stated datum the fields are not bound
to `lat` and `lon`; every field is a raw key of module `ros2nmea`. `Sentence` carries
the raw NMEA text.
