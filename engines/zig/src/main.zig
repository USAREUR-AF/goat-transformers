// gt-engines Zig engine — clean-room implementation from spec/ and packs/ only.
// Implements the format engine: decode(wire->model), encode(model->wire),
// convert(from,to[,context]) = decode, fill from context, derive, encode; plus
// a conformance harness.
//
// Wires: xml, geojson, json, bits (lsb and msb bit order), protobuf, text.
// Transforms: string, float, int, iso8601_ms, bool, uint, twos,
// linscale:<maxpos>:<range>, uscale/sscale:<factor>[:<offset>], f32, f64,
// ascii, pstring, pvarint, psint, pdouble, pfloat; on text also int:<w>,
// dec:<f>[:<w>], dm:<d>:<f>:<PN>, hms:<f>, hms_dmy:<f> (spec Version 0.10).
// Model modules and distribution (spec Version 0.4), message kinds
// (`kind` / `when` / `requires`, spec Version 0.5) and the mapping rules of
// spec Version 0.6 (`const`, `default`, `map` / `via`, the field options
// `swap` / `trim` / `optional`, a `root` per kind, `derive` lines in model
// modules, caller-supplied keys) are checked at load by `Engine`. Groups (spec
// Version 0.7): `list` lines in model modules, `group … end` blocks on every
// wire, lists in the entity. Sequential binary layouts (spec Version 0.8):
// `layout sequential` on the bits wire, `uses` lines and five more derive
// functions in model modules. Absent-value sentinels (spec Version 0.9): the
// `absent` field option on every wire. The strict rulings of spec Version
// 0.11: named load errors, strict number and time grammars, XML text, the
// capability report and the limit on list items. Stdlib only.
//
// Errors the specification names are Zig errors whose name IS the spec token
// (`error.@"no-kind"`); `Engine.last_error` holds `<kind>: <detail>`.

const std = @import("std");

// ---------------------------------------------------------------------------
// Model
// ---------------------------------------------------------------------------

pub const MV = union(enum) {
    str: []const u8,
    int: i64,
    float: f64,
};

const Residue = struct {
    fmt: []const u8, // source format name; residue does not cross formats
    locator: []const u8,
    // xml: the attribute text. geojson and json: canonical JSON text.
    value: []const u8,
};

// A map from a name to a value, kept as one array in insertion order. An
// entity holds a handful of keys and a message may hold a list item per
// input bit, so an item costs what its keys take and no more: a hash map's
// smallest table is several hundred bytes. Names are not copied.
fn SmallMap(comptime V: type) type {
    return struct {
        const Self = @This();
        const Entry = struct { key: []const u8, value: V };
        ptr: [*]Entry = undefined,
        len: u32 = 0,
        cap: u32 = 0,

        fn find(self: *const Self, key: []const u8) ?*Entry {
            for (self.ptr[0..self.len]) |*en| {
                if (std.mem.eql(u8, en.key, key)) return en;
            }
            return null;
        }
        pub fn contains(self: *const Self, key: []const u8) bool {
            return self.find(key) != null;
        }
        pub fn get(self: *const Self, key: []const u8) ?V {
            return if (self.find(key)) |en| en.value else null;
        }
        fn put(self: *Self, alloc: std.mem.Allocator, key: []const u8, value: V) !void {
            if (self.find(key)) |en| {
                en.value = value;
                return;
            }
            if (self.len == self.cap) {
                // 1, 2, 4, …: the old array is given back to the allocator
                const grown = if (self.cap == 0)
                    try alloc.alloc(Entry, 1)
                else
                    try alloc.realloc(self.ptr[0..self.cap], @as(usize, self.cap) * 2);
                self.ptr = grown.ptr;
                self.cap = @intCast(grown.len);
            }
            self.ptr[self.len] = .{ .key = key, .value = value };
            self.len += 1;
        }
    };
}

// An entity, and an item of a list: an item holds model keys and lists exactly
// as an entity does, without residue and without a kind.
pub const Entity = struct {
    alloc: std.mem.Allocator,
    fields: SmallMap(MV) = .{},
    // list name -> items; a present, empty list is an entry of length 0
    lists: SmallMap([]Entity) = .{},
    residue: std.ArrayListUnmanaged(Residue) = .{},
    // Entity.kind is the pair (format, kind name); null when no kind is recorded.
    kind_fmt: ?[]const u8 = null,
    kind_name: []const u8 = "",

    pub fn init(alloc: std.mem.Allocator) Entity {
        return .{ .alloc = alloc };
    }
    pub fn put(self: *Entity, key: []const u8, value: MV) !void {
        try self.fields.put(self.alloc, key, value);
    }
    pub fn putList(self: *Entity, name: []const u8, items: []Entity) !void {
        try self.lists.put(self.alloc, name, items);
    }
    fn addResidue(self: *Entity, r: Residue) !void {
        try self.residue.append(self.alloc, r);
    }
    // `requires <key>`: the key is present, or the list is present with at
    // least one item.
    fn has(self: *const Entity, key: []const u8) bool {
        if (self.fields.contains(key)) return true;
        if (self.lists.get(key)) |items| return items.len > 0;
        return false;
    }
    fn get(self: *const Entity, key: []const u8) ?MV {
        return self.fields.get(key);
    }
    fn clearKind(self: *Entity) void {
        self.kind_fmt = null;
        self.kind_name = "";
    }
};

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

const EngineError = error{
    // Version 0.11 (ruling 5): every load and call failure has a kind
    @"unterminated-quote",
    @"unknown-directive",
    @"unknown-transform",
    @"unknown-wire",
    @"unknown-format",
    @"bad-locator",
    @"missing-format",
    @"missing-version",
    @"missing-wire",
    @"missing-module",
    @"duplicate-format",
    @"missing-root",
    // Version 0.4 load errors: the error name IS the spec's kind token.
    @"missing-distribution",
    @"missing-source",
    @"distribution-refused",
    @"unknown-module",
    @"distribution-violation",
    @"module-not-used",
    @"undeclared-key",
    @"key-type-mismatch",
    @"duplicate-module",
    @"duplicate-key",
    // Version 0.5
    @"no-kind",
    @"duplicate-kind",
    @"transform-encode",
    @"transform-decode",
    @"malformed-wire",
    @"bad-directive",
};
const E = EngineError;

// Detail text of a failure, filled where the failure is raised.
const Diag = struct {
    msg: []const u8 = "",
    // ruling 7 of 0.11: the limit on the list items one decode holds, the
    // items held so far, and whether the limit was what failed
    max_items: usize = default_max_items,
    held: usize = 0,
    limit_hit: bool = false,
    // a decode run again that reads no field: it only counts the items
    count_only: bool = false,
    // the failure is a line check of a load (ruling 5b of 0.11)
    line_err: bool = false,
};

// A load failure kept until the file has been read (ruling 5b of 0.11).
const Deferred = struct { err: anyerror, msg: []const u8 };

// Keep the first failure of a cause that is checked after the file is read.
fn deferBad(deferred: *?Deferred, alloc: std.mem.Allocator, err: anyerror, comptime fmt: []const u8, args: anytype) !void {
    if (deferred.* != null) return;
    const msg = try std.fmt.allocPrint(alloc, fmt, args);
    deferred.* = .{ .err = err, .msg = msg };
}

// A failure of a line check, steps 1 to 10 of ruling 5b of 0.11: reported
// as the line is read.
fn lineBad(diag: *Diag, alloc: std.mem.Allocator, err: anyerror, comptime fmt: []const u8, args: anytype) anyerror {
    diag.line_err = true;
    return bad(diag, alloc, err, fmt, args);
}

// The limit on list items when the caller sets none (ruling 7b of 0.11).
pub const default_max_items: usize = 100_000;

// Hold `n` more list items, or fail with `malformed-wire` when the decode
// would then hold more than the limit (ruling 7 of 0.11).
fn takeItems(diag: *Diag, alloc: std.mem.Allocator, n: u64, list: []const u8) anyerror!void {
    const room = diag.max_items - diag.held;
    if (n > room) {
        diag.limit_hit = true;
        return bad(diag, alloc, E.@"malformed-wire", "list {s}: {d} more items would pass the limit of {d} list items", .{ list, n, diag.max_items });
    }
    diag.held += @intCast(n);
}

// The list items an entity holds, at every nesting level.
fn itemsHeld(items: []const Entity) usize {
    var n: usize = items.len;
    for (items) |*it| {
        for (it.lists.ptr[0..it.lists.len]) |en| n += itemsHeld(en.value);
    }
    return n;
}

fn bad(diag: *Diag, alloc: std.mem.Allocator, err: anyerror, comptime fmt: []const u8, args: anytype) anyerror {
    diag.msg = std.fmt.allocPrint(alloc, fmt, args) catch "";
    return err;
}

// ---------------------------------------------------------------------------
// Pack model
// ---------------------------------------------------------------------------

const Wire = enum { xml, geojson, json, bits, protobuf, text };
const TKind = enum {
    string,
    float,
    int,
    iso8601_ms,
    // Version 0.12: read as iso8601_ms, written to the whole second
    iso8601_s,
    bool_,
    uint,
    twos,
    linscale,
    uscale,
    sscale,
    f32_,
    f64_,
    ascii,
    pstring,
    pvarint,
    psint,
    pdouble,
    pfloat,
    // the `text` wire only (Version 0.10)
    int_w,
    dec,
    dm,
    hms,
    hms_dmy,
};

// `rec`: the transforms valid on the `text` wire only
const KindCat = enum { text, bits, proto, rec };

fn kindCategory(k: TKind) KindCat {
    return switch (k) {
        .string, .float, .int, .iso8601_ms, .iso8601_s, .bool_ => .text,
        .uint, .twos, .linscale, .uscale, .sscale, .f32_, .f64_, .ascii => .bits,
        .pstring, .pvarint, .psint, .pdouble, .pfloat => .proto,
        .int_w, .dec, .dm, .hms, .hms_dmy => .rec,
    };
}

fn wireCategory(w: Wire) KindCat {
    return switch (w) {
        .xml, .geojson, .json, .text => .text,
        .bits => .bits,
        .protobuf => .proto,
    };
}

const Transform = struct {
    kind: TKind,
    // linscale
    maxpos: f64 = 0,
    range: f64 = 0,
    // uscale / sscale
    factor: Factor = .{},
    offset: f64 = 0,
    // text: `int:<w>`, `dec:<f>[:<w>]` (w 0: none), `dm:<d>:<f>:<PN>`,
    // `hms:<f>`, `hms_dmy:<f>`
    w: usize = 0,
    f: usize = 0,
    d: usize = 0,
    letp: u8 = 0,
    letn: u8 = 0,
};

const LineTag = enum { field, when, constant, group };

// One row of a value table: `map <table> <native> <model>`.
const TableEntry = struct { native: []const u8, model: []const u8 };

const Table = struct {
    name: []const u8,
    entries: std.ArrayList(TableEntry),
    // the type of the `<model>` side: `string` unless every value is an
    // integer (`int`) or every one is a number (`float`)
    model_ty: KeyType = .string,
};

// One `default <model-key> <value>` line.
const Default = struct {
    key: []const u8,
    text: []const u8,
    value: MV = .{ .int = 0 }, // `text` read as the key's declared type, at load
};

// A `group <list> <locator> … end` block. Its body is a scope of its own: the
// locators of its lines are read relative to one item.
const Group = struct {
    list: []const u8,
    locator: []const u8,
    lineno: usize,
    parent: ?*const Group = null, // the group this one is nested in
    lines: []Line = &.{},
    defaults: std.ArrayList(Default),
    body: Scope = .{},
    // `item <bits>` and `count <count-locator | n>` as written
    item_txt: ?[]const u8 = null,
    count_txt: ?[]const u8 = null,
    // xml: the element names before the last, and the item element's name
    xpath: []const []const u8 = &.{},
    xname: []const u8 = "",
    // json, and geojson inside an item: the member path of the array
    segs: []const []const u8 = &.{},
    // protobuf: field-number path; the last number is the item's
    ppath: []const usize = &.{},
    // bits: where the first item starts (from the scope's first bit), the
    // least size of an item, and the count: fixed, or a bit range of the scope
    gstart: usize = 0,
    item_bits: usize = 0,
    count_fixed: ?usize = null,
    cstart: usize = 0,
    clen: usize = 0,
    // text: the index of the first item's first field, and the fields of an item
    tstart: usize = 0,
    titem: usize = 0,
};

// The lines that apply together: common lines plus one kind's, or one group
// body.
const Scope = struct {
    lines: []const Line = &.{},
    // `default` values in scope, by key (a kind's replaces the common one)
    defaults: std.StringHashMapUnmanaged(MV) = .{},
    // bits: one past the furthest bit of the scope's `field`, `when`, `const`
    // lines and count locators, counted from the scope's first bit; and the
    // same over the lines that are not `optional`
    nbits: usize = 0,
    nbits_req: usize = 0,
    // a group body: its first `.` field line (the item itself as a scalar),
    // and whether a line addresses into the item
    dot: ?*const Line = null,
    needs_sub: bool = false,

    fn defaultFor(self: *const Scope, key: []const u8) ?MV {
        if (self.defaults.count() == 0) return null;
        return self.defaults.get(key);
    }
};

// One `field`, `when`, `const` or `group` line.
const Line = struct {
    tag: LineTag = .field,
    grp: ?*Group = null, // group
    dot: bool = false, // the locator `.`: the item itself
    // field options
    via_name: []const u8 = "",
    via: ?*const Table = null,
    swap: bool = false,
    trim: bool = false,
    optional: bool = false,
    // `absent <value>[,<value>…]` (Version 0.9): the argument as written,
    // then, once the line is resolved against its wire, the sentinels
    absent_raw: ?[]const u8 = null,
    abs_set: bool = false,
    // the `absent` values were checked as the line was read
    abs_checked: bool = false,
    abs_ints: []const u64 = &.{}, // bits, and the integer forms of protobuf
    abs_texts: []const []const u8 = &.{}, // text wires and pstring: the text compared
    abs_json: []const u8 = "", // json, geojson: the JSON text the first sentinel is written as
    kty: KeyType = .string, // the key's declared type, set when the pack loads

    key: []const u8 = "",
    locator: []const u8,
    transform: Transform = .{ .kind = .string },
    lineno: usize = 0,
    // bits: absolute bit offset of the first bit, and the bit length
    bstart: usize = 0,
    blen: usize = 0,
    // protobuf: field-number path
    ppath: []const usize = &.{},
    // json: member-name path
    segs: []const []const u8 = &.{},
    // when
    wraw: []const u8 = "", // the value as written
    wtext: []const u8 = "", // text value, a leading `=` stripped
    wpresent: bool = false,
    wforced: bool = false, // written with a leading `=`
    wint: u64 = 0, // bits / protobuf integer value
    // text: a field `<i>`, a column `<i>:<from>:<len>` or a pair `<i>+<j>`
    tloc: TLoc = .whole,
    ti: usize = 0,
    tj: usize = 0,
    tfrom: usize = 0,
    tlen: usize = 0,

    fn isField(self: *const Line) bool {
        return self.tag == .field;
    }
    fn isWhen(self: *const Line) bool {
        return self.tag == .when;
    }
    // a `when` or `const` line: a value the encoder writes
    fn isFixed(self: *const Line) bool {
        return self.tag == .when or self.tag == .constant;
    }
    // Does the line map its locator (so the member is not residue)? A
    // `when <locator> present` on a text wire does not (ruling 27 of 0.5).
    fn maps(self: *const Line) bool {
        return !(self.tag == .when and self.wpresent);
    }
};

const TLoc = enum { whole, column, pair };

const Kind = struct {
    name: []const u8,
    lines: std.ArrayList(Line),
    requires: std.ArrayList([]const u8),
    defaults: std.ArrayList(Default),
    // xml: this kind's root element; null uses the pack's
    root: ?[]const u8 = null,
    // common lines then this kind's lines
    scope: Scope = .{},
};

// A key named by a `field` (with its transform) or a `requires` line, in file
// order, for the Version 0.4 load checks.
const KeyUse = struct {
    key: []const u8,
    tkind: ?TKind,
    via: []const u8 = "",
    use: enum { field, group, requires, default } = .field,
    // the innermost group the line is in: `model_keys` lists a key inside a
    // group as `<list>[].<key>`
    grp: ?*const Group = null,
};

const Pack = struct {
    format: []const u8,
    version: []const u8,
    wire: Wire,
    root: []const u8 = "",
    word_bytes: usize = 0,
    msb: bool = false,
    bit_order_set: bool = false,
    common: std.ArrayList(Line),
    kinds: std.ArrayList(Kind),
    common_defaults: std.ArrayList(Default),
    tables: std.StringHashMap(*Table),
    // xml: kind indices by root element name, each list in pack order
    root_index: std.StringHashMap(std.ArrayList(usize)),
    // the scope of a pack with no kinds: the common lines
    common_scope: Scope = .{},
    key_uses: std.ArrayList(KeyUse),
    tm_nat2cot: std.StringHashMap([]const u8),
    tm_cot2nat: std.StringHashMap([]const u8),
    // Version 0.4
    distribution: ?Dist = null,
    sources: std.ArrayList([]const u8),
    uses: std.ArrayList([]const u8),
    // Version 0.8: `layout` as written, and the lines of a sequential pack
    layout_set: bool = false,
    seq: ?*SBody = null,
    // Version 0.10, the `text` wire: the delimiter (null: `none`), the start
    // text, the `nmea` checksum; and whether each directive was given
    delim: ?u8 = ',',
    start: []const u8 = "",
    nmea: bool = false,
    text_dirs: bool = false,
    // the three directives as written, and the first line that repeats one
    // or gives one after the first `kind`
    delim_raw: ?[]const u8 = null,
    start_raw: ?[]const u8 = null,
    cksum_raw: ?[]const u8 = null,
    tdir_bad: usize = 0,

    fn usesModule(self: *const Pack, name: []const u8) bool {
        if (std.mem.eql(u8, name, "core")) return true; // `core` is always used
        for (self.uses.items) |u| if (std.mem.eql(u8, u, name)) return true;
        return false;
    }

    fn hasKinds(self: *const Pack) bool {
        return self.kinds.items.len > 0;
    }

    // The scope of a message of kind `k`: the common lines, then the kind's.
    fn scope(self: *const Pack, k: ?usize) *const Scope {
        if (k) |idx| return &self.kinds.items[idx].scope;
        return &self.common_scope;
    }

    // bits: `nbits` bits as bytes, a whole number of words.
    fn wordBytes(self: *const Pack, nbits: usize) usize {
        const wbits = self.word_bytes * 8;
        if (wbits == 0) return 0;
        return ((nbits + wbits - 1) / wbits) * self.word_bytes;
    }

    // The root element a message of kind `k` has (xml).
    fn rootName(self: *const Pack, k: ?usize) []const u8 {
        if (k) |idx| {
            if (self.kinds.items[idx].root) |r| return r;
        }
        return self.root;
    }

    fn kindIndex(self: *const Pack, name: []const u8) ?usize {
        for (self.kinds.items, 0..) |k, i| if (std.mem.eql(u8, k.name, name)) return i;
        return null;
    }
};

// model_keys(format): the union of keys over common and all kinds, in first
// appearance order. A list is `<list>[]`, an item key `<list>[].<key>`, nested
// lists likewise.
fn modelKeys(alloc: std.mem.Allocator, p: *const Pack) ![]const []const u8 {
    var out = std.ArrayList([]const u8).init(alloc);
    var seen = std.StringHashMap(void).init(alloc);
    for (p.key_uses.items) |ku| {
        if (ku.use != .field and ku.use != .group) continue; // `requires` and `default` keys are not mapped keys
        const name = try mkName(alloc, ku.grp, ku.key, ku.use == .group);
        if (seen.contains(name)) continue;
        try seen.put(name, {});
        try out.append(name);
    }
    return out.toOwnedSlice();
}

// ---------------------------------------------------------------------------
// Model modules and distribution (Version 0.4)
// ---------------------------------------------------------------------------

// `public` is below `controlled`.
pub const Dist = enum { public, controlled };

fn parseDist(s: []const u8) !Dist {
    if (std.mem.eql(u8, s, "public")) return .public;
    if (std.mem.eql(u8, s, "controlled")) return .controlled;
    return E.@"bad-directive";
}

const KeyType = enum { string, float, int };

const ModKey = struct {
    name: []const u8,
    ty: KeyType,
    unit: []const u8,
    meaning: []const u8 = "",
};

const Module = struct {
    name: []const u8,
    version: []const u8,
    distribution: ?Dist = null,
    sources: std.ArrayList([]const u8),
    keys: std.ArrayList(ModKey),
    index: std.StringHashMap(usize),
    // `list` lines; a list shares the key namespace of its module
    lists: std.StringHashMap(void),
    derives: std.ArrayList(Derive),
    // the `derive` lines as written, until `checkDerives` resolves them
    derive_lines: std.ArrayList([]const []const u8),
    // `uses <module>` lines (Version 0.8): the modules whose keys a `derive`
    // line of this module may take as arguments
    uses: std.ArrayList([]const u8),

    fn usesModule(self: *const Module, name: []const u8) bool {
        for (self.uses.items) |u| if (std.mem.eql(u8, u, name)) return true;
        return false;
    }

    fn key(self: *const Module, name: []const u8) ?ModKey {
        if (self.index.get(name)) |i| return self.keys.items[i];
        return null;
    }
};

// A scale factor: a decimal number, or the fraction num/den of two decimal
// integers (ruling 1 of 0.5).
const Factor = struct {
    factor: f64 = 1,
    is_frac: bool = false,
    num: f64 = 1,
    den: f64 = 1,

    fn mul(self: Factor, v: f64) f64 {
        return if (self.is_frac) v * self.num / self.den else v * self.factor;
    }
    fn div(self: Factor, v: f64) f64 {
        return if (self.is_frac) v * self.den / self.num else v / self.factor;
    }
};

const DFn = enum { copy, hypot, bearing, east_of, north_of, neg, scale, offset, join, day_seconds, any, not, parse_int, text_of };

// One `derive <model-key> <function> <argument-key>…` line of a module.
const Derive = struct {
    target: []const u8,
    f: DFn,
    args: []const []const u8,
    factor: Factor = .{}, // scale
    int_mode: bool = false, // offset on an int target and argument
    off_f: f64 = 0,
    off_i: i64 = 0,
    sep: []const u8 = "", // join
};

// The type a transform yields (spec: "The type a transform yields").
fn yields(k: TKind) KeyType {
    return switch (k) {
        .string, .pstring, .ascii => .string,
        .float, .linscale, .uscale, .sscale, .f32_, .f64_, .pdouble, .pfloat, .dec, .dm, .hms => .float,
        .int, .iso8601_ms, .iso8601_s, .bool_, .uint, .twos, .pvarint, .psint, .int_w, .hms_dmy => .int,
    };
}

// A model key with no '.' is a key of `core`; otherwise the text before the
// first '.' is the module name.
const KeyRef = struct { module: []const u8, name: []const u8 };

fn splitKey(model_key: []const u8) KeyRef {
    if (std.mem.indexOfScalar(u8, model_key, '.')) |dot| {
        return .{ .module = model_key[0..dot], .name = model_key[dot + 1 ..] };
    }
    return .{ .module = "core", .name = model_key };
}

// ---------------------------------------------------------------------------
// pack.def tokenizer (comments only at token start; quotes group whitespace;
// `#` inside a quoted value is literal; a quoted value has no escape)
// ---------------------------------------------------------------------------

// The tokens of one line into `toks`, which is emptied first: one buffer
// serves every line of a file.
fn tokenizeInto(toks: *std.ArrayList([]const u8), line: []const u8) !void {
    toks.clearRetainingCapacity();
    var i: usize = 0;
    while (i < line.len) {
        while (i < line.len and (line[i] == ' ' or line[i] == '\t' or line[i] == '\r')) i += 1;
        if (i >= line.len) break;
        if (line[i] == '#') break; // comment to end of line, only at token start
        if (line[i] == '"') {
            i += 1;
            const start = i;
            while (i < line.len and line[i] != '"') i += 1;
            // a value that begins with `"` closes on its own line (ruling 5)
            if (i >= line.len) return E.@"unterminated-quote";
            try toks.append(line[start..i]);
            i += 1;
        } else {
            const start = i;
            while (i < line.len and line[i] != ' ' and line[i] != '\t' and line[i] != '\r') i += 1;
            try toks.append(line[start..i]);
        }
    }
}

fn isDigit(c: u8) bool {
    return c >= '0' and c <= '9';
}

fn allDigits(s: []const u8) bool {
    if (s.len == 0) return false;
    for (s) |c| if (!isDigit(c)) return false;
    return true;
}

// Number text (ruling 2b of 0.11): an optional `-`, one or more digits,
// optionally `.` and one or more digits, optionally `e` or `E`, an optional
// sign and one or more digits; nothing else.
fn isDecimalText(s: []const u8) bool {
    var i: usize = 0;
    if (i < s.len and s[i] == '-') i += 1;
    const d0 = i;
    while (i < s.len and isDigit(s[i])) i += 1;
    if (i == d0) return false;
    if (i < s.len and s[i] == '.') {
        i += 1;
        const f0 = i;
        while (i < s.len and isDigit(s[i])) i += 1;
        if (i == f0) return false;
    }
    if (i < s.len and (s[i] == 'e' or s[i] == 'E')) {
        i += 1;
        if (i < s.len and (s[i] == '-' or s[i] == '+')) i += 1;
        const e0 = i;
        while (i < s.len and isDigit(s[i])) i += 1;
        if (i == e0) return false;
    }
    return i == s.len;
}

// Number text to the nearest double (ruling 2b of 0.11); a text whose nearest
// double is infinite is refused. A text that begins with `-` and reads as
// zero is -0.0.
fn parseDecimal(s: []const u8) !f64 {
    if (!isDecimalText(s)) return E.@"transform-decode";
    var f = std.fmt.parseFloat(f64, s) catch return E.@"transform-decode";
    if (!std.math.isFinite(f)) return E.@"transform-decode"; // a model float is always finite
    if (f == 0 and s[0] == '-') f = -0.0;
    return f;
}

fn mvType(mv: MV) KeyType {
    return switch (mv) {
        .str => .string,
        .int => .int,
        .float => .float,
    };
}

// Text read as a key type: a string as-is, an int as decimal digits, a float
// as a decimal number.
fn readAs(ty: KeyType, text: []const u8) !MV {
    return switch (ty) {
        .string => MV{ .str = text },
        .int => MV{ .int = try parseDecimalInt(text) },
        .float => MV{ .float = try parseDecimal(text) },
    };
}

// Does a value's canonical text equal a table token's?
fn tableMatches(mv: MV, tok: []const u8) bool {
    return switch (mv) {
        .str => |s| std.mem.eql(u8, s, tok),
        .int => |i| (parseDecimalInt(tok) catch return false) == i,
        .float => |f| (parseDecimal(tok) catch return false) == f,
    };
}

// Decode side of `via`: the transform's value to the key's value. The first
// entry with that `<native>` wins; a value with no entry passes through when
// the two types are the same.
fn tableDecode(t: *const Table, mv: MV, key_ty: KeyType) !MV {
    for (t.entries.items) |en| {
        if (tableMatches(mv, en.native)) return readAs(key_ty, en.model) catch E.@"transform-decode";
    }
    if (mvType(mv) == key_ty) return mv;
    return E.@"transform-decode";
}

// Encode side of `via`: the key's value to what the transform takes.
fn tableEncode(t: *const Table, mv: MV, wire_ty: KeyType) !MV {
    for (t.entries.items) |en| {
        if (tableMatches(mv, en.model)) return readAs(wire_ty, en.native) catch E.@"transform-encode";
    }
    if (mvType(mv) == wire_ty) return mv;
    return E.@"transform-encode";
}

// Integer text (ruling 2a of 0.11): an optional `-` and one or more ASCII
// digits, within a signed 64-bit integer.
fn parseDecimalInt(s: []const u8) !i64 {
    const body = if (s.len > 0 and s[0] == '-') s[1..] else s;
    if (!allDigits(body)) return E.@"transform-decode";
    return std.fmt.parseInt(i64, s, 10) catch E.@"transform-decode";
}

// The integer text of the `text` wire (Version 0.10): an optional `+` or `-`.
fn parseTextInt(s: []const u8) !i64 {
    const body = if (s.len > 0 and (s[0] == '-' or s[0] == '+')) s[1..] else s;
    if (!allDigits(body)) return E.@"transform-decode";
    return std.fmt.parseInt(i64, s, 10) catch E.@"transform-decode";
}

// The text of `parse_int` (ruling 28 of 0.8): an optional `-`, then digits,
// leading zeros included, within 64 bits. Anything else is null.
fn parseIntText(s: []const u8) ?i64 {
    const digits = if (s.len > 0 and s[0] == '-') s[1..] else s;
    if (!allDigits(digits)) return null;
    return std.fmt.parseInt(i64, s, 10) catch null;
}

fn parseUnsigned(s: []const u8) ?u64 {
    if (!allDigits(s)) return null;
    return std.fmt.parseInt(u64, s, 10) catch null;
}

// A scale factor: number text, or `<num>/<den>`. For `uscale` and `sscale`
// (`transform`, ruling 4d of 0.11) the two are unsigned decimal integers, and
// neither the factor nor either part is zero; for the `scale` derive function
// `<num>` may carry a `-`.
fn parseFactor(fac: []const u8, transform: bool) ?Factor {
    if (std.mem.indexOfScalar(u8, fac, '/')) |slash| {
        const ns = fac[0..slash];
        const ds = fac[slash + 1 ..];
        const nbody = if (!transform and ns.len > 0 and ns[0] == '-') ns[1..] else ns;
        if (!allDigits(nbody) or !allDigits(ds)) return null;
        const f = Factor{
            .is_frac = true,
            .num = std.fmt.parseFloat(f64, ns) catch return null,
            .den = std.fmt.parseFloat(f64, ds) catch return null,
        };
        if (f.den == 0 or (transform and f.num == 0)) return null;
        return f;
    }
    const v = parseDecimal(fac) catch return null;
    if (transform and v == 0) return null;
    return .{ .factor = v };
}

fn parseTransform(s: []const u8) !Transform {
    const simple = [_]struct { n: []const u8, k: TKind }{
        .{ .n = "string", .k = .string },   .{ .n = "float", .k = .float },
        .{ .n = "int", .k = .int },         .{ .n = "iso8601_ms", .k = .iso8601_ms },
        .{ .n = "iso8601_s", .k = .iso8601_s },
        .{ .n = "bool", .k = .bool_ },      .{ .n = "uint", .k = .uint },
        .{ .n = "twos", .k = .twos },       .{ .n = "f32", .k = .f32_ },
        .{ .n = "f64", .k = .f64_ },        .{ .n = "ascii", .k = .ascii },
        .{ .n = "pstring", .k = .pstring }, .{ .n = "pvarint", .k = .pvarint },
        .{ .n = "psint", .k = .psint },     .{ .n = "pdouble", .k = .pdouble },
        .{ .n = "pfloat", .k = .pfloat },
    };
    for (simple) |e| if (std.mem.eql(u8, s, e.n)) return .{ .kind = e.k };

    var it = std.mem.splitScalar(u8, s, ':');
    const head = it.next() orelse return E.@"unknown-transform";
    // a transform of the specification that takes no parameter, given one
    // (ruling 5 of 0.11): `bad-directive`
    for (simple) |e| if (std.mem.eql(u8, head, e.n)) {
        if (!std.mem.eql(u8, head, "int")) return E.@"bad-directive";
    };
    // the parameters of the scaled transforms (ruling 4d of 0.11): each
    // failure is `bad-directive`
    if (std.mem.eql(u8, head, "linscale")) {
        const bdl = E.@"bad-directive";
        const mp = it.next() orelse return bdl;
        const rg = it.next() orelse return bdl;
        if (it.next() != null) return bdl;
        const maxpos = parseUnsigned(mp) orelse return bdl;
        if (maxpos < 1) return bdl;
        const range = parseDecimal(rg) catch return bdl;
        if (range == 0) return bdl;
        return .{ .kind = .linscale, .maxpos = @floatFromInt(maxpos), .range = range };
    }
    if (std.mem.eql(u8, head, "uscale") or std.mem.eql(u8, head, "sscale")) {
        const bds = E.@"bad-directive";
        var t = Transform{ .kind = if (head[0] == 'u') .uscale else .sscale };
        const fac = it.next() orelse return bds;
        t.factor = parseFactor(fac, true) orelse return bds;
        if (it.next()) |off| {
            t.offset = parseDecimal(off) catch return bds;
            if (it.next() != null) return bds;
        }
        return t;
    }
    // the transforms of the `text` wire: a parameter out of range, missing
    // or extra is `bad-directive` (Version 0.10, rule 1)
    const bd = E.@"bad-directive";
    const TextHead = enum { int, dec, dm, hms, hms_dmy };
    const th = std.meta.stringToEnum(TextHead, head) orelse return E.@"unknown-transform";
    var ps: [4][]const u8 = undefined;
    var np: usize = 0;
    while (it.next()) |part| {
        if (np == ps.len) return bd;
        ps[np] = part;
        np += 1;
    }
    const num = struct {
        fn f(txt: []const u8, lo: usize, hi: usize) !usize {
            const v = parseUnsigned(txt) orelse return E.@"bad-directive";
            if (v < lo or v > hi) return E.@"bad-directive";
            return @intCast(v);
        }
    }.f;
    switch (th) {
        .int => {
            if (np != 1) return bd;
            return .{ .kind = .int_w, .w = try num(ps[0], 1, 20) };
        },
        .dec => {
            if (np != 1 and np != 2) return bd;
            return .{ .kind = .dec, .f = try num(ps[0], 0, 9), .w = if (np == 2) try num(ps[1], 1, 20) else 0 };
        },
        .dm => {
            if (np != 3) return bd;
            const l = ps[2];
            if (l.len != 2 or l[0] < 'A' or l[0] > 'Z' or l[1] < 'A' or l[1] > 'Z' or l[0] == l[1]) return bd;
            return .{ .kind = .dm, .d = try num(ps[0], 1, 3), .f = try num(ps[1], 0, 9), .letp = l[0], .letn = l[1] };
        },
        .hms, .hms_dmy => {
            if (np != 1) return bd;
            return .{ .kind = if (th == .hms) .hms else .hms_dmy, .f = try num(ps[0], 0, 3) };
        },
    }
}

// The declared type of a key a `derive` line names: a key of `core` or of the
// module itself, else null.
fn deriveKeyType(m: *const Module, mods: *const ModuleMap, text: []const u8, is_arg: bool) ?KeyType {
    const ref = splitKey(text);
    if (std.mem.eql(u8, ref.module, m.name)) {
        return if (m.key(ref.name)) |k| k.ty else null;
    }
    // a key of `core`, or, for an argument, of a module this one uses
    if (std.mem.eql(u8, ref.module, "core") or (is_arg and m.usesModule(ref.module))) {
        const c = mods.get(ref.module) orelse return null;
        return if (c.key(ref.name)) |k| k.ty else null;
    }
    return null;
}

const ModuleMap = std.StringHashMap(*Module);

// Check one `derive` line and resolve its function. null: the function name,
// the argument count, a key or a type does not fit.
fn resolveDerive(alloc: std.mem.Allocator, m: *const Module, mods: *const ModuleMap, toks: []const []const u8) ?Derive {
    if (toks.len < 4) return null;
    var d = Derive{ .target = toks[1], .f = .copy, .args = toks[3..] };
    const tt = deriveKeyType(m, mods, d.target, false) orelse return null;
    const at = alloc.alloc(KeyType, d.args.len) catch return null;
    for (d.args, 0..) |a, i| at[i] = deriveKeyType(m, mods, a, true) orelse return null;
    const fname = toks[2];
    const colon = std.mem.indexOfScalar(u8, fname, ':');
    const head = if (colon) |c| fname[0..c] else fname;
    const param: ?[]const u8 = if (colon) |c| fname[c + 1 ..] else null;
    const all_float = blk: {
        if (tt != .float) break :blk false;
        for (at) |ty| if (ty != .float) break :blk false;
        break :blk true;
    };
    const eq = std.mem.eql;
    if (eq(u8, head, "copy") and param == null) {
        if (d.args.len != 1 or at[0] != tt) return null;
        d.f = .copy;
    } else if (eq(u8, head, "hypot") and param == null) {
        if (d.args.len != 2 or !all_float) return null;
        d.f = .hypot;
    } else if (eq(u8, head, "bearing") and param == null) {
        if (d.args.len != 2 or !all_float) return null;
        d.f = .bearing;
    } else if (eq(u8, head, "east_of") and param == null) {
        if (d.args.len != 2 or !all_float) return null;
        d.f = .east_of;
    } else if (eq(u8, head, "north_of") and param == null) {
        if (d.args.len != 2 or !all_float) return null;
        d.f = .north_of;
    } else if (eq(u8, head, "neg") and param == null) {
        if (d.args.len != 1 or !all_float) return null;
        d.f = .neg;
    } else if (eq(u8, head, "scale")) {
        if (d.args.len != 1 or !all_float) return null;
        d.f = .scale;
        d.factor = parseFactor(param orelse return null, false) orelse return null;
    } else if (eq(u8, head, "offset")) {
        if (d.args.len != 1) return null;
        d.f = .offset;
        const n = param orelse return null;
        if (tt == .int and at[0] == .int) {
            d.int_mode = true;
            d.off_i = parseDecimalInt(n) catch return null;
        } else if (all_float) {
            d.off_f = parseDecimal(n) catch return null;
        } else return null;
    } else if (eq(u8, head, "join")) {
        if (d.args.len < 1 or tt != .string) return null;
        for (at) |ty| if (ty != .string) return null;
        d.f = .join;
        d.sep = param orelse return null;
    } else if (eq(u8, head, "day_seconds") and param == null) {
        if (d.args.len != 1 or at[0] != .int or tt != .float) return null;
        d.f = .day_seconds;
    } else if (eq(u8, head, "any") and param == null) {
        if (d.args.len < 1 or tt != .int) return null;
        for (at) |ty| if (ty != .int) return null;
        d.f = .any;
    } else if (eq(u8, head, "not") and param == null) {
        if (d.args.len != 1 or at[0] != .int or tt != .int) return null;
        d.f = .not;
    } else if (eq(u8, head, "parse_int") and param == null) {
        if (d.args.len != 1 or at[0] != .string or tt != .int) return null;
        d.f = .parse_int;
    } else if (eq(u8, head, "text_of") and param == null) {
        if (d.args.len != 1 or at[0] != .int or tt != .string) return null;
        d.f = .text_of;
    } else return null;
    return d;
}

// The part of a `derive` check that needs no key (ruling 32 of 0.8): the line
// has a target, a function and an argument; the function is one the
// specification names, with a parameter exactly when it takes one and one it
// can read; the argument count fits it.
fn deriveShapeOk(toks: []const []const u8) bool {
    if (toks.len < 4) return false;
    const fname = toks[2];
    const colon = std.mem.indexOfScalar(u8, fname, ':');
    const head = if (colon) |c| fname[0..c] else fname;
    const nargs = toks.len - 3;
    const Shape = struct { name: []const u8, param: bool, min: usize, max: usize };
    const many = std.math.maxInt(usize);
    const shapes = [_]Shape{
        .{ .name = "copy", .param = false, .min = 1, .max = 1 },
        .{ .name = "hypot", .param = false, .min = 2, .max = 2 },
        .{ .name = "bearing", .param = false, .min = 2, .max = 2 },
        .{ .name = "east_of", .param = false, .min = 2, .max = 2 },
        .{ .name = "north_of", .param = false, .min = 2, .max = 2 },
        .{ .name = "neg", .param = false, .min = 1, .max = 1 },
        .{ .name = "scale", .param = true, .min = 1, .max = 1 },
        .{ .name = "offset", .param = true, .min = 1, .max = 1 },
        .{ .name = "join", .param = true, .min = 1, .max = many },
        .{ .name = "day_seconds", .param = false, .min = 1, .max = 1 },
        .{ .name = "any", .param = false, .min = 1, .max = many },
        .{ .name = "not", .param = false, .min = 1, .max = 1 },
        .{ .name = "parse_int", .param = false, .min = 1, .max = 1 },
        .{ .name = "text_of", .param = false, .min = 1, .max = 1 },
    };
    for (shapes) |sh| {
        if (!std.mem.eql(u8, sh.name, head)) continue;
        if (sh.param != (colon != null) or nargs < sh.min or nargs > sh.max) return false;
        // a parameter no key type could accept
        const param = if (colon) |c| fname[c + 1 ..] else "";
        if (std.mem.eql(u8, head, "scale")) return parseFactor(param, false) != null;
        if (std.mem.eql(u8, head, "offset")) return !std.meta.isError(parseDecimal(param));
        return true;
    }
    return false;
}

// Parse one model module file. Fails with the line errors as the file is
// read (`duplicate-key`, the grammar errors, and `bad-directive` for a
// `derive` line refused on its own text), then `missing-distribution`, then
// `missing-source`. The keys and types of its `derive` lines are checked by
// `checkDerives` (ruling 29 of 0.8).
fn parseModule(alloc: std.mem.Allocator, def_text: []const u8, diag: *Diag) anyerror!*Module {
    const m = try alloc.create(Module);
    m.* = .{
        .name = "",
        .version = "",
        .sources = std.ArrayList([]const u8).init(alloc),
        .keys = std.ArrayList(ModKey).init(alloc),
        .index = std.StringHashMap(usize).init(alloc),
        .lists = std.StringHashMap(void).init(alloc),
        .derives = std.ArrayList(Derive).init(alloc),
        .derive_lines = std.ArrayList([]const []const u8).init(alloc),
        .uses = std.ArrayList([]const u8).init(alloc),
    };
    var lines = std.mem.splitScalar(u8, def_text, '\n');
    var tokbuf = std.ArrayList([]const u8).init(alloc);
    var lineno: usize = 0;
    var have_version = false;
    // the causes of a module line that are not line checks, reported once
    // the file is read (ruling 5b of 0.11)
    var deferred: ?Deferred = null;
    const bd = E.@"bad-directive";
    while (lines.next()) |line| {
        lineno += 1;
        // the line checks of ruling 5b of 0.11: the quote, the directive, the
        // argument count, a repeated header line, the distribution value
        tokenizeInto(&tokbuf, line) catch |err|
            return lineBad(diag, alloc, err, "line {d}: a quoted value has no closing quote", .{lineno});
        const toks = tokbuf.items;
        if (toks.len == 0) continue;
        const kw = toks[0];
        const Dir = enum { module, version, distribution, source, uses, key, list, derive };
        const dir = std.meta.stringToEnum(Dir, kw) orelse
            return bad(diag, alloc, E.@"unknown-directive", "line {d}: unknown directive {s}", .{ lineno, kw });
        const nargs = toks.len - 1;
        const args_ok = switch (dir) {
            .module, .version, .distribution, .source, .uses => nargs == 1,
            .key => nargs == 3 or nargs == 4,
            .list => nargs == 1 or nargs == 2,
            .derive => true, // its own checks below (ruling 32 of 0.8)
        };
        if (!args_ok) return bad(diag, alloc, bd, "line {d}: {s} takes another number of arguments", .{ lineno, kw });
        switch (dir) {
            .module => {
                if (m.name.len > 0) return bad(diag, alloc, bd, "line {d}: a second module line", .{lineno});
                m.name = toks[1];
                if (m.name.len == 0) {
                    try deferBad(&deferred, alloc, bd, "line {d}: an empty module name", .{lineno});
                    continue;
                }
            },
            .version => {
                if (have_version) return bad(diag, alloc, bd, "line {d}: a second version line", .{lineno});
                have_version = true;
                m.version = toks[1];
            },
            .distribution => {
                if (m.distribution != null) return bad(diag, alloc, bd, "line {d}: a second distribution line", .{lineno});
                m.distribution = parseDist(toks[1]) catch |err|
                    return bad(diag, alloc, err, "line {d}: distribution {s} is not public or controlled", .{ lineno, toks[1] });
            },
            .source => try m.sources.append(toks[1]),
            .uses => try m.uses.append(toks[1]),
            .key => {
                const name = toks[1];
                if (name.len == 0 or std.mem.indexOfScalar(u8, name, '.') != null) {
                    try deferBad(&deferred, alloc, bd, "line {d}: key name {s} is empty or holds a dot", .{ lineno, name });
                    continue;
                }
                const ty: KeyType = if (std.mem.eql(u8, toks[2], "string"))
                    .string
                else if (std.mem.eql(u8, toks[2], "float"))
                    .float
                else if (std.mem.eql(u8, toks[2], "int"))
                    .int
                else {
                    try deferBad(&deferred, alloc, bd, "line {d}: key type {s} is not string, float or int", .{ lineno, toks[2] });
                    continue;
                };
                if (m.index.contains(name) or m.lists.contains(name)) {
                    try deferBad(&deferred, alloc, E.@"duplicate-key", "key {s} appears twice", .{name});
                    continue;
                }
                try m.index.put(name, m.keys.items.len);
                try m.keys.append(.{
                    .name = name,
                    .ty = ty,
                    .unit = toks[3],
                    .meaning = if (toks.len > 4) toks[4] else "",
                });
            },
            .list => {
                // list <name> ["meaning"]
                const name = toks[1];
                if (name.len == 0 or std.mem.indexOfScalar(u8, name, '.') != null) {
                    try deferBad(&deferred, alloc, bd, "line {d}: list name {s} is empty or holds a dot", .{ lineno, name });
                    continue;
                }
                if (m.index.contains(name) or m.lists.contains(name)) {
                    try deferBad(&deferred, alloc, E.@"duplicate-key", "list {s}: the name appears twice", .{name});
                    continue;
                }
                try m.lists.put(name, {});
            },
            .derive => {
                // refused on its own text: a line error (ruling 32 of 0.8)
                if (!deriveShapeOk(toks)) {
                    try deferBad(&deferred, alloc, bd, "derive {s}: the function, its parameter or its argument count does not fit", .{if (toks.len > 1) toks[1] else ""});
                    continue;
                }
                try m.derive_lines.append(try alloc.dupe([]const u8, toks));
            },
        }
    }
    if (deferred) |d| {
        diag.msg = d.msg;
        return d.err;
    }
    if (m.name.len == 0) return bad(diag, alloc, E.@"missing-module", "the module has no module line", .{});
    if (!have_version) return bad(diag, alloc, E.@"missing-version", "module {s} has no version line", .{m.name});
    if (m.distribution == null) return bad(diag, alloc, E.@"missing-distribution", "module {s} has no distribution line", .{m.name});
    if (m.sources.items.len == 0) return bad(diag, alloc, E.@"missing-source", "module {s} has no source line", .{m.name});
    return m;
}

// The `derive` checks of a module on keys and types, run once the whole file
// is read (a line may name a key the file declares further down) and after
// the module's distribution and `uses` checks (ruling 29 of 0.8).
fn checkDerives(alloc: std.mem.Allocator, m: *Module, mods: *const ModuleMap, diag: *Diag) anyerror!void {
    for (m.derive_lines.items) |toks| {
        // an argument of a used module that is not loaded: `unknown-module`
        if (toks.len >= 4) for (toks[3..]) |a| {
            const ref = splitKey(a);
            if (!std.mem.eql(u8, ref.module, m.name) and m.usesModule(ref.module) and !mods.contains(ref.module)) {
                return bad(diag, alloc, E.@"unknown-module", "module {s} is not loaded", .{ref.module});
            }
        };
        const d = resolveDerive(alloc, m, mods, toks) orelse
            return bad(diag, alloc, E.@"bad-directive", "derive {s}: the keys or types do not fit the function", .{if (toks.len > 1) toks[1] else ""});
        try m.derives.append(d);
    }
}

// Resolve one line against the pack's wire: parse its locator, check its
// transform belongs to the wire, check the bit length its transform allows.
fn finalizeLine(alloc: std.mem.Allocator, p: *Pack, ln: *Line, in_group: bool, diag: *Diag) anyerror!void {
    // `.`: the item itself as a scalar, inside a group only
    if (std.mem.eql(u8, ln.locator, ".") and (p.wire == .json or p.wire == .geojson or p.wire == .protobuf)) {
        if (!in_group) return bad(diag, alloc, E.@"bad-directive", "line {d}: the locator `.` outside a group", .{ln.lineno});
        ln.dot = true;
    }
    if (ln.dot and ln.tag == .constant) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: const on the item itself (`.`)", .{ln.lineno});
    }
    if (ln.isField() and p.wire == .text) {
        // on `text`: the text transforms but `bool`, and the transforms of
        // the wire (Version 0.10)
        const kc = kindCategory(ln.transform.kind);
        if ((kc != .text and kc != .rec) or ln.transform.kind == .bool_) {
            return bad(diag, alloc, E.@"bad-directive", "line {d}: the transform of {s} is not valid on the text wire", .{ ln.lineno, ln.key });
        }
    } else if (ln.isField() and kindCategory(ln.transform.kind) == .rec) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: the transform of {s} is valid only on the text wire", .{ ln.lineno, ln.key });
    } else if (ln.isField() and wireCategory(p.wire) != kindCategory(ln.transform.kind)) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: transform of {s} does not belong to wire {s}", .{ ln.lineno, ln.key, @tagName(p.wire) });
    }
    if (ln.isField() and ln.transform.kind == .bool_ and p.wire != .json) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: bool is valid only on the json wire", .{ln.lineno});
    }
    // `const <locator> present` writes nothing: refused; `=present` is the text
    if (ln.tag == .constant and std.mem.eql(u8, ln.wraw, "present")) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: const {s} present", .{ ln.lineno, ln.locator });
    }
    // field options: an option on a wire or transform it does not apply to
    if (p.wire == .text and (ln.swap or ln.trim)) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: swap and trim are not options of the text wire", .{ln.lineno});
    }
    if (p.wire == .text and ln.optional and in_group) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: optional inside a group of the text wire", .{ln.lineno});
    }
    if (p.wire != .bits and p.wire != .text and (ln.swap or ln.trim or ln.optional)) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: swap, trim and optional are for the bits wire", .{ln.lineno});
    }
    if (ln.trim and ln.transform.kind != .ascii) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: trim is for the ascii transform", .{ln.lineno});
    }
    if (ln.via_name.len > 0) {
        ln.via = p.tables.get(ln.via_name) orelse
            return bad(diag, alloc, E.@"bad-directive", "line {d}: via {s} names a table with no map line", .{ ln.lineno, ln.via_name });
    }
    switch (p.wire) {
        .bits => {
            var it = std.mem.splitScalar(u8, ln.locator, ':');
            const ws = it.next() orelse "";
            const ps = it.next() orelse "";
            const ls = it.next() orelse "";
            const w = parseUnsigned(ws);
            const ps_v = parseUnsigned(ps);
            const l = parseUnsigned(ls);
            if (allDigits(ln.locator)) {
                return bad(diag, alloc, E.@"bad-directive", "line {d}: {s} is a bit length; a fixed-layout pack takes <word>:<pos>:<len>", .{ ln.lineno, ln.locator });
            }
            if (w == null or ps_v == null or l == null or it.next() != null) {
                return bad(diag, alloc, E.@"bad-locator", "line {d}: bits locator {s} is not <word>:<pos>:<len>", .{ ln.lineno, ln.locator });
            }
            ln.bstart = @as(usize, @intCast(w.?)) * p.word_bytes * 8 + @as(usize, @intCast(ps_v.?));
            ln.blen = @intCast(l.?);
            if (ln.isFixed()) {
                if (ln.blen < 1 or ln.blen > 64) {
                    return bad(diag, alloc, E.@"bad-directive", "line {d}: bit length {d} is not 1..64", .{ ln.lineno, ln.blen });
                }
                const v = parseUnsigned(ln.wraw) orelse
                    return bad(diag, alloc, E.@"bad-directive", "line {d}: value {s} is not an unsigned decimal integer", .{ ln.lineno, ln.wraw });
                if (ln.blen < 64 and (v >> @as(u6, @intCast(ln.blen))) != 0) {
                    return bad(diag, alloc, E.@"bad-directive", "line {d}: value {d} does not fit {d} bits", .{ ln.lineno, v, ln.blen });
                }
                ln.wint = v;
            } else {
                const ok = switch (ln.transform.kind) {
                    .f32_ => ln.blen == 32,
                    .f64_ => ln.blen == 64,
                    .ascii => ln.blen >= 8 and ln.blen <= 2040 and ln.blen % 8 == 0,
                    else => ln.blen >= 1 and ln.blen <= 64,
                };
                if (!ok) {
                    return bad(diag, alloc, E.@"bad-directive", "line {d}: bit length {d} is not allowed for the transform of {s}", .{ ln.lineno, ln.blen, ln.key });
                }
                if (ln.swap and ln.blen % 8 != 0) {
                    return bad(diag, alloc, E.@"bad-directive", "line {d}: swap needs a bit length that is a multiple of 8, not {d}", .{ ln.lineno, ln.blen });
                }
            }
        },
        .protobuf => {
            if (!ln.dot) {
                ln.ppath = parsePbPath(alloc, ln.locator) catch |err| switch (err) {
                    error.OutOfMemory => return err,
                    else => return bad(diag, alloc, E.@"bad-directive", "line {d}: protobuf path {s} is not field numbers separated by dots", .{ ln.lineno, ln.locator }),
                };
            }
            if (ln.isFixed()) {
                if (std.mem.eql(u8, ln.wraw, "present")) {
                    ln.wpresent = true;
                } else {
                    ln.wint = parseUnsigned(ln.wraw) orelse
                        return bad(diag, alloc, E.@"bad-directive", "line {d}: value {s} is not `present` or an unsigned decimal integer", .{ ln.lineno, ln.wraw });
                }
            }
        },
        .xml, .geojson, .json => {
            if (ln.isFixed()) {
                if (std.mem.eql(u8, ln.wraw, "present")) {
                    ln.wpresent = true;
                } else if (ln.wraw.len > 0 and ln.wraw[0] == '=') {
                    ln.wforced = true;
                    ln.wtext = ln.wraw[1..];
                } else {
                    ln.wtext = ln.wraw;
                }
            }
            // json, and geojson inside an item: a member path
            if ((p.wire == .json or (p.wire == .geojson and in_group)) and !ln.dot) {
                ln.segs = try splitSegs(alloc, ln.locator, '.');
            }
        },
        .text => try textFinalizeLine(alloc, p, ln, diag),
    }
    if (ln.isField() and !ln.abs_checked) try parseAbsent(alloc, p.wire, ln, in_group, diag);
}

// Is the text a JSON number (RFC 8259): -?(0|[1-9][0-9]*)(.[0-9]+)?([eE][+-]?[0-9]+)?
fn isJsonNumber(s: []const u8) bool {
    var i: usize = 0;
    if (i < s.len and s[i] == '-') i += 1;
    if (i >= s.len) return false;
    if (s[i] == '0') {
        i += 1;
    } else if (s[i] >= '1' and s[i] <= '9') {
        while (i < s.len and isDigit(s[i])) i += 1;
    } else return false;
    if (i < s.len and s[i] == '.') {
        i += 1;
        const from = i;
        while (i < s.len and isDigit(s[i])) i += 1;
        if (i == from) return false;
    }
    if (i < s.len and (s[i] == 'e' or s[i] == 'E')) {
        i += 1;
        if (i < s.len and (s[i] == '+' or s[i] == '-')) i += 1;
        const from = i;
        while (i < s.len and isDigit(s[i])) i += 1;
        if (i == from) return false;
    }
    return i == s.len;
}

// Version 0.9: the sentinels of a field's `absent` option, read against the
// wire and transform of the line (and its bit length on `bits`).
fn parseAbsent(alloc: std.mem.Allocator, wire: Wire, ln: *Line, in_group: bool, diag: *Diag) anyerror!void {
    const raw = ln.absent_raw orelse return;
    const bd = E.@"bad-directive";
    const no = ln.lineno;
    // ruling 16 of 0.10: `absent` on the text wire is not stated yet
    if (wire == .text) return lineBad(diag, alloc, bd, "line {d}: absent is not an option of the text wire", .{no});
    if (std.mem.indexOfScalar(u8, raw, '"') != null) {
        return lineBad(diag, alloc, bd, "line {d}: an absent value holds a double quote", .{no});
    }
    // the quoted empty token `""` is the one value "the empty text"
    var vals = std.ArrayList([]const u8).init(alloc);
    if (raw.len == 0) {
        try vals.append("");
    } else {
        var it = std.mem.splitScalar(u8, raw, ',');
        while (it.next()) |v| {
            if (v.len == 0) return lineBad(diag, alloc, bd, "line {d}: absent {s} holds an empty value", .{ no, raw });
            try vals.append(v);
        }
    }
    const k = ln.transform.kind;
    if (wire == .bits or (wire == .protobuf and k != .pstring)) {
        // the raw value is an unsigned integer of the field's width
        if (wire == .bits and ln.blen > 64) {
            return lineBad(diag, alloc, bd, "line {d}: absent on a bits field of {d} bits; at most 64", .{ no, ln.blen });
        }
        const width: usize = if (wire == .bits) ln.blen else if (k == .pfloat) 32 else 64;
        const ints = try alloc.alloc(u64, vals.items.len);
        for (vals.items, 0..) |v, i| {
            const x = parseUnsigned(v) orelse
                return lineBad(diag, alloc, bd, "line {d}: absent value `{s}` is not an unsigned decimal integer", .{ no, v });
            if (!fitsBits(x, width)) return lineBad(diag, alloc, bd, "line {d}: absent value {s} does not fit {d} bits", .{ no, v, width });
            ints[i] = x;
        }
        ln.abs_ints = ints;
    } else if (wire == .protobuf) {
        // pstring: the text as written, `=` included (ruling 12)
        ln.abs_texts = vals.items;
    } else {
        // a `geojson` coordinate outside a group takes number text only (ruling 25)
        const coord = wire == .geojson and !in_group and std.mem.startsWith(u8, ln.locator, geom_prefix);
        const texts = try alloc.alloc([]const u8, vals.items.len);
        for (vals.items, 0..) |v, i| {
            const forced = v.len > 0 and v[0] == '=';
            const t = if (forced) v[1..] else v;
            if (t.len == 0 and raw.len != 0) {
                return lineBad(diag, alloc, bd, "line {d}: absent value `{s}` is empty after its `=`; the empty text is `\"\"`", .{ no, v });
            }
            if (wire == .xml) {
                texts[i] = t;
                continue;
            }
            // json, geojson: typed as a `when` value is written (rulings 9, 13)
            var jtext: []const u8 = undefined;
            var is_bool = false;
            if (!forced and std.mem.eql(u8, t, "null")) {
                return lineBad(diag, alloc, bd, "line {d}: absent null; a member whose value is null is absent already", .{no});
            } else if (!forced and (std.mem.eql(u8, t, "true") or std.mem.eql(u8, t, "false"))) {
                is_bool = true;
                texts[i] = t;
                jtext = t;
            } else if (!forced and isJsonNumber(t)) {
                const f = std.fmt.parseFloat(f64, t) catch
                    return lineBad(diag, alloc, bd, "line {d}: absent value {s} is not a number", .{ no, t });
                if (!std.math.isFinite(f)) return lineBad(diag, alloc, bd, "line {d}: absent value {s} does not fit a double", .{ no, t });
                texts[i] = try floatToStr(alloc, f);
                jtext = texts[i];
            } else {
                texts[i] = t;
                jtext = try jsonStr(alloc, t);
            }
            if (coord and !(!forced and isJsonNumber(t))) {
                return lineBad(diag, alloc, bd, "line {d}: absent value `{s}` on the coordinate {s} is not number text", .{ no, v, ln.locator });
            }
            if (k == .bool_ and !is_bool) {
                return lineBad(diag, alloc, bd, "line {d}: absent value `{s}` on the bool transform is not true or false", .{ no, v });
            }
            if (i == 0) ln.abs_json = jtext;
        }
        ln.abs_texts = texts;
    }
    ln.abs_set = true;
}

fn absentText(ln: *const Line, text: []const u8) bool {
    for (ln.abs_texts) |t| if (std.mem.eql(u8, t, text)) return true;
    return false;
}

fn absentInt(ln: *const Line, v: u64) bool {
    for (ln.abs_ints) |x| if (x == v) return true;
    return false;
}

fn splitSegs(alloc: std.mem.Allocator, text: []const u8, sep: u8) ![]const []const u8 {
    var segs = std.ArrayList([]const u8).init(alloc);
    var it = std.mem.splitScalar(u8, text, sep);
    while (it.next()) |seg| try segs.append(seg);
    return segs.toOwnedSlice();
}

fn parsePbPath(alloc: std.mem.Allocator, text: []const u8) ![]const usize {
    var nums = std.ArrayList(usize).init(alloc);
    var it = std.mem.splitScalar(u8, text, '.');
    while (it.next()) |seg| {
        const n = parseUnsigned(seg) orelse return E.@"bad-directive";
        if (n == 0 or n > 0x1fffffff) return E.@"bad-directive";
        try nums.append(@intCast(n));
    }
    return nums.toOwnedSlice();
}

// `<a>:<b>` or `<a>:<b>:<c>`: exactly `n` unsigned decimal integers.
fn parseColons(text: []const u8, comptime n: usize) ?[n]usize {
    var out: [n]usize = undefined;
    var it = std.mem.splitScalar(u8, text, ':');
    for (0..n) |i| {
        const v = parseUnsigned(it.next() orelse return null) orelse return null;
        if (v > 1 << 40) return null;
        out[i] = @intCast(v);
    }
    if (it.next() != null) return null;
    return out;
}

fn finalizeLines(alloc: std.mem.Allocator, p: *Pack, lines: []Line, in_group: bool, diag: *Diag) anyerror!void {
    for (lines) |*ln| {
        if (ln.tag == .group) {
            try finalizeGroup(alloc, p, ln.grp.?, in_group, diag);
        } else {
            try finalizeLine(alloc, p, ln, in_group, diag);
        }
    }
}

// Resolve a group against the pack's wire: its locator, `item` and `count`,
// then the lines of its body.
fn finalizeGroup(alloc: std.mem.Allocator, p: *Pack, g: *Group, nested: bool, diag: *Diag) anyerror!void {
    const bd = E.@"bad-directive";
    if (p.wire == .text) return textFinalizeGroup(alloc, p, g, nested, diag);
    if (p.wire != .bits and (g.count_txt != null or g.item_txt != null)) {
        return bad(diag, alloc, bd, "line {d}: `item` and `count` are for the bits wire, not {s}", .{ g.lineno, @tagName(p.wire) });
    }
    switch (p.wire) {
        .xml => {
            const names = try splitSegs(alloc, g.locator, '/');
            for (names) |nm| {
                if (nm.len == 0 or nm[0] == '@' or nm[0] == '#') {
                    return bad(diag, alloc, bd, "line {d}: group locator {s} is not a path of element names", .{ g.lineno, g.locator });
                }
            }
            g.xname = names[names.len - 1];
            g.xpath = names[0 .. names.len - 1];
        },
        .json, .geojson => {
            g.segs = try splitSegs(alloc, g.locator, '.');
            for (g.segs) |seg| {
                if (seg.len == 0) return bad(diag, alloc, bd, "line {d}: group locator {s} is not a member path", .{ g.lineno, g.locator });
            }
            if (p.wire == .geojson and !nested) {
                // a `properties.<name>` member or a top-level member
                const in_props = std.mem.startsWith(u8, g.locator, props_prefix);
                const name = if (in_props) g.locator[props_prefix.len..] else g.locator;
                const reserved = !in_props and (std.mem.eql(u8, name, "type") or std.mem.eql(u8, name, "geometry") or std.mem.eql(u8, name, "properties"));
                if (std.mem.indexOfScalar(u8, name, '.') != null or reserved) {
                    return bad(diag, alloc, bd, "line {d}: group locator {s} is not `properties.<name>` or a top-level member", .{ g.lineno, g.locator });
                }
            }
        },
        .protobuf => {
            g.ppath = parsePbPath(alloc, g.locator) catch |err| switch (err) {
                error.OutOfMemory => return err,
                else => return bad(diag, alloc, bd, "line {d}: group locator {s} is not field numbers separated by dots", .{ g.lineno, g.locator }),
            };
        },
        .bits => {
            const at = parseColons(g.locator, 2) orelse
                return bad(diag, alloc, bd, "line {d}: group locator {s} is not <word>:<pos>", .{ g.lineno, g.locator });
            g.gstart = at[0] * p.word_bytes * 8 + at[1];
            const item_txt = g.item_txt orelse
                return bad(diag, alloc, bd, "line {d}: a bits group needs `item <bits>`", .{g.lineno});
            const ib = parseUnsigned(item_txt) orelse 0;
            if (ib == 0 or ib > 1 << 40) return bad(diag, alloc, bd, "line {d}: item {s} is not a positive number of bits", .{ g.lineno, item_txt });
            g.item_bits = @intCast(ib);
            const count_txt = g.count_txt orelse
                return bad(diag, alloc, bd, "line {d}: a bits group needs `count`", .{g.lineno});
            if (std.mem.indexOfScalar(u8, count_txt, ':') != null) {
                const c = parseColons(count_txt, 3) orelse
                    return bad(diag, alloc, bd, "line {d}: count locator {s} is not <word>:<pos>:<len>", .{ g.lineno, count_txt });
                if (c[2] < 1 or c[2] > 64) return bad(diag, alloc, bd, "line {d}: count locator {s}: the bit length is not 1..64", .{ g.lineno, count_txt });
                g.cstart = c[0] * p.word_bytes * 8 + c[1];
                g.clen = c[2];
            } else {
                const n = parseUnsigned(count_txt) orelse
                    return bad(diag, alloc, bd, "line {d}: count {s} is not a count locator or a number", .{ g.lineno, count_txt });
                if (n > 1 << 32) return bad(diag, alloc, bd, "line {d}: count {s} is too large", .{ g.lineno, count_txt });
                g.count_fixed = @intCast(n);
            }
        },
        .text => unreachable,
    }
    try finalizeLines(alloc, p, g.lines, true, diag);
    if (p.wire == .protobuf) {
        // a body is scalar only when every line is `.`
        var has_dot = false;
        var has_path = false;
        for (g.lines) |*ln| {
            if (ln.tag != .group and ln.dot) has_dot = true else has_path = true;
        }
        if (has_dot and has_path) {
            return bad(diag, alloc, bd, "line {d}: the body of group {s} mixes `.` with paths", .{ g.lineno, g.list });
        }
    }
}

// Does a `field` locator pass through the path of a group of its scope?
fn passesThrough(p: *const Pack, f: *const Line, g: *const Group, in_item: bool) bool {
    switch (p.wire) {
        .xml => {
            // the element path of the field: its locator less the final
            // `@name` or `#text`
            var it = std.mem.splitScalar(u8, f.locator, '/');
            var gi: usize = 0;
            const gn = g.xpath.len + 1;
            while (it.next()) |seg| {
                if (seg.len > 0 and (seg[0] == '@' or seg[0] == '#')) return false;
                const want = if (gi < g.xpath.len) g.xpath[gi] else g.xname;
                if (!std.mem.eql(u8, seg, want)) return false;
                gi += 1;
                if (gi == gn) return true;
            }
            return false;
        },
        .json, .geojson => {
            if (p.wire == .geojson and !in_item) {
                return f.locator.len > g.locator.len and std.mem.startsWith(u8, f.locator, g.locator) and f.locator[g.locator.len] == '.';
            }
            if (f.dot or f.segs.len <= g.segs.len) return false;
            for (g.segs, 0..) |seg, i| if (!std.mem.eql(u8, seg, f.segs[i])) return false;
            return true;
        },
        .protobuf => {
            if (f.dot or f.ppath.len <= g.ppath.len) return false;
            for (g.ppath, 0..) |n, i| if (n != f.ppath[i]) return false;
            return true;
        },
        .bits, .text => return false,
    }
}

// Checks over one scope: the lines `a` then `b` (common plus one kind, or one
// group body). A list is mapped by at most one group. On `bits`: a group
// counted by a locator is the last thing in its scope, and inside an item
// nothing of fixed size reaches beyond `item <bits>`.
fn checkScope(alloc: std.mem.Allocator, p: *const Pack, a: []const Line, b: []const Line, item_bits: ?usize, item_scope: bool, diag: *Diag) anyerror!void {
    const bd = E.@"bad-directive";
    const both = [2][]const Line{ a, b };
    var seen = std.StringHashMap(void).init(alloc);
    defer seen.deinit();
    var n_var: usize = 0;
    for (both) |lines| for (lines) |*ln| {
        if (ln.tag != .group) continue;
        const gop = try seen.getOrPut(ln.key);
        if (gop.found_existing) return bad(diag, alloc, bd, "line {d}: the list {s} is mapped by two groups of one scope", .{ ln.lineno, ln.key });
        if (ln.grp.?.count_fixed == null) n_var += 1;
    };
    // a `field` whose locator passes through a group's path
    for (both) |glines| for (glines) |*gl| {
        if (gl.tag != .group) continue;
        for (both) |lines| for (lines) |*ln| {
            if (ln.tag == .field and passesThrough(p, ln, gl.grp.?, item_scope)) {
                return bad(diag, alloc, bd, "line {d}: the locator {s} passes through the path of the group on line {d}", .{ ln.lineno, ln.locator, gl.lineno });
            }
        };
    };
    if (p.wire != .bits) return;
    if (n_var > 0) {
        for (both) |glines| for (glines) |*gl| {
            if (gl.tag != .group) continue;
            const g = gl.grp.?;
            if (g.count_fixed != null) continue;
            if (g.cstart + g.clen > g.gstart) {
                return bad(diag, alloc, bd, "line {d}: the count locator reaches the start of its group", .{g.lineno});
            }
            for (both) |lines| for (lines) |*ln| {
                if (ln.tag == .group) {
                    const g2 = ln.grp.?;
                    if (g2 != g and g2.gstart >= g.gstart) {
                        return bad(diag, alloc, bd, "line {d}: a group at or beyond the start of the group counted by a locator on line {d}", .{ ln.lineno, g.lineno });
                    }
                    // a fixed-count group that starts before it and whose
                    // items reach its start
                    if (g2.count_fixed) |n2| {
                        if (g2.gstart + n2 * g2.item_bits > g.gstart) {
                            return bad(diag, alloc, bd, "line {d}: the items of a fixed-count group reach the start of the group counted by a locator on line {d}", .{ ln.lineno, g.lineno });
                        }
                    }
                } else if (ln.bstart + ln.blen > g.gstart) {
                    return bad(diag, alloc, bd, "line {d}: bits at or beyond the start of the group counted by a locator on line {d}", .{ ln.lineno, g.lineno });
                }
            };
        };
    }
    if (item_bits) |ib| {
        for (both) |lines| for (lines) |*ln| {
            if (ln.tag == .group) {
                const g = ln.grp.?;
                const n = g.count_fixed orelse {
                    // a nested group's count locator is bounded by `item <bits>`
                    if (g.cstart + g.clen > ib) {
                        return bad(diag, alloc, bd, "line {d}: the count locator of a nested group reaches beyond item {d}", .{ ln.lineno, ib });
                    }
                    continue;
                };
                if (g.gstart + n * g.item_bits > ib) {
                    return bad(diag, alloc, bd, "line {d}: a nested group with a fixed count reaches beyond item {d}", .{ ln.lineno, ib });
                }
            } else if (ln.bstart + ln.blen > ib) {
                return bad(diag, alloc, bd, "line {d}: a field of an item reaches beyond item {d}", .{ ln.lineno, ib });
            }
        };
    }
}

fn checkGroupBodies(alloc: std.mem.Allocator, p: *const Pack, lines: []const Line, diag: *Diag) anyerror!void {
    for (lines) |*ln| {
        if (ln.tag != .group) continue;
        const g = ln.grp.?;
        try checkScope(alloc, p, g.lines, &.{}, if (p.wire == .bits) g.item_bits else null, true, diag);
        try checkGroupBodies(alloc, p, g.lines, diag);
    }
}

// Where the next line of the file goes: the lines of the open groups (`gtmp`,
// cut into each group's own slice at its `end`), else the last kind, else the
// common lines.
fn curLines(p: *Pack, in_group: bool, gtmp: *std.ArrayList(Line)) *std.ArrayList(Line) {
    if (in_group) return gtmp;
    if (p.kinds.items.len == 0) return &p.common;
    return &p.kinds.items[p.kinds.items.len - 1].lines;
}

// The name `model_keys` lists a key or list under: each enclosing list as
// `<list>[].`, outermost first.
fn mkName(alloc: std.mem.Allocator, grp: ?*const Group, key: []const u8, is_list: bool) ![]const u8 {
    if (grp == null and !is_list) return key;
    var chain = std.ArrayList(*const Group).init(alloc);
    var g = grp;
    while (g) |gp| : (g = gp.parent) try chain.append(gp);
    var buf = std.ArrayList(u8).init(alloc);
    var i: usize = chain.items.len;
    while (i > 0) {
        i -= 1;
        try buf.appendSlice(chain.items[i].list);
        try buf.appendSlice("[].");
    }
    try buf.appendSlice(key);
    if (is_list) try buf.appendSlice("[]");
    return buf.toOwnedSlice();
}

fn newPack(alloc: std.mem.Allocator) !*Pack {
    const p = try alloc.create(Pack);
    p.* = .{
        .format = "",
        .version = "",
        .wire = .xml,
        .common = std.ArrayList(Line).init(alloc),
        .kinds = std.ArrayList(Kind).init(alloc),
        .common_defaults = std.ArrayList(Default).init(alloc),
        .tables = std.StringHashMap(*Table).init(alloc),
        .root_index = std.StringHashMap(std.ArrayList(usize)).init(alloc),
        .key_uses = std.ArrayList(KeyUse).init(alloc),
        .tm_nat2cot = std.StringHashMap([]const u8).init(alloc),
        .tm_cot2nat = std.StringHashMap([]const u8).init(alloc),
        .sources = std.ArrayList([]const u8).init(alloc),
        .uses = std.ArrayList([]const u8).init(alloc),
    };
    return p;
}

// The type of each table's `<model>` side.
fn setTableTypes(p: *Pack) void {
    var tit = p.tables.valueIterator();
    while (tit.next()) |tp| {
        var all_int = true;
        var all_num = true;
        for (tp.*.entries.items) |en| {
            if (std.meta.isError(parseDecimalInt(en.model))) all_int = false;
            if (std.meta.isError(parseDecimal(en.model))) all_num = false;
        }
        tp.*.model_ty = if (all_int) .int else if (all_num) .float else .string;
    }
}

// Ruling 5a of 0.11: does a `field`, `when` or `const` locator have the form
// its line takes on the wire? false: `bad-locator`. The cases earlier versions
// name (`.` outside a group, a bit length in a fixed-layout pack, a
// `<word>:<pos>:<len>` locator in a sequential pack) pass here and stay
// `bad-directive`; the `text` wire has no `bad-locator`.
fn locatorFormOk(wire: Wire, sequential: bool, loc: []const u8, in_group: bool) bool {
    switch (wire) {
        .xml => {
            var it = std.mem.splitScalar(u8, loc, '/');
            var last: []const u8 = "";
            var after_leaf = false;
            while (it.next()) |seg| {
                if (seg.len == 0 or after_leaf) return false;
                if (seg[0] == '@') {
                    if (seg.len == 1) return false;
                    after_leaf = true;
                } else if (std.mem.eql(u8, seg, "#text")) after_leaf = true;
                last = seg;
            }
            return after_leaf;
        },
        .json, .geojson => {
            if (std.mem.eql(u8, loc, ".")) return true;
            var it = std.mem.splitScalar(u8, loc, '.');
            while (it.next()) |seg| if (seg.len == 0) return false;
            if (wire == .geojson and !in_group and std.mem.startsWith(u8, loc, "geometry.")) {
                const slot = loc["geometry.".len..];
                return std.mem.eql(u8, slot, "lon") or std.mem.eql(u8, slot, "lat") or std.mem.eql(u8, slot, "alt");
            }
            return true;
        },
        .protobuf => {
            if (std.mem.eql(u8, loc, ".")) return true;
            var it = std.mem.splitScalar(u8, loc, '.');
            while (it.next()) |seg| {
                const v = parseUnsigned(seg) orelse return false;
                if (v == 0 or v > 536870911) return false;
            }
            return true;
        },
        .bits => {
            if (sequential) {
                if (std.mem.indexOfScalar(u8, loc, ':') != null) return true;
                if (!allDigits(loc)) return false;
                const v = parseUnsigned(loc) orelse return true;
                return v != 0;
            }
            // text with no `:` is a bit length (`bad-directive` later) or
            // not a locator at all
            if (std.mem.indexOfScalar(u8, loc, ':') == null) return allDigits(loc);
            var it = std.mem.splitScalar(u8, loc, ':');
            var parts: usize = 0;
            var len_v: ?u64 = null;
            while (it.next()) |seg| {
                parts += 1;
                if (!allDigits(seg)) return false;
                len_v = parseUnsigned(seg);
            }
            if (parts != 3) return false;
            // digits too many for 64 bits: a length far above any transform's
            if (len_v) |l| return l != 0;
            return true;
        },
        .text => return true,
    }
}

// Ruling 5a of 0.11 on a `group` line: an empty step or member name, and on
// `protobuf` a step that is not a field number, are `bad-locator`.
fn groupLocatorFormOk(wire: Wire, loc: []const u8) bool {
    const sep: u8 = switch (wire) {
        .xml => '/',
        .json, .geojson, .protobuf => '.',
        .bits, .text => return true,
    };
    var it = std.mem.splitScalar(u8, loc, sep);
    while (it.next()) |seg| {
        if (seg.len == 0) return false;
        if (wire == .protobuf) {
            const v = parseUnsigned(seg) orelse return false;
            if (v == 0 or v > 536870911) return false;
        }
    }
    return true;
}

// The bit length of a fixed-layout locator `<word>:<pos>:<len>`, null when it
// has another form.
fn fixedLen(loc: []const u8) ?u64 {
    var it = std.mem.splitScalar(u8, loc, ':');
    _ = it.next() orelse return null;
    _ = it.next() orelse return null;
    const l = parseUnsigned(it.next() orelse return null) orelse return null;
    if (it.next() != null) return null;
    return l;
}

// The directives of a pack (ruling 5 of 0.11).
const PackDir = enum { format, version, distribution, source, uses, wire, root, field, when, @"const", kind, requires, default, map, typemap, group, end, word_bytes, bit_order, layout, also, pad, @"align", presence, @"if", opt, chain, fx, length, delimiter, start, checksum };

// The header lines a pack has given so far, for the line checks.
const HeaderSeen = struct {
    format: bool = false,
    version: bool = false,
    wire: bool = false,
    distribution: bool = false,
    // a line of the list that must follow `layout sequential` has been read
    wire_line: bool = false,
};

// Does the directive stand after the `wire` line (ruling 5b of 0.11)?
fn needsWire(d: PackDir) bool {
    return switch (d) {
        .root, .field, .when, .@"const", .group, .end, .word_bytes, .bit_order, .layout, .also, .pad, .@"align", .presence, .@"if", .opt, .chain, .fx, .length => true,
        else => false,
    };
}

// The line checks of a pack that do not depend on the layout, in the order of
// ruling 5b of 0.11: the directive (`unknown-directive`), the number of
// arguments (5e), `missing-wire`, a repeated header line, the `wire` and
// `distribution` values.
fn packLineChecks(alloc: std.mem.Allocator, toks: []const []const u8, lineno: usize, hdr: *HeaderSeen, diag: *Diag) anyerror!void {
    const bd = E.@"bad-directive";
    const kw = toks[0];
    const d = std.meta.stringToEnum(PackDir, kw) orelse
        return lineBad(diag, alloc, E.@"unknown-directive", "line {d}: unknown directive {s}", .{ lineno, kw });
    const n = toks.len - 1;
    const ok = switch (d) {
        .format, .version, .distribution, .source, .uses, .wire, .root, .kind, .word_bytes, .bit_order, .layout, .pad, .@"align", .delimiter, .start, .checksum => n == 1,
        .field => n >= 3,
        .when, .@"const", .default, .typemap => n == 2,
        .map => n == 3,
        .requires, .@"if", .length => n >= 1,
        .group => n >= 2,
        .presence => n == 2,
        .also => n == 1 or n == 3,
        .end, .opt, .chain, .fx => n == 0,
    };
    if (!ok) return lineBad(diag, alloc, bd, "line {d}: {s} takes another number of arguments", .{ lineno, kw });
    if (needsWire(d) and !hdr.wire) {
        return lineBad(diag, alloc, E.@"missing-wire", "line {d}: {s} stands before the wire line", .{ lineno, kw });
    }
    const slot: ?*bool = switch (d) {
        .format => &hdr.format,
        .version => &hdr.version,
        .wire => &hdr.wire,
        .distribution => &hdr.distribution,
        else => null,
    };
    if (slot) |sl| {
        if (sl.*) return lineBad(diag, alloc, bd, "line {d}: a second {s} line", .{ lineno, kw });
        sl.* = true;
    }
    if (d == .wire and std.meta.stringToEnum(Wire, toks[1]) == null) {
        return lineBad(diag, alloc, E.@"unknown-wire", "line {d}: unknown wire {s}", .{ lineno, toks[1] });
    }
    if (d == .distribution) _ = parseDist(toks[1]) catch |err|
        return lineBad(diag, alloc, err, "line {d}: distribution {s} is not public or controlled", .{ lineno, toks[1] });
}

// After the file is read: `missing-format`, `missing-version`, `missing-wire`
// (ruling 5b of 0.11).
fn headerChecks(alloc: std.mem.Allocator, hdr: HeaderSeen, diag: *Diag) anyerror!void {
    if (!hdr.format) return bad(diag, alloc, E.@"missing-format", "the pack has no format line", .{});
    if (!hdr.version) return bad(diag, alloc, E.@"missing-version", "the pack has no version line", .{});
    if (!hdr.wire) return bad(diag, alloc, E.@"missing-wire", "the pack has no wire line", .{});
}

// The state of a fixed-layout pack while its lines are read.
const FState = struct {
    alloc: std.mem.Allocator,
    diag: *Diag,
    p: *Pack,
    any_when: bool = false,
    kind_root: bool = false,
    gstack: std.ArrayList(*Group),
    gtmp: std.ArrayList(Line),
    gfrom: std.ArrayList(usize),
    gline: std.ArrayList(Line),
    lineno: usize = 0,
};

// One line of a fixed-layout pack, after the line checks of steps 1 to 6.
fn fixedLine(st: *FState, toks: []const []const u8) anyerror!void {
    const alloc = st.alloc;
    const diag = st.diag;
    const p = st.p;
    const gstack = &st.gstack;
    const gtmp = &st.gtmp;
    const gfrom = &st.gfrom;
    const gline = &st.gline;
    const lineno = st.lineno;
    const kw = toks[0];
    const is = struct {
        fn f(x: []const u8, y: []const u8) bool {
            return std.mem.eql(u8, x, y);
        }
    }.f;
    const in_group = gstack.items.len > 0;
    // inside a group: `field`, `const`, `default`, `group` and `end` only
    if (in_group and !(is(kw, "field") or is(kw, "const") or is(kw, "default") or is(kw, "group") or is(kw, "end"))) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: {s} inside a group", .{ lineno, kw });
    }
    if (is(kw, "group")) {
        // group <list> <locator> [item <bits>] [count <count-locator | n>]
        if (toks.len < 3) return bad(diag, alloc, E.@"bad-directive", "line {d}: group takes a list and a locator", .{lineno});
        if (!groupLocatorFormOk(p.wire, toks[2])) {
            return lineBad(diag, alloc, E.@"bad-locator", "line {d}: group locator {s} has an empty step or a step that is not a field number", .{ lineno, toks[2] });
        }
        const g = try alloc.create(Group);
        g.* = .{
            .list = toks[1],
            .locator = toks[2],
            .lineno = lineno,
            .parent = if (in_group) gstack.items[gstack.items.len - 1] else null,
            .defaults = std.ArrayList(Default).init(alloc),
        };
        var oi: usize = 3;
        while (oi < toks.len) : (oi += 2) {
            const is_item = is(toks[oi], "item");
            if (!is_item and !is(toks[oi], "count")) return bad(diag, alloc, E.@"bad-directive", "line {d}: unknown group option {s}", .{ lineno, toks[oi] });
            const slot = if (is_item) &g.item_txt else &g.count_txt;
            if (oi + 1 >= toks.len or slot.* != null) return bad(diag, alloc, E.@"bad-directive", "line {d}: {s} takes one value, once", .{ lineno, toks[oi] });
            slot.* = toks[oi + 1];
        }
        try p.key_uses.append(.{ .key = toks[1], .tkind = null, .use = .group, .grp = g.parent });
        try gline.append(.{ .tag = .group, .key = toks[1], .locator = toks[2], .grp = g, .lineno = lineno });
        try gfrom.append(gtmp.items.len);
        try gstack.append(g);
    } else if (is(kw, "end")) {
        if (toks.len != 1) return bad(diag, alloc, E.@"bad-directive", "line {d}: end takes no argument", .{lineno});
        if (!in_group) return bad(diag, alloc, E.@"bad-directive", "line {d}: end with no open group", .{lineno});
        const g = gstack.pop();
        const from = gfrom.pop();
        g.lines = try alloc.dupe(Line, gtmp.items[from..]);
        gtmp.shrinkRetainingCapacity(from);
        try curLines(p, gstack.items.len > 0, gtmp).append(gline.pop());
    } else if (is(kw, "format")) {
        if (toks.len != 2) return bad(diag, alloc, E.@"bad-directive", "line {d}: format takes one argument", .{lineno});
        p.format = toks[1];
    } else if (is(kw, "version")) {
        if (toks.len != 2) return bad(diag, alloc, E.@"bad-directive", "line {d}: version takes one argument", .{lineno});
        p.version = toks[1];
    } else if (is(kw, "wire")) {
        if (toks.len != 2) return bad(diag, alloc, E.@"bad-directive", "line {d}: wire takes one argument", .{lineno});
        p.wire = std.meta.stringToEnum(Wire, toks[1]) orelse
            return bad(diag, alloc, E.@"unknown-wire", "line {d}: unknown wire {s}", .{ lineno, toks[1] });
    } else if (is(kw, "distribution")) {
        if (toks.len != 2) return bad(diag, alloc, E.@"bad-directive", "line {d}: distribution takes one argument", .{lineno});
        p.distribution = parseDist(toks[1]) catch |err|
            return bad(diag, alloc, err, "line {d}: distribution {s} is not public or controlled", .{ lineno, toks[1] });
    } else if (is(kw, "source")) {
        if (toks.len != 2) return bad(diag, alloc, E.@"bad-directive", "line {d}: source takes one argument", .{lineno});
        try p.sources.append(toks[1]);
    } else if (is(kw, "uses")) {
        if (toks.len != 2) return bad(diag, alloc, E.@"bad-directive", "line {d}: uses takes one argument", .{lineno});
        try p.uses.append(toks[1]);
    } else if (is(kw, "root")) {
        if (toks.len != 2) return bad(diag, alloc, E.@"bad-directive", "line {d}: root takes one argument", .{lineno});
        if (p.kinds.items.len == 0) {
            p.root = toks[1];
        } else {
            // inside a kind: that kind's root element (xml)
            p.kinds.items[p.kinds.items.len - 1].root = toks[1];
            st.kind_root = true;
        }
    } else if (is(kw, "word_bytes")) {
        if (toks.len != 2) return bad(diag, alloc, E.@"bad-directive", "line {d}: word_bytes takes one argument", .{lineno});
        const n = parseUnsigned(toks[1]) orelse 0;
        if (n == 0 or n > 1 << 20) return bad(diag, alloc, E.@"bad-directive", "line {d}: word_bytes {s} is not a positive integer", .{ lineno, toks[1] });
        p.word_bytes = @intCast(n);
    } else if (is(kw, "bit_order")) {
        if (toks.len != 2) return bad(diag, alloc, E.@"bad-directive", "line {d}: bit_order takes one argument", .{lineno});
        if (is(toks[1], "msb")) {
            p.msb = true;
        } else if (is(toks[1], "lsb")) {
            p.msb = false;
        } else return bad(diag, alloc, E.@"bad-directive", "line {d}: bit_order {s} is not lsb or msb", .{ lineno, toks[1] });
        p.bit_order_set = true;
    } else if (is(kw, "layout")) {
        // layout <fixed | sequential>, bits wire only; default fixed
        if (toks.len != 2 or !(is(toks[1], "fixed") or is(toks[1], "sequential"))) {
            return bad(diag, alloc, E.@"bad-directive", "line {d}: layout takes `fixed` or `sequential`", .{lineno});
        }
        p.layout_set = true;
    } else if (is(kw, "pad") or is(kw, "align") or is(kw, "presence") or is(kw, "if") or is(kw, "opt") or is(kw, "chain") or is(kw, "fx") or is(kw, "length") or is(kw, "also")) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: {s} is a line of a sequential pack (`layout sequential` on the bits wire)", .{ lineno, kw });
    } else if (is(kw, "typemap")) {
        if (toks.len != 3) return bad(diag, alloc, E.@"bad-directive", "line {d}: typemap takes two arguments", .{lineno});
        try p.tm_nat2cot.put(toks[1], toks[2]);
        try p.tm_cot2nat.put(toks[2], toks[1]);
    } else if (is(kw, "delimiter") or is(kw, "start") or is(kw, "checksum")) {
        // the `text` wire (Version 0.10): checked against the wire and
        // one another after the file is read
        if (toks.len != 2) return bad(diag, alloc, E.@"bad-directive", "line {d}: {s} takes one value", .{ lineno, kw });
        const slot = if (is(kw, "delimiter")) &p.delim_raw else if (is(kw, "start")) &p.start_raw else &p.cksum_raw;
        if ((slot.* != null or p.kinds.items.len > 0) and p.tdir_bad == 0) p.tdir_bad = lineno;
        slot.* = toks[1];
        p.text_dirs = true;
    } else if (is(kw, "kind")) {
        if (toks.len != 2) return bad(diag, alloc, E.@"bad-directive", "line {d}: kind takes one argument", .{lineno});
        if (p.kindIndex(toks[1]) != null) {
            return bad(diag, alloc, E.@"duplicate-kind", "line {d}: kind {s} is declared twice", .{ lineno, toks[1] });
        }
        try p.kinds.append(.{
            .name = toks[1],
            .lines = std.ArrayList(Line).init(alloc),
            .requires = std.ArrayList([]const u8).init(alloc),
            .defaults = std.ArrayList(Default).init(alloc),
        });
    } else if (is(kw, "requires")) {
        if (p.kinds.items.len == 0) {
            return bad(diag, alloc, E.@"bad-directive", "line {d}: requires before the first kind", .{lineno});
        }
        if (toks.len < 2) return bad(diag, alloc, E.@"bad-directive", "line {d}: requires takes at least one key", .{lineno});
        const k = &p.kinds.items[p.kinds.items.len - 1];
        for (toks[1..]) |key| {
            try k.requires.append(key);
            try p.key_uses.append(.{ .key = key, .tkind = null, .use = .requires });
        }
    } else if (is(kw, "when") or is(kw, "const")) {
        const is_when = is(kw, "when");
        if (toks.len != 3) return bad(diag, alloc, E.@"bad-directive", "line {d}: {s} takes a locator and a value", .{ lineno, kw });
        if (is_when) st.any_when = true;
        if (!locatorFormOk(p.wire, false, toks[1], in_group)) {
            return lineBad(diag, alloc, E.@"bad-locator", "line {d}: locator {s} does not have the form of a {s} on the {s} wire", .{ lineno, toks[1], kw, @tagName(p.wire) });
        }
        const ln = Line{ .tag = if (is_when) .when else .constant, .locator = toks[1], .wraw = toks[2], .lineno = lineno };
        try curLines(p, in_group, gtmp).append(ln);
    } else if (is(kw, "default")) {
        if (toks.len != 3) return bad(diag, alloc, E.@"bad-directive", "line {d}: default takes a key and a value", .{lineno});
        const d = Default{ .key = toks[1], .text = toks[2] };
        if (in_group) {
            // a `default` inside a group applies to items
            try gstack.items[gstack.items.len - 1].defaults.append(d);
        } else if (p.kinds.items.len == 0) {
            try p.common_defaults.append(d);
        } else {
            try p.kinds.items[p.kinds.items.len - 1].defaults.append(d);
        }
        try p.key_uses.append(.{ .key = toks[1], .tkind = null, .use = .default });
    } else if (is(kw, "map")) {
        if (toks.len != 4) return bad(diag, alloc, E.@"bad-directive", "line {d}: map takes a table, a native value and a model value", .{lineno});
        const gop = try p.tables.getOrPut(toks[1]);
        if (!gop.found_existing) {
            const t = try alloc.create(Table);
            t.* = .{ .name = toks[1], .entries = std.ArrayList(TableEntry).init(alloc) };
            gop.value_ptr.* = t;
        }
        try gop.value_ptr.*.entries.append(.{ .native = toks[2], .model = toks[3] });
    } else if (is(kw, "field")) {
        if (toks.len < 4) return bad(diag, alloc, E.@"bad-directive", "line {d}: field takes a key, a locator and a transform", .{lineno});
        const t = parseTransform(toks[3]) catch |err| switch (err) {
            error.@"unknown-transform" => return lineBad(diag, alloc, err, "line {d}: unknown transform {s}", .{ lineno, toks[3] }),
            else => return lineBad(diag, alloc, err, "line {d}: the parameters of transform {s} are not valid", .{ lineno, toks[3] }),
        };
        if (!locatorFormOk(p.wire, false, toks[2], in_group)) {
            return lineBad(diag, alloc, E.@"bad-locator", "line {d}: locator {s} does not have the form of a field on the {s} wire", .{ lineno, toks[2], @tagName(p.wire) });
        }
        var ln = Line{ .key = toks[1], .locator = toks[2], .transform = t, .lineno = lineno };
        // options, in any order
        var oi: usize = 4;
        while (oi < toks.len) : (oi += 1) {
            const o = toks[oi];
            // an unknown or repeated option is `bad-directive`
            var again = false;
            if (is(o, "via")) {
                oi += 1;
                if (oi >= toks.len or toks[oi].len == 0) return lineBad(diag, alloc, E.@"bad-directive", "line {d}: via takes a table name", .{lineno});
                again = ln.via_name.len > 0;
                ln.via_name = toks[oi];
            } else if (is(o, "swap")) {
                again = ln.swap;
                ln.swap = true;
            } else if (is(o, "trim")) {
                again = ln.trim;
                ln.trim = true;
            } else if (is(o, "optional")) {
                again = ln.optional;
                ln.optional = true;
            } else if (is(o, "absent")) {
                // the next token is the argument, whatever it is (ruling 11 of 0.9)
                oi += 1;
                if (oi >= toks.len) return lineBad(diag, alloc, E.@"bad-directive", "line {d}: absent takes one or more values", .{lineno});
                again = ln.absent_raw != null;
                ln.absent_raw = toks[oi];
            } else return lineBad(diag, alloc, E.@"bad-directive", "line {d}: unknown field option {s}", .{ lineno, o });
            if (again) return lineBad(diag, alloc, E.@"bad-directive", "line {d}: field option {s} is repeated", .{ lineno, o });
        }
        // the values of the `absent` option are a line check, except on a
        // `bits` field above 64 bits (ruling 4d of 0.11)
        if (p.wire == .bits) ln.blen = @intCast(@min(fixedLen(toks[2]) orelse 0, 1 << 20));
        if (!(p.wire == .bits and ln.blen > 64)) {
            try parseAbsent(alloc, p.wire, &ln, in_group, diag);
            ln.abs_checked = true;
        }
        try curLines(p, in_group, gtmp).append(ln);
        try p.key_uses.append(.{ .key = toks[1], .tkind = t.kind, .via = ln.via_name, .grp = if (in_group) gstack.items[gstack.items.len - 1] else null });
    } else {
        return bad(diag, alloc, E.@"unknown-directive", "line {d}: unknown directive {s}", .{ lineno, kw });
    }
}

fn parsePack(alloc: std.mem.Allocator, def_text: []const u8, diag: *Diag) anyerror!*Pack {
    // `layout sequential` on the bits wire: lines read in order from a cursor
    if (try isSequentialPack(alloc, def_text)) return parseSeqPack(alloc, def_text, diag);
    const p = try newPack(alloc);
    // The open groups, innermost last. The body lines of every open group
    // collect in `gtmp`; `gfrom` is where each group's begin, `gline` the
    // group's own line, which joins the enclosing lines at its `end`.
    var st = FState{
        .alloc = alloc,
        .diag = diag,
        .p = p,
        .gstack = std.ArrayList(*Group).init(alloc),
        .gtmp = std.ArrayList(Line).init(alloc),
        .gfrom = std.ArrayList(usize).init(alloc),
        .gline = std.ArrayList(Line).init(alloc),
    };
    const gstack = &st.gstack;
    var deferred: ?Deferred = null;
    var lineno: usize = 0;
    var lines = std.mem.splitScalar(u8, def_text, '\n');
    var tokbuf = std.ArrayList([]const u8).init(alloc);
    var hdr = HeaderSeen{};
    while (lines.next()) |line| {
        lineno += 1;
        tokenizeInto(&tokbuf, line) catch |err|
            return lineBad(diag, alloc, err, "line {d}: a quoted value has no closing quote", .{lineno});
        const toks = tokbuf.items;
        if (toks.len == 0) continue;
        // ruling 5b of 0.11, steps 2 to 6
        try packLineChecks(alloc, toks, lineno, &hdr, diag);
        st.lineno = lineno;
        // every cause not in steps 1 to 10 of ruling 5b is reported after
        // the file is read: the first such failure is kept and the file read on
        fixedLine(&st, toks) catch |err| {
            if (err == error.OutOfMemory or diag.line_err) return err;
            if (deferred == null) deferred = .{ .err = err, .msg = diag.msg };
        };
    }

    try headerChecks(alloc, hdr, diag);
    if (deferred) |d| {
        diag.msg = d.msg;
        return d.err;
    }
    if (gstack.items.len > 0) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: a `group` with no `end`", .{gstack.items[gstack.items.len - 1].lineno});
    }
    // Checks that need the whole file: the wire may be named after the lines
    // it governs.
    if (p.bit_order_set and p.wire != .bits) {
        return bad(diag, alloc, E.@"bad-directive", "bit_order on wire {s}; it is for the bits wire only", .{@tagName(p.wire)});
    }
    if (p.layout_set and p.wire != .bits) {
        return bad(diag, alloc, E.@"bad-directive", "layout on wire {s}; it is for the bits wire only", .{@tagName(p.wire)});
    }
    if (st.any_when and p.kinds.items.len == 0) {
        return bad(diag, alloc, E.@"bad-directive", "a `when` line in a pack with no `kind` line", .{});
    }
    if (st.kind_root and p.wire != .xml) {
        return bad(diag, alloc, E.@"bad-directive", "a `root` line inside a kind on wire {s}; it is for the xml wire only", .{@tagName(p.wire)});
    }
    if (p.wire == .bits and p.word_bytes == 0) {
        return bad(diag, alloc, E.@"bad-directive", "a fixed-layout bits pack needs word_bytes", .{});
    }
    // an `xml` pack has a root for the pack or for each of its kinds
    if (p.wire == .xml and p.root.len == 0) {
        if (p.kinds.items.len == 0) return bad(diag, alloc, E.@"missing-root", "the xml pack has no root line", .{});
        for (p.kinds.items) |k| {
            if (k.root == null) return bad(diag, alloc, E.@"missing-root", "kind {s} of the xml pack has no root", .{k.name});
        }
    }
    try textDirectives(alloc, p, diag);
    setTableTypes(p);
    try finalizeLines(alloc, p, p.common.items, false, diag);
    for (p.kinds.items) |*k| try finalizeLines(alloc, p, k.lines.items, false, diag);
    // the group checks, scope by scope
    if (p.kinds.items.len == 0) try checkScope(alloc, p, p.common.items, &.{}, null, false, diag);
    for (p.kinds.items) |*k| try checkScope(alloc, p, p.common.items, k.lines.items, null, false, diag);
    try checkGroupBodies(alloc, p, p.common.items, diag);
    for (p.kinds.items) |*k| try checkGroupBodies(alloc, p, k.lines.items, diag);
    if (p.wire == .text) {
        if (p.kinds.items.len == 0) try textCheckScope(alloc, p.common.items, &.{}, diag);
        for (p.kinds.items) |*k| try textCheckScope(alloc, p.common.items, k.lines.items, diag);
    }

    if (p.distribution == null) return bad(diag, alloc, E.@"missing-distribution", "the pack has no distribution line", .{});
    if (p.sources.items.len == 0) return bad(diag, alloc, E.@"missing-source", "the pack has no source line", .{});
    return p;
}

// ---------------------------------------------------------------------------
// Engine: loaded modules and packs, the distribution limit, the load-time
// checks, and decode / encode / convert by format name
// ---------------------------------------------------------------------------

// One caller-supplied key: `convert(from, to, bytes, context)`, CLI `--set`.
pub const KV = struct { key: []const u8, value: []const u8 };

// One scope from its lines and its `default` lines; `d1` takes precedence
// over `d2` (a kind's default over the common one).
fn buildScope(alloc: std.mem.Allocator, lines: []const Line, d1: []const Default, d2: []const Default, body: bool) !Scope {
    var sc = Scope{ .lines = lines };
    const both = [2][]const Default{ d1, d2 };
    for (both) |ds| for (ds) |d| {
        const gop = try sc.defaults.getOrPut(alloc, d.key);
        if (!gop.found_existing) gop.value_ptr.* = d.value;
    };
    for (lines) |*ln| {
        if (ln.tag == .group) {
            const g = ln.grp.?;
            if (g.count_fixed == null) {
                // a count locator is a bit range of the scope
                sc.nbits = @max(sc.nbits, g.cstart + g.clen);
                sc.nbits_req = @max(sc.nbits_req, g.cstart + g.clen);
            }
            if (body) sc.needs_sub = true;
            continue;
        }
        sc.nbits = @max(sc.nbits, ln.bstart + ln.blen);
        if (!ln.optional) sc.nbits_req = @max(sc.nbits_req, ln.bstart + ln.blen);
        if (!body) continue;
        if (ln.dot) {
            if (ln.isField() and sc.dot == null) sc.dot = ln;
        } else sc.needs_sub = true;
    }
    return sc;
}

fn buildGroupBodies(alloc: std.mem.Allocator, lines: []const Line) anyerror!void {
    for (lines) |*ln| {
        if (ln.tag != .group) continue;
        const g = ln.grp.?;
        try buildGroupBodies(alloc, g.lines);
        g.body = try buildScope(alloc, g.lines, g.defaults.items, &.{}, true);
    }
}

// Lines of a pack that become final once its keys are known: the scope of
// each group body and of each kind, the bit lengths, and the kinds by root
// element.
fn finishPack(alloc: std.mem.Allocator, p: *Pack) !void {
    try buildGroupBodies(alloc, p.common.items);
    for (p.kinds.items) |*k| try buildGroupBodies(alloc, k.lines.items);
    p.common_scope = try buildScope(alloc, p.common.items, p.common_defaults.items, &.{}, false);
    for (p.kinds.items, 0..) |*k, i| {
        const act = try alloc.alloc(Line, p.common.items.len + k.lines.items.len);
        @memcpy(act[0..p.common.items.len], p.common.items);
        @memcpy(act[p.common.items.len..], k.lines.items);
        k.scope = try buildScope(alloc, act, k.defaults.items, p.common_defaults.items, false);
        if (p.wire == .xml) {
            const gop = try p.root_index.getOrPut(k.root orelse p.root);
            if (!gop.found_existing) gop.value_ptr.* = std.ArrayList(usize).init(alloc);
            try gop.value_ptr.append(i);
        }
    }
}

// The module files of a model directory, as `Engine.scanModelDir` read them.
const ModelFiles = struct {
    dir: []const u8,
    names: []const []const u8,
    texts: [][]const u8,
    mod_names: [][]const u8,
    mod_uses: [][]const []const u8,
    state: []u8,
};

// What a directory load loaded: the number of modules, and the directory
// names of the packs.
const Loaded = struct { modules: usize, packs: []const []const u8 };

// The capability report of one ordered pair of formats (ruling 6 of 0.11).
pub const Capability = struct {
    grade: []const u8, // `full`, `partial` or `none`
    carried: []const []const u8,
    dropped: []const []const u8,
};

pub const Engine = struct {
    alloc: std.mem.Allocator,
    // Where decode, encode and convert allocate their results and the failure
    // message. A caller that runs many conversions points it at an arena it
    // resets; by default it is `alloc`.
    scratch: std.mem.Allocator,
    modules: ModuleMap,
    // the loaded modules in byte order of name (the order derivations run in)
    module_order: std.ArrayList(*Module),
    packs: std.ArrayList(*Pack),
    pack_index: std.StringHashMap(*Pack),
    max_distribution: Dist = .controlled,
    // The limit on the list items one decode holds (ruling 7 of 0.11).
    max_items: usize = default_max_items,
    // Message of the last failure: "<kind>: <detail>".
    last_error: []const u8 = "",

    pub fn init(alloc: std.mem.Allocator) Engine {
        return .{
            .alloc = alloc,
            .scratch = alloc,
            .modules = std.StringHashMap(*Module).init(alloc),
            .module_order = std.ArrayList(*Module).init(alloc),
            .packs = std.ArrayList(*Pack).init(alloc),
            .pack_index = std.StringHashMap(*Pack).init(alloc),
        };
    }

    pub fn setMaxDistribution(self: *Engine, d: Dist) void {
        self.max_distribution = d;
    }

    fn fail(self: *Engine, err: anyerror, comptime fmt: []const u8, args: anytype) void {
        const detail = std.fmt.allocPrint(self.scratch, fmt, args) catch "";
        self.last_error = std.fmt.allocPrint(self.scratch, "{s}: {s}", .{ @errorName(err), detail }) catch @errorName(err);
    }

    // load_model(text): load one model module.
    pub fn loadModel(self: *Engine, def_text: []const u8) !*Module {
        var mdiag = Diag{};
        const m = parseModule(self.alloc, def_text, &mdiag) catch |err| {
            self.fail(err, "model module: {s}", .{mdiag.msg});
            return err;
        };
        if (m.distribution.? == .controlled and self.max_distribution == .public) {
            const err = E.@"distribution-refused";
            self.fail(err, "module {s} is controlled; this engine's limit is public", .{m.name});
            return err;
        }
        // Version 0.8: every used module is loaded, and a public module uses
        // only public modules
        for (m.uses.items) |u| {
            if (std.mem.eql(u8, u, m.name)) continue;
            if (!self.modules.contains(u)) {
                const err = E.@"unknown-module";
                self.fail(err, "module {s}: module {s} is not loaded", .{ m.name, u });
                return err;
            }
        }
        if (m.distribution.? == .public) {
            for (m.uses.items) |u| {
                if (std.mem.eql(u8, u, m.name)) continue;
                if (self.modules.get(u).?.distribution.? != .public) {
                    const err = E.@"distribution-violation";
                    self.fail(err, "public module {s} uses controlled module {s}", .{ m.name, u });
                    return err;
                }
            }
        }
        // the `derive` checks, then `duplicate-module`
        checkDerives(self.alloc, m, &self.modules, &mdiag) catch |err| {
            self.fail(err, "model module: {s}", .{mdiag.msg});
            return err;
        };
        if (self.modules.contains(m.name)) {
            const err = E.@"duplicate-module";
            self.fail(err, "module {s} is already loaded", .{m.name});
            return err;
        }
        try self.modules.put(m.name, m);
        var at: usize = self.module_order.items.len;
        for (self.module_order.items, 0..) |o, i| {
            if (std.mem.lessThan(u8, m.name, o.name)) {
                at = i;
                break;
            }
        }
        try self.module_order.insert(at, m);
        return m;
    }

    // load(pack): parse a pack.def and check it against the modules loaded so
    // far, in the spec's order.
    pub fn loadPack(self: *Engine, def_text: []const u8) !*Pack {
        var diag = Diag{};
        const p = parsePack(self.alloc, def_text, &diag) catch |err| {
            self.fail(err, "pack.def: {s}", .{diag.msg});
            return err;
        };
        const dist = p.distribution.?;
        if (dist == .controlled and self.max_distribution == .public) {
            const err = E.@"distribution-refused";
            self.fail(err, "pack {s} is controlled; this engine's limit is public", .{p.format});
            return err;
        }
        // unknown-module: `core` and every module in a `uses` line is loaded
        if (!self.modules.contains("core")) {
            const err = E.@"unknown-module";
            self.fail(err, "pack {s}: module core is not loaded", .{p.format});
            return err;
        }
        for (p.uses.items) |u| {
            if (!self.modules.contains(u)) {
                const err = E.@"unknown-module";
                self.fail(err, "pack {s}: module {s} is not loaded", .{ p.format, u });
                return err;
            }
        }
        // distribution-violation: a public pack uses only public modules
        if (dist == .public) {
            if (self.modules.get("core").?.distribution.? != .public) {
                const err = E.@"distribution-violation";
                self.fail(err, "public pack {s} uses controlled module core", .{p.format});
                return err;
            }
            for (p.uses.items) |u| {
                if (self.modules.get(u).?.distribution.? != .public) {
                    const err = E.@"distribution-violation";
                    self.fail(err, "public pack {s} uses controlled module {s}", .{ p.format, u });
                    return err;
                }
            }
        }
        // module-not-used: every `field` line in every kind, and `requires` keys
        for (p.key_uses.items) |ku| {
            const ref = splitKey(ku.key);
            if (!p.usesModule(ref.module)) {
                const err = E.@"module-not-used";
                self.fail(err, "pack {s}: key {s} needs `uses {s}`", .{ p.format, ku.key, ref.module });
                return err;
            }
        }
        // undeclared-key: a key or, for a `group` or a `requires`, a list
        for (p.key_uses.items) |ku| {
            const ref = splitKey(ku.key);
            const m = self.modules.get(ref.module).?;
            if (m.key(ref.name) == null and !m.lists.contains(ref.name)) {
                const err = E.@"undeclared-key";
                self.fail(err, "pack {s}: module {s} declares no key {s}", .{ p.format, ref.module, ref.name });
                return err;
            }
        }
        // key-type-mismatch: the transform yields the key's type, or, with
        // `via`, the table's model side is of the key's type
        for (p.key_uses.items) |ku| {
            // a `group` naming a scalar key, a `field` naming a list
            const is_list = self.isList(ku.key);
            const fits = switch (ku.use) {
                .group => is_list,
                .field, .default => !is_list,
                .requires => true,
            };
            if (!fits) {
                const err = E.@"key-type-mismatch";
                self.fail(err, "pack {s}: {s} is {s}, named by a {s} line", .{ p.format, ku.key, if (is_list) "a list" else "a scalar key", @tagName(ku.use) });
                return err;
            }
            const tk = ku.tkind orelse continue;
            const want = self.keyType(ku.key).?;
            const got = if (ku.via.len > 0) p.tables.get(ku.via).?.model_ty else yields(tk);
            // an all-integer table on a `float` key is accepted, its model
            // side read as float (ruling 4 of 0.6)
            const int_table_on_float = ku.via.len > 0 and got == .int and want == .float;
            if (got != want and !int_table_on_float) {
                const err = E.@"key-type-mismatch";
                if (ku.via.len > 0) {
                    self.fail(err, "pack {s}: key {s} is {s}, the model side of table {s} is {s}", .{ p.format, ku.key, @tagName(want), ku.via, @tagName(got) });
                } else {
                    self.fail(err, "pack {s}: key {s} is {s}, its transform yields {s}", .{ p.format, ku.key, @tagName(want), @tagName(got) });
                }
                return err;
            }
        }
        // every key is known now: each line's key type, each default's value
        try self.resolveLines(p, p.common.items);
        for (p.kinds.items) |*k| {
            try self.resolveLines(p, k.lines.items);
            for (k.defaults.items) |*d| try self.readDefault(p, d);
        }
        for (p.common_defaults.items) |*d| try self.readDefault(p, d);
        if (p.seq) |b| try self.resolveSeqBody(p, b);
        try finishPack(self.alloc, p);
        // last: a format name already loaded (ruling 5 of 0.11); the first
        // pack stays loaded
        if (self.pack_index.contains(p.format)) {
            const err = E.@"duplicate-format";
            self.fail(err, "a pack of format {s} is already loaded", .{p.format});
            return err;
        }
        try self.packs.append(p);
        try self.pack_index.put(p.format, p);
        return p;
    }

    // Read every `*.def` in `models_dir`: the file names in byte order with
    // `core.def` first, whatever its name sorts as (ruling 9 of 0.6: a
    // `derive` line of another module may name a key of `core`), each file's
    // text, module name and `uses` lines. null: there is no such directory.
    fn scanModelDir(self: *Engine, models_dir: []const u8) !?ModelFiles {
        var dir = std.fs.cwd().openDir(models_dir, .{ .iterate = true }) catch |err| switch (err) {
            error.FileNotFound => return null,
            else => return err,
        };
        defer dir.close();
        var names = std.ArrayList([]const u8).init(self.alloc);
        var it = dir.iterate();
        while (try it.next()) |entry| {
            if (entry.kind != .file) continue;
            if (!std.mem.endsWith(u8, entry.name, ".def")) continue;
            try names.append(try self.alloc.dupe(u8, entry.name));
        }
        std.mem.sort([]const u8, names.items, {}, strLess);
        for (names.items, 0..) |name, i| {
            if (!std.mem.eql(u8, name, "core.def")) continue;
            std.mem.copyBackwards([]const u8, names.items[1 .. i + 1], names.items[0..i]);
            names.items[0] = name;
            break;
        }
        const n = names.items.len;
        const mf = ModelFiles{
            .dir = models_dir,
            .names = names.items,
            .texts = try self.alloc.alloc([]const u8, n),
            .mod_names = try self.alloc.alloc([]const u8, n),
            .mod_uses = try self.alloc.alloc([]const []const u8, n),
            .state = try self.alloc.alloc(u8, n),
        };
        @memset(mf.state, 0);
        var tokbuf = std.ArrayList([]const u8).init(self.alloc);
        for (names.items, 0..) |name, i| {
            const path = try std.fmt.allocPrint(self.alloc, "{s}/{s}", .{ models_dir, name });
            mf.texts[i] = try std.fs.cwd().readFileAlloc(self.alloc, path, max_file);
            mf.mod_names[i] = "";
            var uses = std.ArrayList([]const u8).init(self.alloc);
            var lines = std.mem.splitScalar(u8, mf.texts[i], '\n');
            while (lines.next()) |line| {
                tokenizeInto(&tokbuf, line) catch |err| switch (err) {
                    error.OutOfMemory => return err,
                    else => continue,
                };
                if (tokbuf.items.len < 2) continue;
                if (std.mem.eql(u8, tokbuf.items[0], "module")) mf.mod_names[i] = tokbuf.items[1];
                if (std.mem.eql(u8, tokbuf.items[0], "uses")) try uses.append(tokbuf.items[1]);
            }
            mf.mod_uses[i] = uses.items;
        }
        return mf;
    }

    // Load every `*.def` in `models_dir`: `core.def` first, then byte order
    // of file name, each module after the modules it uses (Version 0.8); a
    // cycle is `bad-directive`. Returns the number of modules loaded.
    pub fn loadModelDir(self: *Engine, models_dir: []const u8) !usize {
        const mf = (try self.scanModelDir(models_dir)) orelse return 0; // no model directory: no modules
        for (0..mf.names.len) |i| try self.loadModelOrdered(mf, i);
        return mf.names.len;
    }

    fn loadModelOrdered(self: *Engine, mf: ModelFiles, i: usize) anyerror!void {
        // 0: not visited, 1: being loaded, 2: loaded
        if (mf.state[i] == 2) return;
        if (mf.state[i] == 1) {
            const err = E.@"bad-directive";
            self.fail(err, "model module {s}: its `uses` lines form a cycle ({s}/{s})", .{ mf.mod_names[i], mf.dir, mf.names[i] });
            return err;
        }
        mf.state[i] = 1;
        for (mf.mod_uses[i]) |u| {
            for (mf.mod_names, 0..) |mn, j| {
                if (j != i and std.mem.eql(u8, mn, u)) try self.loadModelOrdered(mf, j);
            }
        }
        _ = self.loadModel(mf.texts[i]) catch |err| {
            self.last_error = try std.fmt.allocPrint(self.alloc, "{s} ({s}/{s})", .{ self.last_error, mf.dir, mf.names[i] });
            return err;
        };
        mf.state[i] = 2;
    }

    // Load only the named packs of `packs_dir` (directory names), in byte
    // order of name, and before them the modules they need from
    // `models_dir`: `core`, the modules their `uses` lines name, and the
    // modules those use. A name given twice is loaded once; a name with no
    // `pack.def` is `error.FileNotFound`. A module a pack names that the
    // model directory lacks is left to the pack's own `unknown-module`.
    pub fn loadPacksOnly(self: *Engine, packs_dir: []const u8, models_dir: []const u8, pack_names: []const []const u8) !Loaded {
        const alloc = self.alloc;
        var names = std.ArrayList([]const u8).init(alloc);
        for (pack_names) |name| {
            var seen = false;
            for (names.items) |have| {
                if (std.mem.eql(u8, have, name)) seen = true;
            }
            if (!seen) try names.append(name);
        }
        std.mem.sort([]const u8, names.items, {}, strLess);
        const mf_opt = try self.scanModelDir(models_dir);
        if (mf_opt) |mf| {
            for (mf.mod_names, 0..) |mn, j| {
                if (std.mem.eql(u8, mn, "core")) try self.loadModelOrdered(mf, j);
            }
        }
        const texts = try alloc.alloc([]const u8, names.items.len);
        var tokbuf = std.ArrayList([]const u8).init(alloc);
        for (names.items, 0..) |name, i| {
            const def_path = try std.fmt.allocPrint(alloc, "{s}/{s}/pack.def", .{ packs_dir, name });
            texts[i] = std.fs.cwd().readFileAlloc(alloc, def_path, max_file) catch |err| {
                self.fail(err, "pack {s}: cannot read {s}", .{ name, def_path });
                return err;
            };
            const mf = mf_opt orelse continue;
            var lines = std.mem.splitScalar(u8, texts[i], '\n');
            while (lines.next()) |line| {
                tokenizeInto(&tokbuf, line) catch |err| switch (err) {
                    error.OutOfMemory => return err,
                    else => continue,
                };
                if (tokbuf.items.len != 2 or !std.mem.eql(u8, tokbuf.items[0], "uses")) continue;
                for (mf.mod_names, 0..) |mn, j| {
                    if (std.mem.eql(u8, mn, tokbuf.items[1])) try self.loadModelOrdered(mf, j);
                }
            }
        }
        for (names.items, 0..) |name, i| {
            _ = self.loadPack(texts[i]) catch |err| {
                self.last_error = try std.fmt.allocPrint(alloc, "{s} ({s}/{s}/pack.def)", .{ self.last_error, packs_dir, name });
                return err;
            };
        }
        return .{ .modules = self.modules.count(), .packs = names.items };
    }

    // The declared type of a model key, null when no loaded module declares it.
    fn keyType(self: *const Engine, model_key: []const u8) ?KeyType {
        const ref = splitKey(model_key);
        const m = self.modules.get(ref.module) orelse return null;
        return if (m.key(ref.name)) |k| k.ty else null;
    }

    // Is the name a list some loaded module declares?
    fn isList(self: *const Engine, model_key: []const u8) bool {
        const ref = splitKey(model_key);
        const m = self.modules.get(ref.module) orelse return false;
        return m.lists.contains(ref.name);
    }

    // Each field line's key type and each group's defaults, group bodies
    // included.
    fn resolveLines(self: *Engine, p: *const Pack, lines: []Line) anyerror!void {
        for (lines) |*ln| {
            switch (ln.tag) {
                .field => ln.kty = self.keyType(ln.key).?,
                .group => {
                    const g = ln.grp.?;
                    try self.resolveLines(p, g.lines);
                    for (g.defaults.items) |*d| try self.readDefault(p, d);
                },
                else => {},
            }
        }
    }

    // A sequential pack: each field's key types, each body's defaults.
    fn resolveSeqBody(self: *Engine, p: *const Pack, b: *SBody) anyerror!void {
        try self.resolveSeqDefaults(p, b.defaults.items, &b.dmap);
        try self.resolveSeqNodes(p, b.common);
        for (b.kinds) |*k| {
            try self.resolveSeqDefaults(p, k.defaults.items, &k.dmap);
            try self.resolveSeqNodes(p, k.lines);
        }
    }

    fn resolveSeqDefaults(self: *Engine, p: *const Pack, ds: []Default, map: *DMap) anyerror!void {
        for (ds) |*d| {
            try self.readDefault(p, d);
            const gop = try map.getOrPut(self.alloc, d.key);
            if (!gop.found_existing) gop.value_ptr.* = d.value;
        }
    }

    fn resolveSeqNodes(self: *Engine, p: *const Pack, list: []SNode) anyerror!void {
        for (list) |*n| {
            if (n.tag == .field) {
                n.ln.kty = self.keyType(n.ln.key).?;
                for (n.also.items) |*a| a.kty = self.keyType(a.key).?;
            }
            try self.resolveSeqNodes(p, n.body);
            if (n.gbody) |b| try self.resolveSeqBody(p, b);
        }
    }

    // A `default` value is read as its key's declared type.
    fn readDefault(self: *Engine, p: *const Pack, d: *Default) !void {
        d.value = readAs(self.keyType(d.key).?, d.text) catch {
            const err = E.@"key-type-mismatch";
            self.fail(err, "pack {s}: default {s} {s} is not of the key's type", .{ p.format, d.key, d.text });
            return err;
        };
    }

    pub fn findPack(self: *const Engine, fmt: []const u8) ?*Pack {
        return self.pack_index.get(fmt);
    }

    fn pack(self: *Engine, fmt: []const u8) !*Pack {
        return self.findPack(fmt) orelse {
            self.fail(E.@"unknown-format", "no loaded pack has format {s}", .{fmt});
            return E.@"unknown-format";
        };
    }

    // decode(format, bytes) -> Entity
    pub fn decode(self: *Engine, fmt: []const u8, bytes: []const u8) !Entity {
        const p = try self.pack(fmt);
        var diag = Diag{ .max_items = self.max_items };
        return decodePack(self.scratch, p, bytes, &diag) catch |err| {
            self.fail(err, "decode {s}: {s}", .{ fmt, diag.msg });
            return err;
        };
    }

    // encode(format, Entity) -> bytes
    pub fn encode(self: *Engine, fmt: []const u8, e: *const Entity) ![]u8 {
        const p = try self.pack(fmt);
        var diag = Diag{};
        return encodePack(self.scratch, p, e, &diag) catch |err| {
            self.fail(err, "encode {s}: {s}", .{ fmt, diag.msg });
            return err;
        };
    }

    // Set each context key the entity lacks. A key no loaded module declares
    // is `undeclared-key`; a value that is not of the key's type is
    // `key-type-mismatch`.
    pub fn fillContext(self: *Engine, e: *Entity, context: []const KV) !void {
        for (context) |kv| {
            const ty = self.keyType(kv.key) orelse {
                if (self.isList(kv.key)) {
                    // a list is declared, and no text is of its type
                    const err = E.@"key-type-mismatch";
                    self.fail(err, "context key {s} is a list", .{kv.key});
                    return err;
                }
                const err = E.@"undeclared-key";
                self.fail(err, "context key {s} is declared by no loaded module", .{kv.key});
                return err;
            };
            const mv = readAs(ty, kv.value) catch {
                const err = E.@"key-type-mismatch";
                self.fail(err, "context key {s} is {s}; the value {s} is not", .{ kv.key, @tagName(ty), kv.value });
                return err;
            };
            if (!e.fields.contains(kv.key)) try e.put(kv.key, mv);
        }
    }

    // complete(entity): apply the derivations. The loaded modules in byte
    // order of name, each module's `derive` lines in order; a line whose
    // target is absent and whose arguments are all present sets the target.
    // The pass repeats until a pass sets nothing, at most 8 times.
    pub fn complete(self: *Engine, e: *Entity) !void {
        var pass: usize = 0;
        while (pass < 8) : (pass += 1) {
            var set_any = false;
            for (self.module_order.items) |m| {
                for (m.derives.items) |d| {
                    if (try applyDerive(self.scratch, d, e)) set_any = true;
                }
            }
            if (!set_any) break;
        }
    }

    // convert(from, to, bytes, context): decode; clear Entity.kind unless
    // from == to; fill absent keys from the context; derive; encode. With
    // from == to and no context the entity goes to the encoder as decoded.
    // model_keys(format) (ruling 6a of 0.11).
    pub fn modelKeysOf(self: *Engine, fmt: []const u8) ![]const []const u8 {
        return modelKeys(self.scratch, try self.pack(fmt));
    }

    // capability(from, to): computed from the two packs alone (ruling 6 of
    // 0.11). `from` is checked, then `to`.
    pub fn capability(self: *Engine, from: []const u8, to: []const u8) !Capability {
        const src = try self.modelKeysOf(from);
        const dst = try self.modelKeysOf(to);
        var carried = std.ArrayList([]const u8).init(self.scratch);
        var dropped = std.ArrayList([]const u8).init(self.scratch);
        for (src) |k| {
            var found = false;
            for (dst) |d| {
                if (std.mem.eql(u8, k, d)) {
                    found = true;
                    break;
                }
            }
            try (if (found) &carried else &dropped).append(k);
        }
        const grade: []const u8 = if (carried.items.len == 0) "none" else if (dropped.items.len == 0) "full" else "partial";
        return .{ .grade = grade, .carried = carried.items, .dropped = dropped.items };
    }

    pub fn setMaxItems(self: *Engine, n: usize) void {
        self.max_items = n;
    }

    pub fn convert(self: *Engine, from: []const u8, to: []const u8, bytes: []const u8, context: ?[]const KV) ![]u8 {
        // `from`, then `to`, before the input is read (ruling 5 of 0.11)
        _ = try self.pack(from);
        _ = try self.pack(to);
        const same = std.mem.eql(u8, from, to);
        var e = try self.decode(from, bytes);
        if (!same) e.clearKind();
        if (!same or context != null) {
            if (context) |c| try self.fillContext(&e, c);
            try self.complete(&e);
        }
        return self.encode(to, &e);
    }
};

const deg_to_rad: f64 = std.math.pi / 180.0;
// radians become degrees by multiplying by 180/π, the quotient computed first
// as a double (ruling 1 of 0.6)
const rad_to_deg: f64 = 180.0 / std.math.pi;

// One `derive` line against an entity. true: the target was set.
fn applyDerive(alloc: std.mem.Allocator, d: Derive, e: *Entity) !bool {
    if (e.fields.contains(d.target)) return false;
    if (d.f == .any) {
        // set when only some arguments are present: 1 when any present
        // argument is not 0
        var present = false;
        var nonzero = false;
        for (d.args) |a| {
            const v = e.get(a) orelse continue;
            if (v != .int) return false;
            present = true;
            if (v.int != 0) nonzero = true;
        }
        if (!present) return false;
        try e.put(d.target, MV{ .int = if (nonzero) 1 else 0 });
        return true;
    }
    for (d.args) |a| if (!e.fields.contains(a)) return false;
    const a0 = e.get(d.args[0]).?;
    var out: MV = undefined;
    switch (d.f) {
        .copy => out = a0,
        .any => unreachable,
        .day_seconds => {
            if (a0 != .int) return false;
            out = MV{ .float = @as(f64, @floatFromInt(@mod(a0.int, 86400000))) / 1000.0 };
        },
        .not => {
            if (a0 != .int) return false;
            out = MV{ .int = if (a0.int == 0) 1 else 0 };
        },
        .parse_int => {
            if (a0 != .str) return false;
            out = MV{ .int = parseIntText(a0.str) orelse return false };
        },
        .text_of => {
            if (a0 != .int) return false;
            out = MV{ .str = try intToStr(alloc, a0.int) };
        },
        .join => {
            var buf = std.ArrayList(u8).init(alloc);
            for (d.args, 0..) |a, i| {
                const v = e.get(a).?;
                if (v != .str) return false;
                if (i > 0) try buf.appendSlice(d.sep);
                try buf.appendSlice(v.str);
            }
            out = MV{ .str = try buf.toOwnedSlice() };
        },
        .offset => {
            if (d.int_mode) {
                if (a0 != .int) return false;
                const r = @addWithOverflow(a0.int, d.off_i);
                if (r[1] != 0) return false;
                out = MV{ .int = r[0] };
            } else {
                out = MV{ .float = (mvFloat(a0) catch return false) + d.off_f };
            }
        },
        else => {
            const a = mvFloat(a0) catch return false;
            const b: f64 = if (d.args.len > 1) (mvFloat(e.get(d.args[1]).?) catch return false) else 0;
            const r: f64 = switch (d.f) {
                .hypot => @sqrt(a * a + b * b),
                .bearing => blk: {
                    if (a == 0 and b == 0) return false; // absent when both are 0
                    var deg = std.math.atan2(a, b) * rad_to_deg;
                    if (deg < 0) deg += 360;
                    if (deg >= 360) deg -= 360;
                    break :blk deg;
                },
                .east_of => a * @sin(b * deg_to_rad),
                .north_of => a * @cos(b * deg_to_rad),
                .neg => -a,
                .scale => d.factor.mul(a),
                else => unreachable,
            };
            out = MV{ .float = r };
        },
    }
    // a result that is not finite leaves the target absent
    if (out == .float and !std.math.isFinite(out.float)) return false;
    try e.put(d.target, out);
    return true;
}

const max_file: usize = 64 << 20;

// ---------------------------------------------------------------------------
// Numeric / string helpers
// ---------------------------------------------------------------------------

// Shortest decimal that round-trips to the same double, plain notation, no
// decimal point on an integer value, negative zero as "0".
fn floatToStr(alloc: std.mem.Allocator, v: f64) ![]const u8 {
    if (!std.math.isFinite(v)) return E.@"transform-encode";
    if (v == 0) return alloc.dupe(u8, "0"); // covers +0 and -0 -> "0"
    var buf: [512]u8 = undefined;
    const s = try std.fmt.formatFloat(&buf, v, .{ .mode = .decimal });
    return alloc.dupe(u8, s);
}

fn intToStr(alloc: std.mem.Allocator, v: i64) ![]const u8 {
    return std.fmt.allocPrint(alloc, "{d}", .{v});
}

// ---------------------------------------------------------------------------
// Civil date arithmetic (Howard Hinnant's algorithms)
// ---------------------------------------------------------------------------

fn daysFromCivil(y_in: i64, m: i64, d: i64) i64 {
    const y = y_in - @as(i64, if (m <= 2) 1 else 0);
    const era = @divFloor(if (y >= 0) y else y - 399, 400);
    const yoe = y - era * 400; // [0, 399]
    const mp = if (m > 2) m - 3 else m + 9; // [0,11]
    const doy = @divFloor(153 * mp + 2, 5) + d - 1; // [0,365]
    const doe = yoe * 365 + @divFloor(yoe, 4) - @divFloor(yoe, 100) + doy; // [0,146096]
    return era * 146097 + doe - 719468;
}

const Civil = struct { y: i64, m: i64, d: i64 };

fn civilFromDays(z_in: i64) Civil {
    const z = z_in + 719468;
    const era = @divFloor(if (z >= 0) z else z - 146096, 146097);
    const doe = z - era * 146097; // [0, 146096]
    const yoe = @divFloor(doe - @divFloor(doe, 1460) + @divFloor(doe, 36524) - @divFloor(doe, 146096), 365); // [0,399]
    const y = yoe + era * 400;
    const doy = doe - (365 * yoe + @divFloor(yoe, 4) - @divFloor(yoe, 100)); // [0,365]
    const mp = @divFloor(5 * doy + 2, 153); // [0,11]
    const d = doy - @divFloor(153 * mp + 2, 5) + 1; // [1,31]
    const m = if (mp < 10) mp + 3 else mp - 9; // [1,12]
    return .{ .y = y + @as(i64, if (m <= 2) 1 else 0), .m = m, .d = d };
}

fn digitsToInt(s: []const u8) !i64 {
    if (!allDigits(s)) return E.@"transform-decode";
    return std.fmt.parseInt(i64, s, 10) catch E.@"transform-decode";
}

// YYYY-MM-DDTHH:MM:SS[.fff] then `Z`, `z`, `+hh:mm` or `-hh:mm`; the `T` may be
// lowercase. The instant is converted to UTC. Fraction digits beyond
// milliseconds are truncated.
fn isoToMs(s: []const u8) !i64 {
    if (s.len < 20) return E.@"transform-decode";
    if (s[4] != '-' or s[7] != '-' or (s[10] != 'T' and s[10] != 't') or s[13] != ':' or s[16] != ':') return E.@"transform-decode";
    const y = try digitsToInt(s[0..4]);
    const mo = try digitsToInt(s[5..7]);
    const d = try digitsToInt(s[8..10]);
    const hh = try digitsToInt(s[11..13]);
    const mm = try digitsToInt(s[14..16]);
    const ss = try digitsToInt(s[17..19]);
    // ruling 3b of 0.11: year 0001 to 9999, a day of that month, no leap second
    if (y < 1 or mo < 1 or mo > 12 or d < 1 or d > daysInMonth(y, mo) or hh > 23 or mm > 59 or ss > 59) return E.@"transform-decode";
    var i: usize = 19;
    var frac: i64 = 0;
    if (i < s.len and s[i] == '.') {
        i += 1;
        var digits: usize = 0;
        var seen: usize = 0;
        while (i < s.len and isDigit(s[i])) : (i += 1) {
            seen += 1;
            if (digits < 3) {
                frac = frac * 10 + @as(i64, s[i] - '0');
                digits += 1;
            }
        }
        if (seen == 0) return E.@"transform-decode";
        while (digits < 3) : (digits += 1) frac *= 10;
    }
    var offset_s: i64 = 0;
    const rest = s[i..];
    if (rest.len == 1 and (rest[0] == 'Z' or rest[0] == 'z')) {
        // UTC
    } else if (rest.len == 6 and (rest[0] == '+' or rest[0] == '-') and rest[3] == ':') {
        const oh = try digitsToInt(rest[1..3]);
        const om = try digitsToInt(rest[4..6]);
        if (oh > 23 or om > 59) return E.@"transform-decode";
        offset_s = oh * 3600 + om * 60;
        if (rest[0] == '-') offset_s = -offset_s;
    } else return E.@"transform-decode";
    const days = daysFromCivil(y, mo, d);
    const secs = days * 86400 + hh * 3600 + mm * 60 + ss - offset_s;
    const ms = secs * 1000 + frac;
    // the instant lies from 0001-01-01T00:00:00.000Z to 9999-12-31T23:59:59.999Z (3d)
    if (ms < iso_min_ms or ms > iso_max_ms) return E.@"transform-decode";
    return ms;
}

const iso_min_ms: i64 = -62135596800000;
const iso_max_ms: i64 = 253402300799999;

fn msToIso(alloc: std.mem.Allocator, ms: i64) ![]const u8 {
    if (ms < iso_min_ms or ms > iso_max_ms) return E.@"transform-encode"; // ruling 3f of 0.11
    const total_secs = @divFloor(ms, 1000);
    const msec = @mod(ms, 1000);
    const days = @divFloor(total_secs, 86400);
    var rem = @mod(total_secs, 86400);
    const hh = @divFloor(rem, 3600);
    rem -= hh * 3600;
    const mm = @divFloor(rem, 60);
    const ss = rem - mm * 60;
    const c = civilFromDays(days);
    if (c.y < 0 or c.y > 9999) return E.@"transform-encode"; // no four-digit year
    return std.fmt.allocPrint(alloc, "{d:0>4}-{d:0>2}-{d:0>2}T{d:0>2}:{d:0>2}:{d:0>2}.{d:0>3}Z", .{
        @as(u64, @intCast(c.y)), @as(u64, @intCast(c.m)), @as(u64, @intCast(c.d)),
        @as(u64, @intCast(hh)),  @as(u64, @intCast(mm)),  @as(u64, @intCast(ss)),
        @as(u64, @intCast(msec)),
    });
}

// `iso8601_s` encode (Version 0.12): the text of msToIso less its `.fff`,
// so the second that holds the instant.
fn msToIsoSeconds(alloc: std.mem.Allocator, ms: i64) ![]const u8 {
    const full = try msToIso(alloc, ms);
    return std.fmt.allocPrint(alloc, "{s}Z", .{full[0..19]});
}

// ---------------------------------------------------------------------------
// XML DOM + parser
// ---------------------------------------------------------------------------

// `weak`: written by a sentinel (Version 0.9); a field line whose key is
// present writes over it.
const XmlAttr = struct { name: []const u8, value: []const u8, weak: bool = false };

const XmlNode = struct {
    name: []const u8,
    attrs: std.ArrayList(XmlAttr),
    children: std.ArrayList(*XmlNode),
    text: []const u8 = "",
    text_set: bool = false,
    text_weak: bool = false, // the text was written by a sentinel
    // a parsed element holds character data (ruling 1m of 0.11): without
    // it, `#text` is absent
    has_text: bool = false,

    fn attr(self: *const XmlNode, name: []const u8) ?[]const u8 {
        for (self.attrs.items) |a| if (std.mem.eql(u8, a.name, name)) return a.value;
        return null;
    }
    fn child(self: *const XmlNode, name: []const u8) ?*XmlNode {
        for (self.children.items) |c| if (std.mem.eql(u8, c.name, name)) return c;
        return null;
    }
};

fn xmlNewNode(alloc: std.mem.Allocator, name: []const u8) !*XmlNode {
    const node = try alloc.create(XmlNode);
    node.* = .{
        .name = name,
        .attrs = std.ArrayList(XmlAttr).init(alloc),
        .children = std.ArrayList(*XmlNode).init(alloc),
    };
    return node;
}

// Is the code point a character XML 1.0 allows?
fn xmlCharOk(c: u21) bool {
    return c == 0x9 or c == 0xa or c == 0xd or (c >= 0x20 and c <= 0xd7ff) or (c >= 0xe000 and c <= 0xfffd) or (c >= 0x10000 and c <= 0x10ffff);
}

// One reference at `s[i]` (an `&`), decoded into `out` (ruling 1j of 0.11):
// the five predefined entities, in lower case, and numeric character
// references, decimal or `x` and hexadecimal digits naming a character XML
// 1.0 allows (ruling 40 of 0.8). Any other `&` is `malformed-wire`. Returns
// the index after the `;`.
fn xmlRef(s: []const u8, i: usize, out: *std.ArrayList(u8)) !usize {
    const mw = E.@"malformed-wire";
    var j = i + 1;
    while (j < s.len and (std.ascii.isAlphanumeric(s[j]) or s[j] == '#')) j += 1;
    if (j >= s.len or s[j] != ';') return mw;
    const ent = s[i + 1 .. j];
    if (ent.len > 0 and ent[0] == '#') {
        var digits = ent[1..];
        var base: u8 = 10;
        if (digits.len > 0 and digits[0] == 'x') {
            digits = digits[1..];
            base = 16;
        }
        if (digits.len == 0) return mw;
        var cp: u32 = 0;
        for (digits) |c| {
            const d = std.fmt.charToDigit(c, base) catch return mw;
            cp = cp * base + d;
            if (cp > 0x10ffff) return mw;
        }
        if (!xmlCharOk(@intCast(cp))) return mw;
        var ubuf: [4]u8 = undefined;
        const n = std.unicode.utf8Encode(@intCast(cp), &ubuf) catch return mw;
        try out.appendSlice(ubuf[0..n]);
        return j + 1;
    }
    const names = [_]struct { n: []const u8, c: u8 }{
        .{ .n = "amp", .c = '&' },  .{ .n = "lt", .c = '<' },    .{ .n = "gt", .c = '>' },
        .{ .n = "quot", .c = '"' }, .{ .n = "apos", .c = '\'' },
    };
    for (names) |nm| {
        if (std.mem.eql(u8, ent, nm.n)) {
            try out.append(nm.c);
            return j + 1;
        }
    }
    return mw;
}

// Can the text be written on `xml` (ruling 1d of 0.11)? Not below U+0020
// other than tab, line feed and carriage return; not U+FFFE or U+FFFF.
fn xmlWritable(s: []const u8) bool {
    var i: usize = 0;
    while (i < s.len) : (i += 1) {
        const c = s[i];
        if (c < 0x20 and c != 0x9 and c != 0xa and c != 0xd) return false;
        if (c == 0xef and i + 2 < s.len and s[i + 1] == 0xbf and (s[i + 2] == 0xbe or s[i + 2] == 0xbf)) return false;
    }
    return true;
}

// The deepest nesting a message may have on `xml` (elements, the root is
// level 1) and on `json` and `geojson` (arrays and objects, the outermost is
// level 1): ruling 35 of 0.8.
const max_nesting: usize = 64;

const XmlParser = struct {
    s: []const u8,
    i: usize = 0,
    alloc: std.mem.Allocator,

    const mw = E.@"malformed-wire";

    fn ws(self: *XmlParser) void {
        while (self.i < self.s.len and (self.s[self.i] == ' ' or self.s[self.i] == '\t' or self.s[self.i] == '\n' or self.s[self.i] == '\r')) self.i += 1;
    }
    fn starts(self: *XmlParser, pat: []const u8) bool {
        return self.s.len - self.i >= pat.len and std.mem.eql(u8, self.s[self.i .. self.i + pat.len], pat);
    }
    // Skip a construct that opens with `open_len` bytes at the cursor and
    // ends with `close`; the input ending inside it is malformed.
    fn skipPast(self: *XmlParser, open_len: usize, close: []const u8) !void {
        const at = std.mem.indexOfPos(u8, self.s, self.i + open_len, close) orelse return mw;
        self.i = at + close.len;
    }
    // Whitespace, comments and processing instructions. A document type
    // declaration is not skipped: it is malformed wherever it stands
    // (ruling 40 of 0.8).
    fn skipMisc(self: *XmlParser) !void {
        while (true) {
            self.ws();
            if (self.starts("<?")) {
                try self.skipPast(2, "?>");
            } else if (self.starts("<!--")) {
                try self.skipPast(4, "-->");
            } else break;
        }
    }
    fn readName(self: *XmlParser) ![]const u8 {
        const start = self.i;
        while (self.i < self.s.len) {
            const c = self.s[self.i];
            if (c == ' ' or c == '\t' or c == '\n' or c == '\r' or c == '=' or c == '>' or c == '/') break;
            if (c == '<' or c == '"' or c == '\'' or c == '&') return mw;
            self.i += 1;
        }
        if (self.i == start) return mw;
        return self.s[start..self.i];
    }
    // `depth`: the level of the element at the cursor, the root being 1.
    fn parseElement(self: *XmlParser, depth: usize) anyerror!*XmlNode {
        if (depth > max_nesting) return mw;
        if (self.i >= self.s.len or self.s[self.i] != '<') return mw;
        self.i += 1;
        // `<!`: a declaration or CDATA section where an element must stand
        if (self.i < self.s.len and self.s[self.i] == '!') return mw;
        const node = try xmlNewNode(self.alloc, try self.readName());
        // attributes
        while (true) {
            self.ws();
            if (self.i >= self.s.len) return mw;
            if (self.s[self.i] == '>' or self.s[self.i] == '/') break;
            const an = try self.readName();
            self.ws();
            if (self.i >= self.s.len or self.s[self.i] != '=') return mw;
            self.i += 1;
            self.ws();
            if (self.i >= self.s.len or (self.s[self.i] != '"' and self.s[self.i] != '\'')) return mw;
            const q = self.s[self.i];
            self.i += 1;
            // ruling 1i of 0.11: a literal tab or line feed reads as a space,
            // one written as a reference is kept; a `<` is malformed
            var vbuf = std.ArrayList(u8).init(self.alloc);
            while (self.i < self.s.len and self.s[self.i] != q) {
                const c = self.s[self.i];
                if (c == '<') return mw;
                if (c == '&') {
                    self.i = try xmlRef(self.s, self.i, &vbuf);
                    continue;
                }
                try vbuf.append(if (c == '\t' or c == '\n') ' ' else c);
                self.i += 1;
            }
            if (self.i >= self.s.len) return mw;
            self.i += 1; // closing quote
            // an attribute name twice on one element (ruling 1o)
            if (node.attr(an) != null) return mw;
            try node.attrs.append(.{ .name = an, .value = try vbuf.toOwnedSlice() });
        }
        if (self.s[self.i] == '/') {
            // self-closing "/>"
            self.i += 1;
            if (self.i >= self.s.len or self.s[self.i] != '>') return mw;
            self.i += 1;
            return node;
        }
        self.i += 1; // consume '>'
        // content
        var textbuf = std.ArrayList(u8).init(self.alloc);
        var closed = false;
        while (self.i < self.s.len) {
            if (self.starts("</")) {
                // the closing tag names the open element
                self.i += 2;
                const cn = try self.readName();
                if (!std.mem.eql(u8, cn, node.name)) return mw;
                self.ws();
                if (self.i >= self.s.len or self.s[self.i] != '>') return mw;
                self.i += 1;
                closed = true;
                break;
            } else if (self.starts("<!--")) {
                try self.skipPast(4, "-->");
            } else if (self.starts("<?")) {
                try self.skipPast(2, "?>");
            } else if (self.starts("<![CDATA[")) {
                // character data exactly as written (ruling 1k of 0.11)
                const from = self.i + 9;
                try self.skipPast(9, "]]>");
                try textbuf.appendSlice(self.s[from .. self.i - 3]);
            } else if (self.starts("<!")) {
                return mw;
            } else if (self.s[self.i] == '<') {
                const c = try self.parseElement(depth + 1);
                try node.children.append(c);
            } else if (self.s[self.i] == '&') {
                self.i = try xmlRef(self.s, self.i, &textbuf);
            } else {
                try textbuf.append(self.s[self.i]);
                self.i += 1;
            }
        }
        if (!closed) return mw;
        node.has_text = textbuf.items.len > 0;
        node.text = try textbuf.toOwnedSlice();
        return node;
    }
};

// One well-formed document: the root element, and after it only whitespace,
// comments and processing instructions. An input with no element is
// malformed (ruling 37 of 0.8).
fn parseXml(alloc: std.mem.Allocator, s_in: []const u8) !*XmlNode {
    var s = s_in;
    // one byte order mark at the very start is skipped (ruling 1g of 0.11)
    if (std.mem.startsWith(u8, s, "\xef\xbb\xbf")) s = s[3..];
    // each CR LF, and each CR alone, is read as one LF (ruling 1h)
    if (std.mem.indexOfScalar(u8, s, '\r') != null) {
        const n = try alloc.alloc(u8, s.len);
        var k: usize = 0;
        var i: usize = 0;
        while (i < s.len) : (i += 1) {
            if (s[i] == '\r') {
                n[k] = '\n';
                if (i + 1 < s.len and s[i + 1] == '\n') i += 1;
            } else n[k] = s[i];
            k += 1;
        }
        s = n[0..k];
    }
    var p = XmlParser{ .s = s, .alloc = alloc };
    try p.skipMisc();
    const root = try p.parseElement(1);
    try p.skipMisc();
    if (p.i != s.len) return E.@"malformed-wire";
    return root;
}

// The node a locator's path reaches, and the locator's last segment.
const XmlTarget = struct { node: *XmlNode, last: []const u8 };

fn xmlTarget(root: *XmlNode, locator: []const u8) ?XmlTarget {
    var node: *XmlNode = root;
    var rest = locator;
    while (std.mem.indexOfScalar(u8, rest, '/')) |slash| {
        node = node.child(rest[0..slash]) orelse return null;
        rest = rest[slash + 1 ..];
    }
    return .{ .node = node, .last = rest };
}

// The text at a locator: an attribute value, or an element's text content.
// null when the attribute or element does not exist.
fn xmlGet(root: *XmlNode, locator: []const u8) ?[]const u8 {
    const t = xmlTarget(root, locator) orelse return null;
    if (t.last.len > 0 and t.last[0] == '@') return t.node.attr(t.last[1..]);
    if (std.mem.eql(u8, t.last, "#text")) return if (t.node.has_text) t.node.text else null;
    return null;
}

// Is the locator a root-level attribute, i.e. "@name" with no '/'?
fn isRootAttr(locator: []const u8) bool {
    return locator.len > 0 and locator[0] == '@' and std.mem.indexOfScalar(u8, locator, '/') == null;
}

// ---------------------------------------------------------------------------
// JSON helpers (geojson and json wires)
// ---------------------------------------------------------------------------

const JValue = std.json.Value;

// One JSON value from the scanner's tokens, every number kept as its text
// (`.number_string`). Of two members with one name, the last value is used at
// the first position.
fn jsonValueAsWritten(alloc: std.mem.Allocator, sc: *std.json.Scanner, tok: std.json.Token) anyerror!JValue {
    switch (tok) {
        .object_begin => {
            var obj = std.json.ObjectMap.init(alloc);
            while (true) {
                switch (try sc.nextAlloc(alloc, .alloc_always)) {
                    .object_end => break,
                    .allocated_string => |name| {
                        const v = try jsonValueAsWritten(alloc, sc, try sc.nextAlloc(alloc, .alloc_always));
                        try obj.put(name, v);
                    },
                    else => return error.SyntaxError,
                }
            }
            return .{ .object = obj };
        },
        .array_begin => {
            var arr = std.json.Array.init(alloc);
            while (true) {
                const t = try sc.nextAlloc(alloc, .alloc_always);
                if (t == .array_end) break;
                try arr.append(try jsonValueAsWritten(alloc, sc, t));
            }
            return .{ .array = arr };
        },
        .true => return .{ .bool = true },
        .false => return .{ .bool = false },
        .null => return .null,
        .allocated_number => |text| return .{ .number_string = text },
        .allocated_string => |text| return .{ .string = text },
        else => return error.SyntaxError,
    }
}

fn parseJsonAsWritten(alloc: std.mem.Allocator, bytes: []const u8) anyerror!JValue {
    var sc = std.json.Scanner.initCompleteInput(alloc, bytes);
    defer sc.deinit();
    const v = try jsonValueAsWritten(alloc, &sc, try sc.nextAlloc(alloc, .alloc_always));
    if (try sc.nextAlloc(alloc, .alloc_always) != .end_of_document) return error.SyntaxError;
    return v;
}

// Is the input one JSON value (RFC 8259) followed only by whitespace, nested
// no deeper than `max_nesting` arrays and objects? Checked before the input
// is parsed, with no recursion: numbers, escapes and string characters as the
// grammar has them (rulings 35 and 39 of 0.8).
fn jsonValidate(s: []const u8) EngineError!void {
    const mw = E.@"malformed-wire";
    const St = enum { value, value_or_end, key, key_or_end, colon, after_value };
    var open: [max_nesting]u8 = undefined; // '{' or '[' per open level
    var depth: usize = 0;
    var st: St = .value;
    var i: usize = 0;
    while (true) {
        while (i < s.len and (s[i] == ' ' or s[i] == '\t' or s[i] == '\n' or s[i] == '\r')) i += 1;
        if (st == .after_value and depth == 0) {
            if (i != s.len) return mw; // a second value, or anything else
            return;
        }
        if (i >= s.len) return mw;
        const c = s[i];
        switch (st) {
            .value, .value_or_end => {
                if (st == .value_or_end and c == ']') {
                    i += 1;
                    depth -= 1;
                    st = .after_value;
                    continue;
                }
                switch (c) {
                    '{', '[' => {
                        if (depth == max_nesting) return mw;
                        open[depth] = c;
                        depth += 1;
                        i += 1;
                        st = if (c == '{') .key_or_end else .value_or_end;
                    },
                    '"' => {
                        i = try jsonSkipString(s, i);
                        st = .after_value;
                    },
                    '-', '0'...'9' => {
                        i = try jsonSkipNumber(s, i);
                        st = .after_value;
                    },
                    't', 'f', 'n' => {
                        const lit: []const u8 = if (c == 't') "true" else if (c == 'f') "false" else "null";
                        if (!std.mem.startsWith(u8, s[i..], lit)) return mw;
                        i += lit.len;
                        st = .after_value;
                    },
                    else => return mw,
                }
            },
            .key, .key_or_end => {
                if (st == .key_or_end and c == '}') {
                    i += 1;
                    depth -= 1;
                    st = .after_value;
                    continue;
                }
                if (c != '"') return mw;
                i = try jsonSkipString(s, i);
                st = .colon;
            },
            .colon => {
                if (c != ':') return mw;
                i += 1;
                st = .value;
            },
            .after_value => {
                const in_obj = open[depth - 1] == '{';
                if (c == ',') {
                    i += 1;
                    st = if (in_obj) .key else .value;
                } else if ((c == '}' and in_obj) or (c == ']' and !in_obj)) {
                    i += 1;
                    depth -= 1;
                } else return mw;
            },
        }
    }
}

// One string, from its opening quote; the result is the index after its
// closing quote.
fn jsonSkipString(s: []const u8, start: usize) EngineError!usize {
    const mw = E.@"malformed-wire";
    var i = start + 1;
    while (i < s.len) {
        const c = s[i];
        if (c == '"') return i + 1;
        if (c < 0x20) return mw; // a raw control character
        if (c != '\\') {
            i += 1;
            continue;
        }
        if (s.len - i < 2) return mw;
        switch (s[i + 1]) {
            '"', '\\', '/', 'b', 'f', 'n', 'r', 't' => i += 2,
            'u' => {
                const hi = try jsonHex4(s, i);
                i += 6;
                // half of a surrogate pair without its other half
                if (hi >= 0xdc00 and hi <= 0xdfff) return mw;
                if (hi >= 0xd800 and hi <= 0xdbff) {
                    const lo = try jsonHex4(s, i);
                    if (lo < 0xdc00 or lo > 0xdfff) return mw;
                    i += 6;
                }
            },
            else => return mw, // an unknown escape
        }
    }
    return mw;
}

// The value of the `\\uXXXX` escape at `i`.
fn jsonHex4(s: []const u8, i: usize) EngineError!u16 {
    const mw = E.@"malformed-wire";
    if (s.len - i < 6 or s[i] != '\\' or s[i + 1] != 'u') return mw;
    var v: u16 = 0;
    for (s[i + 2 .. i + 6]) |h| {
        const d = std.fmt.charToDigit(h, 16) catch return mw;
        v = v * 16 + d;
    }
    return v;
}

// One number: [-] (0 | 1-9 digits) [. digits] [e|E [+|-] digits].
fn jsonSkipNumber(s: []const u8, start: usize) EngineError!usize {
    const mw = E.@"malformed-wire";
    var i = start;
    if (i < s.len and s[i] == '-') i += 1;
    if (i >= s.len or !isDigit(s[i])) return mw;
    if (s[i] == '0') {
        i += 1;
        if (i < s.len and isDigit(s[i])) return mw; // a leading zero
    } else {
        while (i < s.len and isDigit(s[i])) i += 1;
    }
    if (i < s.len and s[i] == '.') {
        i += 1;
        if (i >= s.len or !isDigit(s[i])) return mw;
        while (i < s.len and isDigit(s[i])) i += 1;
    }
    if (i < s.len and (s[i] == 'e' or s[i] == 'E')) {
        i += 1;
        if (i < s.len and (s[i] == '+' or s[i] == '-')) i += 1;
        if (i >= s.len or !isDigit(s[i])) return mw;
        while (i < s.len and isDigit(s[i])) i += 1;
    }
    return i;
}

// `as_written`: numbers are kept as their text (`.number_string`), for the
// geojson wire, whose residue gives a number back as it was written.
fn parseJsonObject(alloc: std.mem.Allocator, bytes: []const u8, as_written: bool) !std.json.ObjectMap {
    try jsonValidate(bytes);
    const parsed = if (as_written)
        parseJsonAsWritten(alloc, bytes)
    else
        std.json.parseFromSliceLeaky(JValue, alloc, bytes, .{ .duplicate_field_behavior = .use_last });
    const v = parsed catch |err| switch (err) {
        error.OutOfMemory => return error.OutOfMemory,
        else => return E.@"malformed-wire",
    };
    if (v != .object) return E.@"malformed-wire";
    return v.object;
}

// json wire: the same member name twice in one object is `malformed-wire`
// (ruling 22 of 0.5). The input is already known to be well-formed JSON.
fn jsonCheckNoDuplicates(alloc: std.mem.Allocator, bytes: []const u8) !void {
    const Frame = struct { is_obj: bool, expect_key: bool, keys: std.StringHashMap(void) };
    var stack = std.ArrayList(Frame).init(alloc);
    var sc = std.json.Scanner.initCompleteInput(alloc, bytes);
    defer sc.deinit();
    while (true) {
        const tok = sc.nextAlloc(alloc, .alloc_always) catch |err| switch (err) {
            error.OutOfMemory => return err,
            else => return E.@"malformed-wire",
        };
        switch (tok) {
            .end_of_document => return,
            .object_begin => try stack.append(.{ .is_obj = true, .expect_key = true, .keys = std.StringHashMap(void).init(alloc) }),
            .array_begin => try stack.append(.{ .is_obj = false, .expect_key = false, .keys = std.StringHashMap(void).init(alloc) }),
            .object_end, .array_end => {
                _ = stack.pop();
                if (stack.items.len > 0) stack.items[stack.items.len - 1].expect_key = stack.items[stack.items.len - 1].is_obj;
            },
            else => {
                if (stack.items.len == 0) continue;
                const top = &stack.items[stack.items.len - 1];
                if (top.is_obj and top.expect_key) {
                    const name = switch (tok) {
                        .allocated_string => |str| str,
                        else => return E.@"malformed-wire",
                    };
                    if (top.keys.contains(name)) return E.@"malformed-wire";
                    try top.keys.put(name, {});
                    top.expect_key = false;
                } else {
                    top.expect_key = top.is_obj;
                }
            },
        }
    }
}

fn jsonEscape(buf: *std.ArrayList(u8), s: []const u8) !void {
    try buf.append('"');
    for (s) |c| {
        switch (c) {
            '"' => try buf.appendSlice("\\\""),
            '\\' => try buf.appendSlice("\\\\"),
            '\n' => try buf.appendSlice("\\n"),
            '\r' => try buf.appendSlice("\\r"),
            '\t' => try buf.appendSlice("\\t"),
            0x08 => try buf.appendSlice("\\b"),
            0x0c => try buf.appendSlice("\\f"),
            else => {
                if (c < 0x20) {
                    try std.fmt.format(buf.writer(), "\\u{x:0>4}", .{c});
                } else try buf.append(c);
            },
        }
    }
    try buf.append('"');
}

fn jsonStr(alloc: std.mem.Allocator, s: []const u8) ![]const u8 {
    var buf = std.ArrayList(u8).init(alloc);
    try jsonEscape(&buf, s);
    return buf.toOwnedSlice();
}

// Canonical text of a JSON number value (ruling 3 of 0.1.1); null when the
// value is not a number.
fn jsonNumberText(alloc: std.mem.Allocator, v: JValue) !?[]const u8 {
    return switch (v) {
        .integer => |i| try intToStr(alloc, i),
        .float => |f| try floatToStr(alloc, f),
        .number_string => |s| {
            // an integer keeps every digit; anything else goes through a double
            if (parseDecimalInt(s)) |i| return try intToStr(alloc, i) else |_| {}
            return try floatToStr(alloc, std.fmt.parseFloat(f64, s) catch return null);
        },
        else => null,
    };
}

// Canonical JSON text of any value (objects and arrays included).
// `as_written`: a number kept as text is written as it was.
fn jsonCanon(alloc: std.mem.Allocator, buf: *std.ArrayList(u8), v: JValue, as_written: bool) anyerror!void {
    switch (v) {
        .number_string => |s| if (as_written) try buf.appendSlice(s) else try buf.appendSlice((try jsonNumberText(alloc, v)) orelse "null"),
        .null => try buf.appendSlice("null"),
        .bool => |b| try buf.appendSlice(if (b) "true" else "false"),
        .string => |s| try jsonEscape(buf, s),
        .integer, .float => try buf.appendSlice((try jsonNumberText(alloc, v)) orelse "null"),
        .array => |arr| {
            try buf.append('[');
            for (arr.items, 0..) |item, i| {
                if (i > 0) try buf.append(',');
                try jsonCanon(alloc, buf, item, as_written);
            }
            try buf.append(']');
        },
        .object => |obj| {
            try buf.append('{');
            var it = obj.iterator();
            var first = true;
            while (it.next()) |en| {
                if (!first) try buf.append(',');
                first = false;
                try jsonEscape(buf, en.key_ptr.*);
                try buf.append(':');
                try jsonCanon(alloc, buf, en.value_ptr.*, as_written);
            }
            try buf.append('}');
        },
    }
}

fn jsonCanonText(alloc: std.mem.Allocator, v: JValue, as_written: bool) ![]const u8 {
    var buf = std.ArrayList(u8).init(alloc);
    try jsonCanon(alloc, &buf, v, as_written);
    return buf.toOwnedSlice();
}

// A JSON value through a text transform (geojson and json wires). A value of
// the wrong JSON type is a transform decode failure.
fn jsonToMV(t: TKind, val: JValue) !MV {
    switch (t) {
        .string => {
            if (val != .string) return E.@"transform-decode";
            return MV{ .str = val.string };
        },
        .float => {
            const f: f64 = switch (val) {
                .integer => |i| @floatFromInt(i),
                .float => |x| x,
                .number_string => |s| std.fmt.parseFloat(f64, s) catch return E.@"transform-decode",
                else => return E.@"transform-decode",
            };
            if (!std.math.isFinite(f)) return E.@"transform-decode"; // a model float is always finite
            return MV{ .float = f };
        },
        .int => {
            const f: f64 = switch (val) {
                .integer => |i| return MV{ .int = i },
                .float => |x| x,
                // the exact value of the number text (ruling 2d of 0.11)
                .number_string => |s| return MV{ .int = exactJsonInt(s) orelse return E.@"transform-decode" },
                else => return E.@"transform-decode",
            };
            // any number whose value is integral (1.0, 1e3)
            if (!(f >= -9223372036854775808.0 and f < 9223372036854775808.0) or @floor(f) != f) return E.@"transform-decode";
            return MV{ .int = @intFromFloat(f) };
        },
        .iso8601_ms, .iso8601_s => {
            if (val != .string) return E.@"transform-decode";
            return MV{ .int = try isoToMs(val.string) };
        },
        .bool_ => {
            if (val != .bool) return E.@"transform-decode";
            return MV{ .int = if (val.bool) 1 else 0 };
        },
        else => return E.@"transform-decode",
    }
}

// The exact value of JSON number text when it is an integer within a signed
// 64-bit integer (ruling 2d of 0.11): `1.0`, `1e3` and
// `9.223372036854775807e18` are integers; `1.5` and `1e19` are not. null
// otherwise.
fn exactJsonInt(s: []const u8) ?i64 {
    var i: usize = 0;
    const neg = i < s.len and s[i] == '-';
    if (neg) i += 1;
    const int_from = i;
    while (i < s.len and isDigit(s[i])) i += 1;
    const int_digits = s[int_from..i];
    var frac_digits: []const u8 = "";
    if (i < s.len and s[i] == '.') {
        i += 1;
        const f0 = i;
        while (i < s.len and isDigit(s[i])) i += 1;
        frac_digits = s[f0..i];
    }
    var exp: i64 = 0;
    if (i < s.len and (s[i] == 'e' or s[i] == 'E')) {
        i += 1;
        var eneg = false;
        if (i < s.len and (s[i] == '+' or s[i] == '-')) {
            eneg = s[i] == '-';
            i += 1;
        }
        while (i < s.len and isDigit(s[i])) : (i += 1) {
            if (exp < 1 << 40) exp = exp * 10 + (s[i] - '0');
        }
        if (eneg) exp = -exp;
    }
    if (i != s.len or int_digits.len == 0) return null;
    // the significant digits, and the power of ten they are scaled by
    var digits_buf: [64]u8 = undefined;
    var nd: usize = 0;
    var scale: i64 = exp;
    var started = false;
    for ([_][]const u8{ int_digits, frac_digits }, 0..) |part, pi| {
        for (part) |c| {
            if (pi == 1) scale -= 1;
            if (!started and c == '0') continue;
            started = true;
            if (nd == digits_buf.len) return null; // far more digits than 64 bits hold
            digits_buf[nd] = c;
            nd += 1;
        }
    }
    if (nd == 0) return 0; // zero, `-0` included
    // trailing zeros of the digits move into the scale
    while (nd > 0 and digits_buf[nd - 1] == '0') {
        nd -= 1;
        scale += 1;
    }
    if (scale < 0) return null; // a fraction is left
    if (@as(i64, @intCast(nd)) + scale > 19) return null;
    var v: i128 = 0;
    for (digits_buf[0..nd]) |c| v = v * 10 + (c - '0');
    var k: i64 = 0;
    while (k < scale) : (k += 1) v *= 10;
    if (neg) v = -v;
    if (v < std.math.minInt(i64) or v > std.math.maxInt(i64)) return null;
    return @intCast(v);
}

// The JSON text a model value is written as, through a text transform.
fn jsonRaw(alloc: std.mem.Allocator, t: TKind, mv: MV) ![]const u8 {
    switch (t) {
        .string => {
            if (mv != .str) return E.@"transform-encode";
            return jsonStr(alloc, mv.str);
        },
        .float => return switch (mv) {
            .float => |f| try floatToStr(alloc, f),
            .int => |i| try intToStr(alloc, i),
            else => E.@"transform-encode",
        },
        .int => {
            if (mv != .int) return E.@"transform-encode";
            return intToStr(alloc, mv.int);
        },
        .iso8601_ms => {
            if (mv != .int) return E.@"transform-encode";
            return jsonStr(alloc, try msToIso(alloc, mv.int));
        },
        .iso8601_s => {
            if (mv != .int) return E.@"transform-encode";
            return jsonStr(alloc, try msToIsoSeconds(alloc, mv.int));
        },
        .bool_ => {
            if (mv != .int) return E.@"transform-encode";
            if (mv.int == 1) return "true";
            if (mv.int == 0) return "false";
            return E.@"transform-encode";
        },
        else => return E.@"transform-encode",
    }
}

// Is `s` canonical JSON number text (the text ruling 3 of 0.1.1 writes)?
fn isCanonNumber(alloc: std.mem.Allocator, s: []const u8) bool {
    if (!isDecimalText(s)) return false;
    const f = std.fmt.parseFloat(f64, s) catch return false;
    const c = floatToStr(alloc, f) catch return false;
    return std.mem.eql(u8, c, s);
}

// The JSON text a `when` value is written as (ruling 11).
fn whenJsonRaw(alloc: std.mem.Allocator, ln: Line) ![]const u8 {
    if (!ln.wforced) {
        if (std.mem.eql(u8, ln.wtext, "true") or std.mem.eql(u8, ln.wtext, "false")) return ln.wtext;
        if (isCanonNumber(alloc, ln.wtext)) return ln.wtext;
    }
    return jsonStr(alloc, ln.wtext);
}

// Does a `when` hold for this member value (null: the member is absent)?
fn whenJsonHolds(alloc: std.mem.Allocator, ln: Line, val: ?JValue) bool {
    const v = val orelse return false;
    if (v == .null) return false;
    if (ln.wpresent) return true;
    switch (v) {
        .string => |s| return std.mem.eql(u8, s, ln.wtext),
        .bool => |b| return std.mem.eql(u8, if (b) "true" else "false", ln.wtext),
        .integer, .float, .number_string => {
            const t = (jsonNumberText(alloc, v) catch return false) orelse return false;
            return std.mem.eql(u8, t, ln.wtext);
        },
        else => return false,
    }
}

const GeoDoc = struct {
    obj: std.json.ObjectMap,
    coords: ?std.json.Array,
    props: ?std.json.ObjectMap,
};

const props_prefix = "properties.";
const geom_prefix = "geometry.";

fn geoLookup(d: GeoDoc, loc: []const u8) ?JValue {
    if (std.mem.startsWith(u8, loc, geom_prefix)) {
        const comp = loc[geom_prefix.len..];
        const idx: usize = if (std.mem.eql(u8, comp, "lon")) 0 else if (std.mem.eql(u8, comp, "lat")) 1 else if (std.mem.eql(u8, comp, "alt")) 2 else return null;
        if (d.coords) |arr| {
            if (idx < arr.items.len) return arr.items[idx];
        }
        return null;
    } else if (std.mem.startsWith(u8, loc, props_prefix)) {
        if (d.props) |pm| return pm.get(loc[props_prefix.len..]);
        return null;
    }
    return d.obj.get(loc);
}

fn jsonLookup(obj: std.json.ObjectMap, segs: []const []const u8) ?JValue {
    var cur = obj;
    for (segs, 0..) |seg, i| {
        const v = cur.get(seg) orelse return null;
        if (i + 1 == segs.len) return v;
        if (v != .object) return null;
        cur = v.object;
    }
    return null;
}

// ---------------------------------------------------------------------------
// bits helpers
// ---------------------------------------------------------------------------

// `len` bits (1..64) from absolute bit `start` of the message. lsb: bit i is
// bit (i mod 8) of byte (i div 8), low bit first. msb: bit i is bit
// 7 - (i mod 8) of byte (i div 8), first bit most significant.
fn getBits(buf: []const u8, msb: bool, start: usize, len: usize) u64 {
    var v: u64 = 0;
    var k: usize = 0;
    while (k < len) : (k += 1) {
        const a = start + k;
        const byte = buf[a / 8];
        if (msb) {
            const bit: u64 = (byte >> @as(u3, @intCast(7 - (a % 8)))) & 1;
            v = (v << 1) | bit;
        } else {
            const bit: u64 = (byte >> @as(u3, @intCast(a % 8))) & 1;
            v |= bit << @as(u6, @intCast(k));
        }
    }
    return v;
}

// Write the low `len` bits of `value` over the range (set and clear).
fn setBits(buf: []u8, msb: bool, start: usize, len: usize, value: u64) void {
    var k: usize = 0;
    while (k < len) : (k += 1) {
        const a = start + k;
        const vbit: u64 = if (msb)
            (value >> @as(u6, @intCast(len - 1 - k))) & 1
        else
            (value >> @as(u6, @intCast(k))) & 1;
        const mask: u8 = @as(u8, 1) << @as(u3, @intCast(if (msb) 7 - (a % 8) else a % 8));
        if (vbit != 0) {
            buf[a / 8] |= mask;
        } else {
            buf[a / 8] &= ~mask;
        }
    }
}

fn signExtend(bits: u64, len: usize) i64 {
    if (len == 0 or len >= 64) return @bitCast(bits);
    const sign_bit = @as(u64, 1) << @intCast(len - 1);
    if ((bits & sign_bit) != 0) {
        const span = @as(u64, 1) << @intCast(len);
        return @bitCast(bits -% span);
    }
    return @bitCast(bits);
}

fn hexDecode(alloc: std.mem.Allocator, s: []const u8) ![]u8 {
    var nibbles = std.ArrayList(u8).init(alloc);
    defer nibbles.deinit();
    for (s) |c| {
        const n: ?u8 = switch (c) {
            '0'...'9' => c - '0',
            'a'...'f' => c - 'a' + 10,
            'A'...'F' => c - 'A' + 10,
            ' ', '\t', '\n', '\r' => null,
            else => return E.@"malformed-wire",
        };
        if (n) |nv| try nibbles.append(nv);
    }
    if (nibbles.items.len % 2 != 0) return E.@"malformed-wire";
    var out = try alloc.alloc(u8, nibbles.items.len / 2);
    var i: usize = 0;
    while (i < out.len) : (i += 1) {
        out[i] = nibbles.items[2 * i] * 16 + nibbles.items[2 * i + 1];
    }
    return out;
}

fn hexEncode(alloc: std.mem.Allocator, buf: []const u8) ![]u8 {
    const hexchars = "0123456789abcdef";
    var out = try alloc.alloc(u8, buf.len * 2);
    for (buf, 0..) |b, i| {
        out[2 * i] = hexchars[b >> 4];
        out[2 * i + 1] = hexchars[b & 0x0f];
    }
    return out;
}

// Read one field. With `swap` the field's bytes are taken in reverse order
// before the transform reads them.
fn bitsDecodeField(alloc: std.mem.Allocator, p: *const Pack, buf_in: []const u8, base: usize, ln: *const Line) !MV {
    var buf = buf_in;
    var start = base + ln.bstart;
    if (ln.swap) {
        const n = ln.blen / 8;
        const tmp = try alloc.alloc(u8, n);
        for (0..n) |j| tmp[n - 1 - j] = @intCast(getBits(buf_in, p.msb, base + ln.bstart + 8 * j, 8));
        buf = tmp;
        start = 0;
    }
    const t = ln.transform;
    if (t.kind == .ascii) {
        const n = ln.blen / 8;
        const bytes = try alloc.alloc(u8, n);
        for (bytes, 0..) |*b, j| b.* = @intCast(getBits(buf, p.msb, start + 8 * j, 8));
        var end: usize = n;
        while (end > 0 and bytes[end - 1] == 0) end -= 1; // trailing NUL bytes removed
        if (ln.trim) {
            while (end > 0 and bytes[end - 1] == 0x20) end -= 1; // then trailing spaces
        }
        for (bytes[0..end]) |b| if (b < 0x20 or b > 0x7e) return E.@"transform-decode";
        return MV{ .str = bytes[0..end] };
    }
    const bits = getBits(buf, p.msb, start, ln.blen);
    switch (t.kind) {
        .uint => return MV{ .int = @bitCast(bits) },
        .twos => return MV{ .int = signExtend(bits, ln.blen) },
        .linscale => return MV{ .float = @as(f64, @floatFromInt(signExtend(bits, ln.blen))) / t.maxpos * t.range },
        .uscale, .sscale => {
            const v: f64 = if (t.kind == .uscale) @floatFromInt(bits) else @floatFromInt(signExtend(bits, ln.blen));
            // in doubles, in this order: v * factor (or v * num / den), then + offset
            return MV{ .float = t.factor.mul(v) + t.offset };
        },
        .f32_ => {
            const f: f32 = @bitCast(@as(u32, @intCast(bits)));
            if (!std.math.isFinite(f)) return E.@"transform-decode"; // infinity and NaN on the wire
            return MV{ .float = @as(f64, f) };
        },
        .f64_ => {
            const f: f64 = @bitCast(bits);
            if (!std.math.isFinite(f)) return E.@"transform-decode";
            return MV{ .float = f };
        },
        else => return E.@"transform-decode",
    }
}

// The raw value of a field of at most 64 bits (Version 0.9): its `len` bits as
// an unsigned integer, as `uint` reads them, after `swap`.
fn bitsRaw(p: *const Pack, buf: []const u8, base: usize, ln: *const Line) u64 {
    if (!ln.swap) return getBits(buf, p.msb, base + ln.bstart, ln.blen);
    const n = ln.blen / 8;
    var tmp: [8]u8 = undefined;
    for (0..n) |j| tmp[n - 1 - j] = @intCast(getBits(buf, p.msb, base + ln.bstart + 8 * j, 8));
    return getBits(tmp[0..n], p.msb, 0, ln.blen);
}

// Write a raw value (a sentinel) into a field's bits: the low `len` bits, then
// `swap`.
fn bitsWriteRaw(p: *const Pack, out: []u8, base: usize, ln: *const Line, v: u64) void {
    if (!ln.swap) return setBits(out, p.msb, base + ln.bstart, ln.blen, v);
    const n = ln.blen / 8;
    var tmp = [_]u8{0} ** 8;
    setBits(tmp[0..n], p.msb, 0, ln.blen, v);
    for (0..n) |j| setBits(out, p.msb, base + ln.bstart + 8 * j, 8, tmp[n - 1 - j]);
}

fn mvFloat(mv: MV) !f64 {
    return switch (mv) {
        .float => |f| f,
        .int => |i| @floatFromInt(i),
        else => E.@"transform-encode",
    };
}

// A double narrowed to a single; a value outside single range is an encode
// error.
fn narrowF32(x: f64) !f32 {
    if (!std.math.isFinite(x)) return E.@"transform-encode";
    const f: f32 = @floatCast(x);
    if (!std.math.isFinite(f)) return E.@"transform-encode";
    return f;
}

// The field's value as the low `blen` bits to write (not for `ascii`).
fn bitsEncodeField(ln: *const Line, mv: MV) !u64 {
    const t = ln.transform;
    switch (t.kind) {
        // a value that does not fit the field is `transform-encode`; no
        // low bits are written (ruling 4b of 0.11)
        .uint, .twos => {
            if (mv != .int) return E.@"transform-encode";
            const v: i128 = mv.int;
            const len: u7 = @intCast(ln.blen);
            if (t.kind == .uint) {
                if (len < 64 and (v < 0 or v >= (@as(i128, 1) << len))) return E.@"transform-encode";
            } else {
                const half = @as(i128, 1) << (len - 1);
                if (v < -half or v >= half) return E.@"transform-encode";
            }
            return @bitCast(mv.int);
        },
        .linscale => {
            const r = @round(try mvFloat(mv) / t.range * t.maxpos);
            const hi = std.math.ldexp(@as(f64, 1.0), @as(i32, @intCast(ln.blen - 1)));
            if (!(r >= -hi and r < hi)) return E.@"transform-encode";
            return @bitCast(@as(i64, @intFromFloat(r)));
        },
        .uscale, .sscale => {
            const x = try mvFloat(mv);
            const r = @round(t.factor.div(x - t.offset)); // half away from zero
            // a value outside the field's range after rounding is an encode error
            if (t.kind == .uscale) {
                const hi = std.math.ldexp(@as(f64, 1.0), @as(i32, @intCast(ln.blen)));
                if (!(r >= 0 and r < hi)) return E.@"transform-encode";
                return @as(u64, @intFromFloat(r));
            }
            const hi = std.math.ldexp(@as(f64, 1.0), @as(i32, @intCast(ln.blen - 1)));
            if (!(r >= -hi and r < hi)) return E.@"transform-encode";
            return @bitCast(@as(i64, @intFromFloat(r)));
        },
        .f32_ => return @as(u64, @as(u32, @bitCast(try narrowF32(try mvFloat(mv))))),
        .f64_ => {
            const x = try mvFloat(mv);
            if (!std.math.isFinite(x)) return E.@"transform-encode";
            return @bitCast(x);
        },
        else => return E.@"transform-encode",
    }
}

// Write one field's `blen` bits at absolute bit `start` of `out`.
fn bitsPutField(out: []u8, msb: bool, start: usize, ln: *const Line, mv: MV) !void {
    if (ln.transform.kind == .ascii) {
        const n = ln.blen / 8;
        if (mv != .str or mv.str.len > n) return E.@"transform-encode"; // longer text
        for (mv.str) |b| if (b < 0x20 or b > 0x7e) return E.@"transform-encode";
        for (0..n) |j| {
            const b: u8 = if (j < mv.str.len) mv.str[j] else 0; // NUL-padded
            setBits(out, msb, start + 8 * j, 8, b);
        }
        return;
    }
    setBits(out, msb, start, ln.blen, try bitsEncodeField(ln, mv));
}

// Write one field into the message. With `swap` the bytes the transform wrote
// are reversed.
fn bitsWriteField(alloc: std.mem.Allocator, p: *const Pack, out: []u8, base: usize, ln: *const Line, mv: MV) !void {
    if (!ln.swap) return bitsPutField(out, p.msb, base + ln.bstart, ln, mv);
    const n = ln.blen / 8;
    const tmp = try alloc.alloc(u8, n);
    @memset(tmp, 0);
    try bitsPutField(tmp, p.msb, 0, ln, mv);
    for (0..n) |j| setBits(out, p.msb, base + ln.bstart + 8 * j, 8, tmp[n - 1 - j]);
}

// The message being written: it grows as items are added, zero-filled.
const BitsOut = struct {
    buf: std.ArrayList(u8),

    fn ensure(self: *BitsOut, nbits: usize) !void {
        const nb = (nbits + 7) / 8;
        if (nb > self.buf.items.len) try self.buf.appendNTimes(0, nb - self.buf.items.len);
    }
};

// ---------------------------------------------------------------------------
// protobuf helpers
// ---------------------------------------------------------------------------

// One field occurrence on the wire. For varint/fixed32/fixed64 the numeric
// payload is in `uval` (fixed values already decoded little-endian); for a
// length-delimited field the payload bytes are in `bytes`.
const PbEntry = struct {
    number: usize,
    wt: u3,
    uval: u64 = 0,
    bytes: []const u8 = &.{},
};

fn readVarint(buf: []const u8, i: *usize) !u64 {
    var result: u64 = 0;
    var shift: usize = 0;
    while (true) {
        if (i.* >= buf.len) return E.@"malformed-wire";
        const b = buf[i.*];
        i.* += 1;
        // at most ten bytes, and the tenth holds bit 63 only (ruling 40 of 0.8)
        if (shift >= 64 or (shift == 63 and b > 1)) return E.@"malformed-wire";
        result |= @as(u64, b & 0x7f) << @intCast(shift);
        if (b & 0x80 == 0) break;
        shift += 7;
    }
    return result;
}

// Parse one protobuf message into its field occurrences, in wire order.
fn parsePb(alloc: std.mem.Allocator, buf: []const u8) ![]PbEntry {
    var out = std.ArrayList(PbEntry).init(alloc);
    var i: usize = 0;
    while (i < buf.len) {
        const tag = try readVarint(buf, &i);
        if ((tag >> 3) == 0 or (tag >> 3) > 0x1fffffff) return E.@"malformed-wire";
        const number: usize = @intCast(tag >> 3);
        const wt: u3 = @intCast(tag & 7);
        var en = PbEntry{ .number = number, .wt = wt };
        switch (wt) {
            0 => en.uval = try readVarint(buf, &i),
            1 => {
                if (buf.len - i < 8) return E.@"malformed-wire";
                en.uval = std.mem.readInt(u64, buf[i..][0..8], .little);
                i += 8;
            },
            2 => {
                const len = try readVarint(buf, &i);
                if (len > buf.len - i) return E.@"malformed-wire";
                const n: usize = @intCast(len);
                en.bytes = buf[i .. i + n];
                i += n;
            },
            5 => {
                if (buf.len - i < 4) return E.@"malformed-wire";
                en.uval = std.mem.readInt(u32, buf[i..][0..4], .little);
                i += 4;
            },
            else => return E.@"malformed-wire", // wire types 3/4 (groups) and 6/7
        }
        try out.append(en);
    }
    return out.toOwnedSlice();
}

// Submessages already parsed in this decode, by where their bytes are.
const PbKey = struct { ptr: usize, len: usize };
const PbCache = std.AutoHashMap(PbKey, []const PbEntry);

// A message or a submessage. Inside a group `self` is the occurrence the item
// was read from: what the locator `.` addresses.
const PbDoc = struct { entries: []const PbEntry, cache: *PbCache, self: ?PbEntry = null };

// The fields of a submessage occurrence. One that is not length-delimited, or
// does not parse, is malformed wire.
fn pbSub(alloc: std.mem.Allocator, cache: *PbCache, leaf: PbEntry) anyerror![]const PbEntry {
    if (leaf.wt != 2) return E.@"malformed-wire";
    const key = PbKey{ .ptr = @intFromPtr(leaf.bytes.ptr), .len = leaf.bytes.len };
    if (cache.get(key)) |sub| return sub;
    const sub = try parsePb(alloc, leaf.bytes);
    try cache.put(key, sub);
    return sub;
}

// The fields of the submessage a dot-path reaches; null when a field on the
// path is absent. When a field number repeats, the last occurrence wins, a
// submessage as a whole (not merged).
fn pbDescend(alloc: std.mem.Allocator, doc: PbDoc, path: []const usize) anyerror!?[]const PbEntry {
    var entries = doc.entries;
    for (path) |number| {
        var found: ?PbEntry = null;
        for (entries) |en| {
            if (en.number == number) found = en;
        }
        entries = try pbSub(alloc, doc.cache, found orelse return null);
    }
    return entries;
}

// Resolve a dot-path to the leaf field occurrence. When a field number
// repeats, the last occurrence wins, a submessage as a whole (not merged).
// Absent field -> null; a field in the middle of the path that is not a
// submessage is malformed wire.
fn resolvePb(alloc: std.mem.Allocator, doc: PbDoc, path: []const usize) anyerror!?PbEntry {
    if (path.len == 0) return null;
    const entries = (try pbDescend(alloc, doc, path[0 .. path.len - 1])) orelse return null;
    var found: ?PbEntry = null;
    for (entries) |en| {
        if (en.number == path[path.len - 1]) found = en;
    }
    return found;
}

fn decodeProtoTransform(t: TKind, leaf: PbEntry) !MV {
    switch (t) {
        .pstring => {
            if (leaf.wt != 2) return E.@"transform-decode";
            if (!std.unicode.utf8ValidateSlice(leaf.bytes)) return E.@"transform-decode";
            return MV{ .str = leaf.bytes };
        },
        .pvarint => {
            if (leaf.wt != 0) return E.@"transform-decode";
            return MV{ .int = @bitCast(leaf.uval) };
        },
        .psint => {
            if (leaf.wt != 0) return E.@"transform-decode";
            const z = leaf.uval;
            // zig-zag decode: (z >> 1) ^ -(z & 1)
            const dec: u64 = (z >> 1) ^ (~(z & 1) +% 1);
            return MV{ .int = @bitCast(dec) };
        },
        .pdouble => {
            if (leaf.wt != 1) return E.@"transform-decode";
            const f: f64 = @bitCast(leaf.uval);
            if (!std.math.isFinite(f)) return E.@"transform-decode"; // infinity and NaN on the wire
            return MV{ .float = f };
        },
        .pfloat => {
            if (leaf.wt != 5) return E.@"transform-decode";
            const bits32: u32 = @intCast(leaf.uval);
            const fv: f32 = @bitCast(bits32);
            if (!std.math.isFinite(fv)) return E.@"transform-decode";
            return MV{ .float = @as(f64, fv) };
        },
        else => return E.@"transform-decode",
    }
}

fn writeVarint(buf: *std.ArrayList(u8), value: u64) !void {
    var v = value;
    while (true) {
        var b: u8 = @intCast(v & 0x7f);
        v >>= 7;
        if (v != 0) b |= 0x80;
        try buf.append(b);
        if (v == 0) break;
    }
}

fn writeTag(buf: *std.ArrayList(u8), number: usize, wt: u3) !void {
    try writeVarint(buf, (@as(u64, number) << 3) | @as(u64, wt));
}

// The wire type a transform fixes.
fn protoWireType(t: TKind) u3 {
    return switch (t) {
        .pvarint, .psint => 0,
        .pdouble => 1,
        .pfloat => 5,
        else => 2,
    };
}

// The payload of one value, without its tag: what a packed field holds back
// to back.
fn encodeProtoPayload(buf: *std.ArrayList(u8), t: TKind, mv: MV) !void {
    switch (t) {
        .pstring => {
            if (mv != .str) return E.@"transform-encode";
            try writeVarint(buf, @as(u64, mv.str.len));
            try buf.appendSlice(mv.str);
        },
        .pvarint => {
            if (mv != .int) return E.@"transform-encode";
            try writeVarint(buf, @as(u64, @bitCast(mv.int))); // a negative integer is ten bytes
        },
        .psint => {
            if (mv != .int) return E.@"transform-encode";
            const uv: u64 = @bitCast(mv.int);
            const sign: u64 = @bitCast(mv.int >> 63); // 0 or all-ones
            try writeVarint(buf, (uv << 1) ^ sign); // zig-zag encode
        },
        .pdouble => {
            const x = try mvFloat(mv);
            if (!std.math.isFinite(x)) return E.@"transform-encode";
            var tmp: [8]u8 = undefined;
            std.mem.writeInt(u64, &tmp, @as(u64, @bitCast(x)), .little);
            try buf.appendSlice(&tmp);
        },
        .pfloat => {
            const fv = try narrowF32(try mvFloat(mv)); // outside single range: an encode error
            var tmp: [4]u8 = undefined;
            std.mem.writeInt(u32, &tmp, @as(u32, @bitCast(fv)), .little);
            try buf.appendSlice(&tmp);
        },
        else => return E.@"transform-encode",
    }
}

// The payload of a field's first sentinel (Version 0.9): the integer as a
// varint (no zig-zag), as 8 or 4 little-endian bytes, or the text.
fn encodeSentinelPayload(buf: *std.ArrayList(u8), ln: *const Line) !void {
    switch (ln.transform.kind) {
        .pstring => {
            try writeVarint(buf, @as(u64, ln.abs_texts[0].len));
            try buf.appendSlice(ln.abs_texts[0]);
        },
        .pvarint, .psint => try writeVarint(buf, ln.abs_ints[0]),
        .pdouble => {
            var tmp: [8]u8 = undefined;
            std.mem.writeInt(u64, &tmp, ln.abs_ints[0], .little);
            try buf.appendSlice(&tmp);
        },
        .pfloat => {
            var tmp: [4]u8 = undefined;
            std.mem.writeInt(u32, &tmp, @intCast(ln.abs_ints[0]), .little);
            try buf.appendSlice(&tmp);
        },
        else => return E.@"transform-encode",
    }
}

// Encode one leaf field (tag + payload) in canonical form.
fn encodeProtoField(buf: *std.ArrayList(u8), t: TKind, number: usize, mv: MV) !void {
    if (kindCategory(t) != .proto) return E.@"transform-encode";
    try writeTag(buf, number, protoWireType(t));
    try encodeProtoPayload(buf, t, mv);
}

// The message to write, as a tree by field number. A node with `leaf` is a
// written field (tag + payload); a node with children is a submessage.
// `forced` marks a `<path> present` line: with nothing written under it the
// node is an empty length-delimited field (ruling 14 of 0.5).
const PbNode = struct {
    number: usize,
    leaf: ?[]const u8 = null,
    weak: bool = false, // `leaf` is a sentinel (Version 0.9)
    forced: bool = false,
    children: std.ArrayList(*PbNode),

    fn child(self: *PbNode, alloc: std.mem.Allocator, number: usize) !*PbNode {
        for (self.children.items) |c| if (c.number == number) return c;
        const c = try alloc.create(PbNode);
        c.* = .{ .number = number, .children = std.ArrayList(*PbNode).init(alloc) };
        try self.children.append(c);
        return c;
    }
};

fn pbNodeLess(_: void, a: *PbNode, b: *PbNode) bool {
    return a.number < b.number;
}

// Serialise a (sub)message canonically: ascending field-number order,
// submessages likewise.
fn encodeProtoNode(alloc: std.mem.Allocator, node: *PbNode, buf: *std.ArrayList(u8)) anyerror!void {
    std.mem.sort(*PbNode, node.children.items, {}, pbNodeLess);
    for (node.children.items) |c| {
        if (c.leaf) |bytes| {
            try buf.appendSlice(bytes);
            continue;
        }
        var sub = std.ArrayList(u8).init(alloc);
        try encodeProtoNode(alloc, c, &sub);
        if (sub.items.len > 0 or c.forced) { // otherwise omit an empty submessage
            try writeTag(buf, c.number, 2);
            try writeVarint(buf, @as(u64, sub.items.len));
            try buf.appendSlice(sub.items);
        }
    }
}

// ---------------------------------------------------------------------------
// Decode
// ---------------------------------------------------------------------------

// A `bits` message, and where the scope being read starts in it.
const BitsDoc = struct { buf: []const u8, base: usize = 0 };

// A JSON message or one element of an array. `geo`: read with the `geojson`
// value types.
const JItem = struct { v: JValue, geo: bool = false };

// The parsed wire message, or one item of a group.
const Doc = union(enum) {
    xml: *XmlNode,
    geojson: GeoDoc,
    json: JItem,
    bits: BitsDoc,
    protobuf: PbDoc,
    text: TextDoc,
};

fn parseDoc(alloc: std.mem.Allocator, p: *const Pack, bytes: []const u8, diag: *Diag) anyerror!Doc {
    switch (p.wire) {
        .xml => {
            const root = parseXml(alloc, bytes) catch |err| return bad(diag, alloc, err, "the input is not well-formed xml", .{});
            return .{ .xml = root };
        },
        .geojson => {
            const obj = parseJsonObject(alloc, bytes, true) catch |err| return bad(diag, alloc, err, "the input is not one JSON object", .{});
            var d = GeoDoc{ .obj = obj, .coords = null, .props = null };
            if (obj.get("geometry")) |g| {
                if (g == .object) {
                    if (g.object.get("coordinates")) |c| {
                        if (c == .array) d.coords = c.array;
                    }
                }
            }
            if (obj.get("properties")) |pr| {
                if (pr == .object) d.props = pr.object;
            }
            return .{ .geojson = d };
        },
        .json => {
            const obj = parseJsonObject(alloc, bytes, true) catch |err| return bad(diag, alloc, err, "the input is not one JSON object", .{});
            jsonCheckNoDuplicates(alloc, bytes) catch |err| return bad(diag, alloc, err, "a member name appears twice in one object", .{});
            return .{ .json = .{ .v = .{ .object = obj } } };
        },
        .bits => {
            const buf = hexDecode(alloc, bytes) catch |err| return bad(diag, alloc, err, "the input is not hex of even length", .{});
            return .{ .bits = .{ .buf = buf } };
        },
        .protobuf => {
            const buf = hexDecode(alloc, bytes) catch |err| return bad(diag, alloc, err, "the input is not hex of even length", .{});
            const entries = parsePb(alloc, buf) catch |err| return bad(diag, alloc, err, "the input is not a protobuf message", .{});
            const cache = try alloc.create(PbCache);
            cache.* = PbCache.init(alloc);
            return .{ .protobuf = .{ .entries = entries, .cache = cache } };
        },
        .text => return .{ .text = try textParse(alloc, p, bytes, diag) },
    }
}

// The value a line addresses in a JSON message or item: the item itself for
// `.`, else a member path into it when it is an object.
fn jitemLookup(it: JItem, ln: *const Line) ?JValue {
    if (ln.dot) return it.v;
    if (it.v != .object) return null;
    return jsonLookup(it.v.object, ln.segs);
}

// Does the wire hold the `when` line's value at its locator? Compared with
// the raw wire value, before any transform.
fn whenHolds(alloc: std.mem.Allocator, p: *const Pack, doc: Doc, ln: *const Line) bool {
    switch (doc) {
        .xml => |root| {
            // `present` on `#text`: the element exists (ruling 1m of 0.11)
            if (ln.wpresent and std.mem.endsWith(u8, ln.locator, "#text")) {
                const t = xmlTarget(root, ln.locator) orelse return false;
                return std.mem.eql(u8, t.last, "#text");
            }
            const got = xmlGet(root, ln.locator) orelse return false;
            if (ln.wpresent) return true;
            return std.mem.eql(u8, got, ln.wtext);
        },
        .geojson => |d| return whenJsonHolds(alloc, ln.*, geoLookup(d, ln.locator)),
        .json => |it| return whenJsonHolds(alloc, ln.*, jitemLookup(it, ln)),
        .bits => |bd| {
            // a `when` that lies beyond the input does not hold
            if (bd.base + ln.bstart + ln.blen > bd.buf.len * 8) return false;
            return getBits(bd.buf, p.msb, bd.base + ln.bstart, ln.blen) == ln.wint;
        },
        .protobuf => |pd| {
            const leaf = (resolvePb(alloc, pd, ln.ppath) catch return false) orelse return false;
            if (ln.wpresent) return true;
            return leaf.wt == 0 and leaf.uval == ln.wint;
        },
        .text => |td| {
            // a `when` on a column its field does not reach does not hold
            const got = textRead(td, ln, ln.ti, false) orelse return false;
            if (ln.wpresent) return true;
            return std.mem.eql(u8, got, ln.wtext);
        },
    }
}

// Text through a text transform (xml, geojson).
fn textToMV(t: TKind, raw: []const u8) !MV {
    return switch (t) {
        .string => MV{ .str = raw },
        .float => MV{ .float = try parseDecimal(raw) },
        .int => MV{ .int = try parseDecimalInt(raw) },
        .iso8601_ms, .iso8601_s => MV{ .int = try isoToMs(raw) },
        else => E.@"transform-decode",
    };
}

// geojson: the text of a scalar member (a string as-is, a number or boolean as
// its canonical text); null for an object, an array or `null`.
fn geoText(alloc: std.mem.Allocator, v: JValue) !?[]const u8 {
    return switch (v) {
        .string => |str| str,
        .bool => |b| if (b) "true" else "false",
        .integer, .float, .number_string => try jsonNumberText(alloc, v),
        else => null,
    };
}

// The raw value of a JSON member for a sentinel (Version 0.9): a string's
// text, a boolean's, or a number's canonical text through a double (ruling 19);
// null for anything else.
fn jsonWireText(alloc: std.mem.Allocator, v: JValue) !?[]const u8 {
    const f: f64 = switch (v) {
        .string => |s| return s,
        .bool => |b| return if (b) "true" else "false",
        .integer => |i| @floatFromInt(i),
        .float => |x| x,
        .number_string => |s| std.fmt.parseFloat(f64, s) catch return null,
        else => return null,
    };
    if (!std.math.isFinite(f)) return null;
    return try floatToStr(alloc, f);
}

fn jsonIsSentinel(alloc: std.mem.Allocator, ln: *const Line, v: JValue) !bool {
    if (!ln.abs_set) return false;
    const t = (try jsonWireText(alloc, v)) orelse return false;
    return absentText(ln, t);
}

// Read one field through its transform. null: the field is absent, also when
// its raw value is one of its sentinels (Version 0.9).
fn readField(alloc: std.mem.Allocator, p: *const Pack, doc: Doc, ln: *const Line) anyerror!?MV {
    const t = ln.transform.kind;
    switch (doc) {
        .xml => |root| {
            const raw = xmlGet(root, ln.locator) orelse return null;
            if (ln.abs_set and absentText(ln, raw)) return null; // not trimmed (ruling 14)
            return try textToMV(t, raw);
        },
        .geojson => |d| {
            // 0.1 behaviour (ruling 28 of 0.5): a scalar is read as its text,
            // whatever its JSON type
            const v = geoLookup(d, ln.locator) orelse return null;
            if (v == .null) return null;
            if (try jsonIsSentinel(alloc, ln, v)) return null;
            const raw = (try geoText(alloc, v)) orelse return E.@"transform-decode";
            return try textToMV(t, raw);
        },
        .json => |it| {
            const v = jitemLookup(it, ln) orelse return null;
            if (v == .null) return null; // a member whose value is null is absent
            if (try jsonIsSentinel(alloc, ln, v)) return null;
            if (it.geo) {
                // an item of a geojson group: the json locators and null
                // rule, the geojson value types (ruling 7 of 0.7)
                const raw = (try geoText(alloc, v)) orelse return E.@"transform-decode";
                return try textToMV(t, raw);
            }
            return try jsonToMV(t, v); // `.` on an object or array fails here
        },
        .bits => |bd| {
            // an `optional` field any of whose bits lies beyond the input is absent
            if (ln.optional and bd.base + ln.bstart + ln.blen > bd.buf.len * 8) return null;
            if (ln.abs_set and absentInt(ln, bitsRaw(p, bd.buf, bd.base, ln))) return null;
            return try bitsDecodeField(alloc, p, bd.buf, bd.base, ln);
        },
        .protobuf => |pd| {
            const leaf = if (ln.dot)
                pd.self orelse return null
            else
                (try resolvePb(alloc, pd, ln.ppath)) orelse return null;
            if (ln.abs_set) {
                // a wire type the transform does not fix fails first (ruling 15)
                if (leaf.wt != protoWireType(t)) return E.@"transform-decode";
                if (t == .pstring) {
                    if (absentText(ln, leaf.bytes)) return null;
                } else if (absentInt(ln, leaf.uval)) return null;
            }
            return try decodeProtoTransform(t, leaf);
        },
        .text => |td| {
            if (ln.tloc == .pair) {
                // absent when either field is absent
                const a = textRead(td, ln, ln.ti, false) orelse return null;
                const b = textRead(td, ln, ln.tj, false) orelse return null;
                return try textDecodePair(ln.transform, a, b);
            }
            const raw = textRead(td, ln, ln.ti, textNumeric(t)) orelse return null;
            return try textDecode(ln.transform, raw);
        },
    }
}

// Does a `field`, a `const` or a `when` with a value map the locator?
fn lineMaps(lines: []const Line, locator: []const u8) bool {
    for (lines) |*ln| if (ln.maps() and std.mem.eql(u8, ln.locator, locator)) return true;
    return false;
}

// Do all of a kind's own `when` lines hold?
fn kindHolds(alloc: std.mem.Allocator, p: *const Pack, doc: Doc, k: *const Kind) bool {
    for (k.lines.items) |*ln| {
        if (ln.isWhen() and !whenHolds(alloc, p, doc, ln)) return false;
    }
    return true;
}

// json residue: every scalar member at any depth of nested objects that no
// `field` or `when` maps, keyed by its path, with its canonical JSON text.
fn jsonResidue(alloc: std.mem.Allocator, p: *const Pack, lines: []const Line, obj: std.json.ObjectMap, prefix: []const u8, e: *Entity) anyerror!void {
    var it = obj.iterator();
    while (it.next()) |en| {
        const name = en.key_ptr.*;
        if (std.mem.indexOfScalar(u8, name, '.') != null) continue; // dropped, not residue
        const path = if (prefix.len == 0) name else try std.fmt.allocPrint(alloc, "{s}.{s}", .{ prefix, name });
        switch (en.value_ptr.*) {
            .object => |sub| try jsonResidue(alloc, p, lines, sub, path, e),
            .array, .null => {}, // not carried
            else => {
                if (lineMaps(lines, path)) continue;
                // a residue number whose nearest double is infinite has no
                // canonical text (ruling 2d of 0.11)
                if (en.value_ptr.* == .number_string) {
                    const f = std.fmt.parseFloat(f64, en.value_ptr.*.number_string) catch return E.@"malformed-wire";
                    if (!std.math.isFinite(f)) return E.@"malformed-wire";
                }
                try e.addResidue(.{ .fmt = p.format, .locator = path, .value = try jsonCanonText(alloc, en.value_ptr.*, false) });
            },
        }
    }
}

// Decode the lines of one scope into `e`: the fields, then each group as a
// list. A key takes its value from the earliest line whose locator is present
// on the wire and whose transform succeeds; a key that some line failed on and
// no line filled fails the decode. On `bits` the result is one past the
// furthest bit the scope's items reach (0 when it has none).
fn decodeScope(alloc: std.mem.Allocator, p: *const Pack, sc: *const Scope, doc: Doc, e: *Entity, diag: *Diag) anyerror!usize {
    var failed = std.StringArrayHashMap([]const u8).init(alloc);
    var end: usize = 0;
    for (sc.lines) |*ln| {
        if (ln.tag == .group) {
            end = @max(end, try decodeGroup(alloc, p, ln.grp.?, doc, e, diag));
            continue;
        }
        if (ln.tag != .field) continue;
        if (diag.count_only) continue;
        if (e.fields.contains(ln.key)) continue;
        var ok = true;
        const got: ?MV = readField(alloc, p, doc, ln) catch |err| switch (err) {
            error.OutOfMemory => return err,
            E.@"malformed-wire" => return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator }),
            else => blk: {
                ok = false;
                break :blk null;
            },
        };
        var mv: MV = undefined;
        if (ok) {
            mv = got orelse continue;
            // `via`: through the table after the transform. A line whose
            // transform succeeds and whose table has no entry for a value of
            // another type fails the decode: later lines of the key are not
            // tried (ruling 4 of 0.6, ruling 10 of 0.7).
            if (ln.via) |t| {
                mv = tableDecode(t, mv, ln.kty) catch
                    return bad(diag, alloc, E.@"transform-decode", "field {s} at {s}: the table {s} has no entry for the value", .{ ln.key, ln.locator, ln.via_name });
            }
        }
        if (!ok) {
            if (!failed.contains(ln.key)) try failed.put(ln.key, ln.locator);
            continue;
        }
        // typemap: a native code is replaced by its CoT token before it reaches `type`
        if (mv == .str and std.mem.eql(u8, ln.key, "type")) {
            if (p.tm_nat2cot.get(mv.str)) |cot| mv = MV{ .str = cot };
        }
        try e.put(ln.key, mv);
        // a failed line is forgiven when another line of its key succeeds
        if (failed.count() > 0) _ = failed.orderedRemove(ln.key);
    }
    if (failed.count() > 0) {
        // a line that failed before a later line of its key succeeded
        var msg = std.ArrayList(u8).init(alloc);
        var fit = failed.iterator();
        while (fit.next()) |en| {
            if (e.fields.contains(en.key_ptr.*)) continue;
            if (msg.items.len > 0) try msg.appendSlice(", ");
            try msg.writer().print("{s} at {s}", .{ en.key_ptr.*, en.value_ptr.* });
        }
        if (msg.items.len > 0) return bad(diag, alloc, E.@"transform-decode", "failed fields: {s}", .{msg.items});
    }
    return end;
}

// The items of a list whose number is not known before they are read. They
// are gathered in chunks that are never copied while the list grows, then
// moved once into one array of exactly their number.
const ItemList = struct {
    alloc: std.mem.Allocator,
    chunks: std.ArrayListUnmanaged([]Entity) = .{},
    used: usize = 0, // of the last chunk
    total: usize = 0,

    const max_chunk: usize = 4096;

    fn append(self: *ItemList, it: Entity) !void {
        if (self.chunks.items.len == 0 or self.used == self.chunks.items[self.chunks.items.len - 1].len) {
            const n = @min(@max(self.total, 1), max_chunk);
            try self.chunks.append(self.alloc, try self.alloc.alloc(Entity, n));
            self.used = 0;
        }
        self.chunks.items[self.chunks.items.len - 1][self.used] = it;
        self.used += 1;
        self.total += 1;
    }

    fn finish(self: *ItemList) ![]Entity {
        defer self.chunks.deinit(self.alloc);
        if (self.total == 0) return &[0]Entity{};
        const cs = self.chunks.items;
        if (cs.len == 1 and self.used == cs[0].len) return cs[0];
        const out = try self.alloc.alloc(Entity, self.total);
        var at: usize = 0;
        for (cs, 0..) |c, i| {
            const n = if (i + 1 == cs.len) self.used else c.len;
            @memcpy(out[at .. at + n], c[0..n]);
            at += n;
            self.alloc.free(c);
        }
        return out;
    }
};

// One protobuf occurrence as an item.
fn pbItem(alloc: std.mem.Allocator, p: *const Pack, body: *const Scope, cache: *PbCache, items: *ItemList, self: PbEntry, sub: []const PbEntry, diag: *Diag) anyerror!void {
    try takeItems(diag, alloc, 1, "");
    var it = Entity.init(alloc);
    _ = try decodeScope(alloc, p, body, .{ .protobuf = .{ .entries = sub, .cache = cache, .self = self } }, &it, diag);
    try items.append(it);
}

// Find the items of one group and decode each. On `bits` the result is one
// past the last item's last bit (0 when there is no item).
fn decodeGroup(alloc: std.mem.Allocator, p: *const Pack, g: *const Group, doc: Doc, e: *Entity, diag: *Diag) anyerror!usize {
    const body = &g.body;
    const mw = E.@"malformed-wire";
    switch (doc) {
        .xml => |node| {
            // each child element named by the last name, under the first
            // element matched by the names before it
            var cont = node;
            for (g.xpath) |nm| cont = cont.child(nm) orelse return 0;
            var n: usize = 0;
            for (cont.children.items) |c| {
                if (std.mem.eql(u8, c.name, g.xname)) n += 1;
            }
            if (n == 0) return 0; // no item occurs: the list is absent
            try takeItems(diag, alloc, n, g.list);
            const items = try alloc.alloc(Entity, n);
            var i: usize = 0;
            for (cont.children.items) |c| {
                if (!std.mem.eql(u8, c.name, g.xname)) continue;
                items[i] = Entity.init(alloc);
                _ = try decodeScope(alloc, p, body, .{ .xml = c }, &items[i], diag);
                i += 1;
            }
            try e.putList(g.list, items);
            return 0;
        },
        .geojson, .json => {
            const found: ?JValue = switch (doc) {
                .geojson => |d| geoLookup(d, g.locator),
                .json => |it| if (it.v == .object) jsonLookup(it.v.object, g.segs) else null,
                else => unreachable,
            };
            const v = found orelse return 0;
            if (v == .null) return 0; // `null` is absent
            if (v != .array) return bad(diag, alloc, mw, "group {s}: the member at {s} is not an array", .{ g.list, g.locator });
            try takeItems(diag, alloc, v.array.items.len, g.list);
            const items = try alloc.alloc(Entity, v.array.items.len);
            for (v.array.items, 0..) |el, i| {
                items[i] = Entity.init(alloc);
                _ = try decodeScope(alloc, p, body, .{ .json = .{ .v = el, .geo = p.wire == .geojson } }, &items[i], diag);
            }
            try e.putList(g.list, items);
            return 0;
        },
        .protobuf => |pd| {
            const found = pbDescend(alloc, pd, g.ppath[0 .. g.ppath.len - 1]) catch |err| switch (err) {
                error.OutOfMemory => return err,
                else => return bad(diag, alloc, mw, "group {s} at {s}: a field on the path is not a submessage", .{ g.list, g.locator }),
            };
            const entries = found orelse return 0;
            const number = g.ppath[g.ppath.len - 1];
            var items = ItemList{ .alloc = alloc };
            // a body of `.` lines only reads each occurrence as a scalar
            const scalar = !body.needs_sub and body.dot != null;
            const tk: TKind = if (body.dot) |dl| dl.transform.kind else .pstring;
            for (entries) |en| {
                if (en.number != number) continue;
                if (scalar and tk != .pstring and en.wt == 2) {
                    // the packed form: the values back to back
                    const b = en.bytes;
                    var i: usize = 0;
                    switch (tk) {
                        .pvarint, .psint => while (i < b.len) {
                            const v = readVarint(b, &i) catch
                                return bad(diag, alloc, mw, "group {s} at {s}: a packed varint is cut short", .{ g.list, g.locator });
                            try pbItem(alloc, p, body, pd.cache, &items, .{ .number = number, .wt = 0, .uval = v }, &.{}, diag);
                        },
                        .pdouble => {
                            if (b.len % 8 != 0) return bad(diag, alloc, mw, "group {s} at {s}: {d} packed bytes are not whole doubles", .{ g.list, g.locator, b.len });
                            while (i < b.len) : (i += 8) {
                                try pbItem(alloc, p, body, pd.cache, &items, .{ .number = number, .wt = 1, .uval = std.mem.readInt(u64, b[i..][0..8], .little) }, &.{}, diag);
                            }
                        },
                        .pfloat => {
                            if (b.len % 4 != 0) return bad(diag, alloc, mw, "group {s} at {s}: {d} packed bytes are not whole singles", .{ g.list, g.locator, b.len });
                            while (i < b.len) : (i += 4) {
                                try pbItem(alloc, p, body, pd.cache, &items, .{ .number = number, .wt = 5, .uval = std.mem.readInt(u32, b[i..][0..4], .little) }, &.{}, diag);
                            }
                        },
                        else => unreachable,
                    }
                    continue;
                }
                var sub: []const PbEntry = &.{};
                if (body.needs_sub) {
                    // an item that is not a submessage where the body needs one
                    if (en.wt != 2) return bad(diag, alloc, mw, "group {s} at {s}: an item is not a submessage", .{ g.list, g.locator });
                    sub = parsePb(alloc, en.bytes) catch |err| switch (err) {
                        error.OutOfMemory => return err,
                        else => return bad(diag, alloc, mw, "group {s} at {s}: an item is not a submessage", .{ g.list, g.locator }),
                    };
                }
                try pbItem(alloc, p, body, pd.cache, &items, en, sub, diag);
            }
            if (items.total == 0) return 0; // no item occurs: the list is absent
            try e.putList(g.list, try items.finish());
            return 0;
        },
        .bits => |bd| {
            const total = bd.buf.len * 8;
            // the count locator is inside the bits the scope requires
            const count: u64 = if (g.count_fixed) |n| n else getBits(bd.buf, p.msb, bd.base + g.cstart, g.clen);
            var pos = bd.base + g.gstart;
            // the count against the limit, before any item is read (7d)
            try takeItems(diag, alloc, count, g.list);
            if (count > 0 and (pos > total or count > (total - pos) / g.item_bits)) {
                return bad(diag, alloc, mw, "group {s}: the input ends before its {d} items", .{ g.list, count });
            }
            const need = @max(g.item_bits, body.nbits_req);
            const items = try alloc.alloc(Entity, @intCast(count));
            for (items) |*it| {
                if (pos + need > total) return bad(diag, alloc, mw, "group {s}: the input ends before its {d} items", .{ g.list, count });
                it.* = Entity.init(alloc);
                const iend = try decodeScope(alloc, p, body, .{ .bits = .{ .buf = bd.buf, .base = pos } }, it, diag);
                // a nested group counted by a locator may run past `item
                // <bits>`; the next item then starts where it ends
                pos = @max(pos + need, iend);
            }
            try e.putList(g.list, items);
            return if (count == 0) 0 else pos;
        },
        .text => |td| {
            // items from field `tstart` to the end of the record, the last
            // one possibly cut short; no field there: the list is absent
            const nf = td.fields.len;
            if (nf <= g.tstart) return 0;
            const count = (nf - g.tstart + g.titem - 1) / g.titem;
            try takeItems(diag, alloc, count, g.list);
            const items = try alloc.alloc(Entity, count);
            for (items, 0..) |*it, k| {
                it.* = Entity.init(alloc);
                _ = try decodeScope(alloc, p, body, .{ .text = .{ .fields = td.fields, .base = g.tstart + k * g.titem } }, it, diag);
            }
            try e.putList(g.list, items);
            return 0;
        },
    }
}

fn decodePack(alloc: std.mem.Allocator, p: *const Pack, bytes: []const u8, diag: *Diag) anyerror!Entity {
    if (p.seq != null) return seqDecode(alloc, p, bytes, diag);
    const doc = try parseDoc(alloc, p, bytes, diag);

    // kind selection
    var kind_idx: ?usize = null;
    if (p.hasKinds()) {
        for (p.common.items) |*ln| {
            if (ln.isWhen() and !whenHolds(alloc, p, doc, ln)) {
                return bad(diag, alloc, E.@"no-kind", "the common `when {s} {s}` does not hold", .{ ln.locator, ln.wraw });
            }
        }
        if (doc == .xml) {
            // a kind is considered only when the document's root element has
            // its root's name, before its `when` lines
            if (p.root_index.get(doc.xml.name)) |cands| {
                for (cands.items) |i| {
                    if (kindHolds(alloc, p, doc, &p.kinds.items[i])) {
                        kind_idx = i;
                        break;
                    }
                }
            }
            if (kind_idx == null) return bad(diag, alloc, E.@"no-kind", "no kind has the root element {s} and `when` lines that all hold", .{doc.xml.name});
        } else {
            for (p.kinds.items, 0..) |*k, i| {
                if (kindHolds(alloc, p, doc, k)) {
                    kind_idx = i;
                    break;
                }
            }
            if (kind_idx == null) return bad(diag, alloc, E.@"no-kind", "no kind's `when` lines all hold", .{});
        }
    } else if (doc == .xml and !std.mem.eql(u8, doc.xml.name, p.root)) {
        return bad(diag, alloc, E.@"missing-root", "the root element is {s}, the pack's root is {s}", .{ doc.xml.name, p.root });
    }
    const sc = p.scope(kind_idx);
    const lines = sc.lines;

    if (doc == .bits) {
        // every bit a line that is not `optional` maps must be in the input
        const need = p.wordBytes(sc.nbits_req);
        if (doc.bits.buf.len < need) {
            return bad(diag, alloc, E.@"malformed-wire", "the message is {d} bytes, the input holds {d}", .{ need, doc.bits.buf.len });
        }
    }

    var e = Entity.init(alloc);
    if (kind_idx) |k| {
        e.kind_fmt = p.format;
        e.kind_name = p.kinds.items[k].name;
    }

    const end = decodeScope(alloc, p, sc, doc, &e, diag) catch |err| {
        // Going over the limit wins over a field that fails (ruling 7f of
        // 0.11): the scope is read again for its items alone.
        if (err == error.OutOfMemory or err == E.@"malformed-wire") return err;
        const msg = diag.msg;
        diag.count_only = true;
        diag.held = 0;
        var scratch_e = Entity.init(alloc);
        _ = decodeScope(alloc, p, sc, doc, &scratch_e, diag) catch |err2| {
            if (err2 == error.OutOfMemory) return err2;
            if (diag.limit_hit) return err2;
        };
        diag.msg = msg;
        return err;
    };
    if (doc == .bits) {
        // the message length is extended by the items, to whole words
        const need = p.wordBytes(@max(sc.nbits_req, end));
        if (doc.bits.buf.len < need) {
            return bad(diag, alloc, E.@"malformed-wire", "the message with its items is {d} bytes, the input holds {d}", .{ need, doc.bits.buf.len });
        }
    }

    // residue: what no common or selected-kind `field` or `when` maps
    switch (doc) {
        .xml => |root| {
            // unmapped root attributes, input order
            for (root.attrs.items) |a| {
                var mapped = false;
                for (lines) |*ln| {
                    if (ln.maps() and isRootAttr(ln.locator) and std.mem.eql(u8, ln.locator[1..], a.name)) {
                        mapped = true;
                        break;
                    }
                }
                if (!mapped) {
                    const loc = try std.fmt.allocPrint(alloc, "@{s}", .{a.name});
                    try e.addResidue(.{ .fmt = p.format, .locator = loc, .value = a.value });
                }
            }
        },
        .geojson => |d| {
            // unmapped `properties` members, input order
            if (d.props) |pm| {
                var it = pm.iterator();
                while (it.next()) |en| {
                    const loc = try std.fmt.allocPrint(alloc, "{s}{s}", .{ props_prefix, en.key_ptr.* });
                    if (lineMaps(lines, loc)) continue;
                    // A scalar comes back as a string: a number keeps its
                    // text as written. Arrays and objects come back as they
                    // were; `null` is dropped (ruling 13 of 0.6).
                    const val = switch (en.value_ptr.*) {
                        .null => continue,
                        .number_string => |txt| try jsonStr(alloc, txt),
                        .array, .object => try jsonCanonText(alloc, en.value_ptr.*, true),
                        else => try jsonStr(alloc, (try geoText(alloc, en.value_ptr.*)) orelse ""),
                    };
                    try e.addResidue(.{ .fmt = p.format, .locator = loc, .value = val });
                }
            }
        },
        .json => |it| jsonResidue(alloc, p, lines, it.v.object, "", &e) catch |err| switch (err) {
            E.@"malformed-wire" => return bad(diag, alloc, err, "a number no line maps lies beyond the range of a double", .{}),
            else => return err,
        },
        .text => |td| try textResidue(alloc, p, lines, td, &e),
        .bits, .protobuf => {},
    }
    return e;
}

// ---------------------------------------------------------------------------
// Encode
// ---------------------------------------------------------------------------

// Kind selection on encode: the recorded kind when it names this format, else
// the first kind whose every `requires` key is present.
fn selectKindEncode(alloc: std.mem.Allocator, p: *const Pack, e: *const Entity, diag: *Diag) anyerror!?usize {
    if (!p.hasKinds()) return null;
    if (e.kind_fmt) |kf| {
        if (std.mem.eql(u8, kf, p.format)) {
            // a kind the pack does not have is `no-kind` (ruling 24 of 0.5)
            return p.kindIndex(e.kind_name) orelse
                bad(diag, alloc, E.@"no-kind", "the entity records kind {s}, which the pack does not have", .{e.kind_name});
        }
    }
    for (p.kinds.items, 0..) |k, i| {
        var all = true;
        for (k.requires.items) |key| {
            // a key that is present, or a list with at least one item
            if (!e.has(key)) {
                all = false;
                break;
            }
        }
        if (all) return i;
    }
    return bad(diag, alloc, E.@"no-kind", "the entity has the `requires` keys of no kind", .{});
}

// The value a field line writes: the entity's (or item's) value, else the
// `default` in scope; the CoT type token mapped back to the format's native
// code; then through the line's `via` table. null: nothing to write.
fn fieldValue(p: *const Pack, sc: *const Scope, e: *const Entity, ln: *const Line) !?MV {
    var mv = e.get(ln.key) orelse sc.defaultFor(ln.key) orelse return null;
    if (mv == .str and std.mem.eql(u8, ln.key, "type")) {
        if (p.tm_cot2nat.get(mv.str)) |nat| mv = MV{ .str = nat };
    }
    if (ln.via) |t| mv = try tableEncode(t, mv, yields(ln.transform.kind));
    return mv;
}

fn xmlText(alloc: std.mem.Allocator, t: TKind, mv: MV) ![]const u8 {
    switch (t) {
        .string => {
            if (mv != .str) return E.@"transform-encode";
            return mv.str;
        },
        .float => return switch (mv) {
            .float => |f| try floatToStr(alloc, f),
            .int => |i| try intToStr(alloc, i),
            else => E.@"transform-encode",
        },
        .int => {
            if (mv != .int) return E.@"transform-encode";
            return intToStr(alloc, mv.int);
        },
        .iso8601_ms => {
            if (mv != .int) return E.@"transform-encode";
            return msToIso(alloc, mv.int);
        },
        .iso8601_s => {
            if (mv != .int) return E.@"transform-encode";
            return msToIsoSeconds(alloc, mv.int);
        },
        else => return E.@"transform-encode",
    }
}

// How a value is written at a place another line may also write: a field's
// value (the earliest line wins), a `when` or `const` value (written over any
// field), or a sentinel (Version 0.9: written only where no field value is,
// and any field value is written over it, ruling 16).
const WMode = enum { field, fixed, sentinel };

// Write a value at an xml locator. A locator already written keeps its value
// (the earliest line wins) unless the new value is a `when` value.
fn xmlSet(alloc: std.mem.Allocator, root: *XmlNode, locator: []const u8, value: []const u8, mode: WMode) !void {
    var node: *XmlNode = root;
    var rest = locator;
    while (std.mem.indexOfScalar(u8, rest, '/')) |slash| {
        const name = rest[0..slash];
        node = node.child(name) orelse blk: {
            const c = try xmlNewNode(alloc, name);
            try node.children.append(c);
            break :blk c;
        };
        rest = rest[slash + 1 ..];
    }
    if (rest.len > 0 and rest[0] == '@') {
        for (node.attrs.items) |*a| {
            if (std.mem.eql(u8, a.name, rest[1..])) {
                if (mode == .fixed or (mode == .field and a.weak)) {
                    a.value = value;
                    a.weak = false;
                }
                return;
            }
        }
        try node.attrs.append(.{ .name = rest[1..], .value = value, .weak = mode == .sentinel });
    } else if (std.mem.eql(u8, rest, "#text")) {
        if (node.text_set and !(mode == .fixed or (mode == .field and node.text_weak))) return;
        node.text = value;
        node.text_set = true;
        node.text_weak = mode == .sentinel;
    }
}

fn xmlWrite(buf: *std.ArrayList(u8), node: *XmlNode) anyerror!void {
    try buf.append('<');
    try buf.appendSlice(node.name);
    for (node.attrs.items) |a| {
        try buf.append(' ');
        try buf.appendSlice(a.name);
        try buf.appendSlice("=\"");
        try xmlEscape(buf, a.value, true);
        try buf.append('"');
    }
    if (node.children.items.len == 0 and node.text.len == 0) {
        try buf.appendSlice("/>");
        return;
    }
    try buf.append('>');
    if (node.text.len > 0) try xmlEscape(buf, node.text, false);
    for (node.children.items) |c| try xmlWrite(buf, c);
    try buf.appendSlice("</");
    try buf.appendSlice(node.name);
    try buf.append('>');
}

// Ruling 1a and 1b of 0.11: an attribute value escapes `&`, `<`, `>`, `"`,
// tab, line feed and carriage return; text content escapes `&`, `<`, `>` and
// carriage return. Nothing else is escaped.
fn xmlEscape(buf: *std.ArrayList(u8), s: []const u8, attr: bool) !void {
    for (s) |c| {
        switch (c) {
            '&' => try buf.appendSlice("&amp;"),
            '<' => try buf.appendSlice("&lt;"),
            '>' => try buf.appendSlice("&gt;"),
            '\r' => try buf.appendSlice("&#13;"),
            '"' => if (attr) try buf.appendSlice("&quot;") else try buf.append(c),
            '\t' => if (attr) try buf.appendSlice("&#9;") else try buf.append(c),
            '\n' => if (attr) try buf.appendSlice("&#10;") else try buf.append(c),
            else => try buf.append(c),
        }
    }
}

// Members of one flat JSON object in output order: name and JSON text.
const Member = struct { name: []const u8, raw: []const u8, weak: bool = false };

// Add a member. A name already written keeps its value (the earliest line
// wins) unless the new value is a `when` value.
fn memberAdd(list: *std.ArrayList(Member), name: []const u8, raw: []const u8, mode: WMode) !void {
    for (list.items) |*m| {
        if (std.mem.eql(u8, m.name, name)) {
            if (mode == .fixed or (mode == .field and m.weak)) {
                m.raw = raw;
                m.weak = false;
            }
            return;
        }
    }
    try list.append(.{ .name = name, .raw = raw, .weak = mode == .sentinel });
}

fn membersWrite(buf: *std.ArrayList(u8), list: []const Member, first_in: bool) !void {
    var first = first_in;
    for (list) |m| {
        if (!first) try buf.append(',');
        first = false;
        try jsonEscape(buf, m.name);
        try buf.append(':');
        try buf.appendSlice(m.raw);
    }
}

// json wire output tree. A node with `raw` is a written member; a node with
// children is a nested object; a node with neither is not written.
const JNode = struct {
    name: []const u8,
    raw: ?[]const u8 = null,
    weak: bool = false, // `raw` was written by a sentinel
    children: std.ArrayList(*JNode),

    fn child(self: *const JNode, name: []const u8) ?*JNode {
        for (self.children.items) |c| if (std.mem.eql(u8, c.name, name)) return c;
        return null;
    }
};

fn jnodeNew(alloc: std.mem.Allocator, name: []const u8) !*JNode {
    const n = try alloc.create(JNode);
    n.* = .{ .name = name, .children = std.ArrayList(*JNode).init(alloc) };
    return n;
}

// Place a line in the tree. The nested objects on its path are created at
// this position whether or not a value is written. `raw` null writes no
// member.
fn jnodeInsert(alloc: std.mem.Allocator, root: *JNode, segs: []const []const u8, raw: ?[]const u8, mode: WMode) !void {
    if (segs.len == 0) return;
    var node = root;
    for (segs[0 .. segs.len - 1]) |s| {
        node = node.child(s) orelse blk: {
            const c = try jnodeNew(alloc, s);
            try node.children.append(c);
            break :blk c;
        };
    }
    const last = segs[segs.len - 1];
    if (node.child(last)) |c| {
        const r = raw orelse return;
        // `when` and `const` values are written over any field, a field's
        // value over a sentinel
        if (c.raw != null and (mode == .fixed or (mode == .field and c.weak))) {
            c.raw = r;
            c.weak = false;
        }
        return;
    }
    if (raw == null) return;
    const c = try jnodeNew(alloc, last);
    c.raw = raw;
    c.weak = mode == .sentinel;
    try node.children.append(c);
}

fn jnodeHas(n: *const JNode) bool {
    if (n.raw != null) return true;
    for (n.children.items) |c| if (jnodeHas(c)) return true;
    return false;
}

fn jnodeWrite(buf: *std.ArrayList(u8), n: *const JNode) anyerror!void {
    if (n.raw) |r| {
        try buf.appendSlice(r);
        return;
    }
    try buf.append('{');
    var first = true;
    for (n.children.items) |c| {
        if (!jnodeHas(c)) continue; // a nested object with no members is not written
        if (!first) try buf.append(',');
        first = false;
        try jsonEscape(buf, c.name);
        try buf.append(':');
        try jnodeWrite(buf, c);
    }
    try buf.append('}');
}

// xml: write one scope's lines into `node` (the root, or one item element):
// mapped values, `when` and `const` values and groups in line order.
fn xmlEncodeScope(alloc: std.mem.Allocator, p: *const Pack, sc: *const Scope, node: *XmlNode, e: *const Entity, diag: *Diag) anyerror!void {
    for (sc.lines) |*ln| {
        switch (ln.tag) {
            .when, .constant => {
                if (!ln.wpresent) try xmlSet(alloc, node, ln.locator, ln.wtext, .fixed);
            },
            .field => {
                const mv = (fieldValue(p, sc, e, ln) catch |err|
                    return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator })) orelse {
                    // an absent key writes its first sentinel (Version 0.9)
                    if (ln.abs_set) {
                        if (!xmlWritable(ln.abs_texts[0])) return bad(diag, alloc, E.@"transform-encode", "field {s} at {s}: the sentinel holds a character xml cannot hold", .{ ln.key, ln.locator });
                        try xmlSet(alloc, node, ln.locator, ln.abs_texts[0], .sentinel);
                    }
                    continue;
                };
                const vs = xmlText(alloc, ln.transform.kind, mv) catch |err|
                    return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator });
                // ruling 1d of 0.11
                if (!xmlWritable(vs)) return bad(diag, alloc, E.@"transform-encode", "field {s} at {s}: the value holds a character xml cannot hold", .{ ln.key, ln.locator });
                try xmlSet(alloc, node, ln.locator, vs, .field);
            },
            .group => {
                // one element per item at the group's position; an absent or
                // empty list writes nothing
                const g = ln.grp.?;
                const items = e.lists.get(g.list) orelse continue;
                if (items.len == 0) continue;
                var cont = node;
                for (g.xpath) |nm| {
                    cont = cont.child(nm) orelse blk: {
                        const c = try xmlNewNode(alloc, nm);
                        try cont.children.append(c);
                        break :blk c;
                    };
                }
                for (items) |*it| {
                    const c = try xmlNewNode(alloc, g.xname);
                    try cont.children.append(c);
                    try xmlEncodeScope(alloc, p, &g.body, c, it, diag);
                }
            },
        }
    }
}

// json (and the items of a geojson group): write one scope's lines into the
// tree under `root`. A `.` line sets the item itself.
fn jsonEncodeScope(alloc: std.mem.Allocator, p: *const Pack, sc: *const Scope, root: *JNode, e: *const Entity, diag: *Diag) anyerror!void {
    for (sc.lines) |*ln| {
        var raw: ?[]const u8 = null;
        var mode: WMode = .field;
        switch (ln.tag) {
            .when, .constant => {
                // `present` writes nothing; the objects on its path keep this position
                if (!ln.wpresent) raw = try whenJsonRaw(alloc, ln.*);
                mode = .fixed;
            },
            .field => {
                const got = fieldValue(p, sc, e, ln) catch |err|
                    return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator });
                if (got) |mv| {
                    raw = jsonRaw(alloc, ln.transform.kind, mv) catch |err|
                        return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator });
                } else if (ln.abs_set) {
                    // an absent key writes its first sentinel (Version 0.9)
                    raw = ln.abs_json;
                    mode = .sentinel;
                }
            },
            .group => {
                const g = ln.grp.?;
                try jnodeInsert(alloc, root, g.segs, try jsonGroupRaw(alloc, p, g, e, diag), .field);
                continue;
            },
        }
        if (ln.dot) {
            if (raw) |r| {
                if (root.raw == null or mode == .fixed or (mode == .field and root.weak)) {
                    root.raw = r;
                    root.weak = mode == .sentinel;
                }
            }
        } else try jnodeInsert(alloc, root, ln.segs, raw, mode);
    }
}

// The JSON text of a list: an array with one element per item. null: the
// entity does not have the list.
fn jsonGroupRaw(alloc: std.mem.Allocator, p: *const Pack, g: *const Group, e: *const Entity, diag: *Diag) anyerror!?[]const u8 {
    const items = e.lists.get(g.list) orelse return null;
    var buf = std.ArrayList(u8).init(alloc);
    try buf.append('[');
    for (items, 0..) |*it, i| {
        if (i > 0) try buf.append(',');
        const root = try jnodeNew(alloc, "");
        try jsonEncodeScope(alloc, p, &g.body, root, it, diag);
        if (root.raw) |r| {
            try buf.appendSlice(r); // a scalar item
        } else if (g.body.dot != null and !jnodeHas(root)) {
            try buf.appendSlice("null"); // a scalar item with no value
        } else {
            try jnodeWrite(&buf, root); // an item with no members written is `{}`
        }
    }
    try buf.append(']');
    return buf.items;
}

// protobuf: write one scope's lines into the tree under `root` (the message,
// or one item's submessage).
fn pbEncodeScope(alloc: std.mem.Allocator, p: *const Pack, sc: *const Scope, root: *PbNode, e: *const Entity, diag: *Diag) anyerror!void {
    for (sc.lines) |*ln| {
        if (ln.tag == .group) {
            const g = ln.grp.?;
            const items = e.lists.get(g.list) orelse continue;
            if (items.len == 0) continue; // an empty list writes nothing
            const number = g.ppath[g.ppath.len - 1];
            const body = &g.body;
            var fb = std.ArrayList(u8).init(alloc);
            if (!body.needs_sub and body.dot != null) {
                const dl = body.dot.?;
                const tk = dl.transform.kind;
                if (tk != .pstring) {
                    // a numeric `.` field: the packed form
                    var payload = std.ArrayList(u8).init(alloc);
                    var nvals: usize = 0;
                    for (items) |*it| {
                        const got = fieldValue(p, body, it, dl) catch |err|
                            return bad(diag, alloc, err, "field {s} in group {s}", .{ dl.key, g.list });
                        if (got) |mv| {
                            encodeProtoPayload(&payload, tk, mv) catch |err|
                                return bad(diag, alloc, err, "field {s} in group {s}", .{ dl.key, g.list });
                        } else if (dl.abs_set) {
                            // an item without the value writes the sentinel (ruling 5 of 0.9)
                            try encodeSentinelPayload(&payload, dl);
                        } else continue;
                        nvals += 1;
                    }
                    // a list whose items all lack the value writes nothing
                    if (nvals == 0) continue;
                    try writeTag(&fb, number, 2);
                    try writeVarint(&fb, @as(u64, payload.items.len));
                    try fb.appendSlice(payload.items);
                } else {
                    // one occurrence per item
                    for (items) |*it| {
                        const got = fieldValue(p, body, it, dl) catch |err|
                            return bad(diag, alloc, err, "field {s} in group {s}", .{ dl.key, g.list });
                        if (got) |mv| {
                            encodeProtoField(&fb, tk, number, mv) catch |err|
                                return bad(diag, alloc, err, "field {s} in group {s}", .{ dl.key, g.list });
                        } else if (dl.abs_set) {
                            try writeTag(&fb, number, 2);
                            try encodeSentinelPayload(&fb, dl);
                        } else {
                            try writeTag(&fb, number, 2);
                            try writeVarint(&fb, 0);
                        }
                    }
                }
            } else {
                // one submessage per item; an item with nothing written is an
                // empty length-delimited occurrence
                var sub = std.ArrayList(u8).init(alloc);
                for (items) |*it| {
                    const iroot = try alloc.create(PbNode);
                    iroot.* = .{ .number = 0, .children = std.ArrayList(*PbNode).init(alloc) };
                    try pbEncodeScope(alloc, p, body, iroot, it, diag);
                    sub.clearRetainingCapacity();
                    try encodeProtoNode(alloc, iroot, &sub);
                    try writeTag(&fb, number, 2);
                    try writeVarint(&fb, @as(u64, sub.items.len));
                    try fb.appendSlice(sub.items);
                }
            }
            var node = root;
            for (g.ppath) |n| node = try node.child(alloc, n);
            if (node.leaf == null) node.leaf = fb.items;
            continue;
        }
        if (ln.ppath.len == 0) continue; // a `.` line: the group writes it
        const number = ln.ppath[ln.ppath.len - 1];
        var fb = std.ArrayList(u8).init(alloc);
        var sentinel = false;
        if (ln.isFixed()) {
            if (!ln.wpresent) {
                try writeTag(&fb, number, 0);
                try writeVarint(&fb, ln.wint);
            }
        } else if (fieldValue(p, sc, e, ln) catch |err|
            return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator })) |mv|
        {
            encodeProtoField(&fb, ln.transform.kind, number, mv) catch |err|
                return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator });
        } else if (ln.abs_set) {
            // an absent key writes its first sentinel (Version 0.9); it is a
            // written field for `when <path> present` (ruling 16)
            try writeTag(&fb, number, protoWireType(ln.transform.kind));
            try encodeSentinelPayload(&fb, ln);
            sentinel = true;
        } else continue;
        var node = root;
        for (ln.ppath) |n| node = try node.child(alloc, n);
        if (ln.isFixed() and ln.wpresent) {
            node.forced = true;
        } else if (node.leaf == null or ln.isFixed() or (node.weak and !sentinel)) {
            // the earliest line whose key is present wins; a `when`
            // or `const` value is written over any field, a present key's
            // value over a sentinel
            node.leaf = fb.items;
            node.weak = sentinel;
        }
    }
}

// bits: write one scope's lines at bit `base` of the message. The result is
// one past the furthest bit the scope's items reach (0 when it has none).
fn bitsEncodeScope(alloc: std.mem.Allocator, p: *const Pack, sc: *const Scope, out: *BitsOut, base: usize, e: *const Entity, diag: *Diag) anyerror!usize {
    const te = E.@"transform-encode";
    const lines = sc.lines;
    try out.ensure(base + sc.nbits);
    // The earlier line takes precedence where two present fields cover the
    // same bits: write in reverse line order, each over the last.
    var has_groups = false;
    var has_fixed = false;
    // Version 0.9: first the sentinels of the absent keys, so that a line
    // whose key is present, or has a default, wins over a sentinel whatever
    // their order (ruling 16); of two sentinels on one bit, the earlier line's
    var si: usize = lines.len;
    while (si > 0) {
        si -= 1;
        const ln = &lines[si];
        if (ln.tag != .field or !ln.abs_set) continue;
        if (e.get(ln.key) != null or sc.defaultFor(ln.key) != null) continue;
        bitsWriteRaw(p, out.buf.items, base, ln, ln.abs_ints[0]);
    }
    var i: usize = lines.len;
    while (i > 0) {
        i -= 1;
        const ln = &lines[i];
        switch (ln.tag) {
            .group => has_groups = true,
            .when, .constant => has_fixed = true,
            .field => {
                const mv = (fieldValue(p, sc, e, ln) catch |err|
                    return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator })) orelse continue;
                bitsWriteField(alloc, p, out.buf.items, base, ln, mv) catch |err|
                    return bad(diag, alloc, err, "field {s} at {s}: the value does not encode", .{ ln.key, ln.locator });
            },
        }
    }
    // the items of each group, back to back
    var end: usize = 0;
    if (has_groups) {
        for (lines) |*ln| {
            if (ln.tag != .group) continue;
            const g = ln.grp.?;
            const got = e.lists.get(g.list);
            if (g.count_fixed) |n| {
                // an absent list, or another number of items, under a fixed count
                const have = got orelse return bad(diag, alloc, te, "group {s}: the list is absent and the count is fixed at {d}", .{ g.list, n });
                if (have.len != n) return bad(diag, alloc, te, "group {s}: {d} items, the count is fixed at {d}", .{ g.list, have.len, n });
            }
            const items: []const Entity = got orelse &.{};
            const size = @max(g.item_bits, g.body.nbits);
            var pos = base + g.gstart;
            for (items) |*it| {
                try out.ensure(pos + size);
                const iend = try bitsEncodeScope(alloc, p, &g.body, out, pos, it, diag);
                pos = @max(pos + size, iend);
            }
            if (items.len > 0) end = @max(end, pos);
        }
    }
    // `when` and `const` values are written over any field
    if (has_fixed) {
        for (lines) |*ln| {
            if (ln.isFixed()) setBits(out.buf.items, p.msb, base + ln.bstart, ln.blen, ln.wint);
        }
    }
    // a count locator is written with the number of items, over any field
    if (has_groups) {
        for (lines) |*ln| {
            if (ln.tag != .group) continue;
            const g = ln.grp.?;
            if (g.count_fixed != null) continue;
            const n: u64 = if (e.lists.get(g.list)) |items| items.len else 0;
            if (g.clen < 64 and (n >> @as(u6, @intCast(g.clen))) != 0) {
                return bad(diag, alloc, te, "group {s}: {d} items do not fit the {d} bits of the count", .{ g.list, n, g.clen });
            }
            setBits(out.buf.items, p.msb, base + g.cstart, g.clen, n);
        }
    }
    return end;
}

fn encodePack(alloc: std.mem.Allocator, p: *const Pack, e: *const Entity, diag: *Diag) anyerror![]u8 {
    if (p.seq != null) return seqEncode(alloc, p, e, diag);
    const kind_idx = try selectKindEncode(alloc, p, e, diag);
    const sc = p.scope(kind_idx);
    const lines = sc.lines;

    switch (p.wire) {
        .xml => {
            const root = try xmlNewNode(alloc, p.rootName(kind_idx));
            try xmlEncodeScope(alloc, p, sc, root, e, diag);
            // residue (root attributes of this format), input order, after mapped
            for (e.residue.items) |r| {
                if (!std.mem.eql(u8, r.fmt, p.format)) continue;
                try xmlSet(alloc, root, r.locator, r.value, .field);
            }
            var buf = std.ArrayList(u8).init(alloc);
            try xmlWrite(&buf, root);
            return buf.toOwnedSlice();
        },
        .geojson => {
            var coords = [3]?[]const u8{ null, null, null };
            var coords_weak = [3]bool{ false, false, false };
            var props = std.ArrayList(Member).init(alloc);
            var top = std.ArrayList(Member).init(alloc);
            for (lines) |*ln| {
                var raw: []const u8 = undefined;
                var mode: WMode = .field;
                if (ln.tag == .group) {
                    // an array at the member; an absent list writes nothing
                    raw = (try jsonGroupRaw(alloc, p, ln.grp.?, e, diag)) orelse continue;
                } else if (ln.isFixed()) {
                    if (ln.wpresent) continue;
                    raw = try whenJsonRaw(alloc, ln.*);
                    mode = .fixed;
                } else if (fieldValue(p, sc, e, ln) catch |err|
                    return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator })) |mv|
                {
                    raw = jsonRaw(alloc, ln.transform.kind, mv) catch |err|
                        return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator });
                } else if (ln.abs_set) {
                    // an absent key writes its first sentinel; for `lon` and
                    // `lat` it counts as a value (ruling 10 of 0.9)
                    raw = ln.abs_json;
                    mode = .sentinel;
                } else continue;
                const loc = ln.locator;
                if (std.mem.startsWith(u8, loc, geom_prefix)) {
                    const comp = loc[geom_prefix.len..];
                    const idx: usize = if (std.mem.eql(u8, comp, "lon")) 0 else if (std.mem.eql(u8, comp, "lat")) 1 else if (std.mem.eql(u8, comp, "alt")) 2 else continue;
                    if (coords[idx] == null or mode == .fixed or (mode == .field and coords_weak[idx])) {
                        coords[idx] = raw;
                        coords_weak[idx] = mode == .sentinel;
                    }
                } else if (std.mem.startsWith(u8, loc, props_prefix)) {
                    try memberAdd(&props, loc[props_prefix.len..], raw, mode);
                } else {
                    if (std.mem.eql(u8, loc, "type") or std.mem.eql(u8, loc, "geometry") or std.mem.eql(u8, loc, "properties")) continue;
                    try memberAdd(&top, loc, raw, mode);
                }
            }
            // residue of this format, input order, after the mapped members
            for (e.residue.items) |r| {
                if (!std.mem.eql(u8, r.fmt, p.format)) continue;
                if (std.mem.startsWith(u8, r.locator, props_prefix)) {
                    try memberAdd(&props, r.locator[props_prefix.len..], r.value, .field);
                } else {
                    try memberAdd(&top, r.locator, r.value, .field);
                }
            }
            var buf = std.ArrayList(u8).init(alloc);
            try buf.appendSlice("{\"type\":\"Feature\",\"geometry\":");
            if (coords[0] != null and coords[1] != null) {
                try buf.appendSlice("{\"type\":\"Point\",\"coordinates\":[");
                try buf.appendSlice(coords[0].?);
                try buf.append(',');
                try buf.appendSlice(coords[1].?);
                if (coords[2]) |av| {
                    try buf.append(',');
                    try buf.appendSlice(av);
                }
                try buf.appendSlice("]}");
            } else {
                try buf.appendSlice("null"); // either lon or lat absent
            }
            try buf.appendSlice(",\"properties\":{");
            try membersWrite(&buf, props.items, true);
            try buf.append('}');
            try membersWrite(&buf, top.items, false);
            try buf.append('}');
            return buf.toOwnedSlice();
        },
        .json => {
            const root = try jnodeNew(alloc, "");
            try jsonEncodeScope(alloc, p, sc, root, e, diag);
            // residue members of each object, input order, after the mapped members
            for (e.residue.items) |r| {
                if (!std.mem.eql(u8, r.fmt, p.format)) continue;
                var segs = std.ArrayList([]const u8).init(alloc);
                var it = std.mem.splitScalar(u8, r.locator, '.');
                while (it.next()) |seg| try segs.append(seg);
                try jnodeInsert(alloc, root, segs.items, r.value, .field);
            }
            var buf = std.ArrayList(u8).init(alloc);
            root.raw = null;
            try jnodeWrite(&buf, root);
            return buf.toOwnedSlice();
        },
        .bits => {
            // the whole message, `optional` fields included, then the items;
            // padded with zero bits to whole words
            var out = BitsOut{ .buf = std.ArrayList(u8).init(alloc) };
            try out.ensure(p.wordBytes(sc.nbits) * 8);
            const end = try bitsEncodeScope(alloc, p, sc, &out, 0, e, diag);
            try out.ensure(p.wordBytes(@max(sc.nbits, end)) * 8);
            return hexEncode(alloc, out.buf.items);
        },
        .protobuf => {
            const root = try alloc.create(PbNode);
            root.* = .{ .number = 0, .children = std.ArrayList(*PbNode).init(alloc) };
            try pbEncodeScope(alloc, p, sc, root, e, diag);
            var buf = std.ArrayList(u8).init(alloc);
            try encodeProtoNode(alloc, root, &buf);
            return hexEncode(alloc, buf.items);
        },
        .text => return textEncode(alloc, p, sc, e, diag),
    }
}

// ---------------------------------------------------------------------------
// Version 0.10: the `text` wire. One record of ASCII text: fields between
// delimiters, optionally framed by a start text and an `nmea` checksum; a
// field may be read as character columns.
// ---------------------------------------------------------------------------

// The fields of a record; inside a group item, `base` is the index of the
// item's first field.
const TextDoc = struct { fields: []const []const u8, base: usize = 0 };

fn printable(s: []const u8) bool {
    for (s) |c| if (c < 0x20 or c > 0x7e) return false;
    return true;
}

fn parseIdx(s: []const u8) ?usize {
    const v = parseUnsigned(s) orelse return null;
    if (v > 1 << 40) return null;
    return @intCast(v);
}

// The checks that relate `wire`, `delimiter`, `start` and `checksum`, after
// the file is read (rulings 2 and 10 of 0.10).
fn textDirectives(alloc: std.mem.Allocator, p: *Pack, diag: *Diag) anyerror!void {
    const bd = E.@"bad-directive";
    if (!p.text_dirs) return;
    if (p.wire != .text) return bad(diag, alloc, bd, "delimiter, start and checksum are directives of the text wire, not {s}", .{@tagName(p.wire)});
    if (p.tdir_bad != 0) return bad(diag, alloc, bd, "line {d}: delimiter, start and checksum appear at most once, before the first kind", .{p.tdir_bad});
    if (p.delim_raw) |d| {
        if (std.mem.eql(u8, d, "none")) {
            p.delim = null;
        } else if (d.len == 1 and d[0] >= 0x21 and d[0] <= 0x7e and d[0] != '"') {
            p.delim = d[0];
        } else return bad(diag, alloc, bd, "delimiter {s} is not one character from 0x21 to 0x7E other than a quote, or none", .{d});
    }
    if (p.cksum_raw) |c| {
        if (std.mem.eql(u8, c, "nmea")) {
            p.nmea = true;
        } else if (!std.mem.eql(u8, c, "none")) return bad(diag, alloc, bd, "checksum {s} is not none or nmea", .{c});
    }
    if (p.start_raw) |st| {
        if (st.len == 0) return bad(diag, alloc, bd, "an empty start", .{});
        for (st) |ch| {
            if (ch < 0x21 or ch > 0x7e) return bad(diag, alloc, bd, "start {s} holds a character outside 0x21 to 0x7E", .{st});
            if (p.delim != null and ch == p.delim.?) return bad(diag, alloc, bd, "start {s} holds the delimiter", .{st});
        }
        p.start = st;
    }
    if (p.nmea and p.delim != null and p.delim.? == '*') return bad(diag, alloc, bd, "delimiter \"*\" with checksum nmea", .{});
}

// One line's locator, and a `when` or `const` value, on the text wire.
fn textFinalizeLine(alloc: std.mem.Allocator, p: *Pack, ln: *Line, diag: *Diag) anyerror!void {
    const bd = E.@"bad-directive";
    const loc = ln.locator;
    if (std.mem.indexOfScalar(u8, loc, '+')) |plus| {
        ln.ti = parseIdx(loc[0..plus]) orelse return bad(diag, alloc, bd, "line {d}: locator {s} is not <i>+<j>", .{ ln.lineno, loc });
        ln.tj = parseIdx(loc[plus + 1 ..]) orelse return bad(diag, alloc, bd, "line {d}: locator {s} is not <i>+<j>", .{ ln.lineno, loc });
        ln.tloc = .pair;
        if (ln.ti == ln.tj) return bad(diag, alloc, bd, "line {d}: the pair {s} names one field twice", .{ ln.lineno, loc });
    } else if (std.mem.indexOfScalar(u8, loc, ':') != null) {
        const c = parseColons(loc, 3) orelse return bad(diag, alloc, bd, "line {d}: locator {s} is not <i>:<from>:<len>", .{ ln.lineno, loc });
        if (c[2] < 1) return bad(diag, alloc, bd, "line {d}: column {s} has length 0", .{ ln.lineno, loc });
        ln.tloc = .column;
        ln.ti = c[0];
        ln.tfrom = c[1];
        ln.tlen = c[2];
    } else {
        ln.ti = parseIdx(loc) orelse return bad(diag, alloc, bd, "line {d}: locator {s} is not a field index", .{ ln.lineno, loc });
    }
    if (ln.tloc == .pair and !ln.isField()) return bad(diag, alloc, bd, "line {d}: {s} on a pair", .{ ln.lineno, @tagName(ln.tag) });
    if (ln.isField()) {
        const two = ln.transform.kind == .dm or ln.transform.kind == .hms_dmy;
        if (two and ln.tloc != .pair) return bad(diag, alloc, bd, "line {d}: the transform of {s} takes a pair", .{ ln.lineno, ln.key });
        if (!two and ln.tloc == .pair) return bad(diag, alloc, bd, "line {d}: the transform of {s} does not take a pair", .{ ln.lineno, ln.key });
    }
    if (p.delim == null and (ln.ti != 0 or (ln.tloc == .pair and ln.tj != 0))) {
        return bad(diag, alloc, bd, "line {d}: under delimiter none the record is field 0, not {s}", .{ ln.lineno, loc });
    }
    if (!ln.isFixed()) return;
    if (ln.tag == .when and std.mem.eql(u8, ln.wraw, "present")) {
        ln.wpresent = true;
        return;
    }
    var v = ln.wraw;
    if (v.len > 0 and v[0] == '=') {
        ln.wforced = true;
        v = v[1..];
    }
    ln.wtext = v;
    const why: ?[]const u8 = blk: {
        if (v.len == 0) break :blk "is empty";
        if (!printable(v)) break :blk "holds a character outside 0x20 to 0x7E";
        if (v[0] == ' ' or v[v.len - 1] == ' ') break :blk "has a space at its start or end";
        if (p.delim) |d| if (std.mem.indexOfScalar(u8, v, d) != null) break :blk "holds the delimiter";
        if (p.nmea and std.mem.indexOfScalar(u8, v, '*') != null) break :blk "holds a * under checksum nmea";
        if (ln.tloc == .column and v.len > ln.tlen) break :blk "is longer than its column";
        break :blk null;
    };
    if (why) |w| return bad(diag, alloc, bd, "line {d}: the value of {s} {s} {s}", .{ ln.lineno, @tagName(ln.tag), ln.locator, w });
}

// `group <list> <i> item <n>` on the text wire.
fn textFinalizeGroup(alloc: std.mem.Allocator, p: *Pack, g: *Group, nested: bool, diag: *Diag) anyerror!void {
    const bd = E.@"bad-directive";
    if (nested) return bad(diag, alloc, bd, "line {d}: a group inside a group on the text wire", .{g.lineno});
    if (p.delim == null) return bad(diag, alloc, bd, "line {d}: a group under delimiter none", .{g.lineno});
    if (g.count_txt != null) return bad(diag, alloc, bd, "line {d}: count on a text group", .{g.lineno});
    const it = g.item_txt orelse return bad(diag, alloc, bd, "line {d}: a text group needs `item <n>`", .{g.lineno});
    g.titem = parseIdx(it) orelse 0;
    if (g.titem == 0) return bad(diag, alloc, bd, "line {d}: item {s} is not a number of fields from 1", .{ g.lineno, it });
    g.tstart = parseIdx(g.locator) orelse return bad(diag, alloc, bd, "line {d}: group locator {s} is not a field index", .{ g.lineno, g.locator });
    try finalizeLines(alloc, p, g.lines, true, diag);
    for (g.lines) |*ln| {
        if (ln.tag == .group) continue;
        if (ln.ti >= g.titem or (ln.tloc == .pair and ln.tj >= g.titem)) {
            return bad(diag, alloc, bd, "line {d}: locator {s} is beyond an item of {d} fields", .{ ln.lineno, ln.locator, g.titem });
        }
    }
}

// A group is the last thing in its scope: one group, and no other line at
// its index or beyond.
fn textCheckScope(alloc: std.mem.Allocator, a: []const Line, b: []const Line, diag: *Diag) anyerror!void {
    const bd = E.@"bad-directive";
    const both = [2][]const Line{ a, b };
    var grp: ?*const Group = null;
    for (both) |lines| for (lines) |*ln| {
        if (ln.tag != .group) continue;
        if (grp != null) return bad(diag, alloc, bd, "line {d}: a second group in one scope", .{ln.lineno});
        grp = ln.grp.?;
    };
    const g = grp orelse return;
    for (both) |lines| for (lines) |*ln| {
        if (ln.tag == .group) continue;
        if (ln.ti >= g.tstart or (ln.tloc == .pair and ln.tj >= g.tstart)) {
            return bad(diag, alloc, bd, "line {d}: locator {s} at or beyond the group at field {d}", .{ ln.lineno, ln.locator, g.tstart });
        }
    };
}

fn hexVal(c: u8) ?u8 {
    return switch (c) {
        '0'...'9' => c - '0',
        'A'...'F' => c - 'A' + 10,
        'a'...'f' => c - 'a' + 10,
        else => null,
    };
}

// Steps 1 to 5 of "Reading a record"; each failure is `malformed-wire`.
fn textParse(alloc: std.mem.Allocator, p: *const Pack, bytes: []const u8, diag: *Diag) anyerror!TextDoc {
    const mw = E.@"malformed-wire";
    var t = bytes;
    if (std.mem.endsWith(u8, t, "\r\n")) {
        t = t[0 .. t.len - 2];
    } else if (std.mem.endsWith(u8, t, "\n")) {
        t = t[0 .. t.len - 1];
    }
    for (t, 0..) |c, i| {
        if (c < 0x20 or c > 0x7e) return bad(diag, alloc, mw, "byte {d} of the record is 0x{x:0>2}, outside 0x20 to 0x7E", .{ i, c });
    }
    if (p.start.len > 0) {
        if (!std.mem.startsWith(u8, t, p.start)) return bad(diag, alloc, mw, "the record does not begin with {s}", .{p.start});
        t = t[p.start.len..];
    }
    if (p.nmea) {
        if (t.len < 3 or t[t.len - 3] != '*') return bad(diag, alloc, mw, "the record does not end with * and two hexadecimal digits", .{});
        const hi = hexVal(t[t.len - 2]) orelse return bad(diag, alloc, mw, "the checksum is not two hexadecimal digits", .{});
        const lo = hexVal(t[t.len - 1]) orelse return bad(diag, alloc, mw, "the checksum is not two hexadecimal digits", .{});
        t = t[0 .. t.len - 3];
        var x: u8 = 0;
        for (t) |c| x ^= c;
        if (x != hi * 16 + lo) return bad(diag, alloc, mw, "the checksum is {X:0>2}, the record's is {X:0>2}", .{ hi * 16 + lo, x });
        if (std.mem.indexOfScalar(u8, t, '*') != null) return bad(diag, alloc, mw, "a * in the body of the record", .{});
    }
    const d = p.delim orelse {
        const one = try alloc.alloc([]const u8, 1);
        one[0] = t;
        return .{ .fields = one };
    };
    const n = std.mem.count(u8, t, &[_]u8{d}) + 1;
    const fields = try alloc.alloc([]const u8, n);
    var it = std.mem.splitScalar(u8, t, d);
    var i: usize = 0;
    while (it.next()) |f| : (i += 1) fields[i] = f;
    return .{ .fields = fields };
}

// The numeric transforms: a column's leading spaces are removed for them,
// and they pad a column with zeros on encode.
fn textNumeric(k: TKind) bool {
    return k == .int or k == .int_w or k == .float or k == .dec;
}

// The text of field `idx` (of the item) as a line reads it; null: absent.
fn textRead(d: TextDoc, ln: *const Line, idx: usize, numeric: bool) ?[]const u8 {
    const at = d.base + idx;
    if (at >= d.fields.len) return null;
    const f = d.fields[at];
    if (ln.tloc != .column) return if (f.len == 0) null else f;
    if (f.len <= ln.tfrom) return null;
    var c = f[ln.tfrom..@min(f.len, ln.tfrom + ln.tlen)];
    c = std.mem.trimRight(u8, c, " ");
    if (numeric) c = std.mem.trimLeft(u8, c, " ");
    return if (c.len == 0) null else c;
}

// `float` and `dec` text: a sign, then digits with at most one `.`, at least
// one digit; no exponent.
fn textDecimal(s: []const u8) !f64 {
    const td = E.@"transform-decode";
    var i: usize = 0;
    if (i < s.len and (s[i] == '+' or s[i] == '-')) i += 1;
    var nd: usize = 0;
    var dots: usize = 0;
    while (i < s.len) : (i += 1) {
        if (isDigit(s[i])) {
            nd += 1;
        } else if (s[i] == '.') {
            dots += 1;
        } else return td;
    }
    if (nd == 0 or dots > 1) return td;
    const v = std.fmt.parseFloat(f64, s) catch return td;
    if (!std.math.isFinite(v)) return td;
    return v;
}

const Hms = struct { h: i64, m: i64, s: i64, secs: []const u8, frac: []const u8 };

// `hhmmss` then optionally `.` and digits.
fn parseHms(s: []const u8) !Hms {
    const td = E.@"transform-decode";
    if (s.len < 6 or !allDigits(s[0..6])) return td;
    const frac = if (s.len > 6) blk: {
        if (s[6] != '.' or !allDigits(s[7..])) return td;
        break :blk s[7..];
    } else "";
    const r = Hms{
        .h = try digitsToInt(s[0..2]),
        .m = try digitsToInt(s[2..4]),
        .s = try digitsToInt(s[4..6]),
        .secs = s[4..],
        .frac = frac,
    };
    if (r.h >= 24 or r.m >= 60 or r.s >= 60) return td;
    return r;
}

fn textDecode(t: Transform, raw: []const u8) !MV {
    return switch (t.kind) {
        .string => MV{ .str = raw },
        .int, .int_w => MV{ .int = try parseTextInt(raw) },
        .float, .dec => MV{ .float = try textDecimal(raw) },
        .iso8601_ms, .iso8601_s => MV{ .int = try isoToMs(raw) },
        .hms => blk: {
            const h = try parseHms(raw);
            const secs = std.fmt.parseFloat(f64, h.secs) catch return E.@"transform-decode";
            break :blk MV{ .float = @as(f64, @floatFromInt(h.h * 3600 + h.m * 60)) + secs };
        },
        else => E.@"transform-decode",
    };
}

fn daysInMonth(y: i64, m: i64) i64 {
    return switch (m) {
        1, 3, 5, 7, 8, 10, 12 => 31,
        4, 6, 9, 11 => 30,
        else => if ((@mod(y, 4) == 0 and @mod(y, 100) != 0) or @mod(y, 400) == 0) 29 else 28,
    };
}

fn textDecodePair(t: Transform, a: []const u8, b: []const u8) !MV {
    const td = E.@"transform-decode";
    switch (t.kind) {
        .dm => {
            const d = t.d;
            if (a.len < d + 2 or !allDigits(a[0 .. d + 2])) return td;
            if (a.len > d + 2 and (a[d + 2] != '.' or !allDigits(a[d + 3 ..]))) return td;
            if (try digitsToInt(a[d .. d + 2]) >= 60) return td;
            const deg: f64 = @floatFromInt(try digitsToInt(a[0..d]));
            const mins = std.fmt.parseFloat(f64, a[d..]) catch return td;
            const v = deg + mins / 60.0;
            if (b.len != 1) return td;
            if (b[0] == t.letp) return MV{ .float = v };
            if (b[0] == t.letn) return MV{ .float = -v };
            return td;
        },
        .hms_dmy => {
            const h = try parseHms(a);
            var ms: i64 = 0;
            for (0..3) |k| ms = ms * 10 + (if (k < h.frac.len) @as(i64, h.frac[k] - '0') else 0);
            if (b.len != 6 or !allDigits(b)) return td;
            const dd = try digitsToInt(b[0..2]);
            const mo = try digitsToInt(b[2..4]);
            const yy = try digitsToInt(b[4..6]);
            const y = if (yy >= 80) 1900 + yy else 2000 + yy;
            if (mo < 1 or mo > 12 or dd < 1 or dd > daysInMonth(y, mo)) return td;
            const days = daysFromCivil(y, mo, dd);
            return MV{ .int = days * 86400000 + (h.h * 3600 + h.m * 60 + h.s) * 1000 + ms };
        },
        else => return td,
    }
}

// Does a line of the scope address field `idx` (Residue: `when … present`
// does not)?
fn textAddresses(ln: *const Line, idx: usize) bool {
    if (ln.tag == .group or !ln.maps()) return false;
    return ln.ti == idx or (ln.tloc == .pair and ln.tj == idx);
}

fn textGroup(lines: []const Line) ?*const Group {
    for (lines) |*ln| if (ln.tag == .group) return ln.grp.?;
    return null;
}

fn textResidue(alloc: std.mem.Allocator, p: *const Pack, lines: []const Line, td: TextDoc, e: *Entity) anyerror!void {
    const g = textGroup(lines);
    for (td.fields, 0..) |f, idx| {
        if (f.len == 0) continue;
        if (g) |gr| if (idx >= gr.tstart) break;
        var addressed = false;
        for (lines) |*ln| {
            if (textAddresses(ln, idx)) {
                addressed = true;
                break;
            }
        }
        if (addressed) continue;
        try e.addResidue(.{ .fmt = p.format, .locator = try intToStr(alloc, @intCast(idx)), .value = f });
    }
}

// ---- encode

const pow10 = [_]f64{ 1, 10, 100, 1e3, 1e4, 1e5, 1e6, 1e7, 1e8, 1e9 };
const two53: f64 = 9007199254740992.0;

// round half away from zero; a value not finite or of 2^53 or more is
// `transform-encode`
fn roundExact(v: f64) !i64 {
    if (!std.math.isFinite(v)) return E.@"transform-encode";
    const r = @round(v);
    if (@abs(r) >= two53) return E.@"transform-encode";
    return @intFromFloat(r);
}

// The digits of `n`, zero-padded to at least `min` digits, with a `.`
// before the last `f`.
fn fixedDigits(buf: *std.ArrayList(u8), n: u64, min: usize, f: usize) !void {
    var tmp: [24]u8 = undefined;
    const ds = std.fmt.bufPrint(&tmp, "{d}", .{n}) catch unreachable;
    const width = @max(min, ds.len);
    var digits: [48]u8 = undefined;
    @memset(digits[0 .. width - ds.len], '0');
    @memcpy(digits[width - ds.len .. width], ds);
    if (f == 0) {
        try buf.appendSlice(digits[0..width]);
        return;
    }
    try buf.appendSlice(digits[0 .. width - f]);
    try buf.append('.');
    try buf.appendSlice(digits[width - f .. width]);
}

const TextOut = struct { a: []const u8, b: []const u8 = "" };

fn textEncodeValue(alloc: std.mem.Allocator, t: Transform, mv: MV) !TextOut {
    const te = E.@"transform-encode";
    var buf = std.ArrayList(u8).init(alloc);
    switch (t.kind) {
        .string, .float, .int, .iso8601_ms, .iso8601_s => return .{ .a = try xmlText(alloc, t.kind, mv) },
        .int_w => {
            if (mv != .int) return te;
            if (mv.int < 0) try buf.append('-');
            try fixedDigits(&buf, @abs(mv.int), t.w, 0);
        },
        .dec => {
            const n = try roundExact((try mvFloat(mv)) * pow10[t.f]);
            var body = std.ArrayList(u8).init(alloc);
            try fixedDigits(&body, @abs(n), t.f + 1, t.f);
            if (n < 0) try buf.append('-');
            if (body.items.len < t.w) try buf.appendNTimes('0', t.w - body.items.len);
            try buf.appendSlice(body.items);
        },
        .dm => {
            const x = try mvFloat(mv);
            const m = try roundExact(@abs(x) * 60.0 * pow10[t.f]);
            const unit: u64 = 60 * @as(u64, @intFromFloat(pow10[t.f]));
            const um: u64 = @intCast(m);
            const deg = um / unit;
            var tmp: [24]u8 = undefined;
            const ds = std.fmt.bufPrint(&tmp, "{d}", .{deg}) catch unreachable;
            if (ds.len > t.d) return te; // the degrees do not fit `d` digits
            try fixedDigits(&buf, deg, t.d, 0);
            try fixedDigits(&buf, um % unit, 2 + t.f, t.f);
            const letter: u8 = if (x < 0 and m > 0) t.letn else t.letp;
            return .{ .a = buf.items, .b = try alloc.dupe(u8, &[_]u8{letter}) };
        },
        .hms => {
            const n = try roundExact((try mvFloat(mv)) * pow10[t.f]);
            const p10: i64 = @intFromFloat(pow10[t.f]);
            if (n < 0 or n >= 86400 * p10) return te;
            try hmsText(&buf, @intCast(@divTrunc(n, p10)), @intCast(@mod(n, p10)), t.f);
        },
        .hms_dmy => {
            if (mv != .int) return te;
            const day = @divFloor(mv.int, 86400000);
            const msd = @mod(mv.int, 86400000);
            const c = civilFromDays(day);
            if (c.y < 1980 or c.y > 2079) return te;
            const div: i64 = @intFromFloat(pow10[3 - t.f]);
            try hmsText(&buf, @intCast(@divTrunc(msd, 1000)), @intCast(@divTrunc(@mod(msd, 1000), div)), t.f);
            const date = try std.fmt.allocPrint(alloc, "{d:0>2}{d:0>2}{d:0>2}", .{ @as(u64, @intCast(c.d)), @as(u64, @intCast(c.m)), @as(u64, @intCast(@mod(c.y, 100))) });
            return .{ .a = buf.items, .b = date };
        },
        else => return te,
    }
    return .{ .a = buf.items };
}

// `hhmmss` of a second of the day, then `.` and `f` digits of `frac`.
fn hmsText(buf: *std.ArrayList(u8), secs: u64, frac: u64, f: usize) !void {
    try buf.writer().print("{d:0>2}{d:0>2}{d:0>2}", .{ secs / 3600, secs / 60 % 60, secs % 60 });
    if (f > 0) {
        try buf.append('.');
        try fixedDigits(buf, frac, f, 0);
    }
}

// One field of the record being written: the text of the first whole-field
// line that writes it, the columns field lines write (the earlier line's
// characters stand), then `when` and `const` values over both.
const TField = struct {
    whole: ?[]const u8 = null,
    cols: std.ArrayListUnmanaged(u8) = .{},
    cmask: std.ArrayListUnmanaged(bool) = .{},
    text: std.ArrayListUnmanaged(u8) = .{},
    fmask: std.ArrayListUnmanaged(bool) = .{},
    fixed_whole: bool = false,
};

const TextEnc = struct {
    alloc: std.mem.Allocator,
    p: *const Pack,
    diag: *Diag,
    fields: std.ArrayListUnmanaged(TField) = .{},
    // `when` and `const` lines, with the index of their item's first field
    fixed: std.ArrayListUnmanaged(struct { ln: *const Line, base: usize }) = .{},

    fn field(self: *TextEnc, idx: usize) !*TField {
        while (self.fields.items.len <= idx) try self.fields.append(self.alloc, .{});
        return &self.fields.items[idx];
    }

    // Text a transform wrote: no delimiter, no `*` under nmea, 0x20 to 0x7E.
    fn check(self: *TextEnc, ln: *const Line, s: []const u8) !void {
        const te = E.@"transform-encode";
        if (!printable(s)) return bad(self.diag, self.alloc, te, "field {s} at {s}: the text holds a character outside 0x20 to 0x7E", .{ ln.key, ln.locator });
        if (self.p.delim) |d| if (std.mem.indexOfScalar(u8, s, d) != null) return bad(self.diag, self.alloc, te, "field {s} at {s}: the text holds the delimiter", .{ ln.key, ln.locator });
        if (self.p.nmea and std.mem.indexOfScalar(u8, s, '*') != null) return bad(self.diag, self.alloc, te, "field {s} at {s}: the text holds a *", .{ ln.key, ln.locator });
    }

    fn whole(self: *TextEnc, idx: usize, s: []const u8) !void {
        const f = try self.field(idx);
        if (f.whole == null) f.whole = s;
    }

    fn column(self: *TextEnc, ln: *const Line, idx: usize, s: []const u8) !void {
        if (s.len > ln.tlen) return bad(self.diag, self.alloc, E.@"transform-encode", "field {s} at {s}: {d} characters do not fit the column", .{ ln.key, ln.locator, s.len });
        // padded to `len`: zeros after any `-` for the numeric transforms,
        // else spaces on the right
        var padded = std.ArrayList(u8).init(self.alloc);
        if (textNumeric(ln.transform.kind)) {
            const neg = s.len > 0 and s[0] == '-';
            if (neg) try padded.append('-');
            try padded.appendNTimes('0', ln.tlen - s.len);
            try padded.appendSlice(if (neg) s[1..] else s);
        } else {
            try padded.appendSlice(s);
            try padded.appendNTimes(' ', ln.tlen - s.len);
        }
        const f = try self.field(idx);
        const end = ln.tfrom + ln.tlen;
        while (f.cols.items.len < end) {
            try f.cols.append(self.alloc, ' ');
            try f.cmask.append(self.alloc, false);
        }
        for (padded.items, ln.tfrom..) |c, at| {
            if (f.cmask.items[at]) continue;
            f.cols.items[at] = c;
            f.cmask.items[at] = true;
        }
    }

    // The field lines of one scope, at `base`; `when` and `const` are kept
    // for the end.
    fn scope(self: *TextEnc, sc: *const Scope, e: *const Entity, base: usize) anyerror!void {
        for (sc.lines) |*ln| {
            switch (ln.tag) {
                .when, .constant => try self.fixed.append(self.alloc, .{ .ln = ln, .base = base }),
                .group => {
                    const g = ln.grp.?;
                    const items = e.lists.get(g.list) orelse continue;
                    for (items, 0..) |*it, k| {
                        // each item `n` fields long whether or not its keys are present
                        if (g.titem > 0) _ = try self.field(base + g.tstart + (k + 1) * g.titem - 1);
                        try self.scope(&g.body, it, base + g.tstart + k * g.titem);
                    }
                },
                .field => {
                    const mv = (fieldValue(self.p, sc, e, ln) catch |err|
                        return bad(self.diag, self.alloc, err, "field {s} at {s}", .{ ln.key, ln.locator })) orelse continue;
                    const out = textEncodeValue(self.alloc, ln.transform, mv) catch |err| switch (err) {
                        error.OutOfMemory => return err,
                        else => return bad(self.diag, self.alloc, err, "field {s} at {s}: the value does not encode", .{ ln.key, ln.locator }),
                    };
                    try self.check(ln, out.a);
                    switch (ln.tloc) {
                        .whole => try self.whole(base + ln.ti, out.a),
                        .column => try self.column(ln, base + ln.ti, out.a),
                        .pair => {
                            try self.check(ln, out.b);
                            try self.whole(base + ln.ti, out.a);
                            try self.whole(base + ln.tj, out.b);
                        },
                    }
                },
            }
        }
    }

    // The text of each field from its lines, then the `when` and `const`
    // values over it.
    fn compose(self: *TextEnc) !void {
        for (self.fields.items) |*f| {
            try f.text.appendSlice(self.alloc, f.whole orelse f.cols.items);
            try f.fmask.appendNTimes(self.alloc, false, f.text.items.len);
        }
        for (self.fixed.items) |fx| {
            const ln = fx.ln;
            if (ln.wpresent) continue;
            const f = try self.field(fx.base + ln.ti);
            if (f.fixed_whole) continue; // the earlier line's characters stand
            if (ln.tloc == .whole) {
                if (std.mem.indexOfScalar(bool, f.fmask.items, true) != null) continue;
                f.text.clearRetainingCapacity();
                try f.text.appendSlice(self.alloc, ln.wtext);
                f.fmask.clearRetainingCapacity();
                try f.fmask.appendNTimes(self.alloc, true, ln.wtext.len);
                f.fixed_whole = true;
                continue;
            }
            const end = ln.tfrom + ln.tlen;
            while (f.text.items.len < end) {
                try f.text.append(self.alloc, ' ');
                try f.fmask.append(self.alloc, false);
            }
            for (0..ln.tlen) |k| {
                const at = ln.tfrom + k;
                if (f.fmask.items[at]) continue;
                f.text.items[at] = if (k < ln.wtext.len) ln.wtext[k] else ' ';
                f.fmask.items[at] = true;
            }
        }
    }
};

fn textEncode(alloc: std.mem.Allocator, p: *const Pack, sc: *const Scope, e: *const Entity, diag: *Diag) anyerror![]u8 {
    var enc = TextEnc{ .alloc = alloc, .p = p, .diag = diag };
    try enc.scope(sc, e, 0);
    const g = textGroup(sc.lines);
    // the record's length: the fields the lines address, the items wrote,
    // and the residue written
    var n: usize = enc.fields.items.len;
    for (sc.lines) |*ln| {
        if (ln.tag == .group or !ln.maps()) continue;
        n = @max(n, ln.ti + 1);
        if (ln.tloc == .pair) n = @max(n, ln.tj + 1);
    }
    for (e.residue.items) |r| {
        if (!std.mem.eql(u8, r.fmt, p.format)) continue;
        const idx = parseIdx(r.locator) orelse continue;
        if (g) |gr| if (idx >= gr.tstart) continue;
        var addressed = false;
        for (sc.lines) |*ln| {
            if (textAddresses(ln, idx)) addressed = true;
        }
        if (addressed) continue;
        try enc.whole(idx, r.value);
        n = @max(n, idx + 1);
    }
    _ = try enc.field(if (n > 0) n - 1 else 0);
    try enc.compose();
    // trailing empty fields that only `optional` lines address are removed
    while (n > 0) {
        const last = n - 1;
        if (enc.fields.items[last].text.items.len > 0) break;
        if (g) |gr| if (last >= gr.tstart) break;
        var any = false;
        var all_optional = true;
        for (sc.lines) |*ln| {
            if (!textAddresses(ln, last)) continue;
            any = true;
            if (!(ln.isField() and ln.optional)) all_optional = false;
        }
        if (!any or !all_optional) break;
        n -= 1;
    }
    var buf = std.ArrayList(u8).init(alloc);
    try buf.appendSlice(p.start);
    const body_at = buf.items.len;
    const count = if (p.delim == null) @min(n, 1) else n;
    for (enc.fields.items[0..count], 0..) |*f, i| {
        if (i > 0) try buf.append(p.delim.?);
        try buf.appendSlice(f.text.items);
    }
    if (p.nmea) {
        var x: u8 = 0;
        for (buf.items[body_at..]) |c| x ^= c;
        try buf.writer().print("*{X:0>2}", .{x});
    }
    return buf.toOwnedSlice();
}

// ---------------------------------------------------------------------------
// Version 0.8: sequential binary layouts (`layout sequential` on the bits
// wire). A locator is a bit length; lines are read, and written, in file
// order from a cursor.
// ---------------------------------------------------------------------------

// One `presence <name> <n>|fx` line.
const SPres = struct {
    name: []const u8,
    n: usize, // the number of presence bits; 0: `fx`
    // named[i - 1]: some `if` block names bit i, with or without `!`
    named: std.ArrayListUnmanaged(bool) = .{},
};

// One `<name>.<i>` or `!<name>.<i>` of an `if` line; `bit` counts from 1.
const SCond = struct { pres: *SPres, bit: usize, neg: bool };

// One `also <key> [via <table>]` line: another key on the bits of a field.
const SAlso = struct {
    key: []const u8,
    via_name: []const u8 = "",
    via: ?*const Table = null,
    kty: KeyType = .string,
    lineno: usize = 0,
};

const SMode = enum { count, while_, more, fx };
const STag = enum { field, constant, when, pad, align_, presence, if_, opt, group, chain, fx, length, whole };
const DMap = std.StringHashMapUnmanaged(MV);

// One line of a sequential pack; a block holds its lines in `body`.
const SNode = struct {
    tag: STag,
    lineno: usize = 0,
    ln: Line = .{ .locator = "" }, // field: key, transform, options, bit length
    also: std.ArrayListUnmanaged(SAlso) = .{},
    // const, when, pad: the bit length; align: the multiple; group: the bit
    // length of the count; length, whole: the bit length of the length field
    len: usize = 0,
    value: u64 = 0, // const, when
    pres: ?*SPres = null, // presence
    conds: []const SCond = &.{}, // if
    body: []SNode = &.{}, // if, opt, chain, length
    list: []const u8 = "", // group
    mode: SMode = .count,
    gbody: ?*SBody = null,
    in_bits: bool = false, // length: counted in bits
    plus: i64 = 0, // length, whole
};

const SKind = struct {
    name: []const u8,
    whens: []SNode = &.{},
    lines: []SNode = &.{},
    requires: std.ArrayListUnmanaged([]const u8) = .{},
    defaults: std.ArrayListUnmanaged(Default) = .{},
    dmap: DMap = .{},
};

// The lines of a message, or of one item of a group: the common lines, then
// the kinds.
const SBody = struct {
    common: []SNode = &.{},
    kinds: []SKind = &.{},
    defaults: std.ArrayListUnmanaged(Default) = .{},
    dmap: DMap = .{},
};

// Is the bit length one the transform allows?
fn bitsLenOk(k: TKind, blen: usize) bool {
    return switch (k) {
        .f32_ => blen == 32,
        .f64_ => blen == 64,
        .ascii => blen >= 8 and blen <= 2040 and blen % 8 == 0,
        else => blen >= 1 and blen <= 64,
    };
}

fn fitsBits(v: u64, len: usize) bool {
    return len >= 64 or (v >> @as(u6, @intCast(len))) == 0;
}

// Does the file hold `wire bits` and `layout sequential`?
fn isSequentialPack(alloc: std.mem.Allocator, def_text: []const u8) !bool {
    var bits = false;
    var seq = false;
    var tokbuf = std.ArrayList([]const u8).init(alloc);
    defer tokbuf.deinit();
    var lines = std.mem.splitScalar(u8, def_text, '\n');
    while (lines.next()) |line| {
        tokenizeInto(&tokbuf, line) catch |err| switch (err) {
            error.OutOfMemory => return err,
            else => continue, // reported by the parser, in its place
        };
        const t = tokbuf.items;
        if (t.len != 2) continue;
        if (std.mem.eql(u8, t[0], "wire") and std.mem.eql(u8, t[1], "bits")) bits = true;
        if (std.mem.eql(u8, t[0], "layout") and std.mem.eql(u8, t[1], "sequential")) seq = true;
    }
    return bits and seq;
}

const SFrameTag = enum { body, if_, opt, chain, length };

// An open block while a sequential pack is read. The message is the first
// frame; a group body is a `body` frame with `is_group`.
const SFrame = struct {
    tag: SFrameTag,
    node: SNode, // the block's own line
    nodes: std.ArrayListUnmanaged(SNode) = .{},
    names_base: usize = 0,
    last_field: bool = false,
    // body frames
    is_group: bool = false,
    sbody: ?*SBody = null,
    kinds: std.ArrayListUnmanaged(SKind) = .{},
    whens: std.ArrayListUnmanaged(SNode) = .{},
    in_whens: bool = false,
    common_when: bool = false,
    kind_names_base: usize = 0,
    grp: ?*Group = null,
};

const SName = struct { name: []const u8, pres: *SPres, depth: usize };

const SParser = struct {
    alloc: std.mem.Allocator,
    p: *Pack,
    diag: *Diag,
    frames: std.ArrayListUnmanaged(SFrame) = .{},
    names: std.ArrayListUnmanaged(SName) = .{},
    lineno: usize = 0,
    hdr: HeaderSeen = .{},

    const bd = E.@"bad-directive";

    fn top(self: *SParser) *SFrame {
        return &self.frames.items[self.frames.items.len - 1];
    }

    // The nearest enclosing message or group body.
    fn bodyFrame(self: *SParser) *SFrame {
        var i = self.frames.items.len;
        while (i > 0) {
            i -= 1;
            if (self.frames.items[i].tag == .body) return &self.frames.items[i];
        }
        unreachable;
    }

    // A failure of a line check (ruling 5b of 0.11, steps 1 to 10).
    fn lineErr(self: *SParser, e: anyerror, comptime fmt: []const u8, args: anytype) anyerror {
        self.diag.line_err = true;
        return self.err(e, fmt, args);
    }

    fn err(self: *SParser, e: anyerror, comptime fmt: []const u8, args: anytype) anyerror {
        const detail = std.fmt.allocPrint(self.alloc, fmt, args) catch "";
        return bad(self.diag, self.alloc, e, "line {d}: {s}", .{ self.lineno, detail });
    }

    // A wire line joins the open block; it ends the `when` lines of its kind.
    fn add(self: *SParser, n: SNode) !void {
        const f = self.top();
        try f.nodes.append(self.alloc, n);
        f.last_field = n.tag == .field;
        if (f.tag == .body) f.in_whens = false;
    }

    fn open(self: *SParser, tag: SFrameTag, n: SNode) !void {
        if (self.top().tag == .body) self.top().in_whens = false;
        self.top().last_field = false;
        try self.frames.append(self.alloc, .{ .tag = tag, .node = n, .names_base = self.names.items.len });
    }

    // The lines read so far in a body become its common lines, or the lines
    // of its last kind.
    fn closeKind(self: *SParser, f: *SFrame) !void {
        if (f.kinds.items.len == 0) {
            f.sbody.?.common = try f.nodes.toOwnedSlice(self.alloc);
        } else {
            const k = &f.kinds.items[f.kinds.items.len - 1];
            k.whens = try f.whens.toOwnedSlice(self.alloc);
            k.lines = try f.nodes.toOwnedSlice(self.alloc);
        }
    }

    fn closeBody(self: *SParser, f: *SFrame) !void {
        try self.closeKind(f);
        f.sbody.?.kinds = try f.kinds.toOwnedSlice(self.alloc);
        if (f.common_when and f.sbody.?.kinds.len == 0) {
            return bad(self.diag, self.alloc, bd, "a `when` line in a body with no `kind` line", .{});
        }
    }

    fn bitLen(self: *SParser, text: []const u8, what: []const u8, max: usize) !usize {
        const v = parseUnsigned(text) orelse
            return self.err(bd, "{s}: {s} is not a bit length (a sequential pack takes no positional locator)", .{ what, text });
        if (v < 1 or v > max) return self.err(bd, "{s}: the bit length {d} is not 1..{d}", .{ what, v, max });
        return @intCast(v);
    }

    fn line(self: *SParser, toks: []const []const u8) anyerror!void {
        const alloc = self.alloc;
        const p = self.p;
        const kw = toks[0];
        const is = struct {
            fn f(a: []const u8, b: []const u8) bool {
                return std.mem.eql(u8, a, b);
            }
        }.f;
        // ruling 5b of 0.11, steps 2 to 6
        try packLineChecks(alloc, toks, self.lineno, &self.hdr, self.diag);
        if (std.meta.stringToEnum(PackDir, kw)) |d| {
            if (d == .layout) {
                // `layout sequential` stands before every line that needs the wire
                if (self.hdr.wire_line) return self.err(bd, "layout sequential after a line it governs", .{});
            } else if (needsWire(d)) self.hdr.wire_line = true;
        }
        // header and table directives belong to the pack, not to a block
        // (ruling 24 of 0.8)
        if (self.frames.items.len > 1) {
            for ([_][]const u8{ "format", "version", "distribution", "source", "uses", "wire", "layout", "bit_order", "map", "typemap" }) |h| {
                if (is(kw, h)) return self.err(bd, "{s} inside a block", .{kw});
            }
        }
        if (is(kw, "format")) {
            if (toks.len != 2) return self.err(E.@"bad-directive", "format takes one argument", .{});
            p.format = toks[1];
        } else if (is(kw, "version")) {
            if (toks.len != 2) return self.err(E.@"bad-directive", "version takes one argument", .{});
            p.version = toks[1];
        } else if (is(kw, "wire")) {
            if (toks.len != 2 or !is(toks[1], "bits")) return self.err(bd, "a sequential pack is on the bits wire", .{});
        } else if (is(kw, "layout")) {
            if (toks.len != 2 or !is(toks[1], "sequential")) return self.err(bd, "layout is given twice, as sequential and as something else", .{});
        } else if (is(kw, "distribution")) {
            if (toks.len != 2) return self.err(E.@"bad-directive", "distribution takes one argument", .{});
            p.distribution = parseDist(toks[1]) catch |e| return self.err(e, "distribution {s} is not public or controlled", .{toks[1]});
        } else if (is(kw, "source")) {
            if (toks.len != 2) return self.err(E.@"bad-directive", "source takes one argument", .{});
            try p.sources.append(toks[1]);
        } else if (is(kw, "uses")) {
            if (toks.len != 2) return self.err(E.@"bad-directive", "uses takes one argument", .{});
            try p.uses.append(toks[1]);
        } else if (is(kw, "bit_order")) {
            if (toks.len != 2) return self.err(bd, "bit_order takes one argument", .{});
            if (is(toks[1], "msb")) {
                p.msb = true;
            } else if (is(toks[1], "lsb")) {
                p.msb = false;
            } else return self.err(bd, "bit_order {s} is not lsb or msb", .{toks[1]});
        } else if (is(kw, "word_bytes") or is(kw, "root")) {
            return self.err(bd, "{s} is not used in a sequential pack", .{kw});
        } else if (is(kw, "delimiter") or is(kw, "start") or is(kw, "checksum")) {
            return self.err(bd, "{s} is a directive of the text wire", .{kw});
        } else if (is(kw, "typemap")) {
            if (toks.len != 3) return self.err(E.@"bad-directive", "typemap takes two arguments", .{});
            try p.tm_nat2cot.put(toks[1], toks[2]);
            try p.tm_cot2nat.put(toks[2], toks[1]);
        } else if (is(kw, "map")) {
            if (toks.len != 4) return self.err(bd, "map takes a table, a native value and a model value", .{});
            const gop = try p.tables.getOrPut(toks[1]);
            if (!gop.found_existing) {
                const t = try alloc.create(Table);
                t.* = .{ .name = toks[1], .entries = std.ArrayList(TableEntry).init(alloc) };
                gop.value_ptr.* = t;
            }
            try gop.value_ptr.*.entries.append(.{ .native = toks[2], .model = toks[3] });
        } else if (is(kw, "kind")) {
            if (toks.len != 2) return self.err(bd, "kind takes one argument", .{});
            if (self.top().tag != .body) return self.err(bd, "kind inside a block", .{});
            const f = self.top();
            for (f.kinds.items) |k| {
                if (is(k.name, toks[1])) return self.err(E.@"duplicate-kind", "kind {s} is declared twice in one body", .{toks[1]});
            }
            try self.closeKind(f);
            if (f.kinds.items.len == 0) {
                f.kind_names_base = self.names.items.len;
            } else {
                // the presence names of the kind before are no longer visible
                self.names.shrinkRetainingCapacity(f.kind_names_base);
            }
            try f.kinds.append(alloc, .{ .name = toks[1] });
            f.in_whens = true;
            f.last_field = false;
        } else if (is(kw, "requires")) {
            const f = self.top();
            if (f.tag != .body or f.kinds.items.len == 0) return self.err(bd, "requires outside a kind", .{});
            if (toks.len < 2) return self.err(bd, "requires takes at least one key", .{});
            const k = &f.kinds.items[f.kinds.items.len - 1];
            for (toks[1..]) |key| {
                try k.requires.append(alloc, key);
                try p.key_uses.append(.{ .key = key, .tkind = null, .use = .requires });
            }
            f.last_field = false;
        } else if (is(kw, "default")) {
            if (toks.len != 3) return self.err(bd, "default takes a key and a value", .{});
            const f = self.bodyFrame();
            const d = Default{ .key = toks[1], .text = toks[2] };
            if (f.kinds.items.len == 0) {
                try f.sbody.?.defaults.append(alloc, d);
            } else {
                try f.kinds.items[f.kinds.items.len - 1].defaults.append(alloc, d);
            }
            try p.key_uses.append(.{ .key = toks[1], .tkind = null, .use = .default });
            self.top().last_field = false;
        } else if (is(kw, "when") or is(kw, "const")) {
            const is_when = is(kw, "when");
            if (toks.len != 3) return self.err(bd, "{s} takes a bit length and a value", .{kw});
            if (!locatorFormOk(.bits, true, toks[1], false)) return self.lineErr(E.@"bad-locator", "{s}: {s} is not a bit length", .{ kw, toks[1] });
            const len = try self.bitLen(toks[1], kw, 64);
            const v = parseUnsigned(toks[2]) orelse return self.err(bd, "{s}: the value {s} is not an unsigned decimal integer", .{ kw, toks[2] });
            if (!fitsBits(v, len)) return self.err(bd, "{s}: the value {d} does not fit {d} bits", .{ kw, v, len });
            const n = SNode{ .tag = if (is_when) .when else .constant, .lineno = self.lineno, .len = len, .value = v };
            if (!is_when) return self.add(n);
            const f = self.top();
            if (f.tag != .body) return self.err(bd, "when inside a block", .{});
            if (f.kinds.items.len == 0) {
                // before the first kind: a common `when`
                f.common_when = true;
                return self.add(n);
            }
            if (!f.in_whens) return self.err(bd, "when after another line of its kind", .{});
            try f.whens.append(alloc, n);
        } else if (is(kw, "field")) {
            if (toks.len < 4) return self.err(E.@"bad-directive", "field takes a key, a bit length and a transform", .{});
            const t = parseTransform(toks[3]) catch |e| switch (e) {
                error.@"unknown-transform" => return self.lineErr(e, "unknown transform {s}", .{toks[3]}),
                else => return self.lineErr(e, "the parameters of transform {s} are not valid", .{toks[3]}),
            };
            if (!locatorFormOk(.bits, true, toks[2], false)) return self.lineErr(E.@"bad-locator", "field {s}: {s} is not a bit length", .{ toks[1], toks[2] });
            if (!allDigits(toks[2])) return self.err(bd, "field {s}: {s} is not a bit length (a sequential pack takes no positional locator)", .{ toks[1], toks[2] });
            // the transform against the wire and the bit length against the
            // transform are checked after the file (ruling 5b of 0.11)
            const blen: usize = @intCast(@min(parseUnsigned(toks[2]) orelse (1 << 20), 1 << 20));
            var ln = Line{ .key = toks[1], .locator = toks[2], .transform = t, .lineno = self.lineno, .blen = blen };
            var oi: usize = 4;
            while (oi < toks.len) : (oi += 1) {
                const o = toks[oi];
                var again = false;
                if (is(o, "via")) {
                    oi += 1;
                    if (oi >= toks.len or toks[oi].len == 0) return self.lineErr(bd, "via takes a table name", .{});
                    again = ln.via_name.len > 0;
                    ln.via_name = toks[oi];
                } else if (is(o, "swap")) {
                    again = ln.swap;
                    ln.swap = true;
                } else if (is(o, "trim")) {
                    again = ln.trim;
                    ln.trim = true;
                } else if (is(o, "optional")) {
                    return self.err(bd, "the field option optional is not for a sequential pack", .{});
                } else if (is(o, "absent")) {
                    oi += 1;
                    if (oi >= toks.len) return self.lineErr(bd, "absent takes one or more values", .{});
                    again = ln.absent_raw != null;
                    ln.absent_raw = toks[oi];
                } else return self.lineErr(bd, "unknown field option {s}", .{o});
                if (again) return self.lineErr(bd, "field option {s} is repeated", .{o});
            }
            if (blen <= 64) {
                try parseAbsent(alloc, .bits, &ln, false, self.diag);
                ln.abs_checked = true;
            }
            try p.key_uses.append(.{ .key = toks[1], .tkind = t.kind, .via = ln.via_name, .grp = self.bodyFrame().grp });
            try self.add(.{ .tag = .field, .lineno = self.lineno, .ln = ln });
        } else if (is(kw, "also")) {
            // also <key> [via <table>], directly after a `field` line
            const f = self.top();
            if (!f.last_field) return self.err(bd, "also is not directly after a field line", .{});
            if (toks.len != 2 and !(toks.len == 4 and is(toks[2], "via") and toks[3].len > 0)) return self.err(bd, "also takes a key and an optional `via <table>`", .{});
            const fld = &f.nodes.items[f.nodes.items.len - 1];
            const via_name: []const u8 = if (toks.len == 4) toks[3] else "";
            try fld.also.append(alloc, .{ .key = toks[1], .via_name = via_name, .lineno = self.lineno });
            try p.key_uses.append(.{ .key = toks[1], .tkind = fld.ln.transform.kind, .via = via_name, .grp = self.bodyFrame().grp });
        } else if (is(kw, "pad")) {
            if (toks.len != 2) return self.err(bd, "pad takes a bit length", .{});
            try self.add(.{ .tag = .pad, .lineno = self.lineno, .len = try self.bitLen(toks[1], kw, 1 << 30) });
        } else if (is(kw, "align")) {
            if (toks.len != 2) return self.err(bd, "align takes a number of bits", .{});
            try self.add(.{ .tag = .align_, .lineno = self.lineno, .len = try self.bitLen(toks[1], kw, 1 << 30) });
        } else if (is(kw, "presence")) {
            if (toks.len != 3) return self.err(bd, "presence takes a name and a number of bits or `fx`", .{});
            const name = toks[1];
            if (name.len == 0 or name[0] == '!' or std.mem.indexOfScalar(u8, name, '.') != null) return self.err(bd, "presence name {s}", .{name});
            const depth = self.frames.items.len;
            for (self.names.items) |nm| {
                if (nm.depth == depth and is(nm.name, name)) return self.err(bd, "presence {s} is declared twice in one block", .{name});
            }
            const pr = try alloc.create(SPres);
            pr.* = .{ .name = name, .n = if (is(toks[2], "fx")) 0 else try self.bitLen(toks[2], kw, 64) };
            try self.names.append(alloc, .{ .name = name, .pres = pr, .depth = depth });
            try self.add(.{ .tag = .presence, .lineno = self.lineno, .pres = pr });
        } else if (is(kw, "if")) {
            if (toks.len < 2) return self.err(bd, "if takes at least one presence bit", .{});
            const conds = try alloc.alloc(SCond, toks.len - 1);
            for (toks[1..], 0..) |tk, ci| {
                const neg = tk.len > 0 and tk[0] == '!';
                const ref = if (neg) tk[1..] else tk;
                const dot = std.mem.lastIndexOfScalar(u8, ref, '.') orelse return self.err(bd, "if {s}: not `<name>.<i>`", .{tk});
                const idx = parseUnsigned(ref[dot + 1 ..]) orelse return self.err(bd, "if {s}: not `<name>.<i>`", .{tk});
                var found: ?*SPres = null;
                var ni = self.names.items.len;
                while (ni > 0) {
                    ni -= 1;
                    if (is(self.names.items[ni].name, ref[0..dot])) {
                        found = self.names.items[ni].pres;
                        break;
                    }
                }
                const pr = found orelse return self.err(bd, "if {s}: no presence of that name is visible here", .{tk});
                if (idx < 1 or idx > 4096 or (pr.n > 0 and idx > pr.n)) return self.err(bd, "if {s}: the bit is beyond the size of the presence", .{tk});
                const bit: usize = @intCast(idx);
                while (pr.named.items.len < bit) try pr.named.append(alloc, false);
                pr.named.items[bit - 1] = true;
                conds[ci] = .{ .pres = pr, .bit = bit, .neg = neg };
            }
            try self.open(.if_, .{ .tag = .if_, .lineno = self.lineno, .conds = conds });
        } else if (is(kw, "opt")) {
            if (toks.len != 1) return self.err(bd, "opt takes no argument", .{});
            try self.open(.opt, .{ .tag = .opt, .lineno = self.lineno });
        } else if (is(kw, "chain")) {
            if (toks.len != 1) return self.err(bd, "chain takes no argument", .{});
            try self.open(.chain, .{ .tag = .chain, .lineno = self.lineno });
        } else if (is(kw, "fx")) {
            if (toks.len != 1 or self.top().tag != .chain) return self.err(bd, "an fx line outside a chain", .{});
            try self.add(.{ .tag = .fx, .lineno = self.lineno });
        } else if (is(kw, "length")) {
            // length <len> [bytes|bits] [plus <n>] [whole]
            if (toks.len < 2) return self.err(bd, "length takes a bit length", .{});
            var n = SNode{ .tag = .length, .lineno = self.lineno, .len = try self.bitLen(toks[1], kw, 64) };
            var unit = false;
            var plus = false;
            var whole = false;
            var oi: usize = 2;
            while (oi < toks.len) : (oi += 1) {
                const o = toks[oi];
                if (is(o, "bytes") or is(o, "bits")) {
                    if (unit) return self.err(bd, "length: the unit is given twice", .{});
                    unit = true;
                    n.in_bits = is(o, "bits");
                } else if (is(o, "plus")) {
                    oi += 1;
                    if (plus or oi >= toks.len) return self.err(bd, "length: plus takes one number, once", .{});
                    plus = true;
                    n.plus = parseDecimalInt(toks[oi]) catch return self.err(bd, "length: plus {s} is not an integer", .{toks[oi]});
                    if (n.plus > 1 << 40 or n.plus < -(1 << 40)) return self.err(bd, "length: plus {s} is too large", .{toks[oi]});
                } else if (is(o, "whole")) {
                    if (whole) return self.err(bd, "length: whole is given twice", .{});
                    whole = true;
                } else return self.err(bd, "length: unknown word {s}", .{o});
            }
            if (whole) {
                if (n.in_bits) return self.err(bd, "length: `bits` with `whole`", .{});
                n.tag = .whole;
                return self.add(n);
            }
            try self.open(.length, n);
        } else if (is(kw, "group")) {
            // group <list> count <len> | while | more | fx
            var n = SNode{ .tag = .group, .lineno = self.lineno };
            if (toks.len == 4 and is(toks[2], "count")) {
                n.mode = .count;
                n.len = try self.bitLen(toks[3], "group count", 64);
            } else if (toks.len == 3 and is(toks[2], "while")) {
                n.mode = .while_;
            } else if (toks.len == 3 and is(toks[2], "more")) {
                n.mode = .more;
            } else if (toks.len == 3 and is(toks[2], "fx")) {
                n.mode = .fx;
            } else return self.err(bd, "a group of a sequential pack is `group <list> count <len>`, `while`, `more` or `fx`", .{});
            n.list = toks[1];
            const parent = self.bodyFrame().grp;
            const g = try alloc.create(Group);
            g.* = .{ .list = toks[1], .locator = "", .lineno = self.lineno, .parent = parent, .defaults = std.ArrayList(Default).init(alloc) };
            try p.key_uses.append(.{ .key = toks[1], .tkind = null, .use = .group, .grp = parent });
            const sb = try alloc.create(SBody);
            sb.* = .{};
            try self.open(.body, n);
            const f = self.top();
            f.is_group = true;
            f.sbody = sb;
            f.grp = g;
        } else if (is(kw, "end")) {
            if (toks.len != 1) return self.err(bd, "end takes no argument", .{});
            if (self.frames.items.len < 2) return self.err(bd, "end with no open block", .{});
            var f = self.frames.pop();
            self.names.shrinkRetainingCapacity(f.names_base);
            var n = f.node;
            if (f.tag == .body) {
                try self.closeBody(&f);
                n.gbody = f.sbody;
            } else {
                n.body = try f.nodes.toOwnedSlice(alloc);
            }
            try self.add(n);
        } else {
            return self.err(E.@"unknown-directive", "unknown directive {s}", .{kw});
        }
    }
};

// `via` names resolve once the whole file is read: a `map` line may follow
// the line that names its table.
fn seqResolveVia(alloc: std.mem.Allocator, p: *Pack, nodes: []SNode, diag: *Diag) anyerror!void {
    const bd = E.@"bad-directive";
    for (nodes) |*n| {
        if (n.tag == .field) {
            const t = n.ln.transform;
            if (kindCategory(t.kind) != .bits) return bad(diag, alloc, bd, "line {d}: the transform of {s} does not belong to wire bits", .{ n.lineno, n.ln.key });
            if (!bitsLenOk(t.kind, n.ln.blen)) return bad(diag, alloc, bd, "line {d}: bit length {d} is not allowed for the transform of {s}", .{ n.lineno, n.ln.blen, n.ln.key });
            if (n.ln.trim and t.kind != .ascii) return bad(diag, alloc, bd, "line {d}: trim is for the ascii transform", .{n.lineno});
            if (n.ln.swap and n.ln.blen % 8 != 0) return bad(diag, alloc, bd, "line {d}: swap needs a bit length that is a multiple of 8, not {d}", .{ n.lineno, n.ln.blen });
            if (!n.ln.abs_checked) try parseAbsent(alloc, .bits, &n.ln, false, diag);
            if (n.ln.via_name.len > 0) {
                n.ln.via = p.tables.get(n.ln.via_name) orelse
                    return bad(diag, alloc, bd, "line {d}: via {s} names a table with no map line", .{ n.lineno, n.ln.via_name });
            }
            for (n.also.items) |*a| {
                if (a.via_name.len == 0) continue;
                a.via = p.tables.get(a.via_name) orelse
                    return bad(diag, alloc, bd, "line {d}: via {s} names a table with no map line", .{ a.lineno, a.via_name });
            }
        }
        try seqResolveVia(alloc, p, n.body, diag);
        if (n.gbody) |b| {
            try seqResolveVia(alloc, p, b.common, diag);
            for (b.kinds) |*k| try seqResolveVia(alloc, p, k.lines, diag);
        }
    }
}

// One group of a sequential scope, with the `if` and `opt` blocks of the scope
// it sits in, outermost first.
const SGroupAt = struct { node: *const SNode, blocks: []const *const SNode };

fn seqCollectGroups(alloc: std.mem.Allocator, nodes: []const SNode, blocks: *std.ArrayListUnmanaged(*const SNode), out: *std.ArrayListUnmanaged(SGroupAt)) anyerror!void {
    for (nodes) |*n| {
        switch (n.tag) {
            .group => try out.append(alloc, .{ .node = n, .blocks = try alloc.dupe(*const SNode, blocks.items) }),
            .if_, .opt => {
                try blocks.append(alloc, n);
                try seqCollectGroups(alloc, n.body, blocks, out);
                _ = blocks.pop();
            },
            .chain, .length => try seqCollectGroups(alloc, n.body, blocks, out),
            else => {},
        }
    }
}

fn seqBlockHolds(blocks: []const *const SNode, b: *const SNode) bool {
    for (blocks) |x| if (x == b) return true;
    return false;
}

// Ruling 23 of 0.8: a list is mapped by two groups of one scope (the common
// lines plus one kind, or one group body likewise) only when the two groups
// sit in different `if` or `opt` blocks: each has such a block around it, and
// neither group's block encloses the other's (ruling 33).
fn seqCheckLists(alloc: std.mem.Allocator, b: *const SBody, diag: *Diag) anyerror!void {
    var blocks = std.ArrayListUnmanaged(*const SNode){};
    var common = std.ArrayListUnmanaged(SGroupAt){};
    try seqCollectGroups(alloc, b.common, &blocks, &common);
    var ki: usize = 0;
    while (ki == 0 or ki < b.kinds.len) : (ki += 1) {
        var all = std.ArrayListUnmanaged(SGroupAt){};
        try all.appendSlice(alloc, common.items);
        if (ki < b.kinds.len) try seqCollectGroups(alloc, b.kinds[ki].lines, &blocks, &all);
        for (all.items, 0..) |g, i| {
            for (all.items[0..i]) |f| {
                if (!std.mem.eql(u8, f.node.list, g.node.list)) continue;
                const apart = f.blocks.len > 0 and g.blocks.len > 0 and
                    !seqBlockHolds(g.blocks, f.blocks[f.blocks.len - 1]) and
                    !seqBlockHolds(f.blocks, g.blocks[g.blocks.len - 1]);
                if (!apart) {
                    return bad(diag, alloc, E.@"bad-directive", "line {d}: the list {s} is mapped by a second group of its scope (line {d}), and the two do not sit in different `if` or `opt` blocks", .{ g.node.lineno, g.node.list, f.node.lineno });
                }
            }
        }
        // each group body is a scope of its own
        for (all.items[if (ki == 0) 0 else common.items.len..]) |g| try seqCheckLists(alloc, g.node.gbody.?, diag);
    }
}

fn parseSeqPack(alloc: std.mem.Allocator, def_text: []const u8, diag: *Diag) anyerror!*Pack {
    const p = try newPack(alloc);
    p.wire = .bits;
    const root = try alloc.create(SBody);
    root.* = .{};
    var sp = SParser{ .alloc = alloc, .p = p, .diag = diag };
    var deferred: ?Deferred = null;
    try sp.frames.append(alloc, .{ .tag = .body, .node = .{ .tag = .group }, .sbody = root });
    var lines = std.mem.splitScalar(u8, def_text, '\n');
    var tokbuf = std.ArrayList([]const u8).init(alloc);
    while (lines.next()) |line| {
        sp.lineno += 1;
        tokenizeInto(&tokbuf, line) catch |err|
            return lineBad(diag, alloc, err, "line {d}: a quoted value has no closing quote", .{sp.lineno});
        if (tokbuf.items.len == 0) continue;
        // every cause not in steps 1 to 10 of ruling 5b of 0.11 is reported
        // after the file is read
        sp.line(tokbuf.items) catch |err| {
            if (err == error.OutOfMemory or diag.line_err) return err;
            if (deferred == null) deferred = .{ .err = err, .msg = diag.msg };
        };
    }
    try headerChecks(alloc, sp.hdr, diag);
    if (deferred) |d| {
        diag.msg = d.msg;
        return d.err;
    }
    if (sp.frames.items.len > 1) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: a block with no `end`", .{sp.top().node.lineno});
    }
    try sp.closeBody(&sp.frames.items[0]);
    setTableTypes(p);
    try seqResolveVia(alloc, p, root.common, diag);
    for (root.kinds) |*k| try seqResolveVia(alloc, p, k.lines, diag);
    try seqCheckLists(alloc, root, diag);
    p.seq = root;
    if (p.distribution == null) return bad(diag, alloc, E.@"missing-distribution", "the pack has no distribution line", .{});
    if (p.sources.items.len == 0) return bad(diag, alloc, E.@"missing-source", "the pack has no source line", .{});
    return p;
}

// The presence bits read, or computed, so far: innermost first.
const PEnv = struct { pres: *const SPres, bits: []const bool, parent: ?*const PEnv };

fn penvBit(env: ?*const PEnv, pres: *const SPres, bit: usize) bool {
    var e = env;
    while (e) |x| : (e = x.parent) {
        if (x.pres == pres) return bit <= x.bits.len and x.bits[bit - 1];
    }
    return false;
}

// An `if` block is read, and written, only when every bit it names is 1, and
// every bit it names with `!` is 0.
fn condsHold(env: ?*const PEnv, conds: []const SCond) bool {
    for (conds) |c| if (penvBit(env, c.pres, c.bit) == c.neg) return false;
    return true;
}

// The `default` values in scope: a kind's, then the common ones of its body.
const DS = struct {
    a: ?*const DMap = null,
    b: ?*const DMap = null,

    fn get(self: DS, key: []const u8) ?MV {
        if (self.a) |m| {
            if (m.get(key)) |v| return v;
        }
        if (self.b) |m| return m.get(key);
        return null;
    }
};

// The entity or item being decoded, and the keys a line failed on.
const SEnt = struct {
    e: *Entity,
    failed: std.ArrayListUnmanaged([]const u8) = .{},
};

const SDec = struct {
    alloc: std.mem.Allocator,
    p: *const Pack,
    buf: []const u8,
    diag: *Diag,
    pos: usize = 0,
    // the end of the input, or of the message a `length … whole` states:
    // reading beyond it is `malformed-wire`
    hard_end: usize,
    // inside a `length` block: the end of its extent
    soft_end: usize,
    in_extent: bool = false,
    // the first field that failed (`transform-decode`), reported at the end
    failed_msg: ?[]const u8 = null,

    const mw = E.@"malformed-wire";
    const Avail = enum { ok, absent };

    fn limit(self: *const SDec) usize {
        return if (self.in_extent) @min(self.soft_end, self.hard_end) else self.hard_end;
    }

    // The bits between the cursor and the limit; 0 when the cursor is at or
    // past it.
    fn left(self: *const SDec) usize {
        return self.limit() -| self.pos;
    }

    fn fits(self: *const SDec, len: usize) bool {
        return len <= self.left();
    }

    // May a line read `len` bits at the cursor? Inside a `length` extent a
    // line that starts at or after its end reads as absent, and one that
    // straddles it is `malformed-wire`, as is reading past the input.
    fn avail(self: *SDec, len: usize, what: []const u8) !Avail {
        if (self.in_extent) {
            if (self.pos >= self.soft_end) return .absent;
            if (!self.fits(len)) {
                return bad(self.diag, self.alloc, mw, "{s}: {d} bits at bit {d} run past the end of the length extent at bit {d}", .{ what, len, self.pos, self.soft_end });
            }
            return .ok;
        }
        if (!self.fits(len)) {
            return bad(self.diag, self.alloc, mw, "{s}: {d} bits at bit {d} run past the end of the message at bit {d}", .{ what, len, self.pos, self.hard_end });
        }
        return .ok;
    }

    // Like `avail`, where the line before said these bits follow.
    fn need(self: *SDec, len: usize, what: []const u8) !void {
        if (!self.fits(len)) {
            return bad(self.diag, self.alloc, mw, "{s}: {d} bits at bit {d} run past the end at bit {d}", .{ what, len, self.pos, self.limit() });
        }
    }

    // An indicator bit of a `while`, `more` or `fx` group: at or after the end
    // of a `length` extent it reads as 0 (ruling 21 of 0.8); past the end of
    // the input it is `malformed-wire`.
    fn indicator(self: *SDec, what: []const u8) !u64 {
        if (self.in_extent and self.pos >= self.soft_end) return 0;
        try self.need(1, what);
        return self.take(1);
    }

    fn take(self: *SDec, len: usize) u64 {
        const v = getBits(self.buf, self.p.msb, self.pos, len);
        self.pos += len;
        return v;
    }

    fn setKey(self: *SDec, se: *SEnt, key: []const u8, via: ?*const Table, via_name: []const u8, kty: KeyType, raw: MV) !void {
        if (se.e.fields.contains(key)) return; // the earliest line of a key wins
        var mv = raw;
        if (via) |t| {
            mv = tableDecode(t, mv, kty) catch
                return self.fieldFailed(try std.fmt.allocPrint(self.alloc, "field {s}: the table {s} has no entry for the value", .{ key, via_name }));
        }
        if (mv == .str and std.mem.eql(u8, key, "type")) {
            if (self.p.tm_nat2cot.get(mv.str)) |cot| mv = MV{ .str = cot };
        }
        try se.e.put(key, mv);
    }

    fn nodes(self: *SDec, list: []const SNode, se: *SEnt, env: *?*const PEnv) anyerror!void {
        for (list) |*n| try self.node(n, se, env);
    }

    fn block(self: *SDec, list: []const SNode, se: *SEnt, env: ?*const PEnv) anyerror!void {
        var inner = env;
        try self.nodes(list, se, &inner);
    }

    fn node(self: *SDec, n: *const SNode, se: *SEnt, env: *?*const PEnv) anyerror!void {
        const alloc = self.alloc;
        switch (n.tag) {
            .field => {
                const ln = &n.ln;
                if (try self.avail(ln.blen, ln.key) == .absent) return;
                const at = self.pos;
                self.pos += ln.blen;
                // a sentinel: neither the key nor an `also` key is set by this line
                if (ln.abs_set and absentInt(ln, bitsRaw(self.p, self.buf, at, ln))) return;
                const raw = bitsDecodeField(alloc, self.p, self.buf, at, ln) catch |err| switch (err) {
                    error.OutOfMemory => return err,
                    else => {
                        // forgiven when another line of the key succeeds
                        try se.failed.append(alloc, ln.key);
                        for (n.also.items) |a| try se.failed.append(alloc, a.key);
                        return;
                    },
                };
                try self.setKey(se, ln.key, ln.via, ln.via_name, ln.kty, raw);
                for (n.also.items) |a| try self.setKey(se, a.key, a.via, a.via_name, a.kty, raw);
            },
            .constant, .pad => {
                if (try self.avail(n.len, if (n.tag == .pad) "pad" else "const") == .absent) return;
                self.pos += n.len;
            },
            .align_ => {
                // stops at the end of the input or extent without error
                const r = self.pos % n.len;
                if (r != 0) self.pos += @min(n.len - r, self.left());
            },
            .when => {
                // a common `when`: it must hold for any message of the format
                if (!self.fits(n.len) or self.take(n.len) != n.value) {
                    return bad(self.diag, alloc, E.@"no-kind", "the common `when {d} {d}` does not hold", .{ n.len, n.value });
                }
            },
            .presence => {
                const pr = n.pres.?;
                var bits = std.ArrayList(bool).init(alloc);
                if (pr.n > 0) {
                    if (try self.avail(pr.n, pr.name) == .ok) {
                        for (0..pr.n) |_| try bits.append(self.take(1) == 1);
                    }
                } else if (try self.avail(8, pr.name) == .ok) {
                    // octets of 7 presence bits, each followed by an extension bit
                    while (true) {
                        for (0..7) |_| try bits.append(self.take(1) == 1);
                        if (self.take(1) == 0) break;
                        try self.need(8, pr.name);
                    }
                }
                // a bit that is 1 and that no `if` block names: the message
                // holds a part the pack does not describe
                for (bits.items, 0..) |b, i| {
                    if (b and (i >= pr.named.items.len or !pr.named.items[i])) {
                        return bad(self.diag, alloc, mw, "presence bit {s}.{d} is 1 and no `if` block names it", .{ pr.name, i + 1 });
                    }
                }
                const pe = try alloc.create(PEnv);
                pe.* = .{ .pres = pr, .bits = bits.items, .parent = env.* };
                env.* = pe;
            },
            .if_ => {
                if (condsHold(env.*, n.conds)) try self.block(n.body, se, env.*);
            },
            .opt => {
                if (try self.avail(1, "opt") == .absent) return;
                if (self.take(1) == 1) try self.block(n.body, se, env.*);
            },
            .chain => {
                var inner = env.*;
                for (n.body, 0..) |*c, j| {
                    if (c.tag != .fx) {
                        try self.node(c, se, &inner);
                        continue;
                    }
                    if (try self.avail(1, "fx") == .absent) break;
                    if (self.take(1) == 0) break; // a 0 bit ends the chain
                    if (j + 1 == n.body.len) {
                        return bad(self.diag, alloc, mw, "the last fx bit of a chain is 1", .{});
                    }
                }
            },
            .length => {
                if (try self.avail(n.len, "length") == .absent) return;
                const stated: i128 = self.take(n.len);
                const count = stated - n.plus;
                if (count < 0) return bad(self.diag, alloc, mw, "the stated length {d} is below its `plus {d}`", .{ stated, n.plus });
                const nbits = if (n.in_bits) count else count * 8;
                if (nbits > @as(i128, self.left())) {
                    return bad(self.diag, alloc, mw, "a length extent of {d} bits at bit {d} runs past the end at bit {d}", .{ nbits, self.pos, self.limit() });
                }
                const end = self.pos + @as(usize, @intCast(nbits));
                const save_end = self.soft_end;
                const save_in = self.in_extent;
                self.soft_end = end;
                self.in_extent = true;
                try self.block(n.body, se, env.*);
                // content of the extent no line read is skipped
                self.pos = end;
                self.soft_end = save_end;
                self.in_extent = save_in;
            },
            .whole => {
                if (try self.avail(n.len, "length") == .absent) return;
                const stated: i128 = self.take(n.len);
                const total = (stated - n.plus) * 8;
                if (total < @as(i128, self.pos)) return bad(self.diag, alloc, mw, "the stated length of the message is shorter than what was already read", .{});
                if (total > @as(i128, self.hard_end)) return bad(self.diag, alloc, mw, "the stated length of the message is {d} bits, the input holds {d}", .{ total, self.hard_end });
                self.hard_end = @intCast(total);
                if (!self.in_extent) self.soft_end = self.hard_end;
            },
            .group => try self.group(n, se, env.*),
            .fx => unreachable, // an `fx` line is a line of a chain
        }
    }

    fn group(self: *SDec, n: *const SNode, se: *SEnt, env: ?*const PEnv) anyerror!void {
        var items = ItemList{ .alloc = self.alloc };
        switch (n.mode) {
            .count => {
                if (try self.avail(n.len, n.list) == .absent) return;
                const cnt = self.take(n.len);
                // the count against the limit, less the items of the list it
                // replaces (rulings 7d and 7g of 0.11), before any item is read
                try self.replaceList(se, n.list);
                try takeItems(self.diag, self.alloc, cnt, n.list);
                // a count larger than the bits left, before any item is read
                if (cnt > self.left()) {
                    return bad(self.diag, self.alloc, mw, "group {s}: a count of {d} is larger than the {d} bits left", .{ n.list, cnt, self.left() });
                }
                for (0..@as(usize, @intCast(cnt))) |_| try self.item(n, &items, env);
            },
            .while_ => {
                if (try self.avail(1, n.list) == .absent) return;
                try self.replaceList(se, n.list);
                while (true) {
                    if (try self.indicator(n.list) == 0) break;
                    try self.item(n, &items, env);
                }
            },
            .more => {
                if (try self.avail(1, n.list) == .absent) return;
                try self.replaceList(se, n.list);
                while (true) {
                    const more = try self.indicator(n.list);
                    try self.item(n, &items, env);
                    if (more == 0) break;
                }
            },
            .fx => {
                if (self.in_extent and self.pos >= self.soft_end) return;
                try self.replaceList(se, n.list);
                while (true) {
                    try self.item(n, &items, env);
                    if (try self.indicator(n.list) == 0) break;
                }
            },
        }
        // two groups of one list both on the wire: the later group's items
        // are kept (ruling 33 of 0.8)
        try se.e.putList(n.list, try items.finish());
    }

    // A later group of a list the entity holds replaces its items (ruling 33
    // of 0.8): they are no longer counted (ruling 7g of 0.11).
    fn replaceList(self: *SDec, se: *SEnt, list: []const u8) !void {
        if (se.e.lists.get(list)) |old| self.diag.held -= itemsHeld(old);
    }

    fn item(self: *SDec, n: *const SNode, items: *ItemList, env: ?*const PEnv) anyerror!void {
        // a counted group took its items before the first was read
        if (n.mode != .count) try takeItems(self.diag, self.alloc, 1, n.list);
        var it = Entity.init(self.alloc);
        var sit = SEnt{ .e = &it };
        try self.body(n.gbody.?, &sit, env);
        try items.append(it);
    }

    // A message, or one item: the common lines; then the first kind whose
    // `when` lines, read where the common lines ended, all hold; then its
    // lines.
    fn body(self: *SDec, b: *const SBody, se: *SEnt, env_in: ?*const PEnv) anyerror!void {
        var env = env_in;
        try self.nodes(b.common, se, &env);
        if (b.kinds.len > 0) {
            var sel: ?*const SKind = null;
            for (b.kinds) |*k| {
                const save = self.pos;
                var ok = true;
                for (k.whens) |*w| {
                    // a `when` any of whose bits lies beyond the input does not hold
                    if (!self.fits(w.len) or self.take(w.len) != w.value) {
                        ok = false;
                        break;
                    }
                }
                if (ok) {
                    sel = k;
                    break;
                }
                self.pos = save;
            }
            const k = sel orelse return bad(self.diag, self.alloc, E.@"no-kind", "no kind's `when` lines all hold at bit {d}", .{self.pos});
            se.e.kind_fmt = self.p.format;
            se.e.kind_name = k.name;
            try self.nodes(k.lines, se, &env);
        }
        for (se.failed.items) |key| {
            if (!se.e.fields.contains(key)) return self.fieldFailed(try std.fmt.allocPrint(self.alloc, "failed fields: {s}", .{key}));
        }
    }

    // A field that fails is reported when the message has been read: going
    // over the limit on list items, later in the message too, wins over it
    // (ruling 7f of 0.11). The first such failure is kept.
    fn fieldFailed(self: *SDec, msg: []const u8) void {
        if (self.failed_msg == null) self.failed_msg = msg;
    }
};

fn seqDecode(alloc: std.mem.Allocator, p: *const Pack, bytes: []const u8, diag: *Diag) anyerror!Entity {
    const buf = hexDecode(alloc, bytes) catch |err| return bad(diag, alloc, err, "the input is not hex of even length", .{});
    var d = SDec{ .alloc = alloc, .p = p, .buf = buf, .diag = diag, .hard_end = buf.len * 8, .soft_end = buf.len * 8 };
    var e = Entity.init(alloc);
    var se = SEnt{ .e = &e };
    try d.body(p.seq.?, &se, null);
    if (d.failed_msg) |m| return bad(diag, alloc, E.@"transform-decode", "{s}", .{m});
    return e;
}

const SWhole = struct { at: usize, len: usize, plus: i64 };

// The encoder lays out a scope in two passes: the presence bits and `fx` bits
// are computed from the entity (`scan`, `hasContent`) before they are written.
const SEnc = struct {
    alloc: std.mem.Allocator,
    p: *const Pack,
    diag: *Diag,
    out: std.ArrayList(u8), // zero beyond the cursor
    pos: usize = 0,
    wholes: std.ArrayListUnmanaged(SWhole) = .{},

    const te = E.@"transform-encode";

    fn ensure(self: *SEnc, nbits: usize) !void {
        const nb = (nbits + 7) / 8;
        if (nb > self.out.items.len) try self.out.appendNTimes(0, nb - self.out.items.len);
    }

    fn put(self: *SEnc, len: usize, value: u64) !void {
        try self.ensure(self.pos + len);
        setBits(self.out.items, self.p.msb, self.pos, len, value);
        self.pos += len;
    }

    fn zeros(self: *SEnc, len: usize) !void {
        try self.ensure(self.pos + len);
        self.pos += len;
    }

    // Encode selects the kind the entity or item recorded for this format,
    // else the first kind whose every `requires` key is present.
    // An item's recorded kind selects only when it names this format and a
    // kind the group has; otherwise the item selects by `requires` (ruling
    // 26 of 0.8).
    fn selectKind(self: *SEnc, b: *const SBody, ent: *const Entity, is_item: bool) anyerror!?*const SKind {
        if (b.kinds.len == 0) return null;
        if (ent.kind_fmt) |kf| {
            if (std.mem.eql(u8, kf, self.p.format)) {
                for (b.kinds) |*k| if (std.mem.eql(u8, k.name, ent.kind_name)) return k;
                if (!is_item) return bad(self.diag, self.alloc, E.@"no-kind", "the entity records kind {s}, which the body does not have", .{ent.kind_name});
            }
        }
        for (b.kinds) |*k| {
            var all = true;
            for (k.requires.items) |key| {
                if (!ent.has(key)) {
                    all = false;
                    break;
                }
            }
            if (all) return k;
        }
        return bad(self.diag, self.alloc, E.@"no-kind", "the entity has the `requires` keys of no kind", .{});
    }

    // The value a field writes: that of the earliest of its keys that the
    // entity holds; when it holds none, the default of the earliest key that
    // has one (ruling 16 of 0.8).
    fn fieldValue(self: *SEnc, n: *const SNode, ent: *const Entity, ds: DS) !?MV {
        const ln = &n.ln;
        const wire_ty = yields(ln.transform.kind);
        const nkeys = n.also.items.len + 1;
        var i: usize = 0;
        while (i < 2 * nkeys) : (i += 1) {
            const j = i % nkeys;
            const key = if (j == 0) ln.key else n.also.items[j - 1].key;
            const via = if (j == 0) ln.via else n.also.items[j - 1].via;
            var mv = (if (i < nkeys) ent.get(key) else ds.get(key)) orelse continue;
            if (mv == .str and std.mem.eql(u8, key, "type")) {
                if (self.p.tm_cot2nat.get(mv.str)) |nat| mv = MV{ .str = nat };
            }
            if (via) |t| {
                mv = tableEncode(t, mv, wire_ty) catch |err|
                    return bad(self.diag, self.alloc, err, "field {s}: the table has no entry for the value", .{key});
            }
            return mv;
        }
        return null;
    }

    fn keyPresent(n: *const SNode, ent: *const Entity, ds: DS) bool {
        if (ent.fields.contains(n.ln.key) or ds.get(n.ln.key) != null) return true;
        for (n.also.items) |a| if (ent.fields.contains(a.key) or ds.get(a.key) != null) return true;
        return false;
    }

    // Would the lines write a present key, a non-empty list, or a nested
    // presence that is not all zero?
    fn hasContent(self: *SEnc, list: []const SNode, ent: *const Entity, ds: DS) anyerror!bool {
        for (list) |*n| {
            switch (n.tag) {
                .field => if (keyPresent(n, ent, ds)) return true,
                .group => {
                    if (ent.lists.get(n.list)) |items| {
                        if (items.len > 0) return true;
                    }
                },
                .if_, .opt, .chain, .length => if (try self.hasContent(n.body, ent, ds)) return true,
                else => {},
            }
        }
        return false;
    }

    fn setBit(self: *SEnc, bits: *std.ArrayList(bool), bit: usize) !void {
        _ = self;
        while (bits.items.len < bit) try bits.append(false);
        bits.items[bit - 1] = true;
    }

    // The bits of `pres` the lines set: every bit an `if` block names without
    // `!`, when the block has content. A group is searched item by item, so
    // any item with the content sets a bit of a presence outside the group.
    fn scan(self: *SEnc, pres: *const SPres, list: []const SNode, ent: *const Entity, ds: DS, bits: *std.ArrayList(bool)) anyerror!void {
        for (list) |*n| {
            switch (n.tag) {
                .if_ => {
                    var names = false;
                    for (n.conds) |c| {
                        if (c.pres == pres and !c.neg) names = true;
                    }
                    if (names and try self.hasContent(n.body, ent, ds)) {
                        for (n.conds) |c| {
                            if (c.pres == pres and !c.neg) try self.setBit(bits, c.bit);
                        }
                    }
                    try self.scan(pres, n.body, ent, ds, bits);
                },
                .opt, .chain, .length => try self.scan(pres, n.body, ent, ds, bits),
                .group => {
                    const items = ent.lists.get(n.list) orelse continue;
                    const b = n.gbody.?;
                    for (items) |*it| {
                        // a block that is not written may hold an item no
                        // kind takes: its common lines are searched
                        const k = self.selectKind(b, it, true) catch |err| switch (err) {
                            E.@"no-kind" => null,
                            else => return err,
                        };
                        const ids = DS{ .a = if (k) |kk| &kk.dmap else null, .b = &b.dmap };
                        try self.scan(pres, b.common, it, ids, bits);
                        if (k) |kk| try self.scan(pres, kk.lines, it, ids, bits);
                    }
                },
                else => {},
            }
        }
    }

    fn body(self: *SEnc, b: *const SBody, ent: *const Entity, env_in: ?*const PEnv, is_item: bool) anyerror!void {
        const k = try self.selectKind(b, ent, is_item);
        const ds = DS{ .a = if (k) |kk| &kk.dmap else null, .b = &b.dmap };
        var env = env_in;
        const tail: []const SNode = if (k) |kk| kk.lines else &.{};
        try self.nodes(b.common, tail, ent, ds, &env);
        if (k) |kk| {
            for (kk.whens) |*w| try self.put(w.len, w.value);
            try self.nodes(kk.lines, &.{}, ent, ds, &env);
        }
    }

    // `tail`: the lines that follow `list` in the same block (the selected
    // kind's lines, while the common lines are written).
    fn nodes(self: *SEnc, list: []const SNode, tail: []const SNode, ent: *const Entity, ds: DS, env: *?*const PEnv) anyerror!void {
        for (list, 0..) |*n, i| try self.node(n, list[i + 1 ..], tail, ent, ds, env);
    }

    fn block(self: *SEnc, list: []const SNode, ent: *const Entity, ds: DS, env: ?*const PEnv) anyerror!void {
        var inner = env;
        try self.nodes(list, &.{}, ent, ds, &inner);
    }

    fn node(self: *SEnc, n: *const SNode, rest: []const SNode, tail: []const SNode, ent: *const Entity, ds: DS, env: *?*const PEnv) anyerror!void {
        const alloc = self.alloc;
        switch (n.tag) {
            .field => {
                const ln = &n.ln;
                try self.ensure(self.pos + ln.blen);
                // an absent key writes zero bits, or with `absent` its first
                // sentinel (Version 0.9), which is not content (ruling 4)
                if (try self.fieldValue(n, ent, ds)) |mv| {
                    bitsWriteField(alloc, self.p, self.out.items, self.pos, ln, mv) catch |err|
                        return bad(self.diag, alloc, err, "field {s}: the value does not encode in {d} bits", .{ ln.key, ln.blen });
                } else if (ln.abs_set) {
                    bitsWriteRaw(self.p, self.out.items, self.pos, ln, ln.abs_ints[0]);
                }
                self.pos += ln.blen;
            },
            .constant, .when => try self.put(n.len, n.value),
            .pad => try self.zeros(n.len),
            .align_ => {
                const r = self.pos % n.len;
                if (r != 0) try self.zeros(n.len - r);
            },
            .presence => {
                const pr = n.pres.?;
                var bits = std.ArrayList(bool).init(alloc);
                try self.scan(pr, rest, ent, ds, &bits);
                try self.scan(pr, tail, ent, ds, &bits);
                if (pr.n > 0) {
                    while (bits.items.len < pr.n) try bits.append(false);
                    for (bits.items[0..pr.n]) |b| try self.put(1, @intFromBool(b));
                } else {
                    // trailing octets that are all zero are not written, and
                    // at least one octet is
                    var last: usize = 0;
                    for (bits.items, 0..) |b, i| {
                        if (b) last = i + 1;
                    }
                    const noct = @max(1, (last + 6) / 7);
                    while (bits.items.len < noct * 7) try bits.append(false);
                    for (0..noct) |o| {
                        for (bits.items[o * 7 .. o * 7 + 7]) |b| try self.put(1, @intFromBool(b));
                        try self.put(1, @intFromBool(o + 1 < noct));
                    }
                }
                const pe = try alloc.create(PEnv);
                pe.* = .{ .pres = pr, .bits = bits.items, .parent = env.* };
                env.* = pe;
            },
            .if_ => {
                if (condsHold(env.*, n.conds)) try self.block(n.body, ent, ds, env.*);
            },
            .opt => {
                const has = try self.hasContent(n.body, ent, ds);
                try self.put(1, @intFromBool(has));
                if (has) try self.block(n.body, ent, ds, env.*);
            },
            .chain => {
                var inner = env.*;
                for (n.body, 0..) |*c, j| {
                    if (c.tag != .fx) {
                        try self.node(c, n.body[j + 1 ..], &.{}, ent, ds, &inner);
                        continue;
                    }
                    // 1 when any line after it in the chain would write a
                    // present key; the bit of a last `fx` line is 0
                    const more = try self.hasContent(n.body[j + 1 ..], ent, ds);
                    try self.put(1, @intFromBool(more));
                    if (!more) break;
                }
            },
            .length => {
                // the block, then the length
                const lpos = self.pos;
                try self.zeros(n.len);
                const start = self.pos;
                try self.block(n.body, ent, ds, env.*);
                if (!n.in_bits) {
                    const r = (self.pos - start) % 8;
                    if (r != 0) try self.zeros(8 - r);
                }
                const size = self.pos - start;
                const stated: i128 = @as(i128, if (n.in_bits) size else size / 8) + n.plus;
                if (stated < 0 or stated > std.math.maxInt(u64) or !fitsBits(@intCast(stated), n.len)) {
                    return bad(self.diag, alloc, te, "the length {d} does not fit its {d} bits", .{ stated, n.len });
                }
                setBits(self.out.items, self.p.msb, lpos, n.len, @intCast(stated));
            },
            .whole => {
                try self.wholes.append(alloc, .{ .at = self.pos, .len = n.len, .plus = n.plus });
                try self.zeros(n.len);
            },
            .group => {
                const items: []const Entity = ent.lists.get(n.list) orelse &.{};
                const b = n.gbody.?;
                switch (n.mode) {
                    .count => {
                        if (!fitsBits(items.len, n.len)) {
                            return bad(self.diag, alloc, te, "group {s}: {d} items do not fit the {d} bits of the count", .{ n.list, items.len, n.len });
                        }
                        try self.put(n.len, items.len);
                        for (items) |*it| try self.body(b, it, env.*, true);
                    },
                    .while_ => {
                        for (items) |*it| {
                            try self.put(1, 1);
                            try self.body(b, it, env.*, true);
                        }
                        try self.put(1, 0);
                    },
                    .more, .fx => {
                        // a list has at least one item on the wire
                        if (items.len == 0) {
                            return bad(self.diag, alloc, te, "group {s}: the list is absent or empty, and the wire holds at least one item", .{n.list});
                        }
                        for (items, 0..) |*it, i| {
                            const more = @intFromBool(i + 1 < items.len);
                            if (n.mode == .more) try self.put(1, more);
                            try self.body(b, it, env.*, true);
                            if (n.mode == .fx) try self.put(1, more);
                        }
                    },
                }
            },
            .fx => unreachable, // an `fx` line is a line of a chain
        }
    }
};

fn seqEncode(alloc: std.mem.Allocator, p: *const Pack, e: *const Entity, diag: *Diag) anyerror![]u8 {
    var enc = SEnc{ .alloc = alloc, .p = p, .diag = diag, .out = std.ArrayList(u8).init(alloc) };
    try enc.body(p.seq.?, e, null, false);
    // a message is a whole number of bytes; `length … whole` holds that
    // number plus n
    const nbytes = enc.out.items.len;
    for (enc.wholes.items) |w| {
        const stated: i128 = @as(i128, nbytes) + w.plus;
        if (stated < 0 or stated > std.math.maxInt(u64) or !fitsBits(@intCast(stated), w.len)) {
            return bad(diag, alloc, E.@"transform-encode", "the message length {d} does not fit its {d} bits", .{ stated, w.len });
        }
        setBits(enc.out.items, p.msb, w.at, w.len, @intCast(stated));
    }
    return hexEncode(alloc, enc.out.items);
}

// ---------------------------------------------------------------------------
// Harness
// ---------------------------------------------------------------------------

fn strLess(_: void, a: []const u8, b: []const u8) bool {
    return std.mem.lessThan(u8, a, b);
}

fn sortedNames(alloc: std.mem.Allocator, dir_path: []const u8, want: std.fs.Dir.Entry.Kind, suffix: []const u8) !?[]const []const u8 {
    var dir = std.fs.cwd().openDir(dir_path, .{ .iterate = true }) catch return null;
    defer dir.close();
    var names = std.ArrayList([]const u8).init(alloc);
    var it = dir.iterate();
    while (try it.next()) |entry| {
        if (entry.kind != want) continue;
        if (!std.mem.endsWith(u8, entry.name, suffix)) continue;
        try names.append(try alloc.dupe(u8, entry.name));
    }
    std.mem.sort([]const u8, names.items, {}, strLess);
    return try names.toOwnedSlice();
}

// Load every pack under `packs_dir` (a directory holding a pack.def), in byte
// order of directory name. Returns the directory names of the loaded packs.
fn loadAllPacks(eng: *Engine, packs_dir: []const u8) ![]const []const u8 {
    const alloc = eng.alloc;
    var dirs = std.ArrayList([]const u8).init(alloc);
    const names = (try sortedNames(alloc, packs_dir, .directory, "")) orelse return error.FileNotFound;
    for (names) |name| {
        const def_path = try std.fmt.allocPrint(alloc, "{s}/{s}/pack.def", .{ packs_dir, name });
        const def_text = std.fs.cwd().readFileAlloc(alloc, def_path, max_file) catch |err| switch (err) {
            error.FileNotFound => continue,
            else => return err,
        };
        _ = eng.loadPack(def_text) catch |err| {
            eng.last_error = try std.fmt.allocPrint(alloc, "{s} ({s})", .{ eng.last_error, def_path });
            return err;
        };
        try dirs.append(name);
    }
    return dirs.toOwnedSlice();
}

fn getStr(obj: std.json.ObjectMap, key: []const u8) ?[]const u8 {
    if (obj.get(key)) |v| {
        if (v == .string) return v.string;
    }
    return null;
}

// Does the message begin with the error kind and a colon?
fn beginsWithKind(msg: []const u8, kind: []const u8) bool {
    return std.mem.startsWith(u8, msg, kind) and msg.len > kind.len and msg[kind.len] == ':';
}

// Are the `from` and `to` formats of a vector both loaded? A vector that does
// not parse counts as loaded, so that `runVector` reports it.
// A format that is not a directory under the packs directory is not left
// out: the vector pins `unknown-format` and is run.
fn vectorFormatsLoaded(eng: *Engine, packs_dir: []const u8, text: []const u8) bool {
    const parsed = std.json.parseFromSliceLeaky(JValue, eng.scratch, text, .{}) catch return true;
    if (parsed != .object) return true;
    for ([_][]const u8{ "from", "to" }) |k| {
        const fmt = getStr(parsed.object, k) orelse return true;
        if (eng.findPack(fmt) != null) continue;
        const path = std.fmt.allocPrint(eng.scratch, "{s}/{s}", .{ packs_dir, fmt }) catch return true;
        var d = std.fs.cwd().openDir(path, .{}) catch continue;
        d.close();
        return false;
    }
    return true;
}

// Run one capability vector (ruling 6 of 0.11). null: it passes.
fn runCapabilityVector(eng: *Engine, text: []const u8) !?[]const u8 {
    const alloc = eng.scratch;
    const parsed = std.json.parseFromSliceLeaky(JValue, alloc, text, .{}) catch return "the vector is not JSON";
    if (parsed != .object) return "the vector is not a JSON object";
    const obj = parsed.object;
    const from = getStr(obj, "from") orelse return "no `from`";
    const to = getStr(obj, "to") orelse return "no `to`";
    const grade = getStr(obj, "grade") orelse return "no `grade`";
    const cap = eng.capability(from, to) catch |err| {
        if (err == error.OutOfMemory) return err;
        return try std.fmt.allocPrint(alloc, "capability failed: {s}", .{eng.last_error});
    };
    if (!std.mem.eql(u8, cap.grade, grade)) return try std.fmt.allocPrint(alloc, "grade: expected {s}, got {s}", .{ grade, cap.grade });
    const pairs = [_]struct { name: []const u8, got: []const []const u8 }{
        .{ .name = "carried", .got = cap.carried },
        .{ .name = "dropped", .got = cap.dropped },
    };
    for (pairs) |pr| {
        const want = obj.get(pr.name) orelse return try std.fmt.allocPrint(alloc, "no `{s}`", .{pr.name});
        if (want != .array) return try std.fmt.allocPrint(alloc, "`{s}` is not an array", .{pr.name});
        var same = want.array.items.len == pr.got.len;
        if (same) for (want.array.items, pr.got) |w, g| {
            if (w != .string or !std.mem.eql(u8, w.string, g)) same = false;
        };
        if (!same) {
            var buf = std.ArrayList(u8).init(alloc);
            for (pr.got, 0..) |g, i| {
                if (i > 0) try buf.appendSlice(", ");
                try buf.appendSlice(g);
            }
            return try std.fmt.allocPrint(alloc, "{s}: got [{s}]", .{ pr.name, buf.items });
        }
    }
    return null;
}

// Run one conversion vector. Returns null on pass, else why it failed.
// Everything is allocated from `eng.scratch`.
fn runVector(eng: *Engine, text: []const u8) !?[]const u8 {
    const alloc = eng.scratch;
    const parsed = std.json.parseFromSliceLeaky(JValue, alloc, text, .{}) catch return "the vector is not JSON";
    if (parsed != .object) return "the vector is not a JSON object";
    const vobj = parsed.object;
    const from_fmt = getStr(vobj, "from") orelse return "no `from`";
    const to_fmt = getStr(vobj, "to") orelse return "no `to`";
    const input = getStr(vobj, "input") orelse return "no `input`";
    const expect = getStr(vobj, "expect");
    const expect_error = getStr(vobj, "expect_error");
    if (expect == null and expect_error == null) return "neither `expect` nor `expect_error`";
    if (expect != null and expect_error != null) return "both `expect` and `expect_error`";
    // `max_items` (Version 0.11): the limit on list items for this vector
    eng.max_items = default_max_items;
    if (vobj.get("max_items")) |mi| {
        if (mi != .integer or mi.integer < 0) return "invalid vector: `max_items` is not an integer of 0 or more";
        eng.max_items = @intCast(mi.integer);
    }
    defer eng.max_items = default_max_items;
    // a `model` value its grammar refuses makes the vector invalid (ruling
    // 2c of 0.11)
    if (vobj.get("model")) |mv0| {
        if (mv0 == .object) {
            var vit = mv0.object.iterator();
            while (vit.next()) |me| {
                if (me.value_ptr.* != .string) continue;
                if (try modelValueInvalid(eng, me.key_ptr.*, me.value_ptr.*.string)) |why| return why;
            }
        }
    }

    // the caller-supplied keys, values in string form
    var context: ?[]const KV = null;
    if (vobj.get("context")) |cv| {
        if (cv != .object) return "`context` is not an object";
        var kvs = std.ArrayList(KV).init(alloc);
        var cit = cv.object.iterator();
        while (cit.next()) |ce| {
            if (ce.value_ptr.* != .string) return try std.fmt.allocPrint(alloc, "context key {s}: the value is not a string", .{ce.key_ptr.*});
            try kvs.append(.{ .key = ce.key_ptr.*, .value = ce.value_ptr.*.string });
        }
        context = kvs.items;
    }

    // 1. convert(from, to, input[, context])
    if (eng.convert(from_fmt, to_fmt, input, context)) |got| {
        if (expect_error) |want| {
            return try std.fmt.allocPrint(alloc, "expected error {s}, convert returned: {s}", .{ want, clip(got) });
        }
        if (!std.mem.eql(u8, got, expect.?)) {
            return try std.fmt.allocPrint(alloc, "convert mismatch{s}\n   expected: {s}\n   got:      {s}", .{ try diffNote(alloc, expect.?, got), clip(expect.?), clip(got) });
        }
    } else |err| {
        if (err == error.OutOfMemory) return err;
        const want = expect_error orelse
            return try std.fmt.allocPrint(alloc, "convert failed: {s}", .{clip(eng.last_error)});
        if (!std.mem.eql(u8, @errorName(err), want) or !beginsWithKind(eng.last_error, want)) {
            return try std.fmt.allocPrint(alloc, "expected error {s}, got: {s}", .{ want, clip(eng.last_error) });
        }
    }

    // 2. model: decode(from, input) has each listed key; "@kind" is the kind
    // name. 3. With "@complete": true the checks run on the entity as convert
    // hands it to the encoder: the context filled in, the derivations applied.
    const mv = vobj.get("model") orelse return null;
    if (mv != .object) return "`model` is not an object";
    var completed = false;
    if (mv.object.get("@complete")) |cv| {
        if (cv != .bool) return "`@complete` is not a boolean";
        completed = cv.bool;
    }
    var ent = eng.decode(from_fmt, input) catch |err| {
        if (err == error.OutOfMemory) return err;
        return try std.fmt.allocPrint(alloc, "model check: decode failed: {s}", .{clip(eng.last_error)});
    };
    if (completed) {
        if (context) |c| {
            eng.fillContext(&ent, c) catch |err| {
                if (err == error.OutOfMemory) return err;
                return try std.fmt.allocPrint(alloc, "model check: context refused: {s}", .{clip(eng.last_error)});
            };
        }
        try eng.complete(&ent);
    }
    // "@absent" (Version 0.9): keys the entity must not have. A listed key
    // that is also a member of `model` makes the vector invalid.
    if (mv.object.get("@absent")) |av| {
        if (av != .array) return "`@absent` is not an array";
        for (av.array.items) |a| {
            if (a != .string) return "an `@absent` entry is not a string";
            if (mv.object.contains(a.string)) {
                return try std.fmt.allocPrint(alloc, "invalid vector: {s} is in `@absent` and is a member of `model`", .{a.string});
            }
        }
        for (av.array.items) |a| {
            if (try checkAbsentKey(alloc, &ent, a.string)) |why| return why;
        }
    }
    var mit = mv.object.iterator();
    while (mit.next()) |me| {
        const key = me.key_ptr.*;
        if (std.mem.eql(u8, key, "@complete") or std.mem.eql(u8, key, "@absent")) continue;
        if (me.value_ptr.* != .string) return try std.fmt.allocPrint(alloc, "model key {s}: the expected value is not a string", .{key});
        const exp = me.value_ptr.*.string;
        if (std.mem.eql(u8, key, "@kind")) {
            const kf = ent.kind_fmt orelse
                return try std.fmt.allocPrint(alloc, "@kind: expected {s}, the entity records no kind", .{exp});
            if (!std.mem.eql(u8, kf, from_fmt) or !std.mem.eql(u8, ent.kind_name, exp)) {
                return try std.fmt.allocPrint(alloc, "@kind: expected {s}, got ({s}, {s})", .{ exp, kf, ent.kind_name });
            }
            continue;
        }
        if (try checkModelKey(alloc, &ent, key, exp, completed)) |why| return why;
    }
    return null;
}

// Ruling 2c of 0.11: a `model` member named by a model key or an item path
// `<list>[<i>].<key>` is read as that key's declared type; `"<list>.#"` is an
// unsigned decimal integer or `absent`; the `@` members are not numbers.
// null: the value is valid.
fn modelValueInvalid(eng: *const Engine, key: []const u8, val: []const u8) !?[]const u8 {
    const alloc = eng.scratch;
    var rest = key;
    while (std.mem.indexOfScalar(u8, rest, '[')) |open| {
        const close = std.mem.indexOfScalarPos(u8, rest, open, ']') orelse return null;
        if (close + 2 > rest.len) return null;
        rest = rest[close + 2 ..];
    }
    if (rest.len > 0 and rest[0] == '@') return null;
    if (std.mem.endsWith(u8, rest, ".#")) {
        if (std.mem.eql(u8, val, "absent") or parseUnsigned(val) != null) return null;
        return try std.fmt.allocPrint(alloc, "invalid vector: model {s}: {s} is not a count or `absent`", .{ key, clip(val) });
    }
    const ty = eng.keyType(rest) orelse return null;
    const ok = switch (ty) {
        .string => true,
        .int => !std.meta.isError(parseDecimalInt(val)),
        .float => !std.meta.isError(parseDecimal(val)),
    };
    if (ok) return null;
    return try std.fmt.allocPrint(alloc, "invalid vector: model {s}: {s} is not {s} text", .{ key, clip(val), @tagName(ty) });
}

// One `model` entry against the decoded entity: a key, `"<list>.#"` (a count
// or `absent`), or `"<list>[<i>].<key>"` with further steps for nested lists.
// null: it holds.
fn checkModelKey(alloc: std.mem.Allocator, ent: *const Entity, key: []const u8, exp: []const u8, completed: bool) !?[]const u8 {
    var cur = ent;
    var rest = key;
    while (std.mem.indexOfScalar(u8, rest, '[')) |open| {
        const close = std.mem.indexOfScalarPos(u8, rest, open, ']');
        const idx: ?u64 = if (close) |c| parseUnsigned(rest[open + 1 .. c]) else null;
        if (idx == null or close.? + 1 >= rest.len or rest[close.? + 1] != '.') {
            return try std.fmt.allocPrint(alloc, "model key {s}: not `<list>[<i>].<key>`", .{key});
        }
        const items = cur.lists.get(rest[0..open]) orelse
            return try std.fmt.allocPrint(alloc, "model key {s}: the list {s} is absent", .{ key, rest[0..open] });
        if (idx.? >= items.len) {
            return try std.fmt.allocPrint(alloc, "model key {s}: the list {s} has {d} items", .{ key, rest[0..open], items.len });
        }
        cur = &items[@intCast(idx.?)];
        rest = rest[close.? + 2 ..];
    }
    if (std.mem.endsWith(u8, rest, ".#")) {
        const name = rest[0 .. rest.len - 2];
        const got = cur.lists.get(name);
        if (std.mem.eql(u8, exp, "absent")) {
            if (got) |items| return try std.fmt.allocPrint(alloc, "model key {s}: expected an absent list, got {d} items", .{ key, items.len });
            return null;
        }
        const want = parseUnsigned(exp) orelse
            return try std.fmt.allocPrint(alloc, "model key {s}: the expected count {s} is not a number or `absent`", .{ key, clip(exp) });
        const items = got orelse
            return try std.fmt.allocPrint(alloc, "model key {s}: expected {d} items, the list is absent", .{ key, want });
        if (items.len != want) {
            return try std.fmt.allocPrint(alloc, "model key {s}: expected {d} items, got {d}", .{ key, want, items.len });
        }
        return null;
    }
    if (std.mem.eql(u8, rest, "@kind")) {
        // the kind an item recorded when it was decoded
        if (cur.kind_fmt == null) return try std.fmt.allocPrint(alloc, "model key {s}: expected {s}, the item records no kind", .{ key, clip(exp) });
        if (!std.mem.eql(u8, cur.kind_name, exp)) {
            return try std.fmt.allocPrint(alloc, "model key {s}: expected {s}, got {s}", .{ key, clip(exp), clip(cur.kind_name) });
        }
        return null;
    }
    const actual = cur.get(rest) orelse return try std.fmt.allocPrint(alloc, "model key {s} absent", .{key});
    if (!modelMatch(actual, exp, completed)) {
        return try std.fmt.allocPrint(alloc, "model key {s}: expected {s}, got {s}", .{ key, clip(exp), clip(try mvText(alloc, actual)) });
    }
    return null;
}

// One `"@absent"` entry: a key or a list name the entity lacks, or
// `"<list>[<i>].<key>"`, an item that exists and lacks the key. null: it holds.
fn checkAbsentKey(alloc: std.mem.Allocator, ent: *const Entity, key: []const u8) !?[]const u8 {
    var cur = ent;
    var rest = key;
    while (std.mem.indexOfScalar(u8, rest, '[')) |open| {
        const close = std.mem.indexOfScalarPos(u8, rest, open, ']');
        const idx: ?u64 = if (close) |c| parseUnsigned(rest[open + 1 .. c]) else null;
        if (idx == null or close.? + 1 >= rest.len or rest[close.? + 1] != '.') {
            return try std.fmt.allocPrint(alloc, "@absent {s}: not `<list>[<i>].<key>`", .{key});
        }
        const items = cur.lists.get(rest[0..open]) orelse
            return try std.fmt.allocPrint(alloc, "@absent {s}: the list {s} is absent", .{ key, rest[0..open] });
        if (idx.? >= items.len) {
            return try std.fmt.allocPrint(alloc, "@absent {s}: the list {s} has {d} items", .{ key, rest[0..open], items.len });
        }
        cur = &items[@intCast(idx.?)];
        rest = rest[close.? + 2 ..];
    }
    if (cur.get(rest)) |v| {
        return try std.fmt.allocPrint(alloc, "@absent {s}: the key is present, {s}", .{ key, clip(try mvText(alloc, v)) });
    }
    if (cur.lists.get(rest)) |items| {
        return try std.fmt.allocPrint(alloc, "@absent {s}: the list is present with {d} items", .{ key, items.len });
    }
    return null;
}

// Failure text is kept short: a message of a megabyte helps no reader.
fn clip(s: []const u8) []const u8 {
    return if (s.len > 600) s[0..600] else s;
}

// Where two long texts first differ, for a mismatch report.
fn diffNote(alloc: std.mem.Allocator, a: []const u8, b: []const u8) ![]const u8 {
    if (a.len <= 600 and b.len <= 600) return "";
    var i: usize = 0;
    while (i < a.len and i < b.len and a[i] == b[i]) i += 1;
    const lo = if (i > 40) i - 40 else 0;
    return std.fmt.allocPrint(alloc, " (lengths {d} and {d}; first difference at byte {d}: expected …{s}… got …{s}…)", .{
        a.len, b.len, i, a[lo..@min(a.len, i + 80)], b[lo..@min(b.len, i + 80)],
    });
}

fn mvText(alloc: std.mem.Allocator, mv: MV) ![]const u8 {
    return switch (mv) {
        .str => |s| s,
        .int => |i| intToStr(alloc, i),
        .float => |f| std.fmt.allocPrint(alloc, "{d}", .{f}),
    };
}

// `relative`: a float of a completed entity compares within 1e-9 relative;
// otherwise within 1e-9.
fn modelMatch(actual: MV, expected: []const u8, relative: bool) bool {
    switch (actual) {
        .str => |s| return std.mem.eql(u8, s, expected),
        .int => |i| {
            const e = parseDecimalInt(expected) catch return false;
            return i == e;
        },
        .float => |f| {
            const e = parseDecimal(expected) catch return false;
            if (f == e) return true;
            if (relative) return @abs(f - e) < 1e-9 * @max(@abs(f), @abs(e));
            return @abs(f - e) <= 1e-9;
        },
    }
}

// Run one load vector on a fresh engine. Returns null on pass, else why it
// failed.
fn runLoadVector(alloc: std.mem.Allocator, text: []const u8) !?[]const u8 {
    const parsed = std.json.parseFromSliceLeaky(JValue, alloc, text, .{}) catch return "not JSON";
    if (parsed != .object) return "not a JSON object";
    const obj = parsed.object;
    const models = obj.get("models") orelse return "no models";
    if (models != .array) return "models is not an array";
    // `pack`, or `packs` (Version 0.11): pack texts loaded in order
    var pack_texts = std.ArrayList([]const u8).init(alloc);
    if (getStr(obj, "pack")) |pt| {
        try pack_texts.append(pt);
    } else if (obj.get("packs")) |pv| {
        if (pv != .array) return "packs is not an array";
        for (pv.array.items) |x| {
            if (x != .string) return "a pack is not a string";
            try pack_texts.append(x.string);
        }
    } else return "no pack";
    const expect_error = getStr(obj, "expect_error");

    var eng = Engine.init(alloc);
    if (getStr(obj, "max_distribution")) |md| {
        eng.setMaxDistribution(parseDist(md) catch return "bad max_distribution");
    }

    // modules in order, then the pack, stopping at the first failure
    var got: ?[]const u8 = null;
    for (models.array.items) |m| {
        if (m != .string) return "a model is not a string";
        _ = eng.loadModel(m.string) catch |err| {
            got = @errorName(err);
            break;
        };
    }
    if (got == null) {
        for (pack_texts.items) |pt| {
            _ = eng.loadPack(pt) catch |err| {
                got = @errorName(err);
                break;
            };
        }
    }

    if (expect_error) |want| {
        const kind = got orelse return try std.fmt.allocPrint(alloc, "expected {s}, load succeeded", .{want});
        if (!std.mem.eql(u8, kind, want)) {
            return try std.fmt.allocPrint(alloc, "expected {s}, got {s}", .{ want, eng.last_error });
        }
        // the message begins with the error kind and a colon
        if (!beginsWithKind(eng.last_error, want)) {
            return try std.fmt.allocPrint(alloc, "message does not begin with `{s}:`: {s}", .{ want, eng.last_error });
        }
        return null;
    }
    if (got != null) return try std.fmt.allocPrint(alloc, "expected success, got {s}", .{eng.last_error});
    return null;
}

// ---------------------------------------------------------------------------
// Memory accounting
// ---------------------------------------------------------------------------

// An allocator that counts the bytes its child holds and refuses to go past
// `cap`: what one `convert` may use is then a test result, not a kill by the
// operating system.
const CapAlloc = struct {
    child: std.mem.Allocator,
    cap: usize,
    live: usize = 0,
    peak: usize = 0,

    fn allocator(self: *CapAlloc) std.mem.Allocator {
        return .{ .ptr = self, .vtable = &.{ .alloc = alloc, .resize = resize, .free = free } };
    }
    fn grow(self: *CapAlloc, n: usize) bool {
        if (n > self.cap -| self.live) return false;
        self.live += n;
        self.peak = @max(self.peak, self.live);
        return true;
    }
    fn alloc(ctx: *anyopaque, len: usize, ptr_align: u8, ra: usize) ?[*]u8 {
        const self: *CapAlloc = @ptrCast(@alignCast(ctx));
        if (!self.grow(len)) return null;
        const got = self.child.rawAlloc(len, ptr_align, ra);
        if (got == null) self.live -= len;
        return got;
    }
    fn resize(ctx: *anyopaque, buf: []u8, buf_align: u8, new_len: usize, ra: usize) bool {
        const self: *CapAlloc = @ptrCast(@alignCast(ctx));
        if (new_len > buf.len and new_len - buf.len > self.cap -| self.live) return false;
        if (!self.child.rawResize(buf, buf_align, new_len, ra)) return false;
        self.live = self.live - buf.len + new_len;
        self.peak = @max(self.peak, self.live);
        return true;
    }
    fn free(ctx: *anyopaque, buf: []u8, buf_align: u8, ra: usize) void {
        const self: *CapAlloc = @ptrCast(@alignCast(ctx));
        self.live -= buf.len;
        self.child.rawFree(buf, buf_align, ra);
    }
};

// ---------------------------------------------------------------------------
// Malformed-input run (`--fuzz`)
// ---------------------------------------------------------------------------

// The kinds a `convert` with no context may fail with.
const named_kinds = [_][]const u8{ "malformed-wire", "transform-decode", "transform-encode", "no-kind", "missing-root" };

const fuzz_steps: usize = 96;
// What one `convert` of the run may hold; more fails the run.
const fuzz_mem_cap: usize = 256 << 20;
const fuzz_bytes = "0f8<>\"'{}[],:\\/-+. &=\x00\x80\xff";

const Fuzz = struct {
    eng: *Engine,
    counted: *CapAlloc,
    arena: std.heap.ArenaAllocator,
    seen: std.StringHashMap(void),
    peak: usize = 0,
    peak_what: []const u8 = "",
    inputs: usize = 0,
    failures: std.ArrayList([]const u8),

    // One input through `convert`: it returns a message, or fails with a
    // named kind and a message that begins with it. A panic ends the run.
    fn one(self: *Fuzz, from: []const u8, to: []const u8, input: []const u8, what: []const u8, n: usize) !void {
        _ = self.arena.reset(.free_all);
        self.counted.peak = 0;
        self.eng.scratch = self.arena.allocator();
        defer self.eng.scratch = self.eng.alloc;
        self.inputs += 1;
        const res = self.eng.convert(from, to, input, null);
        if (self.counted.peak > self.peak) {
            self.peak = self.counted.peak;
            self.peak_what = try std.fmt.allocPrint(self.eng.alloc, "{s}, {s} {d}, {d} input bytes", .{ from, what, n, input.len });
        }
        if (res) |_| {} else |err| {
            const name = @errorName(err);
            var ok = false;
            if (err == error.OutOfMemory) {
                try self.failures.append(try std.fmt.allocPrint(self.eng.alloc, "{s} -> {s}, {s} {d}: {d} input bytes need more than {d} bytes of memory", .{ from, to, what, n, input.len, fuzz_mem_cap }));
                return;
            }
            for (named_kinds) |k| {
                if (std.mem.eql(u8, name, k) and beginsWithKind(self.eng.last_error, k)) ok = true;
            }
            if (!ok and self.failures.items.len < 200) {
                try self.failures.append(try std.fmt.allocPrint(self.eng.alloc, "{s} -> {s}, {s} {d}: {s} is not a named kind", .{ from, to, what, n, name }));
            }
        }
    }

    // Every vector input cut at prefixes and with single bytes replaced: all
    // of them when the input is short, else `fuzz_steps` evenly spaced.
    fn vector(self: *Fuzz, text: []const u8) !void {
        const alloc = self.eng.alloc;
        const parsed = std.json.parseFromSliceLeaky(JValue, alloc, text, .{}) catch return;
        if (parsed != .object) return;
        const from = getStr(parsed.object, "from") orelse return;
        const to = getStr(parsed.object, "to") orelse return;
        const input = getStr(parsed.object, "input") orelse return;
        if (self.eng.findPack(from) == null or self.eng.findPack(to) == null) return;
        const len = input.len;
        const steps = @min(len, fuzz_steps);
        for (0..steps) |k| try self.one(from, to, input[0 .. k * len / steps], "prefix", k * len / steps);
        const buf = try alloc.dupe(u8, input);
        for (0..steps) |k| {
            const at = k * len / steps;
            const keep = buf[at];
            buf[at] = keep ^ 0x01;
            try self.one(from, to, buf, "bit flipped at byte", at);
            for (0..3) |j| {
                buf[at] = fuzz_bytes[(at * 7 + j * 11 + len) % fuzz_bytes.len];
                try self.one(from, to, buf, "byte replaced at", at);
            }
            buf[at] = keep;
        }
        if (!self.seen.contains(from)) {
            try self.seen.put(from, {});
            try self.deep(from, to);
        }
    }

    // Once per format: text nested 200000 levels deep, and hex of one unit
    // repeated to 700000 digits, which a sequential pack reads as some
    // hundred thousand list items.
    fn deep(self: *Fuzz, from: []const u8, to: []const u8) !void {
        const alloc = self.eng.alloc;
        const units = [_][]const u8{ "<a>", "<a b=\"c\">", "[", "{\"a\":", "{\"properties\":{\"a\":[", "ff", "82", "0a", "0b", "0aff", "22ffffffffffffffffff01" };
        for (units, 0..) |u, n| {
            const reps: usize = if (n < 5) 200000 else 700000 / u.len;
            const big = try alloc.alloc(u8, u.len * reps);
            defer alloc.free(big);
            for (0..reps) |r| @memcpy(big[r * u.len ..][0..u.len], u);
            try self.one(from, to, big, "repeated unit", n);
        }
    }
};

// What a list item may cost: 200000 one-byte items of the pack
// `conformance-seq-groups` (an indicator bit, six bits of `probe.qty`, an
// `opt` bit of 0) must decode within `list_mem_cap` bytes.
const list_items: usize = 200000;
const list_mem_cap: usize = 128 << 20;

// null: the pack is not loaded. Else the most bytes the decode held.
fn listMemory(eng: *Engine) !?usize {
    const fmt = "conformance-seq-groups";
    if (eng.findPack(fmt) == null) return null;
    const input = try eng.alloc.alloc(u8, 4 + 2 * list_items + 4);
    defer eng.alloc.free(input);
    @memset(input, '0');
    for (0..list_items) |i| input[4 + 2 * i] = '8';
    for (0..list_items) |i| input[5 + 2 * i] = '2';
    var counted = CapAlloc{ .child = std.heap.page_allocator, .cap = list_mem_cap };
    var arena = std.heap.ArenaAllocator.init(counted.allocator());
    defer arena.deinit();
    eng.scratch = arena.allocator();
    defer eng.scratch = eng.alloc;
    // the run measures memory per item: the limit on list items (ruling 7
    // of 0.11) is raised to the items it decodes
    const limit = eng.max_items;
    eng.max_items = list_items;
    defer eng.max_items = limit;
    const e = try eng.decode(fmt, input);
    const items = e.lists.get("probe.items") orelse return error.Unexpected;
    if (items.len != list_items) return error.Unexpected;
    return counted.peak;
}

fn runFuzz(eng: *Engine, packs_dir: []const u8, pack_dirs: []const []const u8, stdout: anytype) !bool {
    const alloc = eng.alloc;
    var counted = CapAlloc{ .child = std.heap.page_allocator, .cap = fuzz_mem_cap };
    var fz = Fuzz{
        .eng = eng,
        .counted = &counted,
        .arena = std.heap.ArenaAllocator.init(counted.allocator()),
        .seen = std.StringHashMap(void).init(alloc),
        .failures = std.ArrayList([]const u8).init(alloc),
    };
    defer fz.arena.deinit();
    for (pack_dirs) |dir| {
        const vdir_path = try std.fmt.allocPrint(alloc, "{s}/{s}/vectors", .{ packs_dir, dir });
        const vnames = (try sortedNames(alloc, vdir_path, .file, ".json")) orelse continue;
        for (vnames) |vn| {
            const vpath = try std.fmt.allocPrint(alloc, "{s}/{s}", .{ vdir_path, vn });
            const before = fz.failures.items.len;
            try fz.vector(try std.fs.cwd().readFileAlloc(alloc, vpath, max_file));
            for (fz.failures.items[before..]) |*f| f.* = try std.fmt.allocPrint(alloc, "{s}/{s}: {s}", .{ dir, vn, f.* });
        }
    }
    for (fz.failures.items) |f| try stdout.print("FAIL {s}\n", .{f});
    try stdout.print("malformed inputs: {d} run, {d} failed\n", .{ fz.inputs, fz.failures.items.len });
    try stdout.print("most memory for one input: {d} bytes ({s}); the limit is {d}\n", .{ fz.peak, fz.peak_what, fuzz_mem_cap });
    var list_ok = true;
    if (listMemory(eng)) |got| {
        if (got) |peak| try stdout.print("list memory: {d} bytes for {d} items, {d} per item; the limit is {d}\n", .{ peak, list_items, peak / list_items, list_mem_cap });
    } else |err| {
        list_ok = false;
        try stdout.print("FAIL list memory: {d} items of conformance-seq-groups do not decode within {d} bytes ({s})\n", .{ list_items, list_mem_cap, @errorName(err) });
    }
    return fz.failures.items.len == 0 and list_ok;
}

pub fn main() !void {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    const alloc = arena.allocator();

    var bw = std.io.bufferedWriter(std.io.getStdOut().writer());
    const stdout = bw.writer();

    // usage: gt-engine-zig [<packs-dir>] [--models <dir>] [--packs-only <a>,<b>…]
    //        [--max-distribution public|controlled] [--model-keys <format>]
    //        [--convert <from> <to> [--set <key>=<value>]…] [--fuzz]
    const args = try std.process.argsAlloc(alloc);
    var packs_dir: []const u8 = "../../packs";
    var models_opt: ?[]const u8 = null;
    var keys_opt: ?[]const u8 = null;
    var only_opt: ?[]const u8 = null;
    var conv_from: ?[]const u8 = null;
    var conv_to: []const u8 = "";
    var fuzz = false;
    var peak = false;
    var sets = std.ArrayList(KV).init(alloc);
    var eng = Engine.init(alloc);
    var ai: usize = 1;
    while (ai < args.len) : (ai += 1) {
        const a = args[ai];
        const eq = std.mem.eql;
        if (eq(u8, a, "--models") or eq(u8, a, "--max-distribution") or eq(u8, a, "--packs") or eq(u8, a, "--packs-only") or eq(u8, a, "--model-keys") or eq(u8, a, "--set") or eq(u8, a, "--convert") or eq(u8, a, "--max-items")) {
            ai += 1;
            if (ai >= args.len or (eq(u8, a, "--convert") and ai + 1 >= args.len)) {
                try stdout.print("error: {s} needs a value\n", .{a});
                try bw.flush();
                std.process.exit(2);
            }
            if (eq(u8, a, "--models")) {
                models_opt = args[ai];
            } else if (eq(u8, a, "--packs")) {
                packs_dir = args[ai];
            } else if (eq(u8, a, "--packs-only")) {
                only_opt = args[ai];
            } else if (eq(u8, a, "--model-keys")) {
                keys_opt = args[ai];
            } else if (eq(u8, a, "--convert")) {
                conv_from = args[ai];
                ai += 1;
                conv_to = args[ai];
            } else if (eq(u8, a, "--max-items")) {
                eng.setMaxItems(@intCast(parseUnsigned(args[ai]) orelse {
                    try stdout.print("error: --max-items takes an integer of 0 or more\n", .{});
                    try bw.flush();
                    std.process.exit(2);
                }));
            } else if (eq(u8, a, "--set")) {
                const at = std.mem.indexOfScalar(u8, args[ai], '=') orelse {
                    try stdout.print("error: --set takes <key>=<value>\n", .{});
                    try bw.flush();
                    std.process.exit(2);
                };
                try sets.append(.{ .key = args[ai][0..at], .value = args[ai][at + 1 ..] });
            } else {
                eng.setMaxDistribution(parseDist(args[ai]) catch {
                    try stdout.print("error: --max-distribution takes public or controlled\n", .{});
                    try bw.flush();
                    std.process.exit(2);
                });
            }
        } else if (eq(u8, a, "--fuzz")) {
            fuzz = true;
        } else if (eq(u8, a, "--peak")) {
            peak = true;
        } else if (std.mem.startsWith(u8, a, "--")) {
            try stdout.print("error: unknown option {s}\n", .{a});
            try bw.flush();
            std.process.exit(2);
        } else {
            packs_dir = a;
        }
    }
    // the model directory sits beside the packs directory
    const models_dir: []const u8 = models_opt orelse try std.fmt.allocPrint(alloc, "{s}/../model", .{packs_dir});

    // --packs-only <a>,<b>…: those packs and the modules they need; else
    // every module and every pack
    var n_modules: usize = 0;
    var pack_dirs: []const []const u8 = &.{};
    if (only_opt) |only| {
        var wanted = std.ArrayList([]const u8).init(alloc);
        var parts = std.mem.splitScalar(u8, only, ',');
        while (parts.next()) |part| {
            const name = std.mem.trim(u8, part, " ");
            if (name.len > 0) try wanted.append(name);
        }
        const loaded = eng.loadPacksOnly(packs_dir, models_dir, wanted.items) catch |err| {
            if (eng.last_error.len == 0) eng.fail(err, "packs directory {s}", .{packs_dir});
            try stdout.print("load error: {s}\n", .{eng.last_error});
            try bw.flush();
            std.process.exit(1);
        };
        n_modules = loaded.modules;
        pack_dirs = loaded.packs;
    } else {
        n_modules = eng.loadModelDir(models_dir) catch |err| {
            if (eng.last_error.len == 0) eng.fail(err, "model directory {s}", .{models_dir});
            try stdout.print("load error: {s}\n", .{eng.last_error});
            try bw.flush();
            std.process.exit(1);
        };
        pack_dirs = loadAllPacks(&eng, packs_dir) catch |err| {
            if (eng.last_error.len == 0) eng.fail(err, "packs directory {s}", .{packs_dir});
            try stdout.print("load error: {s}\n", .{eng.last_error});
            try bw.flush();
            std.process.exit(1);
        };
    }
    // --convert <from> <to>: the message on standard input, converted, on
    // standard output; --set supplies the context.
    if (conv_from) |from| {
        const input = try std.io.getStdIn().readToEndAlloc(alloc, max_file);
        // the input of a `text` format is the record as it is: decode removes
        // one line terminator and nothing else
        const from_text = if (eng.findPack(from)) |fp| fp.wire == .text else false;
        const msg = if (from_text) input else std.mem.trim(u8, input, " \t\r\n");
        if (peak) {
            // --peak: the bytes the decode alone holds at its highest, on
            // standard error
            var counted = CapAlloc{ .child = std.heap.page_allocator, .cap = std.math.maxInt(usize) };
            var parena = std.heap.ArenaAllocator.init(counted.allocator());
            defer parena.deinit();
            eng.scratch = parena.allocator();
            _ = eng.decode(from, msg) catch {};
            eng.scratch = alloc;
            std.io.getStdErr().writer().print("peak: {d} bytes for a decode of {d} input bytes\n", .{ counted.peak, msg.len }) catch {};
        }
        const out = eng.convert(from, conv_to, msg, if (sets.items.len > 0) sets.items else null) catch |err| {
            if (err == error.OutOfMemory) return err;
            std.io.getStdErr().writer().print("error: {s}\n", .{eng.last_error}) catch {};
            std.process.exit(1);
        };
        try stdout.print("{s}\n", .{out});
        try bw.flush();
        return;
    }
    try stdout.print("loaded: {d} modules, {d} packs\n", .{ n_modules, pack_dirs.len });

    if (keys_opt) |fmt| {
        const p = eng.findPack(fmt) orelse {
            try stdout.print("error: no loaded pack has format {s}\n", .{fmt});
            try bw.flush();
            std.process.exit(2);
        };
        for (try modelKeys(alloc, p)) |k| try stdout.print("{s}\n", .{k});
        try bw.flush();
        return;
    }

    // --fuzz: every vector input cut short and with single bytes replaced
    if (fuzz) {
        const ok = try runFuzz(&eng, packs_dir, pack_dirs, stdout);
        try bw.flush();
        if (!ok) std.process.exit(1);
        return;
    }

    var failures = std.ArrayList([]const u8).init(alloc);

    // conversion vectors: <packs>/<pack>/vectors/*.json
    var total: usize = 0;
    var passed: usize = 0;
    var skipped: usize = 0;
    for (pack_dirs) |dir| {
        const vdir_path = try std.fmt.allocPrint(alloc, "{s}/{s}/vectors", .{ packs_dir, dir });
        const vnames = (try sortedNames(alloc, vdir_path, .file, ".json")) orelse continue;
        for (vnames) |vn| {
            // one arena per vector, so the run's memory stays bounded
            var varena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
            defer varena.deinit();
            eng.scratch = varena.allocator();
            defer eng.scratch = alloc;
            const vpath = try std.fmt.allocPrint(eng.scratch, "{s}/{s}", .{ vdir_path, vn });
            const vtext = try std.fs.cwd().readFileAlloc(eng.scratch, vpath, max_file);
            // with --packs-only, a vector that names a pack left out is
            // not run, and is counted
            if (only_opt != null and !vectorFormatsLoaded(&eng, packs_dir, vtext)) {
                skipped += 1;
                continue;
            }
            total += 1;
            if (try runVector(&eng, vtext)) |detail| {
                try failures.append(try std.fmt.allocPrint(alloc, "{s}/{s}: {s}", .{ dir, vn, detail }));
            } else {
                passed += 1;
            }
        }
    }

    // load vectors: <packs>/conformance/load-vectors/*.json
    var ltotal: usize = 0;
    var lpassed: usize = 0;
    // (with --packs-only, when `conformance` is one of the named packs)
    const ldir_path = try std.fmt.allocPrint(alloc, "{s}/conformance/load-vectors", .{packs_dir});
    var run_load = only_opt == null;
    for (pack_dirs) |dir| {
        if (std.mem.eql(u8, dir, "conformance")) run_load = true;
    }
    if (!run_load) {} else if (try sortedNames(alloc, ldir_path, .file, ".json")) |lnames| {
        for (lnames) |ln| {
            ltotal += 1;
            var larena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
            defer larena.deinit();
            const la = larena.allocator();
            const lpath = try std.fmt.allocPrint(la, "{s}/{s}", .{ ldir_path, ln });
            const ltext = try std.fs.cwd().readFileAlloc(la, lpath, max_file);
            if (try runLoadVector(la, ltext)) |detail| {
                try failures.append(try std.fmt.allocPrint(alloc, "load-vectors/{s}: {s}", .{ ln, detail }));
            } else {
                lpassed += 1;
            }
        }
    }

    // capability vectors: <packs>/conformance/capability-vectors/*.json
    var ctotal: usize = 0;
    var cpassed: usize = 0;
    const cdir_path = try std.fmt.allocPrint(alloc, "{s}/conformance/capability-vectors", .{packs_dir});
    if (try sortedNames(alloc, cdir_path, .file, ".json")) |cnames| {
        for (cnames) |cn| {
            var carena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
            defer carena.deinit();
            eng.scratch = carena.allocator();
            defer eng.scratch = alloc;
            const cpath = try std.fmt.allocPrint(eng.scratch, "{s}/{s}", .{ cdir_path, cn });
            const ctext = try std.fs.cwd().readFileAlloc(eng.scratch, cpath, max_file);
            if (only_opt != null and !vectorFormatsLoaded(&eng, packs_dir, ctext)) {
                skipped += 1;
                continue;
            }
            ctotal += 1;
            if (try runCapabilityVector(&eng, ctext)) |detail| {
                try failures.append(try std.fmt.allocPrint(alloc, "capability-vectors/{s}: {s}", .{ cn, detail }));
            } else {
                cpassed += 1;
            }
        }
    }

    for (failures.items) |fmsg| {
        try stdout.print("FAIL {s}\n", .{fmsg});
    }
    try stdout.print("vectors: {d}/{d} passed\n", .{ passed, total });
    try stdout.print("load vectors: {d}/{d} passed\n", .{ lpassed, ltotal });
    try stdout.print("capability vectors: {d}/{d} passed\n", .{ cpassed, ctotal });
    if (skipped > 0) try stdout.print("skipped: {d} vectors that name a pack not loaded\n", .{skipped});
    try bw.flush();
    if (passed != total or lpassed != ltotal or cpassed != ctotal) std.process.exit(1);
}
