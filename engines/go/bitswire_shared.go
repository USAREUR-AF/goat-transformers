package goatxf

// The declarations of bitswire.go that the pack loader, the transforms or
// another wire use: they are in every build, whatever its set of wires
// (spec/engine-spec.md, Version 0.24).

import (
	"encoding/hex"
	"strings"
)

// parseHexInput reads the hex text a bits wire takes: whitespace ignored, even
// number of digits (spec/engine-spec.md, "I/O and canonicalisation").
func parseHexInput(format string, b []byte) ([]byte, error) {
	var sb strings.Builder
	for _, c := range b {
		if c == ' ' || c == '\t' || c == '\n' || c == '\r' {
			continue
		}
		sb.WriteByte(c)
	}
	s := sb.String()
	if len(s)%2 != 0 {
		return nil, &Error{Kind: ErrMalformedWire, Format: format, Detail: "hex input has an odd number of digits"}
	}
	out, err := hex.DecodeString(s)
	if err != nil {
		return nil, &Error{Kind: ErrMalformedWire, Format: format, Detail: "input is not hex: " + err.Error()}
	}
	return out, nil
}

// bitAt reads message bit i.
func bitAt(data []byte, i int, o bitOrder) uint64 {
	if o != lsbOrder {
		return uint64(data[i/8]>>uint(7-i%8)) & 1
	}
	return uint64(data[i/8]>>uint(i%8)) & 1
}

// bitOrder is the bit order of a bits pack: where bit i of a word lies, and
// in which order a field's bits make its value.
type bitOrder uint8

const (
	// lsbOrder: bit i is bit i mod 8 of its byte; the first bit is the
	// value's least significant.
	lsbOrder bitOrder = iota
	// msbOrder: bit i is bit 7 - i mod 8 of its byte; the first bit is the
	// value's most significant.
	msbOrder
	// msbLsbOrder: positions as msb, values as lsb (spec 0.22).
	msbLsbOrder
)

// getBits reads length (1..64) bits from message bit start.
func getBits(data []byte, start, length int, o bitOrder) uint64 {
	var v uint64
	for k := 0; k < length; k++ {
		if o == msbOrder {
			v = v<<1 | bitAt(data, start+k, o)
		} else {
			v |= bitAt(data, start+k, o) << uint(k)
		}
	}
	return v
}

// putBits writes the low length (1..64) bits of v at message bit start,
// replacing what is there.
func putBits(data []byte, start, length int, v uint64, o bitOrder) {
	for k := 0; k < length; k++ {
		i := start + k
		var bit byte
		if o == msbOrder {
			bit = byte(v>>uint(length-1-k)) & 1
		} else {
			bit = byte(v>>uint(k)) & 1
		}
		mask := byte(1) << uint(i%8)
		if o != lsbOrder {
			mask = 1 << uint(7-i%8)
		}
		if bit == 1 {
			data[i/8] |= mask
		} else {
			data[i/8] &^= mask
		}
	}
}

// swapBytes reverses the n low bytes of v.
func swapBytes(v uint64, n int) uint64 {
	var out uint64
	for k := 0; k < n; k++ {
		out = out<<8 | (v>>(8*uint(k)))&0xff
	}
	return out
}
