"""Load vectors for the 0.28 cbor wire. Run: python3 -I loads.py <worktree>"""
import sys, os, json
WT = sys.argv[1] if len(sys.argv) > 1 else os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
D = os.path.join(WT, "packs/conformance/load-vectors")
CORE = 'module core\nversion 0.1.0\ndistribution public\nsource "probe"\nkey uid string -\nkey lat float deg\nkey lon float deg\nkey time_ms int ms\n'
PROBE = ('module probe\nversion 0.1.0\ndistribution public\nsource "probe"\nkey n int -\nkey val int -\n'
         'key s1 string -\nkey s2 string -\nkey x int -\nkey label string -\nkey qty int -\n'
         'list items "a list"\nlist nums "scalar items"\n')
HEAD = 'format probe\nversion 0.28.0\ndistribution public\nsource "probe"\nuses probe\n'
N = [0]
def lv(slug, body, error=None, head=HEAD + "wire cbor\n"):
    N[0] += 1
    name = "wire-cbor-%02d-%s" % (N[0], slug)
    o = {"name": name, "models": [CORE, PROBE], "pack": head + body}
    if error: o["expect_error"] = error
    with open(os.path.join(D, name + ".json"), "w") as f:
        f.write(json.dumps(o, indent=2) + "\n")
    print(name, error or "loads")

lv("every-transform-and-path-form-loads",
   "tag 18\nfield uid 1 text\nfield probe.n -1 int\nfield probe.val 2 uint\nfield lat 3 float\n"
   "field probe.s2 4 bytes\nfield probe.x flag bool\nfield time_ms 5 epoch_s\n"
   "field probe.s1 a_b-c.[0].d text\n"
   "group probe.items 9\n  field probe.label name text\n  field probe.qty n uint\nend\n"
   "group probe.nums 10\n  field probe.val . int\nend\n")
lv("integer-key-and-position-range-ends-load",
   "field probe.n 18446744073709551615 int\nfield probe.val -9223372036854775808 int\nfield probe.s1 7.[65535] text\n")
for slug, loc in [("position-glued-to-a-key", "a[0]"), ("position-with-a-leading-zero", "[01]"),
                  ("minus-zero", "-0"), ("plus-sign", "+1"), ("empty-step", "a..b"),
                  ("integer-key-above-2-64-minus-1", "18446744073709551616"),
                  ("integer-key-below-minus-2-63", "-9223372036854775809"),
                  ("position-above-65535", "[65536]"), ("character-outside-the-set", "a:b"),
                  ("integer-key-with-a-leading-zero", "01"), ("text-key-beginning-with-minus", "-a")]:
    lv("bad-locator-" + slug, "field probe.n %s int\nbogus\n" % loc, "bad-locator")
lv("bad-locator-on-a-group-line", "group probe.items [01]\n  field probe.label name text\nend\nbogus\n", "bad-locator")
lv("top-map-and-top-array-disagree", "field uid 1 text\nfield probe.n [0] int\n", "bad-directive")
lv("top-type-disagreement-is-checked-after-the-file", "field uid 1 text\nfield probe.n [0] int\nbogus\n", "unknown-directive")
lv("top-type-disagreement-across-kinds",
   "kind a\nwhen [0] 1\nfield uid [1] text\nkind b\nwhen 0 2\nfield probe.n 1 int\n", "bad-directive")
lv("one-step-used-as-map-and-array", "field probe.n 7.1 int\nfield probe.val 7.[0] int\n", "bad-directive")
lv("map-and-array-in-different-kinds-load",
   "kind a\nwhen 0 1\nfield probe.n 7.1 int\nkind b\nwhen 0 2\nfield probe.val 7.[0] int\n")
lv("group-dot-loads", "group probe.nums .\n  field probe.val . int\nend\n")
lv("group-dot-and-a-member-path-disagree", "group probe.nums .\n  field probe.val . int\nend\nfield uid 1 text\n", "bad-directive")
lv("field-under-a-group-path",
   "group probe.items 9\n  field probe.label name text\nend\nfield probe.n 9.1 int\n", "bad-directive")
