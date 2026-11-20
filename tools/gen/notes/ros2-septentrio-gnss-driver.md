None. `PVTGeodetic` and `INSNavGeod` carry a geodetic position, but in radians, and
with a `datum` field that names the datum of each solution, so no one binding holds
for every message. The json `scale` transform would turn radians into degrees only
through an approximate factor (180/pi is not a fraction), and the datum would still
vary. Every field is a raw key of module `ros2septentrio`.

The package builds its messages from `msg/`, except `BlockHeader`, which ROS 2 takes
from `msg_ros2/msg/`. The two `BlockHeader.msg` files differ only in default values
(the ROS 2 one gives defaults for the sync bytes, time of week and week number). This
pack reads `msg/BlockHeader.msg`; defaults are not written in any case (see below),
so the fields and the pack are the same.
