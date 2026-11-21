// The wires of this build (engine-spec.md, Version 0.24). The build defines
// GT_WIRE_<NAME> to 1 or 0 for each wire (CMakeLists.txt, option GT_WIRES); a
// wire the build does not name is in it, so a build that names no set has all
// seven. A wire that is 0 leaves its codec out of the library.
#pragma once

#ifndef GT_WIRE_XML
#define GT_WIRE_XML 1
#endif
#ifndef GT_WIRE_GEOJSON
#define GT_WIRE_GEOJSON 1
#endif
#ifndef GT_WIRE_JSON
#define GT_WIRE_JSON 1
#endif
#ifndef GT_WIRE_BITS
#define GT_WIRE_BITS 1
#endif
#ifndef GT_WIRE_PROTOBUF
#define GT_WIRE_PROTOBUF 1
#endif
#ifndef GT_WIRE_TEXT
#define GT_WIRE_TEXT 1
#endif
#ifndef GT_WIRE_TLV
#define GT_WIRE_TLV 1
#endif

// The JSON reader serves the json and geojson codecs; the hex text of a binary
// message serves bits, protobuf and tlv.
#define GT_WIRE_JSON_READER (GT_WIRE_JSON || GT_WIRE_GEOJSON)
#define GT_WIRE_HEX (GT_WIRE_BITS || GT_WIRE_PROTOBUF || GT_WIRE_TLV)
