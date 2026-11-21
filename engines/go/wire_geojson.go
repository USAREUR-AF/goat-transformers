//go:build !goat_wires || goat_wire_geojson

package goatxf

// The geojson wire is in this build (spec/engine-spec.md, Version 0.24): without
// the tag goat_wires, or with the tag goat_wire_geojson.
func init() {
	registerWire(WireGeoJSON, &wireCodec{
		decode: decodeGeoJSON,
		encode: encodeGeoJSON,
	})
}
