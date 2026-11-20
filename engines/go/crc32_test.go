//go:build !goat_wires || goat_wire_tlv

package goatxf

import "testing"

// The two check values of 0.27, "The CRC".
func TestCRC32MPEGCheckValues(t *testing.T) {
	if got := crc32MPEG([]byte("123456789")); got != 0x0376E6E7 {
		t.Errorf("CRC of 123456789 = %08x, want 0376e6e7", got)
	}
	if got := crc32MPEG(nil); got != 0xFFFFFFFF {
		t.Errorf("CRC of no bytes = %08x, want ffffffff", got)
	}
}
