//go:build !goat_wires || goat_wire_cbor

package goatxf

// The cbor wire is in this build (spec/engine-spec.md, Version 0.24 and 0.28
// ruling 38): without the tag goat_wires, or with the tag goat_wire_cbor.
func init() {
	registerWire(WireCBOR, &wireCodec{
		decode: decodeCBOR,
		encode: encodeCBOR,
	})
}
