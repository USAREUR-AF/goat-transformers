
## The map

The envelope is Apollo's HD map, `apollo.hdmap.Map`: the lanes, roads, junctions, crosswalks,
signals and other features of a map, as Apollo stores it in a map file rather than on a channel.
Geometry is in the map frame (`PointENU`); the projection of that frame is a text in the map's
header, which the pack carries as a raw key and does not apply. The header's `bytes` fields
(version, date, district and others) are not carried. The walk stops at path depth 6.
