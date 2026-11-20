## SUMO in this pack

Eclipse SUMO (Simulation of Urban MObility) writes and reads one XML file type per
purpose: the simulation outputs (floating car data, trip information, emissions, detector
measurements and the rest) and the network and demand inputs (networks, routes, additional
infrastructure, plain nodes and edges). One message is one whole file of one type: its root
element, the time steps or intervals below it, and the vehicles, lanes or detectors of
each. Forty-one packs are generated from the schemas of SUMO 1.28.0, one per file type
(`tools/gen/sumo-run.sh`). The schemas declare no target namespace, so the elements are in
no namespace and a document needs no `xmlns`.

**No shared key is bound.** Every vehicle, person, lane, detector interval or trip of these
files is an item of a list: an fcd file holds many time steps and each step many vehicles.
A shared key (`uid`, `lat`, `lon`, `time_ms`, `speed_ms`, `course`) is bound only outside
lists, as one value per message, so each one stays a raw key of the item it belongs to.
What the SUMO documentation states for them, read for this pack:

- fcd output: `x` and `y` are the position of the vehicle's front bumper in metres in the
  network's projection; with the run option `--fcd-output.geo` the same two attributes
  hold WGS 84 longitude and latitude instead. The file does not say which of the two it
  holds, so even outside a list `x` and `y` could not be bound to `lon` and `lat`. `angle`
  is the heading in degrees clockwise from north, `speed` is in metres per second, and the
  time step's `time` is simulation seconds, not a time of day.
- vehicle type probe output: `lat` and `lon` are stated in degrees times 100000, and `x`
  and `y` in metres.

**Numbers kept as text.** The schemas restrict most numbers (`floatType`, `timeType` and
their variants) to a pattern on `xs:string` that also admits `inf` and, for times, a
`d:h:m:s` form, so those attributes are `string` lines and keep the file's spelling.

Lists of different element names that a file may interleave (the members of a repeated
choice, such as the trips, persons and containers of a trip information file) are read
name by name; an encoder writes all items of one name, then the next name's, so a file
that mixes them comes back grouped by name.
