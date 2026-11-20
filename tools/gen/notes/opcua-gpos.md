## Notes

The GPOS companion specification (global positioning) gives a geographic coordinate as a
longitude, a latitude and an optional elevation, but states that each is read in the coordinate
reference system and elevation reference that the server names in separate properties; the
structure itself states no datum and no unit. The fields therefore stay raw keys of module
`opcuagpos` and are not bound to core `lat`, `lon` or `hae`. A pack that bound them would claim
WGS 84 degrees for a value that may be in any reference system.

The GPOS structures use two structures of namespace 0 (`3DCartesianCoordinates` and
`3DOrientation`); their fields are laid out inline under the GPOS key names.