lv("field-at-a-group-path",
   "group probe.items 9\n  field probe.label name text\nend\nfield probe.n 9 int\n", "bad-directive")
lv("transform-not-in-the-cbor-table", "field probe.n 1 string\n", "bad-directive")
lv("transform-not-in-the-table-is-checked-after-the-file", "field probe.n 1 string\nbogus\n", "unknown-directive")
lv("absent-option-on-cbor", "field probe.n 1 int absent 5\n", "bad-directive")
lv("swap-option-on-cbor", "field probe.n 1 int swap\n", "bad-directive")
lv("swap-option-is-checked-after-the-file", "field probe.n 1 int swap\nbogus\n", "unknown-directive")
lv("optional-option-on-cbor", "field probe.n 1 int optional\n", "bad-directive")
lv("tag-with-two-arguments-is-a-line-check", "tag 1 2\nfield probe.n 1 int\nbogus\n", "bad-directive")
lv("tag-before-wire-loads", "field probe.n 1 int\n", head=HEAD + "tag 18\nwire cbor\n")
lv("tag-range-ends-load", "tag 18446744073709551615\nfield probe.n 1 int\n")
lv("tag-zero-loads", "tag 0\nfield probe.n 1 int\n")
lv("tag-with-a-leading-zero", "tag 018\nfield probe.n 1 int\n", "bad-directive")
lv("tag-value-is-checked-after-the-file", "tag 018\nfield probe.n 1 int\nbogus\n", "unknown-directive")
lv("tag-above-2-64-minus-1", "tag 18446744073709551616\nfield probe.n 1 int\n", "bad-directive")
lv("tag-ber-oid-on-cbor", "tag ber-oid\nfield probe.n 1 int\n", "bad-directive")
lv("tag-twice", "tag 18\ntag 18\nfield probe.n 1 int\n", "bad-directive")
lv("tag-after-the-first-kind", "field uid 1 text\nkind k\nwhen 0 1\ntag 18\n", "bad-directive")
lv("tag-n-on-json", "field probe.n a int\n", "bad-directive", head=HEAD + "wire json\ntag 18\n")
lv("when-and-const-value-forms-load",
   "field uid 1 text\nconst 2 -0005\nconst 3 true\nconst 4 =7\nkind a\nwhen 0 00\nkind b\nwhen 0 -1\nkind c\nwhen 0 18446744073709551615\nkind d\nwhen 0 false\nkind e\nwhen name =5\n")
lv("absent-option-is-checked-after-the-file", "field probe.n 1 int absent 5\nbogus\n", "unknown-directive")
lv("integer-when-at-2-64-minus-1-loads",
   "field uid 1 text\nkind big\nwhen 0 18446744073709551615\nfield probe.n 2 int\n")
lv("value-path-and-container-path-in-one-scope", "field probe.n 2 int\nfield probe.val 2.1 int\n", "bad-directive")
lv("value-and-container-is-checked-after-the-file", "field probe.n 2 int\nfield probe.val 2.1 int\nbogus\n", "unknown-directive")
lv("value-path-and-container-path-in-two-kinds-load",
   "kind a\nwhen 0 1\nfield probe.n 2 int\nkind b\nwhen 0 2\nfield probe.val 2.1 int\n")
lv("group-under-a-group-path",
   "group probe.items 9\n  field probe.label name text\nend\ngroup probe.nums 9.1\n  field probe.val . int\nend\n", "bad-directive")
lv("group-at-a-group-path",
   "group probe.items 9\n  field probe.label name text\nend\ngroup probe.nums 9\n  field probe.val . int\nend\n", "bad-directive")
lv("group-body-mixing-dot-and-a-member-path",
   "group probe.items 9\n  field probe.label . text\n  field probe.qty n uint\nend\n", "bad-directive")
lv("integer-when-beyond-2-64-minus-1-is-text-and-loads",
   "field uid 1 text\nkind big\nwhen 0 18446744073709551616\nconst 2 -9223372036854775809\n")
lv("when-present-at-a-prefix-of-a-field-path-loads",
   "field uid 1 text\nkind located\nwhen 7 present\nrequires lat\nfield lat 7.1 float\n")
