package goatxf

import "testing"

func TestHMSDMYYearRange(t *testing.T) {
	tf, _, err := resolveTextTransform("hms_dmy:2")
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range []struct {
		ms   int64
		ok   bool
		a, b string
	}{
		{3471292800000, false, "", ""},
		{315532799999, false, "", ""},
		{3471292799999, true, "235959.99", "311279"},
		{315532800000, true, "000000.00", "010180"},
	} {
		a, b, err := tf.encode(Value{Kind: KindInt, I: c.ms})
		if (err == nil) != c.ok || a != c.a || b != c.b {
			t.Errorf("%d: got %q %q %v", c.ms, a, b, err)
		}
	}
}
