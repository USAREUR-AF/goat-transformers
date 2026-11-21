"""Vectors for the group clause of ruling 23 of 0.28, on the probe pack
conformance-cbor-group (group probe.nums at [0] with a `.` body of int, and
probe.s2 at [1] by bytes). Executed by build.py in its namespace (vec, H,
positional). Values chosen for these vectors. Expected bytes are hand-written
structures encoded by cbor.py; never an engine."""

CG = "conformance-cbor-group"; DCG = "packs/conformance-cbor-group/vectors"
S2 = b"\x0a\xff"
# The only line that names [0] is the group's own path, which ruling 23 says
# is not walked into: so no `walks` entry for [0], and an absent list there is
# f6 by positional().
CGW = {}
GREF = "packs/conformance-cbor-group/pack.def (group probe.nums [0], field probe.val . int; field probe.s2 [1] bytes);"
def gref(s): return GREF + " " + s

g1 = H(positional({0: [1, -2, 3], 1: S2}, CGW))
vec(DCG, "01-items-round-trip.json", "items-round-trip", CG, CG, g1, g1,
    model={"probe.nums.#": "3", "probe.nums[0].probe.val": "1", "probe.nums[1].probe.val": "-2",
           "probe.nums[2].probe.val": "3", "probe.s2": "0aff"},
    ref=gref("82, [0] the list 83 01 21 03 (1, -2, 3; -2 is major type 1 argument 1), [1] 420aff. Canonical input, so the output equals it (Writing step 4: one element per item in list order)."))

g2 = H(positional({1: S2}, CGW))
assert g2 == "82f6420aff"
vec(DCG, "02-null-at-group-path-list-absent.json", "null-at-group-path-list-absent", CG, CG, g2, g2,
    model={"probe.nums.#": "absent", "probe.s2": "0aff"},
    ref=gref("Reading step 8: a group path at null is an absent list. Writing step 3 and ruling 23: [1] is the highest present position; [0] is the group's own path, which is not walked into, and the list is absent: f6. Output 82 f6 420aff."))

vec(DCG, "03-list-absent-from-context.json", "list-absent-from-context", CG, CG, "80", g2,
    model={"probe.nums.#": "absent", "@absent": ["probe.s2"]}, context={"probe.s2": "0aff"},
    ref=gref("The input 80 has no [0] and no [1]: the list is absent and probe.s2 is absent; the context fills probe.s2. Ruling 23: an absent list at a gap position is f6 (not 80, not a0). Output 82 f6 420aff."))

g4 = H(positional({0: [], 1: S2}, CGW))
assert g4 == "8280420aff"
vec(DCG, "04-empty-list-round-trip.json", "empty-list-round-trip", CG, CG, g4, g4,
    model={"probe.nums.#": "0", "probe.s2": "0aff"},
    ref=gref("[0] is an empty array: a present list with no items. Ruling 23 and Writing step 4: a present list, even empty, writes its array, 80. Output 82 80 420aff."))

vec(DCG, "05-empty-list-from-context.json", "empty-list-from-context", CG, CG, "8180", g4,
    model={"probe.nums.#": "0", "@absent": ["probe.s2"]}, context={"probe.s2": "0aff"},
    ref=gref("Input [[]]: the list is present and empty, probe.s2 absent; the context fills probe.s2 (a context cannot name a list, spec/vector-format.md). The empty list is written by step 4 as 80, not f6. Output 82 80 420aff."))

g6 = H(positional({0: [7, None, 9], 1: S2}, CGW))
vec(DCG, "06-null-item-written-null.json", "null-item-written-null", CG, CG, g6, g6,
    model={"probe.nums.#": "3", "probe.nums[0].probe.val": "7", "probe.nums[2].probe.val": "9",
           "probe.s2": "0aff"},
    ref=gref("Item 1 is null, which the int transform reads as absent (simple value 22): an item with no value. Writing step 4: a scalar item (.) with no value is f6. Output 82 83 07 f6 09 420aff."))

g7 = H(positional({0: [5]}, CGW))
vec(DCG, "07-list-only-trailing-position-not-written.json", "list-only-trailing-position-not-written", CG, CG, g7, g7,
    model={"probe.nums.#": "1", "probe.nums[0].probe.val": "5", "@absent": ["probe.s2"]},
    ref=gref("probe.s2 is absent, so the highest present position is [0] (Writing step 3); [1] is not written. Output 81 81 05."))

# ---------------------------------------------------------------- ruling 24
g8 = H(positional({}, CGW))          # nothing present: positional gives [], the top array written empty
assert g8 == "80"
vec(DCG, "08-null-at-group-path-not-written-back.json", "null-at-group-path-not-written-back", CG, CG,
    H([None]), g8,
    model={"probe.nums.#": "absent", "@absent": ["probe.s2"]},
    ref=gref("Ruling 24: a group line maps its own path, so the null at [0] is an absent list (Reading step 8), not residue, and is not written back. Nothing else is present, so the array has no highest present position and the top item is written empty (Writing steps 2 and 3): 81 f6 -> 80."))
