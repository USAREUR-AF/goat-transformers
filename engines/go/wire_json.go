//go:build !goat_wires || goat_wire_json

package goatxf

// The json wire is in this build (spec/engine-spec.md, Version 0.24): without
// the tag goat_wires, or with the tag goat_wire_json.
func init() {
	registerWire(WireJSON, &wireCodec{
		decode: decodeJSONWire,
		encode: encodeJSONWire,
	})
}
