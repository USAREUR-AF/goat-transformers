//go:build !goat_wires || goat_wire_bits

package goatxf

// The bits wire is in this build (spec/engine-spec.md, Version 0.24): without
// the tag goat_wires, or with the tag goat_wire_bits.
func init() {
	registerWire(WireBits, &wireCodec{
		decode:      decodeBits,
		encode:      func(p *Pack, lay *layout, _ *Entity, rec *Item) ([]byte, error) { return encodeBits(p, lay, rec) },
		encodeWhole: encodeSeq,
		encodeRun:   encodeSeqRun,
		runKind:     seqRunKind,
		pickKind: func(p *Pack, ent *Entity) (*seqKind, error) {
			return seqPick(p, p.sbody, ent.Kind, ent.item(), "the entity")
		},
	})
}
