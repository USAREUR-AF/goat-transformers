//go:build !goat_wires || goat_wire_tlv

package goatxf

// The tlv wire is in this build (spec/engine-spec.md, Version 0.24): without
// the tag goat_wires, or with the tag goat_wire_tlv.
func init() {
	registerWire(WireTLV, &wireCodec{
		decode: decodeTLV,
		encode: encodeTLV,
	})
}
