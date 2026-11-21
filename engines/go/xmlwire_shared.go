package goatxf

// The declarations of xmlwire.go that the pack loader, the transforms or
// another wire use: they are in every build, whatever its set of wires
// (spec/engine-spec.md, Version 0.24).

// maxNesting is the deepest nesting a message may have: elements on xml (the
// root is level 1), arrays and objects on json and geojson (the outermost is
// level 1). A deeper message is malformed-wire (0.8 ruling 35).
const maxNesting = 64
