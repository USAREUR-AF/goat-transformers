// gt-engines Zig engine — clean-room implementation from spec/ and packs/ only.
// Implements the format engine: decode(wire->model), encode(model->wire),
// convert(from,to[,context]) = decode, fill from context, derive, encode; plus
// a conformance harness.
//
// Wires: xml, geojson, json, bits (lsb and msb bit order), protobuf, text,
// tlv (spec Version 0.13; on tlv also the transforms utf8 and hex), cbor
// (spec Version 0.28; on cbor also the transforms text, bytes and epoch_s).
// Transforms: string, float, int, iso8601_ms, iso8601_s, bool, uint, twos,
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
// capability report and the limit on list items. Value transforms (spec
// Version 0.15): uiscale, siscale, smag, smscale, f32scale, f64scale,
// chars:<set> and octal on bits, scale and iscale on the text wires, in exact
// integer arithmetic (big integers where a text number needs them). Kind
// selection (spec Version 0.20): `when` value lists and ranges, `requires
// <key>=<value>…`, and the sequential `switch` / `case` / `else` block.
// Character codes (spec Version 0.46): `charset` lines, `code` and `codenum`
// on bits, `codestr` and `codenum` on the text wires.
// Token parts (spec Version 0.64): `part:<sep>:<n>`, `unlisted` and `const …
// part` on the text wires.
// Stdlib only.
//
// Errors the specification names are Zig errors whose name IS the spec token
// (`error.@"no-kind"`); `Engine.last_error` holds `<kind>: <detail>`.

const std = @import("std");
const build_options = @import("build_options");
const licence = @import("licence.zig");
const builtin = @import("builtin");
pub const Profile = licence.Profile;

// ---------------------------------------------------------------------------
// Version 0.24: the wires of the build (`zig build -Dwires=<w>,<w>…`)
// ---------------------------------------------------------------------------

// Does this build have the wire's codec? Known at compile time: every branch
// that reads or writes a wire the build lacks is guarded by `built(w)` or
// `isW`, so its code is never analysed and is not in the build.
pub inline fn built(comptime w: Wire) bool {
    return @field(build_options, "wire_" ++ @tagName(w));
}

// `wire == w`, false at compile time when the build lacks `w`.
inline fn isW(wire: Wire, comptime w: Wire) bool {
    return built(w) and wire == w;
}

// Does this build have the wire, for a wire known only at run time?
pub fn wireBuilt(w: Wire) bool {
    return switch (w) {
        inline else => |cw| comptime built(cw),
    };
}

// Has this build all eight wires?
pub const all_wires = blk: {
    for (std.enums.values(Wire)) |w| {
        if (!built(w)) break :blk false;
    }
    break :blk true;
};

// The `wire` value of a pack text: the second token of its first `wire`
// line with two tokens; null when there is none.
pub fn packWireValue(alloc: std.mem.Allocator, def_text: []const u8) !?[]const u8 {
    var tokbuf = std.ArrayList([]const u8).init(alloc);
    defer tokbuf.deinit();
    var lines = std.mem.splitScalar(u8, def_text, '\n');
    while (lines.next()) |line| {
        tokenizeInto(&tokbuf, line) catch |err| switch (err) {
            error.OutOfMemory => return err,
            else => continue,
        };
        const t = tokbuf.items;
        if (t.len == 2 and std.mem.eql(u8, t[0], "wire")) return t[1];
    }
    return null;
}

// Is the pack text on a wire of the specification that this build lacks?
pub fn packOnUnbuiltWire(alloc: std.mem.Allocator, def_text: []const u8) !bool {
    if (all_wires) return false;
    const v = (try packWireValue(alloc, def_text)) orelse return false;
    const w = std.meta.stringToEnum(Wire, v) orelse return false;
    return !wireBuilt(w);
}

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
    // Version 0.34: Entity.inner_kind, the pair (format, kind name) of the
    // kind an inner pack selected; null when none is recorded. Set by decode
    // only.
    inner_kind_fmt: ?[]const u8 = null,
    inner_kind_name: []const u8 = "",

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
    fn clearInnerKind(self: *Entity) void {
        self.inner_kind_fmt = null;
        self.inner_kind_name = "";
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
    // Version 0.92
    @"message-count",
    @"duplicate-kind",
    @"transform-encode",
    @"transform-decode",
    @"malformed-wire",
    @"bad-directive",
    // Version 0.29: a licence file that cannot be read as ruling 1 says, or
    // a profile name that is not one of the three
    @"bad-licence",
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
    // Version 0.34: the loaded packs, where decode and encode look up the
    // pack an `inner` line names; null: none is found
    packs: ?*const std.StringHashMap(*Pack) = null,
    // Version 0.34: for an inner decode, the lists the outer entity holds
    discard: []const []const u8 = &.{},
    // the inner entity of a fixed layout, and > 0 while a group whose list is
    // discarded is read: its items are not held
    root: ?*const Entity = null,
    no_hold: usize = 0,
    // what an inner decode that failed with `transform-decode` had read; null:
    // the failure stopped the decode (a `switch` on a key that failed)
    partial: ?Entity = null,
    // with `partial`: the keys whose lines failed and that the inner message
    // does not hold, forgiven when an outer line gives them (ruling 23 of
    // 0.34), and whether something failed that is never forgiven
    failed_keys: []const []const u8 = &.{},
    unforgiven: bool = false,
    // Version 0.34: the decode about to start is an inner one, and whether
    // bytes after its end are an error; taken by that decode
    inner: InnerMode = .none,
    // Version 0.34: an inner decode of a fixed layout is running
    soft: ?*Soft = null,
    // Version 0.92: the outer decode of a run operation, taken by the decode
    // about to start; where a message of a run ended, in bytes; and the
    // messages the encode about to start writes at its `run` line
    run: ?*RunRead = null,
    run_end: usize = 0,
    run_write: ?*RunWrite = null,
    // Version 0.94: the encode about to start is that of `convert` with
    // `from` different from `to`: the chosen kind must hold one of its
    // keys. Taken by that encode, so an inner encode is not checked.
    held_check: bool = false,
};

// `run`: one message of a run, which ends where its own decode ends.
const InnerMode = enum { none, strict, partial, run };

// Version 0.34, an inner decode of a fixed layout: a `transform-decode` does
// not stop it. The first one, and the furthest start of a group (ruling 14).
// The message's keys that failed are kept for the outer decode (ruling 23).
const Soft = struct { msg: ?[]const u8 = null, far: usize = 0, keys: std.ArrayListUnmanaged([]const u8) = .{} };

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

// Hold `n` more list items, unless they are in a list that is discarded
// (Version 0.34, Decode step 4): there a count read from the wire is checked
// against the budget left when it is read (ruling 7 of 0.34) and no item is
// held (7g of 0.11).
fn holdList(diag: *Diag, alloc: std.mem.Allocator, n: u64, list: []const u8, wire_count: bool) anyerror!void {
    if (diag.no_hold == 0) return takeItems(diag, alloc, n, list);
    if (!wire_count) return;
    if (n > diag.max_items - diag.held) {
        diag.limit_hit = true;
        return bad(diag, alloc, E.@"malformed-wire", "list {s}: a count of {d} passes the {d} list items left of the limit of {d}", .{ list, n, diag.max_items - diag.held, diag.max_items });
    }
}

// The list items of every list of an entity, at every nesting level.
fn entityItems(e: *const Entity) usize {
    var n: usize = 0;
    for (e.lists.ptr[0..e.lists.len]) |en| n += itemsHeld(en.value);
    return n;
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

const Wire = enum { xml, geojson, json, bits, protobuf, text, tlv, cbor };
const TKind = enum {
    string,
    float,
    int,
    iso8601_ms,
    bool_,
    uint,
    twos,
    linscale,
    uscale,
    sscale,
    f32_,
    f64_,
    ascii,
    sixbit, // Version 0.14
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
    // the `tlv` wire only (Version 0.13)
    utf8,
    hex,
    // Version 0.15: value transforms
    uiscale,
    siscale,
    smag,
    smscale,
    f32scale,
    f64scale,
    chars,
    octal,
    tscale, // `scale` on the text wires
    iscale,
    // Version 0.18
    iso8601_short,
    // Version 0.26: read as iso8601_ms, written to the whole second
    iso8601_s,
    // the `cbor` wire only (Version 0.28)
    text_,
    bytes,
    epoch_s,
    // Version 0.46: characters of the pack's own sets. `code` on bits,
    // `codestr` on the text wires, `codenum` on both
    code,
    codestr,
    codenum,
    // one part of a token, on the text wires (Version 0.64)
    part,
};

// A transform of Version 0.15: on a wire it does not list it is `bad-directive`.
fn isValueTransform(k: TKind) bool {
    return switch (k) {
        .uiscale, .siscale, .smag, .smscale, .f32scale, .f64scale, .chars, .octal, .tscale, .iscale, .iso8601_short => true,
        else => false,
    };
}

const CharSet = enum { icao6, ais6, ascii7, ascii8 };

// `rec`: the transforms valid on the `text` wire only; `tlv`: on the `tlv`
// wire only
const KindCat = enum { text, bits, proto, rec, tlv, cbor };

fn kindCategory(k: TKind) KindCat {
    return switch (k) {
        .string, .float, .int, .iso8601_ms, .iso8601_short, .iso8601_s, .bool_, .tscale, .iscale, .part => .text,
        // `codenum` is a transform of `bits` too: see `bitsTransform`
        .codestr, .codenum => .text,
        .uint, .twos, .linscale, .uscale, .sscale, .f32_, .f64_, .ascii, .sixbit => .bits,
        .uiscale, .siscale, .smag, .smscale, .f32scale, .f64scale, .chars, .octal, .code => .bits,
        .pstring, .pvarint, .psint, .pdouble, .pfloat => .proto,
        .int_w, .dec, .dm, .hms, .hms_dmy => .rec,
        .utf8, .hex => .tlv,
        .text_, .bytes, .epoch_s => .cbor,
    };
}

// The transforms of the `bits` wire.
fn bitsTransform(k: TKind) bool {
    return kindCategory(k) == .bits or k == .hex or k == .codenum;
}

// Version 0.46: the transforms over a list of the pack's character sets.
fn isCode(k: TKind) bool {
    return k == .code or k == .codestr or k == .codenum;
}

fn wireCategory(w: Wire) KindCat {
    return switch (w) {
        .xml, .geojson, .json, .text => .text,
        .bits => .bits,
        .protobuf => .proto,
        .tlv => .tlv,
        .cbor => .cbor,
    };
}

const Transform = struct {
    kind: TKind,
    // linscale
    maxpos: f64 = 0,
    range: f64 = 0,
    // uscale / sscale, and the float scales of 0.15
    factor: Factor = .{},
    offset: f64 = 0,
    // text: `int:<w>`, `dec:<f>[:<w>]` (w 0: none), `dm:<d>:<f>:<PN>`,
    // `hms:<f>`, `hms_dmy:<f>`
    w: usize = 0,
    f: usize = 0,
    d: usize = 0,
    letp: u8 = 0,
    letn: u8 = 0,
    // the exact scales of 0.15 (uiscale, siscale, iscale): the factor in
    // lowest terms (den > 0) and the integer offset
    num: i64 = 1,
    den: i64 = 1,
    ioff: i64 = 0,
    // chars
    cset: CharSet = .ascii7,
    // part (Version 0.64): the separator and the number of the part
    psep: []const u8 = "",
    pn: usize = 0,
    // code, codestr, codenum (Version 0.46): the list as written, and the
    // set of each position, resolved once the file is read
    sets_raw: []const u8 = "",
    sets: []const *const CodeSet = &.{},
};

// Version 0.46: a `charset` line. `width` is the bits per character on `bits`.
const CodeSet = struct {
    name: []const u8,
    chars: []const u8,
    width_raw: ?[]const u8,
    width: usize = 0,
    lineno: usize,

    fn codeOf(self: *const CodeSet, c: u8) ?u64 {
        return std.mem.indexOfScalar(u8, self.chars, c);
    }
};

const max_positions = 16;

const LineTag = enum { field, when, constant, group, element };

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

// Version 0.17: a gate block `if [!]<locator> <value>[,<value>…]` … `end` on a
// fixed layout. Its lines stay in the lines of the scope it is in, each
// pointing at its innermost block.
const Gate = struct {
    lineno: usize,
    locator: []const u8, // without the `!`
    vals_txt: []const u8,
    neg: bool,
    parent: ?*Gate = null, // the block this one is nested in
    values: []const u64 = &.{},
    bstart: usize = 0,
    blen: usize = 0,
    // the position in the scope's gates (line order, depth first)
    idx: usize = 0,
    defaults: std.ArrayListUnmanaged(Default) = .{},
    dmap: std.StringHashMapUnmanaged(MV) = .{},

    // Does the value of the gate's bits hold the block?
    fn holds(self: *const Gate, v: u64) bool {
        const listed = std.mem.indexOfScalar(u64, self.values, v) != null;
        return listed != self.neg;
    }

    // The value step 3 of encode writes: the first listed value, or for `!`
    // the smallest value not listed (none when every value is listed).
    fn encodeValue(self: *const Gate) ?u64 {
        if (!self.neg) return self.values[0];
        var v: u64 = 0;
        while (true) : (v += 1) {
            if (self.blen < 64 and (v >> @as(u6, @intCast(self.blen))) != 0) return null;
            if (std.mem.indexOfScalar(u64, self.values, v) == null) return v;
            if (v == std.math.maxInt(u64)) return null;
        }
    }
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
    // Version 0.17: the gate blocks of the body, in line order
    gates: std.ArrayListUnmanaged(*Gate) = .{},
    // cbor (Version 0.28): the steps of the group's path (none for `.`), and
    // whether an element is an array (the body's paths begin with positions)
    cpath: []const CStep = &.{},
    cbody_array: bool = false,
};

// Version 0.64: the lines of one scope that share a locator and split its
// token. `slots`: the line of each part, 0 to the highest; `sole`: the part's
// key is mapped by no other `field` line of the scope (ruling 25).
const PartGroup = struct {
    first: *const Line,
    whole: ?*const Line,
    sep: []const u8,
    slots: []const *const Line,
    sole: []const bool,
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
    // Version 0.17: the gate blocks of the scope, in line order, depth
    // first; a gate's `idx` is its position here
    gates: []const *const Gate = &.{},
    // Version 0.64: the part groups of the scope
    parts: []const PartGroup = &.{},

    // The part group the line at `ln` (one of `lines`) belongs to.
    fn partGroup(self: *const Scope, ln: *const Line) ?*const PartGroup {
        if (ln.tag != .field and ln.tag != .constant) return null;
        for (self.parts) |*g| if (std.mem.eql(u8, g.first.locator, ln.locator)) return g;
        return null;
    }

    fn defaultFor(self: *const Scope, key: []const u8) ?MV {
        if (self.defaults.count() == 0) return null;
        return self.defaults.get(key);
    }

    // The default of a line's key: that of its innermost gate block that
    // has one, else the scope's (ruling 5 of 0.17).
    fn lineDefault(self: *const Scope, ln: *const Line) ?MV {
        var g = ln.gate;
        while (g) |gt| : (g = gt.parent) {
            if (gt.dmap.count() > 0) {
                if (gt.dmap.get(ln.key)) |v| return v;
            }
        }
        return self.defaultFor(ln.key);
    }
};

// One `field`, `when`, `const` or `group` line.
const Line = struct {
    tag: LineTag = .field,
    grp: ?*Group = null, // group
    gate: ?*const Gate = null, // the innermost gate block the line is in (0.17)
    dot: bool = false, // the locator `.`: the item itself
    // field options
    via_name: []const u8 = "",
    via: ?*const Table = null,
    swap: bool = false,
    trim: bool = false,
    optional: bool = false,
    // `with <other-key>` (Version 0.18): the line writes only when the
    // entity (inside a group, the item) holds that key
    with_key: ?[]const u8 = null,
    // `unlisted` (Version 0.64): a part with no table entry is absent
    unlisted: bool = false,
    // `absent <value>[,<value>…]` (Version 0.9): the argument as written,
    // then, once the line is resolved against its wire, the sentinels
    absent_raw: ?[]const u8 = null,
    // Version 0.22: `stop <code>` as written, and the code once checked; a
    // sequential `until:<code>` locator's code (the text after `until:`)
    stop_raw: ?[]const u8 = null,
    stop_code: ?u64 = null,
    until_raw: ?[]const u8 = null,
    until_code: ?u64 = null,
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
    // json, geojson: the JSON text the `when` or `const` value is written
    // as, computed once as the pack loads (Version 0.25); "" until then
    wjson: []const u8 = "",
    wint: u64 = 0, // bits / protobuf integer value
    // text: a field `<i>`, a column `<i>:<from>:<len>` or a pair `<i>+<j>`
    tloc: TLoc = .whole,
    ti: usize = 0,
    tj: usize = 0,
    tfrom: usize = 0,
    tlen: usize = 0,
    // tlv: the tags of the path, and the size `:<n>` (0: none)
    tpath: []const u32 = &.{},
    tsize: u8 = 0,
    // a transform that did not parse, refused after the file is read
    t_err: ?anyerror = null,
    // Version 0.20: every value of a `when` list. bits and protobuf: the
    // values and ranges (`wint` is the first value, or the first range's lo);
    // text wires: the texts (`wtext` is the first).
    wranges: []const WRange = &.{},
    walts: []const WAlt = &.{},
    // cbor (Version 0.28): the steps of the path (none for `.`), and a
    // `when` or `const` value with its type
    cpath: []const CStep = &.{},
    cval: CVal = .{},

    fn isField(self: *const Line) bool {
        return self.tag == .field;
    }
    fn isWhen(self: *const Line) bool {
        return self.tag == .when;
    }
    // a `field` or `const` line of one part of a token (Version 0.64)
    fn isPart(self: *const Line) bool {
        return self.transform.kind == .part;
    }
    // a `string` line with no option but, on `text`, `optional`: the whole
    // line of a part group when its locator has part lines
    fn isPlainString(self: *const Line, wire: Wire) bool {
        return self.tag == .field and self.transform.kind == .string and self.via_name.len == 0 and
            !self.swap and !self.trim and !self.unlisted and self.with_key == null and
            self.absent_raw == null and self.stop_raw == null and (!self.optional or wire == .text);
    }
    // a `when` or `const` line: a value the encoder writes
    fn isFixed(self: *const Line) bool {
        return self.tag == .when or self.tag == .constant;
    }
    // Does the line map its locator (so the member is not residue)? A
    // `when <locator> present` on a text wire does not (ruling 27 of 0.5).
    fn maps(self: *const Line) bool {
        if (self.tag == .element) return false;
        return !(self.tag == .when and self.wpresent);
    }
    // Version 0.18: is the line suppressed by `with` for this entity or
    // item? A scalar holds when present, a list when present with at least
    // one item; a `default` never holds (ruling 2).
    fn suppressed(self: *const Line, e: *const Entity) bool {
        const k = self.with_key orelse return false;
        return !e.has(k);
    }
    // The value of the line's own key in the entity, none when the line is
    // suppressed (ruling 1 of 0.18: a suppressed line is absent everywhere).
    fn heldValue(self: *const Line, e: *const Entity) ?MV {
        if (self.suppressed(e)) return null;
        return e.get(self.key);
    }
    // Does the line write its first sentinel for this entity? Its key is
    // absent and it is not suppressed.
    fn sentinelOn(self: *const Line, e: *const Entity) bool {
        return self.abs_set and !self.suppressed(e);
    }
};

const TLoc = enum { whole, column, pair };
// Version 0.20: one value or range `lo..hi` of a `when` list on bits and
// protobuf, both ends included.
const WRange = struct { lo: u64, hi: u64 };

fn inRanges(rs: []const WRange, v: u64) bool {
    for (rs) |r| if (v >= r.lo and v <= r.hi) return true;
    return false;
}

// Is the list more than one single value (ruling 3 applies only then)?
fn isWhenList(rs: []const WRange) bool {
    return rs.len > 1 or (rs.len == 1 and rs[0].lo != rs[0].hi);
}

// `<value>[,<value>…]` on bits and protobuf: unsigned decimal integers or
// ranges `<lo>..<hi>` with lo ≤ hi, each end fitting `width` bits. null: the
// text is `bad-directive`.
fn parseWhenInts(alloc: std.mem.Allocator, text: []const u8, width: usize) !?[]const WRange {
    var out = std.ArrayList(WRange).init(alloc);
    var it = std.mem.splitScalar(u8, text, ',');
    while (it.next()) |item| {
        var lo_t = item;
        var hi_t = item;
        if (std.mem.indexOf(u8, item, "..")) |dd| {
            lo_t = item[0..dd];
            hi_t = item[dd + 2 ..];
        }
        const lo = parseUnsigned(lo_t) orelse return null;
        const hi = parseUnsigned(hi_t) orelse return null;
        if (lo > hi or !fitsBits(hi, width)) return null;
        try out.append(.{ .lo = lo, .hi = hi });
    }
    return out.items;
}

// One text of a `when` list on a text wire; `forced`: written with a leading `=`.
const WAlt = struct { text: []const u8, forced: bool };

// `<value>[,<value>…]` on a text wire: `..` is literal, a comma separates
// values, the empty token alone is the empty text. null: `bad-directive` (an
// empty item, `present` with other values).
fn parseWhenTexts(alloc: std.mem.Allocator, raw: []const u8) !?[]const WAlt {
    var out = std.ArrayList(WAlt).init(alloc);
    if (raw.len == 0) {
        try out.append(.{ .text = "", .forced = false });
        return out.items;
    }
    var it = std.mem.splitScalar(u8, raw, ',');
    var n: usize = 0;
    var present = false;
    while (it.next()) |item| {
        n += 1;
        if (item.len == 0) return null;
        if (std.mem.eql(u8, item, "present")) present = true;
        const forced = item[0] == '=';
        try out.append(.{ .text = if (forced) item[1..] else item, .forced = forced });
    }
    if (present and n > 1) return null;
    return out.items;
}

// Version 0.20: a `requires` term, `<key>` or `<key>=<value>[,<value>…]`.
const ReqTerm = struct {
    key: []const u8,
    vals: ?[]const []const u8 = null, // the `=` values as written
    canon: []const []const u8 = &.{}, // their canonical texts, set at load
    kty: KeyType = .string,
    lineno: usize = 0,
};

// Split a term at its first `=`. null: `k=`, `=v` or an empty item.
fn parseReqTerm(alloc: std.mem.Allocator, tok: []const u8, lineno: usize) !?*ReqTerm {
    const t = try alloc.create(ReqTerm);
    t.* = .{ .key = tok, .lineno = lineno };
    const eq = std.mem.indexOfScalar(u8, tok, '=') orelse return t;
    t.key = tok[0..eq];
    const rest = tok[eq + 1 ..];
    if (t.key.len == 0 or rest.len == 0) return null;
    t.vals = (try splitValueList(alloc, rest)) orelse return null;
    return t;
}

// A comma-separated list with no empty item (ruling 16). null: an empty item.
fn splitValueList(alloc: std.mem.Allocator, text: []const u8) !?[]const []const u8 {
    var out = std.ArrayList([]const u8).init(alloc);
    var it = std.mem.splitScalar(u8, text, ',');
    while (it.next()) |item| {
        if (item.len == 0) return null;
        try out.append(item);
    }
    return out.items;
}

// The canonical text of a `requires =` or `case` value read as the key's
// type (ruling 1); null: it is not of that type. An `int` is an optional `-`
// then digits (ruling 17).
fn canonValue(alloc: std.mem.Allocator, kty: KeyType, text: []const u8) !?[]const u8 {
    return switch (kty) {
        .string => text,
        .int => try intToStr(alloc, parseIntText(text) orelse return null),
        .float => if (isFloatValueText(text)) try floatToStr(alloc, parseDecimal(text) catch return null) else null,
    };
}

// Ruling 24 of 0.20: a float value is `-?digits[.digits]` with an optional
// exponent `e`/`E`, `+`/`-`, digits.
fn isFloatValueText(s: []const u8) bool {
    var i: usize = 0;
    if (i < s.len and s[i] == '-') i += 1;
    const d0 = i;
    while (i < s.len and isDigit(s[i])) i += 1;
    if (i == d0) return false;
    if (i < s.len and s[i] == '.') {
        i += 1;
        const d1 = i;
        while (i < s.len and isDigit(s[i])) i += 1;
        if (i == d1) return false;
    }
    if (i < s.len and (s[i] == 'e' or s[i] == 'E')) {
        i += 1;
        if (i < s.len and (s[i] == '+' or s[i] == '-')) i += 1;
        const d2 = i;
        while (i < s.len and isDigit(s[i])) i += 1;
        if (i == d2) return false;
    }
    return i == s.len;
}

// The canonical text of a model value of a key of type `kty`.
fn canonOfMV(alloc: std.mem.Allocator, kty: KeyType, mv: MV) ![]const u8 {
    return switch (mv) {
        .str => |s| s,
        .int => |i| if (kty == .float) floatToStr(alloc, @floatFromInt(i)) else intToStr(alloc, i),
        .float => |f| floatToStr(alloc, f),
    };
}

fn listHolds(list: []const []const u8, s: []const u8) bool {
    for (list) |v| if (std.mem.eql(u8, v, s)) return true;
    return false;
}

// Does the entity satisfy the term? A plain key: present (a list: with an
// item). With `=`: held, and its canonical text is listed.
fn termHolds(alloc: std.mem.Allocator, t: *const ReqTerm, e: *const Entity) bool {
    if (t.vals == null) return e.has(t.key);
    const mv = e.get(t.key) orelse return false;
    const c = canonOfMV(alloc, t.kty, mv) catch return false;
    return listHolds(t.canon, c);
}

// A value check of ruling 19, step 5, in line order: a `requires =` term or a
// `case` line.
const VCheck = union(enum) {
    req: *ReqTerm,
    case_: struct { sw: *SSwitch, cs: *SCase },
};

const Kind = struct {
    name: []const u8,
    lines: std.ArrayList(Line),
    requires: std.ArrayList(*ReqTerm),
    defaults: std.ArrayList(Default),
    // xml: this kind's root element; null uses the pack's
    root: ?[]const u8 = null,
    // common lines then this kind's lines
    scope: Scope = .{},
    gates: std.ArrayListUnmanaged(*Gate) = .{},
};

// A key named by a `field` (with its transform) or a `requires` line, in file
// order, for the Version 0.4 load checks.
const KeyUse = struct {
    key: []const u8,
    tkind: ?TKind,
    via: []const u8 = "",
    // `as_`: the key a sequential `when … as <key>` binds (Version 0.30)
    use: enum { field, group, requires, default, with, as_ } = .field,
    // a `requires <key>=…` term (Version 0.20)
    eq: bool = false,
    // the innermost group the line is in: `model_keys` lists a key inside a
    // group as `<list>[].<key>`
    grp: ?*const Group = null,
    // a `requires` line of a kind in a group body (an item kind)
    item: bool = false,
};

const Pack = struct {
    format: []const u8,
    version: []const u8,
    wire: Wire,
    root: []const u8 = "",
    word_bytes: usize = 0,
    // the bit order (`lsb`, `msb`, and `msb-lsb` of Version 0.22)
    msb: BitOrd = .lsb,
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
    // the three directives as written, and the first line that repeats one
    // or gives one after the first `kind`
    delim_raw: ?[]const u8 = null,
    start_raw: ?[]const u8 = null,
    cksum_raw: ?[]const u8 = null,
    tdir_bad: usize = 0,
    // Version 0.13, the `tlv` wire: `tag` and `length` (0: ber-oid, ber;
    // else a fixed number of bytes), the key's bytes, the `sum16` tag; and
    // the directives as written (`checksum sum16 <tag>` keeps its tag in
    // `cksum_arg`)
    tlv_tag: u8 = 0,
    tlv_len: u8 = 0,
    tlv_key: []const u8 = "",
    tlv_sum: ?u32 = null,
    // Version 0.27: the checksum item is a four-byte CRC-32 (`checksum crc32
    // <tag>`, its tag in `tlv_sum`), else the two-byte sum of 0.13
    tlv_crc: bool = false,
    tag_raw: ?[]const u8 = null,
    len_raw: ?[]const u8 = null,
    key_raw: ?[]const u8 = null,
    cksum_arg: ?[]const u8 = null,
    // Version 0.14: `armor sixbit` (else hex); the value as written, and the
    // first line that repeats it, gives it after a `kind` or gives it with
    // another number of values; checked after the file is read
    armor: bool = false,
    armor_raw: ?[]const u8 = null,
    armor_bad: usize = 0,
    // Version 0.17: the gate blocks of the common lines, and the line of the
    // first gate of the pack (0: none)
    common_gates: std.ArrayListUnmanaged(*Gate) = .{},
    gate_line: usize = 0,
    // Version 0.18: the line of the first `element` line (0: none)
    element_line: usize = 0,
    // Version 0.19: `encoding` as written and the first line that repeats
    // it, gives it after a `kind` or with another number of values;
    // `encoding uper`; the first line that only a UPER pack takes (a UPER
    // locator, `ext`, `choice`, `alt`, `group … size`). Checked after the
    // file is read.
    enc_raw: ?[]const u8 = null,
    enc_bad: usize = 0,
    // Version 0.92: the line of `framing self` (0: none), and the first that
    // is not `framing self`, is a second one or stands after a kind
    framing_line: usize = 0,
    framing_bad: usize = 0,
    uper: bool = false,
    uper_line: usize = 0,
    // Version 0.20: the `requires =` terms and `case` lines, in line order,
    // for the value checks at load; does the sequential pack hold a `switch`
    vchecks: std.ArrayListUnmanaged(VCheck) = .{},
    seq_switch: bool = false,
    // Version 0.46: the `charset` lines, and the first one that stands after
    // the first message kind (0: none)
    charsets: std.ArrayListUnmanaged(*CodeSet) = .{},
    charset_late: usize = 0,
    // Version 0.33: the first `at` form error and the first window not fixed
    // in its kind, reported last among the module checks (rulings 10, 25)
    at_err: ?[]const u8 = null,
    win_err: ?[]const u8 = null,
    // Version 0.28, the `cbor` wire: the top item is an array (else a map),
    // and `tag <n>`
    cbor_array: bool = false,
    cbor_tag: ?u64 = null,
    // Version 0.34: the `inner` lines in file order, each with the number of
    // key uses read before it (its place in reading order for `model_keys`)
    inners: std.ArrayListUnmanaged(InnerMark) = .{},
    // Version 0.92: does an `inner` line hold the word `run` (a carrier pack)?
    has_run: bool = false,
    // Version 0.52, ruling 20, and Version 0.94: where in `key_uses` each
    // message kind begins
    kind_starts: std.ArrayListUnmanaged(usize) = .{},

    fn charset(self: *const Pack, name: []const u8) ?*const CodeSet {
        for (self.charsets.items) |c| if (std.mem.eql(u8, c.name, name)) return c;
        return null;
    }

    // A `charset` line, kept as written until the file is read.
    fn addCharset(self: *Pack, alloc: std.mem.Allocator, toks: []const []const u8, lineno: usize, late: bool) !void {
        if (late and self.charset_late == 0) self.charset_late = lineno;
        const c = try alloc.create(CodeSet);
        c.* = .{ .name = toks[1], .chars = toks[2], .width_raw = if (toks.len > 3) toks[3] else null, .lineno = lineno };
        try self.charsets.append(alloc, c);
    }

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

    // The name of message kind `i` (fixed or sequential layout).
    fn kindName(self: *const Pack, i: usize) []const u8 {
        if (self.seq) |b| return if (i < b.kinds.len) b.kinds[i].name else "";
        return if (i < self.kinds.items.len) self.kinds.items[i].name else "";
    }

    fn kindIndex(self: *const Pack, name: []const u8) ?usize {
        for (self.kinds.items, 0..) |k, i| if (std.mem.eql(u8, k.name, name)) return i;
        return null;
    }
};

// Version 0.34: an `inner <format>` line of a sequential pack.
// `kind`: 0 in the common lines, else the number of its message kind from 1.
const InnerMark = struct { fmt: []const u8, pos: usize, lineno: usize, kind: usize, run: bool };

// Does an `inner` line of the pack name the format?
fn packHasInner(p: *const Pack, fmt: []const u8) bool {
    for (p.inners.items) |im| if (std.mem.eql(u8, im.fmt, fmt)) return true;
    return false;
}

// model_keys(format): the union of keys over common and all kinds, in first
// appearance order. A list is `<list>[]`, an item key `<list>[].<key>`, nested
// lists likewise.
fn modelKeys(alloc: std.mem.Allocator, p: *const Pack) ![]const []const u8 {
    var out = std.ArrayList([]const u8).init(alloc);
    var seen = std.StringHashMap(void).init(alloc);
    for (p.key_uses.items) |ku| {
        // `requires` and `default` keys are not mapped keys; a `when … as`
        // key is (rulings 5 and 24 of 0.30)
        if (ku.use != .field and ku.use != .group and ku.use != .as_) continue;
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

const DFn = enum {
    copy,
    hypot,
    bearing,
    east_of,
    north_of,
    neg,
    scale,
    offset,
    join,
    day_seconds,
    any,
    not,
    parse_int,
    text_of,
    present, // Version 0.12
    // Version 0.18
    tokens,
    has_token,
    text_if,
    // Version 0.16
    sec_of,
    nsec_of,
    ms_of,
    deg,
    rad,
    add,
    sub,
    deg_lat_of,
    deg_lon_of,
    m_lat_of,
    m_lon_of,
    ecef_x,
    ecef_y,
    ecef_z,
    lat_of_ecef,
    lon_of_ecef,
    hae_of_ecef,
};

// The derive functions of Version 0.16 that take no parameter: the name, the
// argument count, and whether the arguments and the target are `int` (null:
// `add` / `sub`, all `int` or all `float`, ruling 4 of 0.16).
const Fn16 = struct { name: []const u8, f: DFn, nargs: usize, int_args: ?bool, int_target: bool };
const fns16 = [_]Fn16{
    .{ .name = "sec_of", .f = .sec_of, .nargs = 1, .int_args = true, .int_target = true },
    .{ .name = "nsec_of", .f = .nsec_of, .nargs = 1, .int_args = true, .int_target = true },
    .{ .name = "ms_of", .f = .ms_of, .nargs = 2, .int_args = true, .int_target = true },
    .{ .name = "deg", .f = .deg, .nargs = 1, .int_args = false, .int_target = false },
    .{ .name = "rad", .f = .rad, .nargs = 1, .int_args = false, .int_target = false },
    .{ .name = "add", .f = .add, .nargs = 2, .int_args = null, .int_target = false },
    .{ .name = "sub", .f = .sub, .nargs = 2, .int_args = null, .int_target = false },
    .{ .name = "deg_lat_of", .f = .deg_lat_of, .nargs = 2, .int_args = false, .int_target = false },
    .{ .name = "deg_lon_of", .f = .deg_lon_of, .nargs = 2, .int_args = false, .int_target = false },
    .{ .name = "m_lat_of", .f = .m_lat_of, .nargs = 2, .int_args = false, .int_target = false },
    .{ .name = "m_lon_of", .f = .m_lon_of, .nargs = 2, .int_args = false, .int_target = false },
    .{ .name = "ecef_x", .f = .ecef_x, .nargs = 3, .int_args = false, .int_target = false },
    .{ .name = "ecef_y", .f = .ecef_y, .nargs = 3, .int_args = false, .int_target = false },
    .{ .name = "ecef_z", .f = .ecef_z, .nargs = 3, .int_args = false, .int_target = false },
    .{ .name = "lat_of_ecef", .f = .lat_of_ecef, .nargs = 3, .int_args = false, .int_target = false },
    .{ .name = "lon_of_ecef", .f = .lon_of_ecef, .nargs = 3, .int_args = false, .int_target = false },
    .{ .name = "hae_of_ecef", .f = .hae_of_ecef, .nargs = 3, .int_args = false, .int_target = false },
};

fn find16(head: []const u8) ?Fn16 {
    for (fns16) |f| if (std.mem.eql(u8, f.name, head)) return f;
    return null;
}

// One `derive <model-key> <function> <argument-key>…` line of a module.
const Derive = struct {
    target: []const u8,
    f: DFn,
    args: []const []const u8,
    factor: Factor = .{}, // scale
    int_mode: bool = false, // offset on an int target and argument
    off_f: f64 = 0,
    off_i: i64 = 0,
    sep: []const u8 = "", // join; tokens and has_token: the separator
    toks: []const []const u8 = &.{}, // tokens; has_token: the one token
    text: []const u8 = "", // text_if
};

// Version 0.18: whitespace for the parameters of `tokens`, `has_token` and
// `text_if`.
fn isWs(c: u8) bool {
    return c == ' ' or c == '\t' or c == '\n' or c == '\r';
}

// A separator: `space`, `comma`, `colon`, or one code point other than `:`,
// `,` or whitespace.
fn parseSep(st: []const u8) ?[]const u8 {
    if (std.mem.eql(u8, st, "space")) return " ";
    if (std.mem.eql(u8, st, "comma")) return ",";
    if (std.mem.eql(u8, st, "colon")) return ":";
    if (st.len == 0) return null;
    const n = std.unicode.utf8ByteSequenceLength(st[0]) catch return null;
    if (n != st.len or !std.unicode.utf8ValidateSlice(st)) return null;
    if (n == 1 and (st[0] == ':' or st[0] == ',' or isWs(st[0]))) return null;
    return st;
}

// Version 0.64: is the text, up to its first `:`, the word `part`?
fn isPartWord(s: []const u8) bool {
    return std.mem.eql(u8, s[0 .. std.mem.indexOfScalar(u8, s, ':') orelse s.len], "part");
}

// `part:<sep>:<n>`, n 0 to 255 without leading zeros.
fn parsePart(s: []const u8) !Transform {
    const bd = E.@"bad-directive";
    var it = std.mem.splitScalar(u8, s, ':');
    _ = it.next();
    const st = it.next() orelse return bd;
    const ns = it.next() orelse return bd;
    if (it.next() != null) return bd;
    const n = parseUnsigned(ns) orelse return bd;
    if (n > 255 or (ns.len > 1 and ns[0] == '0')) return bd;
    return .{ .kind = .part, .psep = parseSep(st) orelse return bd, .pn = @intCast(n) };
}

// The parameter of `tokens:<sep>:<t…>` or `has_token:<sep>:<t>` (the text
// after the function name and its colon): the separator, and the tokens.
// null: it does not parse, a token is empty or repeated.
const SepParam = struct { sep: []const u8, toks: []const []const u8 };

fn parseSepParam(alloc: std.mem.Allocator, param: []const u8) ?SepParam {
    const c = std.mem.indexOfScalar(u8, param, ':') orelse return null;
    const sep = parseSep(param[0..c]) orelse return null;
    const rest = param[c + 1 ..];
    var list = std.ArrayList([]const u8).init(alloc);
    var it = std.mem.splitScalar(u8, rest, ',');
    while (it.next()) |t| {
        if (t.len == 0) return null;
        for (t) |ch| if (ch == ':' or isWs(ch)) return null;
        if (std.mem.indexOf(u8, t, sep) != null) return null;
        for (list.items) |prev| if (std.mem.eql(u8, prev, t)) return null;
        list.append(t) catch return null;
    }
    return .{ .sep = sep, .toks = list.items };
}

// `text_if:<text>`: one or more characters other than whitespace.
fn textIfOk(text: []const u8) bool {
    if (text.len == 0) return false;
    for (text) |ch| if (isWs(ch)) return false;
    return true;
}

// The type a transform yields (spec: "The type a transform yields").
fn yields(k: TKind) KeyType {
    return switch (k) {
        .string, .pstring, .ascii, .sixbit, .utf8, .hex, .chars, .octal, .text_, .bytes, .code, .codestr, .part => .string,
        .float, .linscale, .uscale, .sscale, .f32_, .f64_, .pdouble, .pfloat, .dec, .dm, .hms, .smscale, .f32scale, .f64scale, .tscale => .float,
        .int, .iso8601_ms, .iso8601_short, .iso8601_s, .bool_, .uint, .twos, .pvarint, .psint, .int_w, .hms_dmy, .uiscale, .siscale, .smag, .iscale, .epoch_s, .codenum => .int,
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
// neither the factor nor either part is zero, and the fraction of every float
// scale transform has an unsigned `num` (ruling 25 of 0.15: a negative factor
// is written as a decimal); for the `scale` derive function, which is not a
// transform, `<num>` may carry a `-` (ruling 2c of 0.11).
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

// Version 0.15, Exact factors: `[-]digits[.digits]` or `[-]num/den`, the
// exact value in lowest terms, numerator and denominator at most 2^32, not 0.
fn parseExactFactor(alloc: std.mem.Allocator, s: []const u8) !?[2]i64 {
    const neg = s.len > 0 and s[0] == '-';
    const body = if (neg) s[1..] else s;
    var nstr: []const u8 = undefined;
    var dstr: ?[]const u8 = null; // the denominator's digits, for a fraction
    var frac_digits: usize = 0;
    if (std.mem.indexOfScalar(u8, body, '/')) |slash| {
        nstr = body[0..slash];
        dstr = body[slash + 1 ..];
        if (!allDigits(nstr) or !allDigits(dstr.?)) return null;
    } else if (std.mem.indexOfScalar(u8, body, '.')) |dot| {
        const ip = body[0..dot];
        const fp = body[dot + 1 ..];
        if (!allDigits(ip) or !allDigits(fp)) return null;
        nstr = try std.mem.concat(alloc, u8, &.{ ip, fp });
        frac_digits = fp.len;
    } else {
        if (!allDigits(body)) return null;
        nstr = body;
    }
    var n = try std.math.big.int.Managed.init(alloc);
    defer n.deinit();
    var d = try std.math.big.int.Managed.init(alloc);
    defer d.deinit();
    try n.setString(10, nstr);
    if (dstr) |ds| {
        try d.setString(10, ds);
    } else {
        var ten = try std.math.big.int.Managed.initSet(alloc, 10);
        defer ten.deinit();
        try d.pow(&ten, @intCast(frac_digits));
    }
    if (n.eqlZero() or d.eqlZero()) return null;
    var g = try std.math.big.int.Managed.init(alloc);
    defer g.deinit();
    try g.gcd(&n, &d);
    var q = try std.math.big.int.Managed.init(alloc);
    defer q.deinit();
    var r = try std.math.big.int.Managed.init(alloc);
    defer r.deinit();
    try q.divTrunc(&r, &n, &g);
    try n.copy(q.toConst());
    try q.divTrunc(&r, &d, &g);
    try d.copy(q.toConst());
    const lim: u64 = 1 << 32;
    const nv = n.to(u64) catch return null;
    const dv = d.to(u64) catch return null;
    if (nv > lim or dv > lim) return null;
    const ni: i64 = @intCast(nv);
    return .{ if (neg) -ni else ni, @intCast(dv) };
}

// Version 0.15: an integer offset, `[-]digits`, absolute value below 2^63.
fn parseExactOffset(s: []const u8) ?i64 {
    const body = if (s.len > 0 and s[0] == '-') s[1..] else s;
    if (!allDigits(body)) return null;
    const v = std.fmt.parseInt(i64, s, 10) catch return null;
    if (v == std.math.minInt(i64)) return null;
    return v;
}

fn parseTransform(alloc: std.mem.Allocator, s: []const u8) !Transform {
    const simple = [_]struct { n: []const u8, k: TKind }{
        .{ .n = "string", .k = .string },   .{ .n = "float", .k = .float },
        .{ .n = "int", .k = .int },         .{ .n = "iso8601_ms", .k = .iso8601_ms }, .{ .n = "iso8601_short", .k = .iso8601_short }, .{ .n = "iso8601_s", .k = .iso8601_s },
        .{ .n = "bool", .k = .bool_ },      .{ .n = "uint", .k = .uint },
        .{ .n = "twos", .k = .twos },       .{ .n = "f32", .k = .f32_ },
        .{ .n = "f64", .k = .f64_ },        .{ .n = "ascii", .k = .ascii },
        .{ .n = "sixbit", .k = .sixbit },
        .{ .n = "pstring", .k = .pstring }, .{ .n = "pvarint", .k = .pvarint },
        .{ .n = "psint", .k = .psint },     .{ .n = "pdouble", .k = .pdouble },
        .{ .n = "pfloat", .k = .pfloat },
        .{ .n = "utf8", .k = .utf8 },       .{ .n = "hex", .k = .hex },
        .{ .n = "text", .k = .text_ },      .{ .n = "bytes", .k = .bytes },
        .{ .n = "epoch_s", .k = .epoch_s },
    };
    for (simple) |e| if (std.mem.eql(u8, s, e.n)) return .{ .kind = e.k };

    var it = std.mem.splitScalar(u8, s, ':');
    const head = it.next() orelse return E.@"unknown-transform";
    if (std.mem.eql(u8, head, "part")) return parsePart(s);
    // Version 0.46: every error of the list is a check after the file, a
    // missing list included (ruling 15)
    for ([_]struct { n: []const u8, k: TKind }{ .{ .n = "code", .k = .code }, .{ .n = "codestr", .k = .codestr }, .{ .n = "codenum", .k = .codenum } }) |e| {
        if (std.mem.eql(u8, head, e.n)) return .{ .kind = e.k, .sets_raw = if (s.len > head.len) s[head.len + 1 ..] else "" };
    }
    // A parameter on a transform that takes none is `bad-directive` (ruling
    // 27 of 0.22). `int:<w>` is the transform of the `text` wire.
    for (simple) |e| {
        if (std.mem.eql(u8, head, e.n) and !std.mem.eql(u8, head, "int")) return E.@"bad-directive";
    }
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
    const th = std.meta.stringToEnum(TextHead, head) orelse return parseValueTransform(alloc, head, s[head.len..]);
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

// The transforms of Version 0.15. `rest` is the text after the name: empty,
// or `:` and the parameters. A parameter that does not parse is
// `bad-directive`; a name that is not one of them is an unknown transform.
fn parseValueTransform(alloc: std.mem.Allocator, head: []const u8, rest: []const u8) !Transform {
    const bd = E.@"bad-directive";
    const Shape = enum { exact, float, none, chars };
    const names = [_]struct { n: []const u8, k: TKind, shape: Shape }{
        .{ .n = "uiscale", .k = .uiscale, .shape = .exact },
        .{ .n = "siscale", .k = .siscale, .shape = .exact },
        .{ .n = "iscale", .k = .iscale, .shape = .exact },
        .{ .n = "smag", .k = .smag, .shape = .none },
        .{ .n = "octal", .k = .octal, .shape = .none },
        .{ .n = "smscale", .k = .smscale, .shape = .float },
        .{ .n = "f32scale", .k = .f32scale, .shape = .float },
        .{ .n = "f64scale", .k = .f64scale, .shape = .float },
        .{ .n = "scale", .k = .tscale, .shape = .float },
        .{ .n = "chars", .k = .chars, .shape = .chars },
    };
    for (names) |en| {
        if (!std.mem.eql(u8, head, en.n)) continue;
        var t = Transform{ .kind = en.k };
        if (en.shape == .none) {
            if (rest.len != 0) return bd;
            return t;
        }
        if (rest.len == 0) return bd; // the parameter is missing
        var it = std.mem.splitScalar(u8, rest[1..], ':');
        const a = it.next().?;
        const b = it.next();
        if (it.next() != null) return bd;
        switch (en.shape) {
            .chars => {
                if (b != null) return bd;
                t.cset = std.meta.stringToEnum(CharSet, a) orelse return bd;
            },
            .exact => {
                const f = (try parseExactFactor(alloc, a)) orelse return bd;
                t.num = f[0];
                t.den = f[1];
                if (b) |off| t.ioff = parseExactOffset(off) orelse return bd;
            },
            .float => {
                t.factor = parseFactor(a, true) orelse return bd;
                if (b) |off| t.offset = parseDecimal(off) catch return bd;
            },
            .none => unreachable,
        }
        return t;
    }
    return E.@"unknown-transform";
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
    if (find16(head)) |fn16| {
        if (param != null or d.args.len != fn16.nargs) return null;
        if (fn16.int_args) |ints| {
            const want: KeyType = if (ints) .int else .float;
            const want_t: KeyType = if (fn16.int_target) .int else .float;
            if (tt != want_t) return null;
            for (at) |ty| if (ty != want) return null;
        } else {
            // add / sub: the target and both arguments all `int` or all `float`
            if (tt != .int and tt != .float) return null;
            for (at) |ty| if (ty != tt) return null;
            d.int_mode = tt == .int;
        }
        d.f = fn16.f;
        return d;
    }
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
    } else if (eq(u8, head, "present") and param == null) {
        // any scalar argument; the result is an int (Version 0.12)
        if (d.args.len != 1 or tt != .int) return null;
        d.f = .present;
    } else if (eq(u8, head, "tokens")) {
        const sp = parseSepParam(alloc, param orelse return null) orelse return null;
        if (sp.toks.len != d.args.len or tt != .string) return null;
        for (at) |ty| if (ty != .int) return null;
        d.f = .tokens;
        d.sep = sp.sep;
        d.toks = sp.toks;
    } else if (eq(u8, head, "has_token")) {
        const sp = parseSepParam(alloc, param orelse return null) orelse return null;
        if (sp.toks.len != 1 or d.args.len != 1 or at[0] != .string or tt != .int) return null;
        d.f = .has_token;
        d.sep = sp.sep;
        d.toks = sp.toks;
    } else if (eq(u8, head, "text_if")) {
        const text = param orelse return null;
        if (!textIfOk(text) or d.args.len != 1 or at[0] != .int or tt != .string) return null;
        d.f = .text_if;
        d.text = text;
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
        .{ .name = "present", .param = false, .min = 1, .max = 1 },
    };
    if (find16(head)) |fn16| return colon == null and nargs == fn16.nargs;
    // Version 0.18: the parameter, and the argument count it fixes
    if (std.mem.eql(u8, head, "tokens") or std.mem.eql(u8, head, "has_token")) {
        const c = colon orelse return false;
        var fba_buf: [4096]u8 = undefined;
        var fba = std.heap.FixedBufferAllocator.init(&fba_buf);
        const sp = parseSepParam(fba.allocator(), fname[c + 1 ..]) orelse return false;
        if (std.mem.eql(u8, head, "has_token")) return sp.toks.len == 1 and nargs == 1;
        return sp.toks.len == nargs;
    }
    if (std.mem.eql(u8, head, "text_if")) {
        const c = colon orelse return false;
        return textIfOk(fname[c + 1 ..]) and nargs == 1;
    }
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

// Version 0.46: the `charset` lines, once the file is read. The width counts
// on `bits` only (ruling 14).
fn charsetCheck(alloc: std.mem.Allocator, p: *Pack, diag: *Diag) anyerror!void {
    const bd = E.@"bad-directive";
    if (p.charset_late != 0) return bad(diag, alloc, bd, "line {d}: charset after the first kind", .{p.charset_late});
    for (p.charsets.items, 0..) |c, i| {
        if (c.name.len == 0) return bad(diag, alloc, bd, "line {d}: charset with an empty name", .{c.lineno});
        for (c.name) |ch| {
            if (!std.ascii.isAlphanumeric(ch) and ch != '_' and ch != '-') return bad(diag, alloc, bd, "line {d}: charset name {s} holds a character other than A-Z, a-z, 0-9, _ and -", .{ c.lineno, c.name });
        }
        for (p.charsets.items[0..i]) |o| {
            if (std.mem.eql(u8, o.name, c.name)) return bad(diag, alloc, bd, "line {d}: charset {s} is declared twice", .{ c.lineno, c.name });
        }
        if (c.chars.len == 0) return bad(diag, alloc, bd, "line {d}: charset {s} holds no character", .{ c.lineno, c.name });
        for (c.chars, 0..) |ch, j| {
            if (ch < 0x21 or ch > 0x7e) return bad(diag, alloc, bd, "line {d}: charset {s} holds a character outside 0x21 to 0x7E", .{ c.lineno, c.name });
            if (std.mem.indexOfScalar(u8, c.chars[0..j], ch) != null) return bad(diag, alloc, bd, "line {d}: charset {s} holds a character twice", .{ c.lineno, c.name });
        }
        if (p.wire != .bits) continue;
        // max(1, ceil(log2(size))); at most 94 characters, so at most 7
        c.width = @max(1, std.math.log2_int_ceil(usize, c.chars.len));
        if (c.width_raw) |raw| {
            const w = if (allDigits(raw)) parseUnsigned(raw) else null;
            if (w == null or w.? < c.width or w.? > 8) return bad(diag, alloc, bd, "line {d}: charset {s}: the width {s} is not {d} to 8", .{ c.lineno, c.name, raw, c.width });
            c.width = @intCast(w.?);
        }
    }
}

// Version 0.46: the sets a `code`, `codestr` or `codenum` list names, first
// position first.
fn resolveCodeSets(alloc: std.mem.Allocator, p: *const Pack, ln: *Line, diag: *Diag) anyerror!void {
    const bd = E.@"bad-directive";
    const t = &ln.transform;
    if (!isCode(t.kind)) return;
    if (t.sets_raw.len == 0) return bad(diag, alloc, bd, "line {d}: {s} names no position", .{ ln.lineno, @tagName(t.kind) });
    var sets = std.ArrayListUnmanaged(*const CodeSet){};
    var product: u128 = 1;
    var it = std.mem.splitScalar(u8, t.sets_raw, ',');
    while (it.next()) |name| {
        if (sets.items.len == max_positions) return bad(diag, alloc, bd, "line {d}: {s} names more than {d} positions", .{ ln.lineno, @tagName(t.kind), max_positions });
        const c = p.charset(name) orelse return bad(diag, alloc, bd, "line {d}: {s}: no charset is named `{s}`", .{ ln.lineno, @tagName(t.kind), name });
        // a character the record cannot carry (ruling 12)
        if (isW(p.wire, .text)) {
            if (p.delim) |d| if (c.codeOf(d) != null) return bad(diag, alloc, bd, "line {d}: charset {s} holds the delimiter", .{ ln.lineno, name });
            if (p.nmea and c.codeOf('*') != null) return bad(diag, alloc, bd, "line {d}: charset {s} holds a * under checksum nmea", .{ ln.lineno, name });
        }
        product *= c.chars.len; // at most 94^16, below 2^128
        try sets.append(alloc, c);
    }
    if (t.kind == .codenum and product > (@as(u128, 1) << 63)) return bad(diag, alloc, bd, "line {d}: codenum: the product of the sizes is above 2^63", .{ln.lineno});
    t.sets = sets.items;
}

// The codes of a text, one character per position, each in its set; null
// when the text does not have that form.
fn codesOfText(t: Transform, text: []const u8) ?[max_positions]u64 {
    if (text.len != t.sets.len) return null;
    var codes = [_]u64{0} ** max_positions;
    for (t.sets, text, 0..) |c, ch, i| codes[i] = c.codeOf(ch) orelse return null;
    return codes;
}

// The value of codes that lie within their sets: the characters, or for
// `codenum` the mixed-radix number, first position most significant.
fn valueOfCodes(alloc: std.mem.Allocator, t: Transform, codes: [max_positions]u64) !MV {
    if (t.kind == .codenum) {
        // the product of the sizes is at most 2^63
        var v: u64 = 0;
        for (t.sets, 0..) |c, i| v = v * c.chars.len + codes[i];
        return MV{ .int = @intCast(v) };
    }
    const out = try alloc.alloc(u8, t.sets.len);
    for (t.sets, 0..) |c, i| out[i] = c.chars[@intCast(codes[i])];
    return MV{ .str = out };
}

// The codes of a model value (encode).
fn codesOfValue(t: Transform, mv: MV) ![max_positions]u64 {
    const te = E.@"transform-encode";
    if (t.kind != .codenum) {
        if (mv != .str) return te;
        return codesOfText(t, mv.str) orelse te;
    }
    if (mv != .int or mv.int < 0) return te;
    var codes = [_]u64{0} ** max_positions;
    var x: u64 = @intCast(mv.int);
    var i = t.sets.len;
    while (i > 0) {
        i -= 1;
        codes[i] = x % t.sets[i].chars.len;
        x /= t.sets[i].chars.len;
    }
    if (x != 0) return te;
    return codes;
}

// `codestr` and `codenum` on the text wires.
fn codeTextDecode(alloc: std.mem.Allocator, t: Transform, raw: []const u8) !MV {
    return valueOfCodes(alloc, t, codesOfText(t, raw) orelse return E.@"transform-decode");
}

fn codeTextEncode(alloc: std.mem.Allocator, t: Transform, mv: MV) ![]const u8 {
    const codes = try codesOfValue(t, mv);
    const out = try alloc.alloc(u8, t.sets.len);
    for (t.sets, 0..) |c, i| out[i] = c.chars[@intCast(codes[i])];
    return out;
}

// On `json` and `geojson` the member is a string (ruling 11).
fn codeJsonDecode(alloc: std.mem.Allocator, t: Transform, v: JValue) !MV {
    if (v != .string) return E.@"transform-decode";
    return codeTextDecode(alloc, t, v.string);
}

// `code` and `codenum` on bits: the field as `uint` reads it, position 0 at
// its most significant end whatever the bit order (ruling 6).
fn codeBitsDecode(alloc: std.mem.Allocator, t: Transform, bits: u64) !MV {
    var codes = [_]u64{0} ** max_positions;
    var v = bits;
    var i = t.sets.len;
    while (i > 0) {
        i -= 1;
        const c = t.sets[i];
        const w: u6 = @intCast(c.width); // at most 8
        codes[i] = v & ((@as(u64, 1) << w) - 1);
        v >>= w;
        if (codes[i] >= c.chars.len) return E.@"transform-decode";
    }
    return valueOfCodes(alloc, t, codes);
}

fn codeBitsEncode(t: Transform, mv: MV) !u64 {
    const codes = try codesOfValue(t, mv);
    var v: u64 = 0;
    for (t.sets, 0..) |c, i| v = (v << @as(u6, @intCast(c.width))) | codes[i];
    return v;
}

// Version 0.64: what one line of a part group must be, once the file is read.
fn partLineCheck(alloc: std.mem.Allocator, p: *const Pack, ln: *const Line, in_group: bool, diag: *Diag) anyerror!void {
    const bd = E.@"bad-directive";
    if (ln.unlisted and (!ln.isPart() or ln.via_name.len == 0)) return bad(diag, alloc, bd, "line {d}: unlisted is an option of a part line with via", .{ln.lineno});
    if (!ln.isPart()) return;
    if (p.wire != .xml and p.wire != .json and p.wire != .geojson and p.wire != .text) return bad(diag, alloc, bd, "line {d}: part on the {s} wire", .{ ln.lineno, @tagName(p.wire) });
    if (p.wire == .geojson and !in_group and std.mem.startsWith(u8, ln.locator, geom_prefix)) return bad(diag, alloc, bd, "line {d}: part on the coordinate {s}", .{ ln.lineno, ln.locator });
    if (isW(p.wire, .text)) {
        if (std.mem.indexOfAny(u8, ln.locator, ":+") != null) return bad(diag, alloc, bd, "line {d}: part on the column or pair {s}", .{ ln.lineno, ln.locator });
        const sep = ln.transform.psep;
        if (p.delim) |d| if (sep.len == 1 and sep[0] == d) return bad(diag, alloc, bd, "line {d}: the separator of the part is the delimiter", .{ln.lineno});
        if (p.nmea and std.mem.eql(u8, sep, "*")) return bad(diag, alloc, bd, "line {d}: the separator * under checksum nmea", .{ln.lineno});
    }
    if (ln.tag == .field) {
        if (ln.swap or ln.trim or ln.stop_raw != null or ln.absent_raw != null or ln.with_key != null or (ln.optional and p.wire != .text)) {
            return bad(diag, alloc, bd, "line {d}: a part line takes via, unlisted and, on the text wire, optional", .{ln.lineno});
        }
        return;
    }
    const text = if (ln.wraw.len > 0 and ln.wraw[0] == '=') ln.wraw[1..] else ln.wraw;
    if (text.len == 0) return bad(diag, alloc, bd, "line {d}: an empty const part", .{ln.lineno});
    if (std.mem.indexOf(u8, text, ln.transform.psep) != null) return bad(diag, alloc, bd, "line {d}: the const part {s} holds the separator", .{ ln.lineno, text });
}

// The part groups of one scope: the lines `a` then `b` (common plus one kind,
// or one group body; rulings 6 and 19 of 0.64).
fn partScopeCheck(alloc: std.mem.Allocator, p: *const Pack, a: []const Line, b: []const Line, diag: *Diag) anyerror!void {
    const bd = E.@"bad-directive";
    const both = [2][]const Line{ a, b };
    var done = std.StringHashMap(void).init(alloc);
    defer done.deinit();
    for (both) |ls| for (ls) |*pl| {
        if (!pl.isPart()) continue;
        if ((try done.getOrPut(pl.locator)).found_existing) continue;
        const loc = pl.locator;
        var named = [_]bool{false} ** 256;
        var high: usize = 0;
        var any_field = false;
        var whole: ?*const Line = null;
        for (both) |lines| for (lines) |*ln| {
            if (!std.mem.eql(u8, ln.locator, loc) or ln.tag == .element) continue;
            if (ln.isPart()) {
                if (!std.mem.eql(u8, ln.transform.psep, pl.transform.psep)) return bad(diag, alloc, bd, "line {d}: a second separator at {s}", .{ ln.lineno, loc });
                const n = ln.transform.pn;
                if (named[n]) return bad(diag, alloc, bd, "line {d}: part {d} of {s} is named twice", .{ ln.lineno, n, loc });
                named[n] = true;
                high = @max(high, n);
                if (ln.tag == .field) any_field = true;
            } else if (ln.isPlainString(p.wire)) {
                if (whole != null) return bad(diag, alloc, bd, "line {d}: a second whole line at {s}", .{ ln.lineno, loc });
                whole = ln;
            } else return bad(diag, alloc, bd, "line {d}: {s} at {s}, which a part line splits", .{ ln.lineno, @tagName(ln.tag), loc });
        };
        if (!any_field) return bad(diag, alloc, bd, "line {d}: no part of {s} is a field", .{ pl.lineno, loc });
        for (named[0 .. high + 1], 0..) |on, n| if (!on) return bad(diag, alloc, bd, "line {d}: no line names part {d} of {s}", .{ pl.lineno, n, loc });
        if (whole) |w| for (both) |lines| for (lines) |*ln| {
            if (ln.tag == .field and ln.isPart() and std.mem.eql(u8, ln.locator, loc) and std.mem.eql(u8, ln.key, w.key)) {
                return bad(diag, alloc, bd, "line {d}: the key {s} is on a part and on the whole of {s}", .{ ln.lineno, w.key, loc });
            }
        };
    };
}

fn partBodyChecks(alloc: std.mem.Allocator, p: *const Pack, lines: []const Line, diag: *Diag) anyerror!void {
    for (lines) |*ln| {
        if (ln.tag != .group) continue;
        try partScopeCheck(alloc, p, ln.grp.?.lines, &.{}, diag);
        try partBodyChecks(alloc, p, ln.grp.?.lines, diag);
    }
}

// The part groups of a scope's lines. A group that a kind completes is not
// one of the common lines alone.
fn buildParts(alloc: std.mem.Allocator, lines: []const Line) ![]const PartGroup {
    var out = std.ArrayListUnmanaged(PartGroup){};
    next: for (lines, 0..) |*pl, at| {
        if (!pl.isPart()) continue;
        for (lines[0..at]) |*x| if (x.isPart() and std.mem.eql(u8, x.locator, pl.locator)) continue :next;
        var by = [_]?*const Line{null} ** 256;
        var count: usize = 0;
        var first: ?*const Line = null;
        var whole: ?*const Line = null;
        for (lines) |*ln| {
            if ((ln.tag != .field and ln.tag != .constant) or !std.mem.eql(u8, ln.locator, pl.locator)) continue;
            if (first == null) first = ln;
            if (ln.isPart()) {
                by[ln.transform.pn] = ln;
                count = @max(count, ln.transform.pn + 1);
            } else whole = ln;
        }
        const slots = try alloc.alloc(*const Line, count);
        const sole = try alloc.alloc(bool, count);
        for (by[0..count], 0..) |m, i| {
            const sl = m orelse continue :next;
            slots[i] = sl;
            sole[i] = true;
            for (lines) |*ln| {
                if (ln != sl and ln.tag == .field and std.mem.eql(u8, ln.key, sl.key)) sole[i] = false;
            }
        }
        try out.append(alloc, .{ .first = first.?, .whole = whole, .sep = pl.transform.psep, .slots = slots, .sole = sole });
    }
    return out.items;
}

// Part `n` of a token; null: the token has no such part.
fn partOf(token: []const u8, sep: []const u8, n: usize) ?[]const u8 {
    var it = std.mem.splitSequence(u8, token, sep);
    var i: usize = 0;
    while (it.next()) |x| : (i += 1) if (i == n) return x;
    return null;
}

// The key's value for a part's text, before `typemap`; null: the table has no
// entry (a value never passes through it, ruling 3).
fn partValue(ln: *const Line, text: []const u8) !?MV {
    const t = ln.via orelse return MV{ .str = text };
    for (t.entries.items) |en| {
        if (std.mem.eql(u8, text, en.native)) return readAs(ln.kty, en.model) catch E.@"transform-decode";
    }
    return null;
}

fn sameValue(a: MV, b: MV) bool {
    if (a == .str or b == .str) return a == .str and b == .str and std.mem.eql(u8, a.str, b.str);
    if (a == .int and b == .int) return a.int == b.int;
    const x: f64 = if (a == .int) @floatFromInt(a.int) else a.float;
    const y: f64 = if (b == .int) @floatFromInt(b.int) else b.float;
    return x == y; // -0 equals 0 (ruling 22)
}

// Encode, step 1: does the whole text agree with the pack's parts and with
// the part keys the entity holds?
fn partCheckWhole(p: *const Pack, g: *const PartGroup, e: *const Entity, token: []const u8) bool {
    for (g.slots, g.sole, 0..) |ln, sole, n| {
        const text = partOf(token, g.sep, n);
        if (ln.tag == .constant) {
            if (text == null or !std.mem.eql(u8, text.?, ln.wtext)) return false;
            continue;
        }
        if (!sole) continue;
        const held = e.get(ln.key);
        const got = partValue(ln, text orelse return false) catch return false;
        if (got) |v| {
            var mv = v;
            if (mv == .str and std.mem.eql(u8, ln.key, "type")) {
                if (p.tm_nat2cot.get(mv.str)) |cot| mv = MV{ .str = cot };
            }
            if (held) |h| if (!sameValue(h, mv)) return false;
        } else if (!ln.unlisted or held != null) return false;
    }
    return true;
}

// The text a part field writes, from its held value or its `default`.
fn partText(p: *const Pack, sc: *const Scope, e: *const Entity, ln: *const Line, sep: []const u8) ![]const u8 {
    const te = E.@"transform-encode";
    var mv = e.get(ln.key) orelse sc.lineDefault(ln) orelse return te;
    if (mv == .str and std.mem.eql(u8, ln.key, "type")) {
        if (p.tm_cot2nat.get(mv.str)) |nat| mv = MV{ .str = nat };
    }
    const text = if (ln.via) |t| blk: {
        for (t.entries.items) |en| if (tableMatches(mv, en.model)) break :blk en.native;
        return te;
    } else if (mv == .str) mv.str else return te;
    if (std.mem.indexOf(u8, text, sep) != null) return te;
    return text;
}

// The token a part group writes; null: nothing.
fn partToken(alloc: std.mem.Allocator, p: *const Pack, sc: *const Scope, g: *const PartGroup, e: *const Entity, diag: *Diag) anyerror!?[]const u8 {
    const te = E.@"transform-encode";
    const loc = g.first.locator;
    var whole: ?MV = null;
    if (g.whole) |w| whole = e.get(w.key);
    if (whole == null) {
        var held = false;
        var all = true;
        for (g.slots) |ln| {
            if (ln.tag != .field) continue;
            if (e.get(ln.key) != null) held = true else if (sc.lineDefault(ln) == null) all = false;
        }
        if (held or all) {
            var buf = std.ArrayList(u8).init(alloc);
            for (g.slots, 0..) |ln, n| {
                if (n > 0) try buf.appendSlice(g.sep);
                if (ln.tag == .constant) {
                    try buf.appendSlice(ln.wtext);
                } else try buf.appendSlice(partText(p, sc, e, ln, g.sep) catch |err|
                    return bad(diag, alloc, err, "field {s} at {s}: part {d} has no value, no table entry, or holds the separator", .{ ln.key, loc, n }));
            }
            return buf.items;
        }
        const w = g.whole orelse return null;
        whole = sc.lineDefault(w) orelse return null;
    }
    const w = g.whole.?;
    if (whole.? != .str) return bad(diag, alloc, te, "field {s} at {s}", .{ w.key, loc });
    var token = whole.?.str;
    if (std.mem.eql(u8, w.key, "type")) token = p.tm_cot2nat.get(token) orelse token;
    if (!partCheckWhole(p, g, e, token)) return bad(diag, alloc, te, "field {s} at {s}: the text does not agree with its parts", .{ w.key, loc });
    return token;
}

// Resolve one line against the pack's wire: parse its locator, check its
// transform belongs to the wire, check the bit length its transform allows.
fn finalizeLine(alloc: std.mem.Allocator, p: *Pack, ln: *Line, in_group: bool, diag: *Diag) anyerror!void {
    // a UPER locator outside a UPER pack (ruling 9 of 0.19); on another
    // wire such a locator is a path as before (ruling 19)
    // `until:` is a locator of sequential layouts only (Version 0.22)
    if (isW(p.wire, .bits) and ln.isField() and std.mem.startsWith(u8, ln.locator, "until:")) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: the locator {s} is for a sequential layout", .{ ln.lineno, ln.locator });
    }
    if (isW(p.wire, .bits) and isUperLocator(ln.locator)) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: the locator {s} is for a pack with `encoding uper`", .{ ln.lineno, ln.locator });
    }
    if (ln.t_err) |err| {
        const why = if (p.wire == .tlv or p.wire == .cbor) E.@"bad-directive" else err;
        return bad(diag, alloc, why, "line {d}: unknown transform or parameters that do not parse", .{ln.lineno});
    }
    try partLineCheck(alloc, p, ln, in_group, diag);
    // `.`: the item itself as a scalar, inside a group only
    if (std.mem.eql(u8, ln.locator, ".") and (p.wire == .json or p.wire == .geojson or p.wire == .protobuf)) {
        if (!in_group) return bad(diag, alloc, E.@"bad-directive", "line {d}: the locator `.` outside a group", .{ln.lineno});
        ln.dot = true;
    }
    if (ln.dot and ln.tag == .constant) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: const on the item itself (`.`)", .{ln.lineno});
    }
    if (ln.isField() and isW(p.wire, .cbor)) {
        // on `cbor`: the transforms of its table only (Version 0.28)
        switch (ln.transform.kind) {
            .uint, .int, .float, .text_, .bytes, .bool_, .epoch_s => {},
            else => return bad(diag, alloc, E.@"bad-directive", "line {d}: the transform of {s} is not valid on the cbor wire", .{ ln.lineno, ln.key }),
        }
    } else if (ln.isField() and kindCategory(ln.transform.kind) == .cbor) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: the transform of {s} is valid only on the cbor wire", .{ ln.lineno, ln.key });
    } else if (ln.isField() and p.wire == .tlv) {
        // on `tlv`: the transforms of its table only (Version 0.13)
        switch (ln.transform.kind) {
            .uint, .twos, .uscale, .sscale, .f32_, .f64_, .utf8, .hex => {},
            else => return bad(diag, alloc, E.@"bad-directive", "line {d}: the transform of {s} is not valid on the tlv wire", .{ ln.lineno, ln.key }),
        }
    } else if (ln.isField() and (ln.transform.kind == .hex or ln.transform.kind == .codenum) and p.wire == .bits) {
        // `hex` (Version 0.22) and `codenum` (Version 0.46) on bits
    } else if (ln.isField() and kindCategory(ln.transform.kind) == .tlv) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: the transform of {s} is valid only on the tlv wire", .{ ln.lineno, ln.key });
    } else if (ln.isField() and p.wire == .text) {
        // on `text`: the text transforms but `bool`, and the transforms of
        // the wire (Version 0.10)
        const kc = kindCategory(ln.transform.kind);
        // `scale` and `iscale` are for xml, json and geojson (Version 0.15)
        if ((kc != .text and kc != .rec) or ln.transform.kind == .bool_ or isValueTransform(ln.transform.kind)) {
            return bad(diag, alloc, E.@"bad-directive", "line {d}: the transform of {s} is not valid on the text wire", .{ ln.lineno, ln.key });
        }
    } else if (ln.isField() and kindCategory(ln.transform.kind) == .rec) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: the transform of {s} is valid only on the text wire", .{ ln.lineno, ln.key });
    } else if (ln.isField() and ln.transform.kind == .sixbit and p.wire != .bits) {
        // `sixbit` is valid on the bits wire only (Version 0.14)
        return bad(diag, alloc, E.@"bad-directive", "line {d}: the transform sixbit of {s} is valid only on the bits wire", .{ ln.lineno, ln.key });
    } else if (ln.isField() and wireCategory(p.wire) != kindCategory(ln.transform.kind)) {
        // a transform of 0.15 on a wire it does not list, as every transform
        // off its wire (ruling 26 of 0.15)
        return bad(diag, alloc, E.@"bad-directive", "line {d}: transform of {s} does not belong to wire {s}", .{ ln.lineno, ln.key, @tagName(p.wire) });
    }
    if (ln.isField()) try resolveCodeSets(alloc, p, ln, diag);
    // a coordinate is a number; inside a group the locator is a member path
    // (ruling 23 of 0.46)
    if (ln.isField() and isCode(ln.transform.kind) and p.wire == .geojson and !in_group and std.mem.startsWith(u8, ln.locator, geom_prefix)) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: the transform of {s} on the coordinate {s}", .{ ln.lineno, ln.key, ln.locator });
    }
    if (ln.isField() and ln.transform.kind == .bool_ and p.wire != .json and p.wire != .cbor) {
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
    if (ln.trim and ln.transform.kind != .ascii and ln.transform.kind != .sixbit) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: trim is for the ascii and sixbit transforms", .{ln.lineno});
    }
    if (ln.swap and ln.transform.kind == .sixbit) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: swap on sixbit", .{ln.lineno});
    }
    if (ln.swap and ln.transform.kind == .hex) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: swap on hex", .{ln.lineno});
    }
    if (ln.stop_raw != null and p.wire != .bits) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: stop is for a chars field of the bits wire", .{ln.lineno});
    }
    if (p.wire == .bits and ln.isField()) try stopCheck(alloc, ln, ln.lineno, diag);
    if (ln.via_name.len > 0) {
        ln.via = p.tables.get(ln.via_name) orelse
            return bad(diag, alloc, E.@"bad-directive", "line {d}: via {s} names a table with no map line", .{ ln.lineno, ln.via_name });
    }
    switch (p.wire) {
        .bits => { if (comptime !built(.bits)) unreachable;
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
                if (ln.isWhen()) {
                    // a list of values and ranges (Version 0.20)
                    ln.wranges = (try parseWhenInts(alloc, ln.wraw, ln.blen)) orelse
                        return bad(diag, alloc, E.@"bad-directive", "line {d}: when {s}: not a list of unsigned values and ranges that fit {d} bits", .{ ln.lineno, ln.wraw, ln.blen });
                    ln.wint = ln.wranges[0].lo;
                    return;
                }
                const v = parseUnsigned(ln.wraw) orelse
                    return bad(diag, alloc, E.@"bad-directive", "line {d}: value {s} is not an unsigned decimal integer", .{ ln.lineno, ln.wraw });
                if (ln.blen < 64 and (v >> @as(u6, @intCast(ln.blen))) != 0) {
                    return bad(diag, alloc, E.@"bad-directive", "line {d}: value {d} does not fit {d} bits", .{ ln.lineno, v, ln.blen });
                }
                ln.wint = v;
            } else {
                if (!bitsLenOk(ln.transform, ln.blen)) {
                    return bad(diag, alloc, E.@"bad-directive", "line {d}: bit length {d} is not allowed for the transform of {s}", .{ ln.lineno, ln.blen, ln.key });
                }
                if (ln.swap and ln.blen % 8 != 0) {
                    return bad(diag, alloc, E.@"bad-directive", "line {d}: swap needs a bit length that is a multiple of 8, not {d}", .{ ln.lineno, ln.blen });
                }
                if (ln.swap and (ln.transform.kind == .chars or ln.transform.kind == .octal)) {
                    return bad(diag, alloc, E.@"bad-directive", "line {d}: swap with {s}", .{ ln.lineno, @tagName(ln.transform.kind) });
                }
            }
        },
        .protobuf => { if (comptime !built(.protobuf)) unreachable;
            if (!ln.dot) {
                ln.ppath = parsePbPath(alloc, ln.locator) catch |err| switch (err) {
                    error.OutOfMemory => return err,
                    else => return bad(diag, alloc, E.@"bad-directive", "line {d}: protobuf path {s} is not field numbers separated by dots", .{ ln.lineno, ln.locator }),
                };
            }
            if (ln.isFixed()) {
                if (std.mem.eql(u8, ln.wraw, "present")) {
                    ln.wpresent = true;
                } else if (ln.isWhen()) {
                    ln.wranges = (try parseWhenInts(alloc, ln.wraw, 64)) orelse
                        return bad(diag, alloc, E.@"bad-directive", "line {d}: when {s}: not `present` or a list of unsigned values and ranges", .{ ln.lineno, ln.wraw });
                    ln.wint = ln.wranges[0].lo;
                } else {
                    ln.wint = parseUnsigned(ln.wraw) orelse
                        return bad(diag, alloc, E.@"bad-directive", "line {d}: value {s} is not `present` or an unsigned decimal integer", .{ ln.lineno, ln.wraw });
                }
            }
        },
        .xml, .geojson, .json => { if (comptime !built(.xml) and !built(.geojson) and !built(.json)) unreachable;
            if (ln.isFixed()) {
                if (std.mem.eql(u8, ln.wraw, "present")) {
                    ln.wpresent = true;
                } else if (ln.isWhen()) {
                    // a list of texts (Version 0.20); the first is written
                    ln.walts = (try parseWhenTexts(alloc, ln.wraw)) orelse
                        return bad(diag, alloc, E.@"bad-directive", "line {d}: when {s}: an empty value, or `present` with other values", .{ ln.lineno, ln.wraw });
                    ln.wtext = ln.walts[0].text;
                    ln.wforced = ln.walts[0].forced;
                } else if (ln.wraw.len > 0 and ln.wraw[0] == '=') {
                    ln.wforced = true;
                    ln.wtext = ln.wraw[1..];
                } else {
                    ln.wtext = ln.wraw;
                }
                // the text encode writes, kept with the line (Version 0.25)
                if (p.wire != .xml and !ln.wpresent and !ln.isPart()) ln.wjson = try whenJsonRaw(alloc, ln.*);
            }
            // json, and geojson inside an item: a member path
            if ((p.wire == .json or (p.wire == .geojson and in_group)) and !ln.dot) {
                ln.segs = try splitSegs(alloc, ln.locator, '.');
            }
        },
        .text => if (comptime !built(.text)) unreachable else try textFinalizeLine(alloc, p, ln, diag),
        .tlv => if (comptime !built(.tlv)) unreachable else try tlvFinalizeLine(alloc, p, ln, diag),
        .cbor => if (comptime !built(.cbor)) unreachable else try cborFinalizeLine(alloc, ln, diag),
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
    // rulings 10 and 14 of 0.13: `absent` on the tlv wire is not stated yet,
    // and is checked after the file is read
    if (wire == .tlv) return bad(diag, alloc, bd, "line {d}: absent is not an option of the tlv wire", .{no});
    // ruling 10 of 0.28: on `cbor` too, checked after the file is read
    if (wire == .cbor) return bad(diag, alloc, bd, "line {d}: absent is not an option of the cbor wire", .{no});
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

// Version 0.17: each gate's locator and values against the fixed layout.
fn finalizeGates(alloc: std.mem.Allocator, p: *Pack, gates: []const *Gate, diag: *Diag) anyerror!void {
    const bd = E.@"bad-directive";
    for (gates) |gt| {
        if (p.wire != .bits) return bad(diag, alloc, bd, "line {d}: a gate block on wire {s}", .{ gt.lineno, @tagName(p.wire) });
        const c = parseColons(gt.locator, 3) orelse
            return bad(diag, alloc, bd, "line {d}: gate locator {s} is not <word>:<pos>:<len>", .{ gt.lineno, gt.locator });
        if (c[2] < 1 or c[2] > 64) return bad(diag, alloc, bd, "line {d}: gate locator {s}: the bit length is not 1..64", .{ gt.lineno, gt.locator });
        gt.bstart = c[0] * p.word_bytes * 8 + c[1];
        gt.blen = c[2];
        var vals = std.ArrayListUnmanaged(u64){};
        var it = std.mem.splitScalar(u8, gt.vals_txt, ',');
        while (it.next()) |vt| {
            const v = parseUnsigned(vt) orelse
                return bad(diag, alloc, bd, "line {d}: gate value {s} is not an unsigned decimal integer", .{ gt.lineno, vt });
            if (gt.blen < 64 and (v >> @as(u6, @intCast(gt.blen))) != 0) {
                return bad(diag, alloc, bd, "line {d}: gate value {d} does not fit {d} bits", .{ gt.lineno, v, gt.blen });
            }
            if (std.mem.indexOfScalar(u64, vals.items, v) != null) {
                return bad(diag, alloc, bd, "line {d}: gate value {d} is listed twice", .{ gt.lineno, v });
            }
            try vals.append(alloc, v);
        }
        gt.values = vals.items;
    }
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
    if (isW(p.wire, .text)) return textFinalizeGroup(alloc, p, g, nested, diag);
    if (p.wire == .tlv) return bad(diag, alloc, bd, "line {d}: group on the tlv wire", .{g.lineno});
    if (p.wire != .bits and (g.count_txt != null or g.item_txt != null)) {
        return bad(diag, alloc, bd, "line {d}: `item` and `count` are for the bits wire, not {s}", .{ g.lineno, @tagName(p.wire) });
    }
    switch (p.wire) {
        .xml => { if (comptime !built(.xml)) unreachable;
            const names = try splitSegs(alloc, g.locator, '/');
            for (names) |nm| {
                if (nm.len == 0 or nm[0] == '@' or nm[0] == '#') {
                    return bad(diag, alloc, bd, "line {d}: group locator {s} is not a path of element names", .{ g.lineno, g.locator });
                }
            }
            g.xname = names[names.len - 1];
            g.xpath = names[0 .. names.len - 1];
        },
        .json, .geojson => { if (comptime !built(.json) and !built(.geojson)) unreachable;
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
        .protobuf => { if (comptime !built(.protobuf)) unreachable;
            g.ppath = parsePbPath(alloc, g.locator) catch |err| switch (err) {
                error.OutOfMemory => return err,
                else => return bad(diag, alloc, bd, "line {d}: group locator {s} is not field numbers separated by dots", .{ g.lineno, g.locator }),
            };
        },
        .bits => { if (comptime !built(.bits)) unreachable;
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
        .cbor => { if (comptime !built(.cbor)) unreachable;
            g.cpath = if (std.mem.eql(u8, g.locator, ".")) &.{} else (try cParsePath(alloc, g.locator, false)) orelse
                return bad(diag, alloc, E.@"bad-locator", "line {d}: {s} is not a cbor path", .{ g.lineno, g.locator });
        },
        .text, .tlv => unreachable,
    }
    try finalizeLines(alloc, p, g.lines, true, diag);
    if (isW(p.wire, .cbor)) {
        // ruling 13 of 0.28: a body that mixes `.` with other paths; an
        // element is an array when the body's paths begin with positions
        var has_dot = false;
        var has_path = false;
        for (g.lines) |*ln| {
            const cp = if (ln.tag == .group) ln.grp.?.cpath else ln.cpath;
            if (ln.tag != .group and ln.dot) has_dot = true else has_path = true;
            if (cp.len > 0 and !g.cbody_array and cp[0].kind == .pos) g.cbody_array = true;
        }
        if (has_dot and has_path) {
            return bad(diag, alloc, bd, "line {d}: the body of group {s} mixes `.` with paths", .{ g.lineno, g.list });
        }
    }
    try finalizeGates(alloc, p, g.gates.items, diag);
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
        // a packed group: a body of `.` fields with numeric transforms only
        // (ruling 17 of 0.18); `with` on one of its fields is `bad-directive`
        // (ruling 4)
        var is_packed = g.lines.len > 0;
        var any_with = false;
        for (g.lines) |*ln| {
            if (!(ln.isField() and ln.dot and ln.transform.kind != .pstring)) is_packed = false;
            if (ln.with_key != null) any_with = true;
        }
        if (is_packed and any_with) {
            return bad(diag, alloc, bd, "line {d}: with on the item of the packed protobuf group {s}", .{ g.lineno, g.list });
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
        .bits, .text, .tlv, .cbor => return false,
    }
}

// Checks over one scope: the lines `a` then `b` (common plus one kind, or one
// group body). A list is mapped by at most one group. On `bits`: a group
// counted by a locator is the last thing in its scope, and inside an item
// nothing of fixed size reaches beyond `item <bits>`.
fn checkScope(alloc: std.mem.Allocator, p: *const Pack, a: []const Line, b: []const Line, ga: []const *Gate, gb: []const *Gate, item_bits: ?usize, item_scope: bool, diag: *Diag) anyerror!void {
    const bd = E.@"bad-directive";
    const both = [2][]const Line{ a, b };
    const gboth = [2][]const *Gate{ ga, gb };
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
            if ((ln.tag == .field or ln.tag == .element) and passesThrough(p, ln, gl.grp.?, item_scope)) {
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
            // a gate at or beyond the start of the group (ruling 2 of 0.17)
            for (gboth) |gates| for (gates) |gt| {
                if (gt.bstart + gt.blen > g.gstart) {
                    return bad(diag, alloc, bd, "line {d}: a gate at or beyond the start of the group counted by a locator on line {d}", .{ gt.lineno, g.lineno });
                }
            };
        };
    }
    // a gate any of whose bits lies within the items of a fixed-count group
    // of the scope (ruling 9 of 0.17)
    for (both) |glines| for (glines) |*gl| {
        if (gl.tag != .group) continue;
        const g = gl.grp.?;
        const n = g.count_fixed orelse continue;
        const gend = g.gstart + n * g.item_bits;
        for (gboth) |gates| for (gates) |gt| {
            if (gt.bstart < gend and gt.bstart + gt.blen > g.gstart) {
                return bad(diag, alloc, bd, "line {d}: the gate lies within the items of the group on line {d}", .{ gt.lineno, g.lineno });
            }
        };
    };
    if (item_bits) |ib| {
        for (gboth) |gates| for (gates) |gt| {
            if (gt.bstart + gt.blen > ib) {
                return bad(diag, alloc, bd, "line {d}: a gate of an item reaches beyond item {d}", .{ gt.lineno, ib });
            }
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
        try checkScope(alloc, p, g.lines, &.{}, g.gates.items, &.{}, if (p.wire == .bits) g.item_bits else null, true, diag);
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
            // `until:<code>` (Version 0.22): refused after the file is read
            // on a fixed layout, its code checked then on a sequential one
            if (std.mem.startsWith(u8, loc, "until:")) return true;
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
        // the paths of the `tlv` wire are checked after the file is read
        // (Version 0.13: `bad-directive`)
        .text, .tlv, .cbor => return true,
    }
}

// Ruling 5a of 0.11 on a `group` line: an empty step or member name, and on
// `protobuf` a step that is not a field number, are `bad-locator`. The
// `protobuf` group locators `rest` and `last` are `bad-directive` after the
// file is read instead (rulings 37 and 44 of 0.21).
fn groupLocatorFormOk(wire: Wire, loc: []const u8) bool {
    const sep: u8 = switch (wire) {
        .xml => '/',
        .json, .geojson, .protobuf => '.',
        .bits, .text, .tlv, .cbor => return true,
    };
    if (wire == .protobuf and (std.mem.eql(u8, loc, "rest") or std.mem.eql(u8, loc, "last"))) return true;
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
const PackDir = enum { format, version, distribution, source, uses, wire, root, field, when, @"const", kind, requires, default, map, typemap, group, end, word_bytes, bit_order, layout, also, pad, @"align", presence, @"if", opt, chain, fx, length, delimiter, start, checksum, tag, key, armor, element, encoding, ext, choice, alt, @"switch", case, @"else", count, inner, framing, charset };

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
        // Version 0.34: `inner` stands after `wire` and `layout sequential`
        .root, .field, .when, .@"const", .group, .end, .word_bytes, .bit_order, .layout, .also, .pad, .@"align", .presence, .@"if", .opt, .chain, .fx, .length, .inner, .framing => true,
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
    // `key <hex>` (one value) is the directive of the `tlv` wire (Version
    // 0.13); a `key` line of another shape is the module's `key`, which is
    // not a directive of a pack (ruling 5 of 0.11, load vector 445)
    const module_key = std.mem.eql(u8, kw, "key") and toks.len != 2;
    const d = (if (module_key) null else std.meta.stringToEnum(PackDir, kw)) orelse
        return lineBad(diag, alloc, E.@"unknown-directive", "line {d}: unknown directive {s}", .{ lineno, kw });
    const n = toks.len - 1;
    const ok = switch (d) {
        // `armor` takes exactly one, checked here (ruling 13 of 0.14)
        .format, .version, .distribution, .source, .uses, .wire, .root, .kind, .word_bytes, .bit_order, .layout, .pad, .@"align", .delimiter, .start, .tag, .key, .armor, .element, .framing => n == 1,
        // Version 0.19: `encoding` takes one, as `armor` does (ruling 13 of
        // 0.14); `ext` none; `choice <n> [ext]` one or two; `alt <i>` one.
        // Their wire, layout and values are checked after the file is read.
        .encoding, .alt => n == 1,
        .choice => n == 1 or n == 2,
        // Version 0.20: `switch <key>` and `case <values>` one, `else` none
        // (ruling 39 of 0.20)
        .@"switch", .case => n == 1,
        // Version 0.21: `count <name> <len> [plus <n>]`; its options are
        // checked by the sequential parser
        .count => n >= 2,
        // Version 0.34: `inner <format> [partial]`
        .inner => n == 1 or n == 2,
        // `checksum sum16 <tag>` and `checksum crc32 <tag>` of the `tlv` wire
        // have two (ruling 12 of 0.13, ruling 2 of 0.27)
        .checksum => n == 1 or (n == 2 and (std.mem.eql(u8, toks[1], "sum16") or std.mem.eql(u8, toks[1], "crc32"))),
        .field => n >= 3,
        // Version 0.30: `when <len> <values> as …`; the tokens after `as`,
        // and the wire and layout it needs, are checked after the file
        // (ruling 16)
        // Version 0.33: or `at …`; a third token that is neither stays this
        // check (ruling 29)
        .when => n == 2 or (n >= 3 and (std.mem.eql(u8, toks[3], "as") or std.mem.eql(u8, toks[3], "at"))),
        // Version 0.64: `const <locator> part:<sep>:<n> <text>`
        .@"const" => n == 2 or (n == 3 and isPartWord(toks[2])),
        .default, .typemap => n == 2,
        .map => n == 3,
        // Version 0.46: `charset <name> <characters> [<width>]`
        .charset => n == 2 or n == 3,
        .requires, .@"if", .length => n >= 1,
        .group => n >= 2,
        .presence => n == 2,
        .also => n == 1 or n == 3,
        .end, .opt, .chain, .fx, .ext, .@"else" => n == 0,
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
    if (d == .wire) {
        const w = std.meta.stringToEnum(Wire, toks[1]) orelse
            return lineBad(diag, alloc, E.@"unknown-wire", "line {d}: unknown wire {s}", .{ lineno, toks[1] });
        // Version 0.24, ruling 1c: a wire of the specification this build
        // does not have
        if (!wireBuilt(w)) {
            return lineBad(diag, alloc, E.@"unknown-wire", "line {d}: wire {s} is a wire of the specification that this build does not have", .{ lineno, toks[1] });
        }
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
    // the open gate blocks (0.17), innermost last; a group cannot open
    // inside one, so they are all of the innermost container
    gtstack: std.ArrayList(*Gate),
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
    const gtstack = &st.gtstack;
    const cur_gate: ?*Gate = if (gtstack.items.len > 0) gtstack.items[gtstack.items.len - 1] else null;
    // inside a gate block: `field`, `const`, `default`, a nested `if` and `end` only
    if (cur_gate != null and !(is(kw, "field") or is(kw, "const") or is(kw, "default") or is(kw, "if") or is(kw, "end"))) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: {s} inside a gate block", .{ lineno, kw });
    }
    // inside a group: `field`, `const`, `default`, `group`, `if` and `end` only
    if (in_group and !(is(kw, "field") or is(kw, "const") or is(kw, "default") or is(kw, "group") or is(kw, "if") or is(kw, "end"))) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: {s} inside a group", .{ lineno, kw });
    }
    if (is(kw, "if")) {
        // if [!]<word>:<pos>:<len> <value>[,<value>…]: exactly one locator
        // and one value list (ruling 12 of 0.17)
        if (toks.len != 3) return bad(diag, alloc, E.@"bad-directive", "line {d}: if takes one locator and one value list", .{lineno});
        const neg = toks[1].len > 0 and toks[1][0] == '!';
        const gt = try alloc.create(Gate);
        gt.* = .{ .lineno = lineno, .locator = if (neg) toks[1][1..] else toks[1], .vals_txt = toks[2], .neg = neg, .parent = cur_gate };
        if (in_group) {
            try gstack.items[gstack.items.len - 1].gates.append(alloc, gt);
        } else if (p.kinds.items.len == 0) {
            try p.common_gates.append(alloc, gt);
        } else {
            try p.kinds.items[p.kinds.items.len - 1].gates.append(alloc, gt);
        }
        if (p.gate_line == 0) p.gate_line = lineno;
        try gtstack.append(gt);
    } else if (is(kw, "end") and cur_gate != null) {
        if (toks.len != 1) return bad(diag, alloc, E.@"bad-directive", "line {d}: end takes no argument", .{lineno});
        _ = gtstack.pop();
    } else if (is(kw, "group")) {
        // group <list> <locator> [item <bits>] [count <count-locator | n>]
        if (toks.len < 3) return bad(diag, alloc, E.@"bad-directive", "line {d}: group takes a list and a locator", .{lineno});
        if (isW(p.wire, .cbor)) {
            // `.` names the top item on a group outside a body only (ruling 22 of 0.28)
            if (!cborLocOk(toks[2], !in_group)) return lineBad(diag, alloc, E.@"bad-locator", "line {d}: group locator {s} is not a cbor path", .{ lineno, toks[2] });
        } else if (!groupLocatorFormOk(p.wire, toks[2])) {
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
        p.msb = bitOrdOf(toks[1]) orelse
            return bad(diag, alloc, E.@"bad-directive", "line {d}: bit_order {s} is not lsb, msb or msb-lsb", .{ lineno, toks[1] });
        p.bit_order_set = true;
    } else if (is(kw, "armor")) {
        // armor <hex | sixbit> (Version 0.14): its argument count, wire,
        // place and value are checked after the file is read
        if ((toks.len != 2 or p.armor_raw != null or p.kinds.items.len > 0) and p.armor_bad == 0) p.armor_bad = lineno;
        p.armor_raw = toks[toks.len - 1];
    } else if (is(kw, "encoding")) {
        // encoding <none | uper> (Version 0.19): its argument count is a
        // line check (packLineChecks); its wire, place and value are checked
        // after the file is read
        if ((p.enc_raw != null or p.kinds.items.len > 0) and p.enc_bad == 0) p.enc_bad = lineno;
        p.enc_raw = toks[toks.len - 1];
    } else if (is(kw, "ext") or is(kw, "choice") or is(kw, "alt")) {
        // lines of a UPER pack only (rulings 9 and 21 of 0.19), refused
        // after the file is read
        if (p.uper_line == 0) p.uper_line = lineno;
    } else if (is(kw, "layout")) {
        // layout <fixed | sequential>, bits wire only; default fixed
        if (toks.len != 2 or !(is(toks[1], "fixed") or is(toks[1], "sequential"))) {
            return bad(diag, alloc, E.@"bad-directive", "line {d}: layout takes `fixed` or `sequential`", .{lineno});
        }
        p.layout_set = true;
    } else if (is(kw, "length") and toks.len == 2) {
        // `length <ber | n>` of the `tlv` wire (Version 0.13), checked
        // after the file is read; the `length` block of 0.8 is refused below
        if ((p.len_raw != null or p.kinds.items.len > 0) and p.tdir_bad == 0) p.tdir_bad = lineno;
        p.len_raw = toks[1];
    } else if (is(kw, "tag") or is(kw, "key")) {
        // `tag` and `key` of the `tlv` wire (Version 0.13)
        if (toks.len != 2) return bad(diag, alloc, E.@"bad-directive", "line {d}: {s} takes one value", .{ lineno, kw });
        const slot = if (is(kw, "tag")) &p.tag_raw else &p.key_raw;
        if ((slot.* != null or p.kinds.items.len > 0) and p.tdir_bad == 0) p.tdir_bad = lineno;
        slot.* = toks[1];
    } else if (is(kw, "pad") or is(kw, "align") or is(kw, "presence") or is(kw, "opt") or is(kw, "chain") or is(kw, "fx") or is(kw, "length") or is(kw, "also") or is(kw, "switch") or is(kw, "case") or is(kw, "else") or is(kw, "count")) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: {s} is a line of a sequential pack (`layout sequential` on the bits wire)", .{ lineno, kw });
    } else if (is(kw, "charset")) {
        // Version 0.46, checked after the file is read
        try p.addCharset(alloc, toks, lineno, p.kinds.items.len > 0);
    } else if (is(kw, "typemap")) {
        if (toks.len != 3) return bad(diag, alloc, E.@"bad-directive", "line {d}: typemap takes two arguments", .{lineno});
        try p.tm_nat2cot.put(toks[1], toks[2]);
        try p.tm_cot2nat.put(toks[2], toks[1]);
    } else if (is(kw, "delimiter") or is(kw, "start") or is(kw, "checksum")) {
        // the `text` wire (Version 0.10): checked against the wire and
        // one another after the file is read
        // `checksum sum16 <tag>` of the `tlv` wire has two values
        const two = is(kw, "checksum") and toks.len == 3;
        if (toks.len != 2 and !two) return bad(diag, alloc, E.@"bad-directive", "line {d}: {s} takes one value", .{ lineno, kw });
        const slot = if (is(kw, "delimiter")) &p.delim_raw else if (is(kw, "start")) &p.start_raw else &p.cksum_raw;
        if ((slot.* != null or p.kinds.items.len > 0) and p.tdir_bad == 0) p.tdir_bad = lineno;
        slot.* = toks[1];
        if (is(kw, "checksum")) p.cksum_arg = if (two) toks[2] else null;
    } else if (is(kw, "kind")) {
        if (toks.len != 2) return bad(diag, alloc, E.@"bad-directive", "line {d}: kind takes one argument", .{lineno});
        if (p.kindIndex(toks[1]) != null) {
            return bad(diag, alloc, E.@"duplicate-kind", "line {d}: kind {s} is declared twice", .{ lineno, toks[1] });
        }
        try p.kinds.append(.{
            .name = toks[1],
            .lines = std.ArrayList(Line).init(alloc),
            .requires = std.ArrayList(*ReqTerm).init(alloc),
            .defaults = std.ArrayList(Default).init(alloc),
        });
        // where the kind's key uses begin (Version 0.94)
        try p.kind_starts.append(alloc, p.key_uses.items.len);
    } else if (is(kw, "requires")) {
        if (p.kinds.items.len == 0) {
            return bad(diag, alloc, E.@"bad-directive", "line {d}: requires before the first kind", .{lineno});
        }
        if (toks.len < 2) return bad(diag, alloc, E.@"bad-directive", "line {d}: requires takes at least one key", .{lineno});
        const k = &p.kinds.items[p.kinds.items.len - 1];
        for (toks[1..]) |key| {
            // a term `<key>` or `<key>=<value>[,<value>…]` (Version 0.20)
            const t = (try parseReqTerm(alloc, key, lineno)) orelse
                return bad(diag, alloc, E.@"bad-directive", "line {d}: requires {s}: a key and a non-empty value list around `=`", .{ lineno, key });
            try k.requires.append(t);
            try p.key_uses.append(.{ .key = t.key, .tkind = null, .use = .requires, .eq = t.vals != null });
            if (t.vals != null) try p.vchecks.append(alloc, .{ .req = t });
        }
    } else if (is(kw, "when") or is(kw, "const")) {
        const is_when = is(kw, "when");
        // Version 0.33: `at` is for a `when` of a `layout sequential` pack
        // only; every `at` error is reported after the key checks (rulings
        // 10, 14 and 30). The line's own line checks (its locator) run first;
        // then it is set aside.
        const at_line = is_when and toks.len > 3 and holdsAt(toks);
        if (!at_line and is_when and toks.len > 3 and is(toks[3], "as")) {
            // Version 0.30: `as` is for a `when` of a `layout sequential`
            // pack only (ruling 1), checked after the file (ruling 16)
            return bad(diag, alloc, E.@"bad-directive", "line {d}: when … as: `as` is for a pack with `layout sequential` on the bits wire", .{lineno});
        }
        // Version 0.64: the parameters of a part are a line check, before the
        // locator's (ruling 11)
        const part_const: ?Transform = if (!is_when and toks.len == 4) parsePart(toks[2]) catch |err|
            return lineBad(diag, alloc, err, "line {d}: the parameters of {s} are not valid", .{ lineno, toks[2] }) else null;
        if (!at_line and part_const == null and toks.len != 3) return bad(diag, alloc, E.@"bad-directive", "line {d}: {s} takes a locator and a value", .{ lineno, kw });
        if (is_when and !at_line) st.any_when = true;
        // a UPER locator on `bits` is `bad-directive` after the file
        // (rulings 24 and 26 of 0.19), not `bad-locator` here
        if (isW(p.wire, .bits) and isUperLocator(toks[1])) {
            if (!at_line and p.uper_line == 0) p.uper_line = lineno;
        } else if (isW(p.wire, .cbor)) {
            if (!cborLocOk(toks[1], false)) return lineBad(diag, alloc, E.@"bad-locator", "line {d}: locator {s} of a {s} is not a cbor path", .{ lineno, toks[1], kw });
        } else if (!locatorFormOk(p.wire, false, toks[1], in_group)) {
            return lineBad(diag, alloc, E.@"bad-locator", "line {d}: locator {s} does not have the form of a {s} on the {s} wire", .{ lineno, toks[1], kw, @tagName(p.wire) });
        }
        if (at_line) {
            if (p.at_err == null) p.at_err = try std.fmt.allocPrint(alloc, "line {d}: when … at: `at` is for a kind's `when` in a pack with `layout sequential` on the bits wire", .{lineno});
            return;
        }
        var ln = Line{ .tag = if (is_when) .when else .constant, .locator = toks[1], .wraw = toks[2], .lineno = lineno, .gate = cur_gate };
        if (part_const) |t| {
            ln.transform = t;
            ln.wraw = toks[3];
        }
        try curLines(p, in_group, gtmp).append(ln);
    } else if (is(kw, "default")) {
        if (toks.len != 3) return bad(diag, alloc, E.@"bad-directive", "line {d}: default takes a key and a value", .{lineno});
        const d = Default{ .key = toks[1], .text = toks[2] };
        if (cur_gate) |gt| {
            // a `default` inside a gate block applies to its fields and
            // those of the blocks nested in it (ruling 5 of 0.17)
            try gt.defaults.append(alloc, d);
        } else if (in_group) {
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
    } else if (is(kw, "element")) {
        // element <path> (Version 0.18, xml): a path of element names
        if (toks.len != 2) return bad(diag, alloc, E.@"bad-directive", "line {d}: element takes one path", .{lineno});
        const path = toks[1];
        if (path.len == 0) return bad(diag, alloc, E.@"bad-directive", "line {d}: element with an empty path", .{lineno});
        var it = std.mem.splitScalar(u8, path, '/');
        while (it.next()) |nm| {
            // a step with `@` or `#` anywhere (ruling 16 of 0.18)
            if (nm.len == 0 or std.mem.indexOfAny(u8, nm, "@#") != null) {
                return bad(diag, alloc, E.@"bad-directive", "line {d}: element {s} is not a path of element names", .{ lineno, path });
            }
        }
        if (p.element_line == 0) p.element_line = lineno;
        try curLines(p, in_group, gtmp).append(.{ .tag = .element, .locator = path, .lineno = lineno });
    } else if (is(kw, "field")) {
        if (toks.len < 4) return bad(diag, alloc, E.@"bad-directive", "line {d}: field takes a key, a locator and a transform", .{lineno});
        // on `tlv` a transform that does not parse is kept and refused after
        // the file is read (ruling 8 of 0.13: `bad-directive`); the wire is
        // known here, since a `field` line stands after it (ruling 5b of 0.11)
        var t_err: ?anyerror = null;
        const t = parseTransform(alloc, toks[3]) catch |err| blk: {
            if (err == error.OutOfMemory) return err;
            // on `cbor` a name no wire has, likewise (ruling 25 of 0.28)
            // on `cbor` too, parameters included (rulings 25 and 34 of 0.28)
            if (p.wire == .tlv or p.wire == .cbor) {
                t_err = err;
                break :blk Transform{ .kind = .string };
            }
            switch (err) {
                error.@"unknown-transform" => return lineBad(diag, alloc, err, "line {d}: unknown transform {s}", .{ lineno, toks[3] }),
                else => return lineBad(diag, alloc, err, "line {d}: the parameters of transform {s} are not valid", .{ lineno, toks[3] }),
            }
        };
        // a UPER locator (`int:`, `enum:`, `chars:`, `octets:`) on a `bits`
        // field outside a UPER pack is `bad-directive`, checked after the
        // file is read (rulings 9 and 19 of 0.19), not `bad-locator` here
        const uper_loc = isW(p.wire, .bits) and isUperLocator(toks[2]);
        if (uper_loc) {
            if (p.uper_line == 0) p.uper_line = lineno;
        } else if (isW(p.wire, .cbor)) {
            // `.` is the element itself, on a field in a group body only
            if (!cborLocOk(toks[2], in_group)) return lineBad(diag, alloc, E.@"bad-locator", "line {d}: locator {s} of a field is not a cbor path", .{ lineno, toks[2] });
        } else if (!locatorFormOk(p.wire, false, toks[2], in_group)) {
            return lineBad(diag, alloc, E.@"bad-locator", "line {d}: locator {s} does not have the form of a field on the {s} wire", .{ lineno, toks[2], @tagName(p.wire) });
        }
        var ln = Line{ .key = toks[1], .locator = toks[2], .transform = t, .lineno = lineno, .t_err = t_err, .gate = cur_gate };
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
            } else if (is(o, "unlisted")) {
                // Version 0.64, checked after the file is read
                again = ln.unlisted;
                ln.unlisted = true;
            } else if (is(o, "optional")) {
                again = ln.optional;
                ln.optional = true;
            } else if (is(o, "absent")) {
                // the next token is the argument, whatever it is (ruling 11 of 0.9)
                oi += 1;
                if (oi >= toks.len) return lineBad(diag, alloc, E.@"bad-directive", "line {d}: absent takes one or more values", .{lineno});
                again = ln.absent_raw != null;
                ln.absent_raw = toks[oi];
            } else if (is(o, "stop")) {
                // stop <code> (Version 0.22), checked after the file is read
                oi += 1;
                if (oi >= toks.len) return lineBad(diag, alloc, E.@"bad-directive", "line {d}: stop takes a code", .{lineno});
                again = ln.stop_raw != null;
                ln.stop_raw = toks[oi];
            } else if (is(o, "with")) {
                // with <other-key> (Version 0.18)
                oi += 1;
                if (oi >= toks.len or toks[oi].len == 0) return lineBad(diag, alloc, E.@"bad-directive", "line {d}: with takes a key", .{lineno});
                again = ln.with_key != null;
                ln.with_key = toks[oi];
            } else return lineBad(diag, alloc, E.@"bad-directive", "line {d}: unknown field option {s}", .{ lineno, o });
            if (again) return lineBad(diag, alloc, E.@"bad-directive", "line {d}: field option {s} is repeated", .{ lineno, o });
        }
        // the values of the `absent` option are a line check, except on a
        // `bits` field above 64 bits (ruling 4d of 0.11) and on `tlv`, where
        // `absent` does not fit the wire, checked after the file is read
        // (ruling 14 of 0.13)
        if (p.wire == .bits) ln.blen = @intCast(@min(fixedLen(toks[2]) orelse 0, 1 << 20));
        if (!(p.wire == .bits and ln.blen > 64) and p.wire != .tlv and p.wire != .cbor and !uper_loc) {
            try parseAbsent(alloc, p.wire, &ln, in_group, diag);
            ln.abs_checked = true;
        }
        try curLines(p, in_group, gtmp).append(ln);
        try p.key_uses.append(.{ .key = toks[1], .tkind = t.kind, .via = ln.via_name, .grp = if (in_group) gstack.items[gstack.items.len - 1] else null });
        if (ln.with_key) |wk| try p.key_uses.append(.{ .key = wk, .tkind = null, .use = .with });
    } else if (is(kw, "framing")) {
        // Version 0.92, likewise
        return bad(diag, alloc, E.@"bad-directive", "line {d}: framing is for the sequential layout of the bits wire", .{lineno});
    } else if (is(kw, "inner")) {
        // Version 0.34: a line of a `layout sequential` `bits` pack only,
        // checked after the file is read
        return bad(diag, alloc, E.@"bad-directive", "line {d}: inner on wire {s} without `layout sequential`; it is for the sequential layout of the bits wire only", .{ lineno, @tagName(p.wire) });
    } else {
        return bad(diag, alloc, E.@"unknown-directive", "line {d}: unknown directive {s}", .{ lineno, kw });
    }
}

fn parsePack(alloc: std.mem.Allocator, def_text: []const u8, diag: *Diag) anyerror!*Pack {
    // `layout sequential` on the bits wire: lines read in order from a cursor
    // (part of `bits`, ruling 1d of 0.24: a build without `bits` reads such
    // a pack as a fixed one, which stops at its `wire bits` line)
    if (built(.bits) and try isSequentialPack(alloc, def_text)) return parseSeqPack(alloc, def_text, diag);
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
        .gtstack = std.ArrayList(*Gate).init(alloc),
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
    if (st.gtstack.items.len > 0) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: an `if` with no `end`", .{st.gtstack.items[st.gtstack.items.len - 1].lineno});
    }
    if (gstack.items.len > 0) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: a `group` with no `end`", .{gstack.items[gstack.items.len - 1].lineno});
    }
    if (p.element_line != 0 and p.wire != .xml) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: element on wire {s}; it is for the xml wire only", .{ p.element_line, @tagName(p.wire) });
    }
    if (p.gate_line != 0 and p.wire != .bits) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: a gate block on wire {s}; it is for the fixed layout of the bits wire", .{ p.gate_line, @tagName(p.wire) });
    }
    // Checks that need the whole file: the wire may be named after the lines
    // it governs.
    if (p.bit_order_set and p.wire != .bits) {
        return bad(diag, alloc, E.@"bad-directive", "bit_order on wire {s}; it is for the bits wire only", .{@tagName(p.wire)});
    }
    if (p.layout_set and p.wire != .bits) {
        return bad(diag, alloc, E.@"bad-directive", "layout on wire {s}; it is for the bits wire only", .{@tagName(p.wire)});
    }
    if (p.enc_raw) |raw| {
        if (p.wire != .bits) return bad(diag, alloc, E.@"bad-directive", "encoding on wire {s}; it is for the bits wire only", .{@tagName(p.wire)});
        if (p.enc_bad != 0) return bad(diag, alloc, E.@"bad-directive", "line {d}: encoding is repeated, given after a kind, or not given one value", .{p.enc_bad});
        if (!std.mem.eql(u8, raw, "none")) return bad(diag, alloc, E.@"bad-directive", "encoding {s}: only `encoding none` is valid outside `layout sequential` with `bit_order msb`", .{raw});
    }
    if (p.uper_line != 0) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: a line of a pack with `encoding uper`", .{p.uper_line});
    }
    try charsetCheck(alloc, p, diag);
    try armorCheck(alloc, p, diag);
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
    try finalizeGates(alloc, p, p.common_gates.items, diag);
    for (p.kinds.items) |*k| try finalizeGates(alloc, p, k.gates.items, diag);
    // the group checks, scope by scope
    if (p.kinds.items.len == 0) try checkScope(alloc, p, p.common.items, &.{}, p.common_gates.items, &.{}, null, false, diag);
    for (p.kinds.items) |*k| try checkScope(alloc, p, p.common.items, k.lines.items, p.common_gates.items, k.gates.items, null, false, diag);
    try checkGroupBodies(alloc, p, p.common.items, diag);
    for (p.kinds.items) |*k| try checkGroupBodies(alloc, p, k.lines.items, diag);
    // the part groups (Version 0.64)
    if (p.kinds.items.len == 0) try partScopeCheck(alloc, p, p.common.items, &.{}, diag);
    for (p.kinds.items) |*k| try partScopeCheck(alloc, p, p.common.items, k.lines.items, diag);
    try partBodyChecks(alloc, p, p.common.items, diag);
    for (p.kinds.items) |*k| try partBodyChecks(alloc, p, k.lines.items, diag);
    if (isW(p.wire, .text)) {
        if (p.kinds.items.len == 0) try textCheckScope(alloc, p.common.items, &.{}, diag);
        for (p.kinds.items) |*k| try textCheckScope(alloc, p.common.items, k.lines.items, diag);
    }
    if (isW(p.wire, .tlv)) {
        if (p.kinds.items.len == 0) try tlvCheckScope(alloc, p.common.items, &.{}, diag);
        for (p.kinds.items) |*k| try tlvCheckScope(alloc, p.common.items, k.lines.items, diag);
    }
    if (isW(p.wire, .cbor)) try cborCheckPack(alloc, p, diag);

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
fn buildScope(alloc: std.mem.Allocator, lines: []const Line, d1: []const Default, d2: []const Default, body: bool, ga: []const *Gate, gb: []const *Gate) !Scope {
    var sc = Scope{ .lines = lines };
    sc.parts = try buildParts(alloc, lines);
    if (ga.len + gb.len > 0) {
        // the gates of the scope; a common gate has the same position in
        // every kind's scope, since the common lines come first
        const gs = try alloc.alloc(*const Gate, ga.len + gb.len);
        for (ga, 0..) |gt, i| {
            gt.idx = i;
            gs[i] = gt;
        }
        for (gb, 0..) |gt, i| {
            gt.idx = ga.len + i;
            gs[ga.len + i] = gt;
        }
        sc.gates = gs;
    }
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
        // a line of a gate block (bits only) counts toward the length only
        // when its block holds (0.17)
        if (ln.gate != null) {
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
        g.body = try buildScope(alloc, g.lines, g.defaults.items, &.{}, true, g.gates.items, &.{});
    }
}

// `armor <hex | sixbit>` (Version 0.14): on the bits wire only, at most once,
// before the first `kind`; `armor sixbit` needs `bit_order msb`.
fn armorCheck(alloc: std.mem.Allocator, p: *Pack, diag: *Diag) anyerror!void {
    const bd = E.@"bad-directive";
    const raw = p.armor_raw orelse return;
    if (p.armor_bad != 0) return bad(diag, alloc, bd, "line {d}: armor is repeated, given after a kind, or not given one value", .{p.armor_bad});
    if (p.wire != .bits) return bad(diag, alloc, bd, "armor on wire {s}; it is for the bits wire only", .{@tagName(p.wire)});
    if (std.mem.eql(u8, raw, "sixbit")) {
        if (!p.bit_order_set or p.msb != .msb) return bad(diag, alloc, bd, "armor sixbit needs bit_order msb", .{});
        p.armor = true;
    } else if (!std.mem.eql(u8, raw, "hex")) {
        return bad(diag, alloc, bd, "armor {s} is not hex or sixbit", .{raw});
    }
}

// Lines of a pack that become final once its keys are known: the scope of
// each group body and of each kind, the bit lengths, and the kinds by root
// element.
fn finishPack(alloc: std.mem.Allocator, p: *Pack) !void {
    try buildGroupBodies(alloc, p.common.items);
    for (p.kinds.items) |*k| try buildGroupBodies(alloc, k.lines.items);
    p.common_scope = try buildScope(alloc, p.common.items, p.common_defaults.items, &.{}, false, p.common_gates.items, &.{});
    for (p.kinds.items, 0..) |*k, i| {
        const act = try alloc.alloc(Line, p.common.items.len + k.lines.items.len);
        @memcpy(act[0..p.common.items.len], p.common.items);
        @memcpy(act[p.common.items.len..], k.lines.items);
        k.scope = try buildScope(alloc, act, k.defaults.items, p.common_defaults.items, false, p.common_gates.items, k.gates.items);
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
    // Version 0.93, ruling 6: set by a load with a profile; from then on the
    // limit is `public`, whatever a caller sets.
    profile_limit: bool = false,
    // Version 0.93, ruling 5: in a test build only, a hook that may change
    // the text of a module file or `pack.def` after it was read for its
    // profile and before it is loaded (this engine loads the pack bytes it
    // checked, so the refusal cannot otherwise be reached for a pack).
    test_load_hook: if (builtin.is_test) ?*const fn (std.mem.Allocator, []const u8, []const u8) []const u8 else void =
        if (builtin.is_test) null else {},
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

    // The distribution limit (Version 0.4). After a load with a profile it
    // is the lower of `public` and `d` (Version 0.93, ruling 6): setting
    // `controlled` then is no error and has no effect.
    pub fn setMaxDistribution(self: *Engine, d: Dist) void {
        self.max_distribution = if (self.profile_limit) .public else d;
    }

    // Does this instance hold a controlled module or pack?
    fn holdsControlled(self: *const Engine) bool {
        var it = self.modules.valueIterator();
        while (it.next()) |m| {
            if (m.*.distribution.? == .controlled) return true;
        }
        for (self.packs.items) |p| {
            if (p.distribution.? == .controlled) return true;
        }
        return false;
    }

    // The text a file of a load with a profile is loaded from: the text read,
    // or what the test hook makes of it (ruling 5 of 0.93).
    fn hooked(self: *Engine, path: []const u8, text: []const u8) []const u8 {
        if (builtin.is_test) {
            if (self.test_load_hook) |h| return h(self.alloc, path, text);
        }
        return text;
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
        // Version 0.20: `requires <list>=…` (ruling 19: after the key
        // checks, before the type checks)
        for (p.key_uses.items) |ku| {
            if (ku.use == .requires and ku.eq and self.isList(ku.key)) {
                const err = E.@"bad-directive";
                self.fail(err, "pack {s}: requires {s}=…: {s} is a list", .{ p.format, ku.key, ku.key });
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
                .field, .default, .as_ => !is_list,
                .requires, .with => true,
            };
            if (!fits) {
                const err = E.@"key-type-mismatch";
                self.fail(err, "pack {s}: {s} is {s}, named by a {s} line", .{ p.format, ku.key, if (is_list) "a list" else "a scalar key", if (ku.use == .as_) "when … as" else @tagName(ku.use) });
                return err;
            }
            // Version 0.30: a key bound by `when … as` is declared `int`
            if (ku.use == .as_) {
                const want = self.keyType(ku.key).?;
                if (want != .int) {
                    const err = E.@"key-type-mismatch";
                    self.fail(err, "pack {s}: when … as {s}: the key is {s}, not int", .{ p.format, ku.key, @tagName(want) });
                    return err;
                }
                continue;
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
        try self.resolveGates(p, p.common_gates.items);
        for (p.kinds.items) |*k| {
            try self.resolveLines(p, k.lines.items);
            try self.resolveGates(p, k.gates.items);
            for (k.defaults.items) |*d| try self.readDefault(p, d);
        }
        for (p.common_defaults.items) |*d| try self.readDefault(p, d);
        if (built(.bits)) if (p.seq) |b| try self.resolveSeqBody(p, b);
        try self.checkValues(p);
        // Version 0.33: the `at` checks run last among the module checks,
        // the form before the fixed window (rulings 10 and 25)
        if (p.at_err) |m| {
            const err = E.@"bad-directive";
            self.fail(err, "pack {s}: {s}", .{ p.format, m });
            return err;
        }
        if (p.win_err) |m| {
            const err = E.@"bad-directive";
            self.fail(err, "pack {s}: {s}", .{ p.format, m });
            return err;
        }
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

    // The module files of `models_dir` (Version 0.23, Loading, 1): the names
    // ending in `.def` of regular files or symbolic links to one, not
    // recursing, in byte order of name with `core.def` first, whatever its
    // name sorts as (ruling 9 of 0.6: a `derive` line of another module may
    // name a key of `core`). null: there is no such directory.
    fn listModelFiles(self: *Engine, models_dir: []const u8) !?[]const []const u8 {
        var dir = std.fs.cwd().openDir(models_dir, .{ .iterate = true }) catch |err| switch (err) {
            error.FileNotFound, error.NotDir => return null, // ruling 4 of 0.4: no modules
            else => return err,
        };
        defer dir.close();
        var names = std.ArrayList([]const u8).init(self.alloc);
        var it = dir.iterate();
        while (try it.next()) |entry| {
            if (!std.mem.endsWith(u8, entry.name, ".def")) continue;
            switch (entry.kind) {
                .file => {},
                .sym_link, .unknown => {
                    const st = dir.statFile(entry.name) catch continue; // follows the link
                    if (st.kind != .file) continue;
                },
                else => continue,
            }
            try names.append(try self.alloc.dupe(u8, entry.name));
        }
        std.mem.sort([]const u8, names.items, {}, strLess);
        for (names.items, 0..) |name, i| {
            if (!std.mem.eql(u8, name, "core.def")) continue;
            std.mem.copyBackwards([]const u8, names.items[1 .. i + 1], names.items[0..i]);
            names.items[0] = name;
            break;
        }
        return names.items;
    }

    // Read every module file of `models_dir`: each file's text, module name
    // and `uses` lines. null: there is no such directory.
    fn scanModelDir(self: *Engine, models_dir: []const u8) !?ModelFiles {
        const names = (try self.listModelFiles(models_dir)) orelse return null;
        return try self.readModelFiles(models_dir, names);
    }

    fn readModelFiles(self: *Engine, models_dir: []const u8, names: []const []const u8) !ModelFiles {
        const n = names.len;
        const mf = ModelFiles{
            .dir = models_dir,
            .names = names,
            .texts = try self.alloc.alloc([]const u8, n),
            .mod_names = try self.alloc.alloc([]const u8, n),
            .mod_uses = try self.alloc.alloc([]const []const u8, n),
            .state = try self.alloc.alloc(u8, n),
        };
        @memset(mf.state, 0);
        var tokbuf = std.ArrayList([]const u8).init(self.alloc);
        for (names, 0..) |name, i| {
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
        const mf_opt = try self.scanModelDir(models_dir);
        if (mf_opt) |mf| {
            for (mf.mod_names, 0..) |mn, j| {
                if (std.mem.eql(u8, mn, "core")) try self.loadModelOrdered(mf, j);
            }
        }
        // Each named pack, and (Version 0.34) each pack an `inner` line of a
        // pack read names, transitively; a name with no `pack.def` under
        // the packs directory is skipped (its use is `unknown-format`).
        var text_list = std.ArrayList([]const u8).init(alloc);
        const named = names.items.len;
        var tokbuf = std.ArrayList([]const u8).init(alloc);
        var i: usize = 0;
        while (i < names.items.len) : (i += 1) {
            const name = names.items[i];
            const def_path = try std.fmt.allocPrint(alloc, "{s}/{s}/pack.def", .{ packs_dir, name });
            const text = std.fs.cwd().readFileAlloc(alloc, def_path, max_file) catch |err| {
                self.fail(err, "pack {s}: cannot read {s}", .{ name, def_path });
                return err;
            };
            try text_list.append(text);
            var lines = std.mem.splitScalar(u8, text, '\n');
            while (lines.next()) |line| {
                tokenizeInto(&tokbuf, line) catch |err| switch (err) {
                    error.OutOfMemory => return err,
                    else => continue,
                };
                if (tokbuf.items.len != 2 and tokbuf.items.len != 3) continue;
                if (std.mem.eql(u8, tokbuf.items[0], "inner")) {
                    const fmt = tokbuf.items[1];
                    if (listHolds(names.items, fmt)) continue;
                    if (fmt.len == 0 or std.mem.indexOfAny(u8, fmt, "/\\") != null or std.mem.eql(u8, fmt, ".") or std.mem.eql(u8, fmt, "..")) continue;
                    const ipath = try std.fmt.allocPrint(alloc, "{s}/{s}/pack.def", .{ packs_dir, fmt });
                    std.fs.cwd().access(ipath, .{}) catch continue;
                    try names.append(try alloc.dupe(u8, fmt));
                    continue;
                }
                const mf = mf_opt orelse continue;
                if (tokbuf.items.len != 2 or !std.mem.eql(u8, tokbuf.items[0], "uses")) continue;
                for (mf.mod_names, 0..) |mn, j| {
                    if (std.mem.eql(u8, mn, tokbuf.items[1])) try self.loadModelOrdered(mf, j);
                }
            }
        }
        // in byte order of name
        const order = try alloc.alloc(usize, names.items.len);
        for (order, 0..) |*o, k| o.* = k;
        std.mem.sort(usize, order, names.items, struct {
            fn less(ns: [][]const u8, a: usize, b: usize) bool {
                return std.mem.lessThan(u8, ns[a], ns[b]);
            }
        }.less);
        var sorted = std.ArrayList([]const u8).init(alloc);
        for (order) |o| {
            const name = names.items[o];
            _ = self.loadPack(text_list.items[o]) catch |err| {
                // a pack reached only through an `inner` line that this
                // build or limit refuses is not loaded
                if (o >= named and (err == E.@"unknown-wire" or err == E.@"distribution-refused")) continue;
                self.last_error = try std.fmt.allocPrint(alloc, "{s} ({s}/{s}/pack.def)", .{ self.last_error, packs_dir, name });
                return err;
            };
            try sorted.append(name);
        }
        return .{ .modules = self.modules.count(), .packs = sorted.items };
    }

    /// What `loadTree` is asked to load (Version 0.23, Loading; Version 0.29).
    pub const TreeOptions = struct {
        /// the directory whose subdirectories are packs
        packs_dir: []const u8,
        /// the model modules; null: `<packs_dir>/../model`
        models_dir: ?[]const u8 = null,
        /// load only these subdirectories, in this order; null: every one
        packs_only: ?[]const []const u8 = null,
        /// `open`, `open+copyleft` or `everything`: load only what it holds.
        /// null: no profile, no licence file is read, nothing is skipped.
        profile: ?[]const u8 = null,
        /// read every licence file (ruling 1) even with no profile, as the
        /// `licences` subcommand does
        read_licences: bool = false,
    };

    /// A pack `loadTree` loaded: its directory name and format, and, when the
    /// licence files were read, its licence and its own profile (2c).
    pub const TreePack = struct {
        dir: []const u8,
        format: []const u8,
        licence: ?[]const u8 = null,
        profile: Profile = .none,
    };

    pub const TreeLoaded = struct { modules: usize, packs: []const TreePack };

    fn failLicence(self: *Engine, msg: []const u8) anyerror {
        self.last_error = try std.fmt.allocPrint(self.alloc, "bad-licence: {s}", .{msg});
        return E.@"bad-licence";
    }

    /// Load a tree as the command-line contract does (Version 0.23, Loading):
    /// every module of the model directory, then the packs, stopping at the
    /// first failure. With a profile (Version 0.29, ruling 3), the licence
    /// files are read first and a module or pack the profile does not hold is
    /// not loaded. A packs directory that cannot be listed (no `packs_only`)
    /// is `error.PacksUnreadable`, a failure with no kind; every other failure
    /// is a kind, and `last_error` holds `<kind>: <detail>`.
    pub fn loadTree(self: *Engine, opts: TreeOptions) !TreeLoaded {
        const alloc = self.alloc;
        self.last_error = "";
        // 3a: a name not one of the three is refused before anything is read
        const profile: ?Profile = if (opts.profile) |name|
            (Profile.parse(name) orelse return self.failLicence(try std.fmt.allocPrint(alloc, "{s} is not a profile (open, open+copyleft, everything)", .{name})))
        else
            null;
        // Version 0.93, ruling 6: a load with a profile on an instance that
        // holds a controlled module or pack is refused before anything is
        // read, the limit unchanged; then the limit is `public`, and stays
        // so whatever happens after.
        if (profile != null) {
            if (self.holdsControlled()) {
                self.fail(E.@"distribution-refused", "a load with a profile on an engine that holds a controlled module or pack", .{});
                return E.@"distribution-refused";
            }
            self.profile_limit = true;
            self.max_distribution = .public;
        }
        const reading = profile != null or opts.read_licences;
        const packs_dir = opts.packs_dir;
        const models_dir = opts.models_dir orelse try std.fmt.allocPrint(alloc, "{s}/../model", .{packs_dir});
        var msg: []const u8 = "";

        // 3b: the table, then each module file's licence and lines
        var table: licence.Table = undefined;
        if (reading) {
            const path = try std.fmt.allocPrint(alloc, "{s}/../licences.toml", .{packs_dir});
            table = licence.readTable(alloc, path, &msg) catch |err| switch (err) {
                error.OutOfMemory => return err,
                else => return self.failLicence(msg),
            };
        }
        const all_names = (self.listModelFiles(models_dir) catch |err| {
            if (err == error.OutOfMemory) return err;
            self.last_error = try std.fmt.allocPrint(alloc, "error: cannot read the model directory {s}: {s}", .{ models_dir, @errorName(err) });
            return err;
        }) orelse &[_][]const u8{};
        var mod_lines: []licence.DefLines = &.{};
        var mod_prof: []Profile = &.{};
        if (reading) {
            mod_lines = try alloc.alloc(licence.DefLines, all_names.len);
            const lic = try alloc.alloc(Profile, all_names.len);
            for (all_names, 0..) |name, i| {
                const lpath = try std.fmt.allocPrint(alloc, "{s}/{s}.license", .{ models_dir, name });
                const id = licence.moduleLicence(alloc, lpath, &msg) catch |err| switch (err) {
                    error.OutOfMemory => return err,
                    else => return self.failLicence(msg),
                };
                lic[i] = licence.licenceProfile(&table, id);
                mod_lines[i] = try licence.defFileLines(alloc, try std.fmt.allocPrint(alloc, "{s}/{s}", .{ models_dir, name }));
                // Version 0.93, ruling 2: a file not shown public is in none
                if (!mod_lines[i].public) lic[i] = .none;
            }
            mod_prof = try licence.moduleProfiles(alloc, mod_lines, lic);
        }

        // 3c: the modules the profile holds, in the same order
        var names = all_names;
        if (profile) |pr| {
            var held = std.ArrayList([]const u8).init(alloc);
            for (all_names, 0..) |name, i| {
                // Version 0.93, ruling 2: a module file 2b gives no name is
                // not loaded, also when it is shown public
                if (mod_lines[i].module == null) continue;
                if (pr.holds(mod_prof[i])) try held.append(name);
            }
            names = held.items;
        }
        const mf = self.readModelFiles(models_dir, names) catch |err| {
            if (err == error.OutOfMemory) return err;
            self.last_error = try std.fmt.allocPrint(alloc, "error: cannot read the model directory {s}: {s}", .{ models_dir, @errorName(err) });
            return err;
        };
        if (profile != null) {
            for (mf.texts, 0..) |*t, i| t.* = self.hooked(mf.names[i], t.*);
        }
        for (0..mf.names.len) |i| try self.loadModelOrdered(mf, i);

        // 3d: the packs, each reached as Version 0.23, Loading, 2 says
        var loaded = std.ArrayList(TreePack).init(alloc);
        if (opts.packs_only) |only| {
            var dir_opt: ?std.fs.Dir = std.fs.cwd().openDir(packs_dir, .{}) catch null;
            defer if (dir_opt) |*d| d.close();
            for (only) |name| {
                const one_component = !(std.mem.eql(u8, name, ".") or std.mem.eql(u8, name, "..") or
                    name.len == 0 or std.mem.indexOfAny(u8, name, "/\\") != null);
                const text: ?[]const u8 = if (!one_component) null else if (dir_opt) |d| readPackDefIn(alloc, d, name) else null;
                const t = text orelse {
                    self.fail(E.@"unknown-format", "{s} is not a subdirectory of {s} holding pack.def", .{ name, packs_dir });
                    return E.@"unknown-format";
                };
                try self.treePack(&loaded, packs_dir, name, t, reading, profile, &table, mod_lines, mod_prof);
            }
        } else {
            var dir = std.fs.cwd().openDir(packs_dir, .{ .iterate = true }) catch |err| {
                self.last_error = try std.fmt.allocPrint(alloc, "error: cannot read the packs directory {s}: {s}", .{ packs_dir, @errorName(err) });
                return error.PacksUnreadable;
            };
            defer dir.close();
            var dirs = std.ArrayList([]const u8).init(alloc);
            var it = dir.iterate();
            while (true) {
                const entry = (it.next() catch |err| {
                    self.last_error = try std.fmt.allocPrint(alloc, "error: cannot read the packs directory {s}: {s}", .{ packs_dir, @errorName(err) });
                    return error.PacksUnreadable;
                }) orelse break;
                if (entry.name.len == 0 or entry.name[0] == '.') continue;
                switch (entry.kind) {
                    .directory => {},
                    .sym_link, .unknown => {
                        const st = dir.statFile(entry.name) catch continue; // follows the link
                        if (st.kind != .directory) continue;
                    },
                    else => continue,
                }
                try dirs.append(try alloc.dupe(u8, entry.name));
            }
            std.mem.sort([]const u8, dirs.items, {}, strLess);
            for (dirs.items) |name| {
                const t = readPackDefIn(alloc, dir, name) orelse continue;
                try self.treePack(&loaded, packs_dir, name, t, reading, profile, &table, mod_lines, mod_prof);
            }
        }
        return .{ .modules = self.modules.count(), .packs = loaded.items };
    }

    // One pack reached by `loadTree`: its licence and `uses` lines when the
    // licence files are read, skipped when the profile does not hold it,
    // else loaded.
    fn treePack(self: *Engine, loaded: *std.ArrayList(TreePack), packs_dir: []const u8, name: []const u8, text: []const u8, reading: bool, profile: ?Profile, table: *const licence.Table, mod_lines: []const licence.DefLines, mod_prof: []const Profile) !void {
        const alloc = self.alloc;
        var entry = TreePack{ .dir = name, .format = "" };
        if (reading) {
            var msg: []const u8 = "";
            const path = try std.fmt.allocPrint(alloc, "{s}/{s}/REUSE.toml", .{ packs_dir, name });
            const id = licence.packLicence(alloc, path, &msg) catch |err| switch (err) {
                error.OutOfMemory => return err,
                else => return self.failLicence(msg),
            };
            const dl = try licence.defLines(alloc, text);
            // 2c: its licence, the module `core`, and the modules it uses
            // Version 0.93, ruling 2: a `pack.def` not shown public is in none
            var p: Profile = if (dl.public) licence.licenceProfile(table, id) else .none;
            p = licence.usesProfile(mod_lines, mod_prof, p, &.{"core"});
            p = licence.usesProfile(mod_lines, mod_prof, p, dl.uses);
            if (profile) |pr| {
                if (!pr.holds(p)) return; // 3e: as if it were not there
            }
            entry.licence = id;
            entry.profile = p;
        }
        const pk = self.loadPack(if (profile != null) self.hooked(name, text) else text) catch |err| {
            if (err == error.OutOfMemory) return err;
            self.last_error = try std.fmt.allocPrint(alloc, "{s} ({s}/{s}/pack.def)", .{ self.last_error, packs_dir, name });
            return err;
        };
        entry.format = pk.format;
        try loaded.append(entry);
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
                    try self.resolveGates(p, g.gates.items);
                    for (g.defaults.items) |*d| try self.readDefault(p, d);
                },
                else => {},
            }
        }
    }

    // The defaults of each gate block (0.17), by key; the first line of a key wins.
    fn resolveGates(self: *Engine, p: *const Pack, gates: []const *Gate) anyerror!void {
        for (gates) |gt| {
            for (gt.defaults.items) |*d| {
                try self.readDefault(p, d);
                const gop = try gt.dmap.getOrPut(self.alloc, d.key);
                if (!gop.found_existing) gop.value_ptr.* = d.value;
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
            // Version 0.20: the switch key's type, each case's defaults
            if (n.sw) |sw| sw.kty = self.keyType(sw.key) orelse .string;
            if (n.cs) |cs| try self.resolveSeqDefaults(p, cs.defaults.items, &cs.dmap);
            try self.resolveSeqNodes(p, n.body);
            if (n.gbody) |b| try self.resolveSeqBody(p, b);
        }
    }

    // Version 0.20, ruling 19: the `requires =` and `case` values in line
    // order, each line its type, then its duplicates.
    fn checkValues(self: *Engine, p: *Pack) anyerror!void {
        for (p.vchecks.items) |vc| {
            switch (vc) {
                .req => |t| {
                    t.kty = self.keyType(t.key) orelse .string;
                    const out = try self.alloc.alloc([]const u8, t.vals.?.len);
                    for (t.vals.?, 0..) |v, i| {
                        out[i] = (try canonValue(self.alloc, t.kty, v)) orelse {
                            const err = E.@"key-type-mismatch";
                            self.fail(err, "pack {s}: line {d}: requires {s}={s}: {s} is not of the key's type {s}", .{ p.format, t.lineno, t.key, v, v, @tagName(t.kty) });
                            return err;
                        };
                    }
                    t.canon = out;
                },
                .case_ => |c| {
                    const kty = self.keyType(c.sw.key) orelse .string;
                    const out = try self.alloc.alloc([]const u8, c.cs.vals.len);
                    for (c.cs.vals, 0..) |v, i| {
                        out[i] = (try canonValue(self.alloc, kty, v)) orelse {
                            const err = E.@"key-type-mismatch";
                            self.fail(err, "pack {s}: line {d}: case {s}: not of the type {s} of {s}", .{ p.format, c.cs.lineno, v, @tagName(kty), c.sw.key });
                            return err;
                        };
                    }
                    for (out, 0..) |v, i| {
                        var dup = listHolds(out[0..i], v);
                        for (c.sw.cases.items) |other| {
                            if (other == c.cs) break;
                            if (listHolds(other.canon, v)) dup = true;
                        }
                        if (dup) {
                            const err = E.@"bad-directive";
                            self.fail(err, "pack {s}: line {d}: case value {s} is listed twice in the switch on {s}", .{ p.format, c.cs.lineno, c.cs.vals[i], c.sw.key });
                            return err;
                        }
                    }
                    c.cs.canon = out;
                },
            }
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
        var diag = Diag{ .max_items = self.max_items, .packs = &self.pack_index };
        return decodePack(self.scratch, p, bytes, &diag) catch |err| {
            self.fail(err, "decode {s}: {s}", .{ fmt, diag.msg });
            return err;
        };
    }

    // encode(format, Entity) -> bytes
    pub fn encode(self: *Engine, fmt: []const u8, e: *const Entity) ![]u8 {
        return self.encodeHeld(fmt, e, false);
    }

    // encode; with `held_check`, the encode of a conversion between two
    // formats: the chosen kind must hold one of its keys (Version 0.94).
    fn encodeHeld(self: *Engine, fmt: []const u8, e: *const Entity, held_check: bool) ![]u8 {
        const p = try self.pack(fmt);
        var diag = Diag{ .packs = &self.pack_index, .held_check = held_check };
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
    // Version 0.34: computed when asked for. Each `inner` line whose pack
    // passes the checks of the line adds, at its place in reading order, the
    // entries of model_keys(<format>) not yet listed.
    pub fn modelKeysOf(self: *Engine, fmt: []const u8) ![]const []const u8 {
        const p = try self.pack(fmt);
        const own = try modelKeys(self.scratch, p);
        if (p.inners.items.len == 0) return own;
        var out = std.ArrayList([]const u8).init(self.scratch);
        var seen = std.StringHashMap(void).init(self.scratch);
        var ui: usize = 0; // the key uses walked so far
        for (p.inners.items) |im| {
            // the outer entries of the key uses before the line
            while (ui < im.pos) : (ui += 1) {
                const ku = p.key_uses.items[ui];
                // a `when … as` key is a mapped key (rulings 5 and 24 of 0.30)
                if (ku.use != .field and ku.use != .group and ku.use != .as_) continue;
                const name = try mkName(self.scratch, ku.grp, ku.key, ku.use == .group);
                if (seen.contains(name)) continue;
                try seen.put(name, {});
                try out.append(name);
            }
            const ip = self.findPack(im.fmt) orelse continue;
            if (innerCheck(p, ip) != null) continue;
            for (try modelKeys(self.scratch, ip)) |name| {
                if (seen.contains(name)) continue;
                try seen.put(name, {});
                try out.append(name);
            }
        }
        for (own) |name| {
            if (seen.contains(name)) continue;
            try seen.put(name, {});
            try out.append(name);
        }
        return out.toOwnedSlice();
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
        self.clearKinds(&e, from, to);
        if (!same or context != null) try self.finish(self.scratch, &e, context);
        return self.encodeHeld(to, &e, !same);
    }

    // Entity.kind is kept when from == to, or when an `inner` line of `to`
    // names its format; Entity.inner_kind when from == to, when it names
    // `to`, or when an `inner` line of `to` names its format (Version 0.34).
    fn clearKinds(self: *const Engine, e: *Entity, from: []const u8, to: []const u8) void {
        if (std.mem.eql(u8, from, to)) return;
        const to_pack = self.findPack(to).?;
        if (e.kind_fmt) |kf| {
            if (!packHasInner(to_pack, kf)) e.clearKind();
        }
        if (e.inner_kind_fmt) |kf| {
            if (!std.mem.eql(u8, kf, to) and !packHasInner(to_pack, kf)) e.clearInnerKind();
        }
    }

    // Steps 2 and 3 of `convert`: the context, then the derivations.
    fn finish(self: *Engine, alloc: std.mem.Allocator, e: *Entity, context: ?[]const KV) !void {
        const keep = self.scratch;
        self.scratch = alloc;
        defer self.scratch = keep;
        if (context) |c| try self.fillContext(e, c);
        try self.complete(e);
    }

    // Version 0.92: one result of `convertRun`.
    pub const RunResult = union(enum) {
        ok: []const u8,
        // the kind, and the message "<kind>: <detail>"
        err: struct { kind: anyerror, msg: []const u8 },
    };

    fn errResult(self: *Engine, err: anyerror) RunResult {
        return .{ .err = .{ .kind = err, .msg = self.last_error } };
    }

    fn oneResult(self: *Engine, r: RunResult) ![]const RunResult {
        const out = try self.scratch.alloc(RunResult, 1);
        out[0] = r;
        return out;
    }

    // convert_run(from, to, bytes, context) (Version 0.92): one result per
    // message of a carrier; one result, the whole, to a carrier pack and for
    // an ordinary message. An error is the call's.
    pub fn convertRun(self: *Engine, from: []const u8, to: []const u8, bytes: []const u8, context: ?[]const KV) ![]const RunResult {
        const fp = try self.pack(from);
        const tp = try self.pack(to);
        if (!built(.bits) or !fp.has_run) {
            var e = self.decode(from, bytes) catch |err| {
                if (err == error.OutOfMemory or tp.has_run) return err;
                return self.oneResult(self.errResult(err));
            };
            return self.finishOne(&e, from, to, context);
        }
        if (comptime built(.bits)) {
            var r = RunRead{ .to_carrier = tp.has_run, .arena = std.heap.ArenaAllocator.init(self.scratch) };
            defer r.arena.deinit();
            var diag = Diag{ .max_items = self.max_items, .packs = &self.pack_index, .run = &r };
            var outer = decodePack(self.scratch, fp, bytes, &diag) catch |err| {
                if (err == error.OutOfMemory) return err;
                self.fail(err, "decode {s}: {s}", .{ from, diag.msg });
                // the call's: to a carrier pack, a `run` line reached, or the
                // decode stopped before that was known (ruling 4)
                if (tp.has_run or r.reached or !(r.ended or r.ordinary)) return err;
                return self.oneResult(self.errResult(err));
            };
            if (!r.reached) return self.finishOne(&outer, from, to, context);
            if (tp.has_run) {
                // the other decode errors of the messages
                for (r.msgs.items) |m| if (m.fail) |f| {
                    self.fail(f.kind, "decode {s}: {s}", .{ from, f.msg });
                    return f.kind;
                };
            }
            // the items of all joined entities (ruling 5), after every other
            // decode error of the call
            r.checkSum(&diag, self.scratch, &outer) catch |err| {
                self.fail(err, "decode {s}: {s}", .{ from, diag.msg });
                return err;
            };
            // the context is checked once, for an empty run too (ruling 10)
            if (context) |c| {
                var probe = Entity.init(self.scratch);
                try self.fillContext(&probe, c);
            }
            if (tp.has_run) return self.oneResult(.{ .ok = try self.writeCarrier(&r, &outer, from, tp, context) });
            const out = try self.scratch.alloc(RunResult, r.msgs.items.len);
            for (r.msgs.items, out) |m, *res| res.* = try self.messageResult(&r, &outer, m, from, to, context);
            return out;
        } else unreachable;
    }

    // The result of an ordinary message that decoded. A bad context key is
    // the call's error, an encode error its result, or the call's to a
    // carrier pack (ruling 4 of 0.92).
    fn finishOne(self: *Engine, e: *Entity, from: []const u8, to: []const u8, context: ?[]const KV) ![]const RunResult {
        self.clearKinds(e, from, to);
        const same = std.mem.eql(u8, from, to);
        if (!same or context != null) try self.finish(self.scratch, e, context);
        const out = self.encodeHeld(to, e, !same) catch |err| {
            if (err == error.OutOfMemory or self.findPack(to).?.has_run) return err;
            return self.oneResult(self.errResult(err));
        };
        return self.oneResult(.{ .ok = out });
    }

    // One message of a run to a format that is not a carrier pack: 0.6 steps
    // 1 to 4 on the joined entity. Only the result is kept.
    fn messageResult(self: *Engine, r: *RunRead, outer: *const Entity, m: RunMsg, from: []const u8, to: []const u8, context: ?[]const KV) !RunResult {
        if (m.fail) |f| {
            self.fail(f.kind, "decode {s}: {s}", .{ from, f.msg });
            return self.errResult(f.kind);
        }
        _ = r.arena.reset(.retain_capacity);
        const a = r.arena.allocator();
        const keep = self.scratch;
        var e = try r.joined(a, outer, m);
        self.clearKinds(&e, from, to);
        try self.finish(a, &e, context);
        self.scratch = a;
        defer self.scratch = keep;
        const out = self.encodeHeld(to, &e, !std.mem.eql(u8, from, to)) catch |err| {
            if (err == error.OutOfMemory) return err;
            // it outlives the arena
            self.last_error = try keep.dupe(u8, self.last_error);
            return self.errResult(err);
        };
        return .{ .ok = try keep.dupe(u8, out) };
    }

    // From a carrier to a carrier pack (ruling 6 of 0.92).
    fn writeCarrier(self: *Engine, r: *RunRead, outer: *const Entity, from: []const u8, tp: *const Pack, context: ?[]const KV) ![]const u8 {
        const to = tp.format;
        const same = std.mem.eql(u8, from, to);
        var oe = Entity.init(self.scratch);
        for (outer.fields.ptr[0..outer.fields.len]) |en| try oe.put(en.key, en.value);
        for (outer.lists.ptr[0..outer.lists.len]) |en| try oe.putList(en.key, en.value);
        if (same) {
            oe.kind_fmt = outer.kind_fmt;
            oe.kind_name = outer.kind_name;
        }
        if (!same or context != null) try self.finish(self.scratch, &oe, context);
        var diag = Diag{ .packs = &self.pack_index };
        // the target's kind, chosen on the outer entity alone
        const body = tp.seq.?;
        var chooser = SEnc{ .alloc = self.scratch, .p = tp, .diag = &diag, .out = std.ArrayList(u8).init(self.scratch) };
        const kind = chooser.selectKind(body, &oe, false) catch |err| {
            self.fail(err, "encode {s}: {s}", .{ to, diag.msg });
            return err;
        };
        const runs = seqRunCount(body.common) + if (kind) |k| seqRunCount(k.lines) else 0;
        if (runs == 0) {
            // a kind without a `run` line takes one message; the count is
            // made first (0.94 ruling 7)
            if (r.msgs.items.len != 1) {
                const err = E.@"message-count";
                self.fail(err, "encode {s}: kind {s} takes one message, the run holds {d}", .{ to, if (kind) |k| k.name else "", r.msgs.items.len });
                return err;
            }
            var e = try r.joined(self.scratch, outer, r.msgs.items[0]);
            self.clearKinds(&e, from, to);
            if (!same or context != null) try self.finish(self.scratch, &e, context);
            if (kind) |k| {
                // Version 0.94, ruling 7: the joined entity is checked as
                // `convert`, kept kinds (ruling 4) included
                if (!same) {
                    const ki = (@intFromPtr(k) - @intFromPtr(body.kinds.ptr)) / @sizeOf(SKind);
                    heldCheck(self.scratch, tp, ki, &e, &diag) catch |err| {
                        self.fail(err, "encode {s}: {s}", .{ to, diag.msg });
                        return err;
                    };
                }
                e.kind_fmt = to;
                e.kind_name = k.name;
            }
            return self.encode(to, &e);
        }
        // Version 0.94, ruling 7: from another carrier, the chosen kind holds
        // a key of the outer entity joined with the first message, or of
        // the outer entity alone when the run is empty. The inner kind the
        // first message records is not a kept kind here.
        if (!same) if (kind) |k| {
            var probe = oe;
            if (r.msgs.items.len > 0) {
                probe = try r.joined(self.scratch, outer, r.msgs.items[0]);
                self.clearKinds(&probe, from, to);
                try self.finish(self.scratch, &probe, context);
                probe.clearInnerKind();
            }
            const ki = (@intFromPtr(k) - @intFromPtr(body.kinds.ptr)) / @sizeOf(SKind);
            heldCheck(self.scratch, tp, ki, &probe, &diag) catch |err| {
                self.fail(err, "encode {s}: {s}", .{ to, diag.msg });
                return err;
            };
        };
        var w = RunWrite{ .eng = self, .read = r, .outer = outer, .from = from, .to = to, .context = context };
        diag.run_write = &w;
        return encodePack(self.scratch, tp, &oe, &diag) catch |err| {
            self.fail(err, "encode {s}: {s}", .{ to, diag.msg });
            return err;
        };
    }

    // decode_run(format, bytes) (Version 0.92): the entity of the outer lines,
    // and the messages, each decoded when it is asked for.
    pub const RunDecode = struct {
        outer: Entity,
        read: ?RunRead,

        pub fn count(self: *const RunDecode) usize {
            return if (self.read) |r| r.msgs.items.len else 1;
        }

        // The joined entity of message `i`, or its failure.
        pub fn message(self: *const RunDecode, alloc: std.mem.Allocator, i: usize) anyerror!Entity {
            const r = &(self.read orelse return self.outer);
            const m = r.msgs.items[i];
            if (m.fail) |f| return f.kind;
            if (comptime built(.bits)) return r.joined(alloc, &self.outer, m) else unreachable;
        }
    };

    pub fn decodeRun(self: *Engine, fmt: []const u8, bytes: []const u8) !RunDecode {
        const p = try self.pack(fmt);
        if (!built(.bits) or !p.has_run) return .{ .outer = try self.decode(fmt, bytes), .read = null };
        var r = RunRead{ .to_carrier = false, .arena = std.heap.ArenaAllocator.init(self.scratch) };
        var diag = Diag{ .max_items = self.max_items, .packs = &self.pack_index, .run = &r };
        const outer = decodePack(self.scratch, p, bytes, &diag) catch |err| {
            r.arena.deinit();
            if (err != error.OutOfMemory) self.fail(err, "decode {s}: {s}", .{ fmt, diag.msg });
            return err;
        };
        r.arena.deinit();
        if (r.reached) r.checkSum(&diag, self.scratch, &outer) catch |err| {
            self.fail(err, "decode {s}: {s}", .{ fmt, diag.msg });
            return err;
        };
        return .{ .outer = outer, .read = if (r.reached) r else null };
    }

    // What one conversion of `convertIn` uses and leaves: its allocator, its
    // limit on list items (null: the engine's), and after a failure its
    // message "<kind>: <detail>", allocated from `alloc`.
    pub const Call = struct {
        alloc: std.mem.Allocator,
        max_items: ?usize = null,
        last_error: []const u8 = "",
    };

    // convert, for an engine shared between threads (Version 0.25, ruling
    // 1c). What was loaded is only read: the engine's `scratch`, `last_error`
    // and `max_items` are not touched, the call's own are used, so any
    // number of threads may call it at once on one loaded engine, each with
    // its own `Call` and an allocator no other thread uses at that moment.
    // Loading is not to run at the same time.
    pub fn convertIn(self: *const Engine, call: *Call, from: []const u8, to: []const u8, bytes: []const u8, context: ?[]const KV) ![]u8 {
        // A copy of the engine's header: its maps and lists share the loaded
        // modules and packs, which a conversion never changes.
        var view = self.*;
        view.scratch = call.alloc;
        view.last_error = "";
        if (call.max_items) |n| view.max_items = n;
        defer call.last_error = view.last_error;
        return view.convert(from, to, bytes, context);
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
    if (d.f == .tokens) {
        // the tokens whose argument is present and not 0, in order; absent
        // when there is none (ruling 7 of 0.18)
        var buf = std.ArrayList(u8).init(alloc);
        var n: usize = 0;
        for (d.args, 0..) |a, i| {
            const v = e.get(a) orelse continue;
            if (v != .int or v.int == 0) continue;
            if (n > 0) try buf.appendSlice(d.sep);
            try buf.appendSlice(d.toks[i]);
            n += 1;
        }
        if (n == 0) return false;
        try e.put(d.target, MV{ .str = try buf.toOwnedSlice() });
        return true;
    }
    for (d.args) |a| if (!e.fields.contains(a)) return false;
    const a0 = e.get(d.args[0]).?;
    if (d.f == .has_token) {
        if (a0 != .str) return false;
        var hit = false;
        var it = std.mem.splitSequence(u8, a0.str, d.sep);
        while (it.next()) |part| {
            if (part.len > 0 and std.mem.eql(u8, part, d.toks[0])) hit = true;
        }
        try e.put(d.target, MV{ .int = @intFromBool(hit) });
        return true;
    }
    if (d.f == .text_if) {
        if (a0 != .int or a0.int == 0) return false;
        try e.put(d.target, MV{ .str = d.text });
        return true;
    }
    var out: MV = undefined;
    if (@intFromEnum(d.f) >= @intFromEnum(DFn.sec_of)) {
        var av: [3]MV = undefined;
        for (d.args, 0..) |a, i| av[i] = e.get(a).?;
        out = derive16(d.f, av[0..d.args.len]) orelse return false;
        if (out == .float and !std.math.isFinite(out.float)) return false;
        try e.put(d.target, out);
        return true;
    }
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
        // held by the entity, whatever the value: 1 (Version 0.12)
        .present => out = MV{ .int = 1 },
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

// ---------------------------------------------------------------------------
// Version 0.16: derive functions for time, distance and frames
// ---------------------------------------------------------------------------

const wgs_a: f64 = 6378137.0;
const wgs_f: f64 = 1.0 / 298.257223563;
const wgs_e2: f64 = wgs_f * (2.0 - wgs_f);
const wgs_b: f64 = wgs_a * (1.0 - wgs_f);

// An integer result in the signed 64-bit range, else absent.
fn int64Of(v: i128) ?MV {
    if (v < std.math.minInt(i64) or v > std.math.maxInt(i64)) return null;
    return MV{ .int = @intCast(v) };
}

// A square root that leaves the target absent on a negative argument
// (ruling 1 of 0.16).
fn sqrtOk(x: f64) ?f64 {
    if (!(x >= 0)) return null;
    return @sqrt(x);
}

// A latitude in degrees as φ; absent outside [-90, 90] (ruling 6 of 0.16).
fn phiOf(lat: f64) ?f64 {
    if (!(lat >= -90 and lat <= 90)) return null;
    return lat * deg_to_rad;
}

// 1 − e² sin² φ
fn wgsW(phi: f64) f64 {
    const s = @sin(phi);
    return 1.0 - wgs_e2 * s * s;
}

fn primeN(phi: f64) ?f64 {
    const r = sqrtOk(wgsW(phi)) orelse return null;
    return wgs_a / r;
}

fn meridM(phi: f64) f64 {
    return wgs_a * (1.0 - wgs_e2) / std.math.pow(f64, wgsW(phi), 1.5);
}

const Geodetic = struct { phi: f64, h: f64 };

// Heikkinen's closed form, in the order the specification gives it. null:
// `G ≤ 0` (ruling 2), or an intermediate that is not finite or a square root
// of a negative number (ruling 1); the square root inside `r0` takes a
// negative argument as 0 (ruling 9).
fn heikkinen(x: f64, y: f64, z: f64) ?Geodetic {
    const a = wgs_a;
    const b = wgs_b;
    const e2 = wgs_e2;
    const e4 = e2 * e2;
    const a2 = a * a;
    const b2 = b * b;
    const p = sqrtOk(x * x + y * y) orelse return null;
    const F = 54.0 * b2 * z * z;
    const G = p * p + (1.0 - e2) * z * z - e2 * (a2 - b2);
    if (!(G > 0)) return null;
    const c = e4 * F * p * p / (G * G * G);
    const s = std.math.cbrt(1.0 + c + (sqrtOk(c * c + 2.0 * c) orelse return null));
    const k = s + 1.0 + 1.0 / s;
    const P = F / (3.0 * k * k * G * G);
    const Q = sqrtOk(1.0 + 2.0 * e4 * P) orelse return null;
    var inner = a2 / 2.0 * (1.0 + 1.0 / Q) - P * (1.0 - e2) * z * z / (Q * (1.0 + Q)) - P * p * p / 2.0;
    if (inner < 0) inner = 0;
    const r0 = -P * e2 * p / (1.0 + Q) + (sqrtOk(inner) orelse return null);
    const pr = p - e2 * r0;
    const U = sqrtOk(pr * pr + z * z) orelse return null;
    const V = sqrtOk(pr * pr + (1.0 - e2) * z * z) orelse return null;
    const z0 = b2 * z / (a * V);
    const h = U * (1.0 - b2 / (a * V));
    const phi = std.math.atan2(z + (a2 - b2) / b2 * z0, p);
    if (!std.math.isFinite(h) or !std.math.isFinite(phi)) return null;
    return .{ .phi = phi, .h = h };
}

// One derive function of Version 0.16 on present arguments of the types the
// load checked. null: the target stays absent; never an error (ruling 1).
fn derive16(f: DFn, av: []const MV) ?MV {
    switch (f) {
        .sec_of, .nsec_of, .ms_of => {
            for (av) |v| if (v != .int) return null;
            const m: i128 = av[0].int;
            return switch (f) {
                .sec_of => int64Of(@divFloor(m, 1000)),
                .nsec_of => int64Of((m - 1000 * @divFloor(m, 1000)) * 1000000),
                else => int64Of(m * 1000 + @divFloor(@as(i128, av[1].int), 1000000)),
            };
        },
        .add, .sub => {
            if (av[0] == .int and av[1] == .int) {
                const x0: i128 = av[0].int;
                const x1: i128 = av[1].int;
                return int64Of(if (f == .add) x0 + x1 else x0 - x1);
            }
            if (av[0] != .float or av[1] != .float) return null;
            return MV{ .float = if (f == .add) av[0].float + av[1].float else av[0].float - av[1].float };
        },
        else => {},
    }
    var x: [3]f64 = undefined;
    for (av, 0..) |v, i| {
        if (v != .float) return null;
        x[i] = v.float;
    }
    const r: f64 = switch (f) {
        .deg => x[0] * rad_to_deg,
        .rad => x[0] * deg_to_rad,
        .deg_lat_of => (x[0] / meridM(phiOf(x[1]) orelse return null)) * rad_to_deg,
        .deg_lon_of => blk: {
            const phi = phiOf(x[1]) orelse return null;
            const cp = @abs(@cos(phi));
            if (!(cp > 1e-12)) return null;
            break :blk (x[0] / ((primeN(phi) orelse return null) * cp)) * rad_to_deg;
        },
        .m_lat_of => x[0] * deg_to_rad * meridM(phiOf(x[1]) orelse return null),
        .m_lon_of => blk: {
            const phi = phiOf(x[1]) orelse return null;
            break :blk x[0] * deg_to_rad * (primeN(phi) orelse return null) * @abs(@cos(phi));
        },
        .ecef_x, .ecef_y, .ecef_z => blk: {
            const phi = phiOf(x[0]) orelse return null;
            const lam = x[1] * deg_to_rad;
            const n = primeN(phi) orelse return null;
            break :blk switch (f) {
                .ecef_x => (n + x[2]) * @cos(phi) * @cos(lam),
                .ecef_y => (n + x[2]) * @cos(phi) * @sin(lam),
                else => (n * (1.0 - wgs_e2) + x[2]) * @sin(phi),
            };
        },
        .lon_of_ecef => blk: {
            if (x[0] == 0 and x[1] == 0) return null;
            var lon = std.math.atan2(x[1], x[0]) * rad_to_deg;
            if (lon == -180) lon = 180; // ruling 5
            break :blk lon;
        },
        .lat_of_ecef => (heikkinen(x[0], x[1], x[2]) orelse return null).phi * rad_to_deg,
        .hae_of_ecef => (heikkinen(x[0], x[1], x[2]) orelse return null).h,
        else => return null,
    };
    if (!std.math.isFinite(r)) return null;
    return MV{ .float = r };
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
    const era = @divFloor(y, 400); // floor division: no adjustment for y < 0
    const yoe = y - era * 400; // [0, 399]
    const mp = if (m > 2) m - 3 else m + 9; // [0,11]
    const doy = @divFloor(153 * mp + 2, 5) + d - 1; // [0,365]
    const doe = yoe * 365 + @divFloor(yoe, 4) - @divFloor(yoe, 100) + doy; // [0,146096]
    return era * 146097 + doe - 719468;
}

const Civil = struct { y: i64, m: i64, d: i64 };

fn civilFromDays(z_in: i64) Civil {
    const z = z_in + 719468;
    const era = @divFloor(z, 146097); // floor division: no adjustment for z < 0
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

// `short` (iso8601_short, Version 0.18): no fraction when the milliseconds
// are 0, else their digits with trailing zeros removed. `iso8601_ms` writes
// 0001-01-01 to 9999-12-31 (ruling 3f of 0.11); `iso8601_short` 0000-01-01
// to 9999-12-31 (ruling 11 of 0.18), checked on the civil year below.
fn msToIso(alloc: std.mem.Allocator, ms: i64, short: bool) ![]const u8 {
    if (!short and (ms < iso_min_ms or ms > iso_max_ms)) return E.@"transform-encode"; // ruling 3f of 0.11
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
    if (short) {
        const head = try std.fmt.allocPrint(alloc, "{d:0>4}-{d:0>2}-{d:0>2}T{d:0>2}:{d:0>2}:{d:0>2}", .{
            @as(u64, @intCast(c.y)), @as(u64, @intCast(c.m)), @as(u64, @intCast(c.d)),
            @as(u64, @intCast(hh)),  @as(u64, @intCast(mm)),  @as(u64, @intCast(ss)),
        });
        if (msec == 0) return std.fmt.allocPrint(alloc, "{s}Z", .{head});
        var digits: [3]u8 = undefined;
        _ = std.fmt.bufPrint(&digits, "{d:0>3}", .{@as(u64, @intCast(msec))}) catch unreachable;
        var n: usize = 3;
        while (digits[n - 1] == '0') n -= 1;
        return std.fmt.allocPrint(alloc, "{s}.{s}Z", .{ head, digits[0..n] });
    }
    return std.fmt.allocPrint(alloc, "{d:0>4}-{d:0>2}-{d:0>2}T{d:0>2}:{d:0>2}:{d:0>2}.{d:0>3}Z", .{
        @as(u64, @intCast(c.y)), @as(u64, @intCast(c.m)), @as(u64, @intCast(c.d)),
        @as(u64, @intCast(hh)),  @as(u64, @intCast(mm)),  @as(u64, @intCast(ss)),
        @as(u64, @intCast(msec)),
    });
}

// `iso8601_s` encode (Version 0.26, ruling 3): the 24 characters of
// iso8601_ms less `.fff`, so the second that holds the instant, never
// rounded; the range is that of iso8601_ms (ruling 3f of 0.11).
fn msToIsoSeconds(alloc: std.mem.Allocator, ms: i64) ![]const u8 {
    const full = try msToIso(alloc, ms, false);
    return std.fmt.allocPrint(alloc, "{s}Z", .{full[0..19]});
}

// ---------------------------------------------------------------------------
// XML DOM + parser
// ---------------------------------------------------------------------------

// `weak`: written by a sentinel (Version 0.9); a field line whose key is
// present writes over it.
// `unset`: a place a line named that no line has written yet (ruling 23 of
// 0.9, ruling 1 of 0.18); it is not output.
const XmlAttr = struct { name: []const u8, value: []const u8, weak: bool = false, unset: bool = false };

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
    // encode: written even when nothing inside it is (an `element` line of
    // 0.18, a group item)
    forced: bool = false,

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
// null when the attribute or element does not exist. This is what a `when`
// compares (`present`: the element exists, whatever its text) and what a
// field decodes: text that is only whitespace is text (ruling 1m of 0.11,
// ruling 24 of 0.15).
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
        .iso8601_ms, .iso8601_short, .iso8601_s => {
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
fn jsonRaw(alloc: std.mem.Allocator, tr: Transform, mv: MV) ![]const u8 {
    switch (tr.kind) {
        .codestr, .codenum => return jsonStr(alloc, try codeTextEncode(alloc, tr, mv)),
        .tscale, .iscale => return textScaleEncode(alloc, tr, mv),
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
        .iso8601_ms, .iso8601_short => {
            if (mv != .int) return E.@"transform-encode";
            return jsonStr(alloc, try msToIso(alloc, mv.int, tr.kind == .iso8601_short));
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
    if (ln.wjson.len > 0) return ln.wjson; // computed as the pack loaded
    if (!ln.wforced) {
        if (std.mem.eql(u8, ln.wtext, "true") or std.mem.eql(u8, ln.wtext, "false")) return ln.wtext;
        if (isCanonNumber(alloc, ln.wtext)) return ln.wtext;
    }
    return jsonStr(alloc, ln.wtext);
}

// Does any value of a `when` list hold for this member value (Version 0.20)?
fn whenJsonHoldsAny(alloc: std.mem.Allocator, ln: *const Line, val: ?JValue) bool {
    if (ln.wpresent) return whenJsonHolds(alloc, ln.*, val);
    var l2 = ln.*;
    for (ln.walts) |a| {
        l2.wtext = a.text;
        l2.wforced = a.forced;
        if (whenJsonHolds(alloc, l2, val)) return true;
    }
    return false;
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

// The bit order of a `bits` pack. lsb: bit i is bit (i mod 8) of byte
// (i div 8), and a field's first bit is its value's least significant. msb:
// bit i is bit 7 - (i mod 8) of byte (i div 8), and a field's first bit is
// its value's most significant. msb-lsb (Version 0.22): positions as msb,
// values as lsb.
const BitOrd = enum {
    lsb,
    msb,
    msb_lsb,

    // Is bit i of a word bit 7 - (i mod 8) of its byte?
    fn highFirst(self: BitOrd) bool {
        return self != .lsb;
    }
};

fn bitOrdOf(text: []const u8) ?BitOrd {
    if (std.mem.eql(u8, text, "lsb")) return .lsb;
    if (std.mem.eql(u8, text, "msb")) return .msb;
    if (std.mem.eql(u8, text, "msb-lsb")) return .msb_lsb;
    return null;
}

// `len` bits (1..64) from absolute bit `start` of the message, in the bit
// order `ord`.
fn getBits(buf: []const u8, ord: BitOrd, start: usize, len: usize) u64 {
    var v: u64 = 0;
    var k: usize = 0;
    while (k < len) : (k += 1) {
        const a = start + k;
        const byte = buf[a / 8];
        const bit: u64 = (byte >> @as(u3, @intCast(if (ord.highFirst()) 7 - (a % 8) else a % 8))) & 1;
        if (ord == .msb) {
            v = (v << 1) | bit;
        } else {
            v |= bit << @as(u6, @intCast(k));
        }
    }
    return v;
}

// Write the low `len` bits of `value` over the range (set and clear).
fn setBits(buf: []u8, ord: BitOrd, start: usize, len: usize, value: u64) void {
    var k: usize = 0;
    while (k < len) : (k += 1) {
        const a = start + k;
        const vbit: u64 = if (ord == .msb)
            (value >> @as(u6, @intCast(len - 1 - k))) & 1
        else
            (value >> @as(u6, @intCast(k))) & 1;
        const mask: u8 = @as(u8, 1) << @as(u3, @intCast(if (ord.highFirst()) 7 - (a % 8) else a % 8));
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

// A message of the bits wire as its input gives it: the bytes, and the number
// of bits (eight per byte for hex, six per character under `armor sixbit`).
const BitsIn = struct { buf: []u8, nbits: usize };

// Six-bit armor (Version 0.14): each character `0`..`W` stands for `c - 0x30`,
// `` ` ``..`w` for `c - 0x38`, most significant bit first; any other character
// is `malformed-wire`. Every character is checked before any bit is read. The
// bits are packed msb first (armor needs `bit_order msb`), the last byte
// zero-filled.
fn armorDecode(alloc: std.mem.Allocator, s: []const u8) !BitsIn {
    for (s) |c| {
        if (!((c >= 0x30 and c <= 0x57) or (c >= 0x60 and c <= 0x77))) return E.@"malformed-wire";
    }
    const nbits = 6 * s.len;
    const out = try alloc.alloc(u8, (nbits + 7) / 8);
    @memset(out, 0);
    for (s, 0..) |c, j| {
        const v: u64 = if (c <= 0x57) c - 0x30 else c - 0x38;
        setBits(out, .msb, 6 * j, 6, v);
    }
    return .{ .buf = out, .nbits = nbits };
}

// The input of a bits pack, hex or armored.
fn bitsInput(alloc: std.mem.Allocator, p: *const Pack, s: []const u8) !BitsIn {
    if (p.armor) return armorDecode(alloc, s);
    const buf = try hexDecode(alloc, s);
    return .{ .buf = buf, .nbits = buf.len * 8 };
}

// The first `nbits` bits of a message (msb order), zero bits up to the next
// multiple of 6, as armored text.
fn armorEncode(alloc: std.mem.Allocator, buf: []const u8, nbits: usize) ![]u8 {
    const n = (nbits + 5) / 6;
    const out = try alloc.alloc(u8, n);
    for (out, 0..) |*c, j| {
        var v: u8 = 0;
        for (0..6) |k| {
            const a = 6 * j + k;
            const bit: u8 = if (a < nbits and a / 8 < buf.len) (buf[a / 8] >> @as(u3, @intCast(7 - (a % 8)))) & 1 else 0;
            v = (v << 1) | bit;
        }
        c.* = if (v < 40) 0x30 + v else 0x38 + v;
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
        // each 8-bit chunk from the field's first bit, in reverse order, as
        // its value reads in the pack's bit order (ruling 13 of 0.22)
        for (0..n) |j| setBits(tmp, p.msb, 8 * (n - 1 - j), 8, getBits(buf_in, p.msb, base + ln.bstart + 8 * j, 8));
        buf = tmp;
        start = 0;
    }
    const t = ln.transform;
    if (t.kind == .chars) return MV{ .str = try charsDecode(alloc, t.cset, buf, p.msb, start, ln.blen, ln.stop_code) };
    if (t.kind == .hex) {
        // Version 0.22: digit k is the 4-bit field at bit 4k, as `uint`
        // reads it in the pack's bit order
        const nd = ln.blen / 4;
        const out = try alloc.alloc(u8, nd);
        for (0..nd) |k| out[k] = "0123456789abcdef"[@intCast(getBits(buf, p.msb, start + 4 * k, 4))];
        return MV{ .str = out };
    }
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
    if (t.kind == .sixbit) {
        // each six bits, first to last in the pack's bit order, as one
        // character: 0..31 as `@`..`_`, 32..63 as space..`?` (Version 0.14)
        const n = ln.blen / 6;
        const chars = try alloc.alloc(u8, n);
        for (chars, 0..) |*c, j| {
            const v: u8 = @intCast(getBits(buf, p.msb, start + 6 * j, 6));
            c.* = if (v < 32) 0x40 + v else v;
        }
        var end: usize = n;
        if (ln.trim) {
            // the whole trailing run of `@` and space, in any mix
            while (end > 0 and (chars[end - 1] == '@' or chars[end - 1] == ' ')) end -= 1;
        } else {
            while (end > 0 and chars[end - 1] == '@') end -= 1;
        }
        return MV{ .str = chars[0..end] };
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
        .uiscale, .siscale => {
            const v: i128 = if (t.kind == .uiscale) bits else signExtend(bits, ln.blen);
            return MV{ .int = try exactBitsDecode(t, v) };
        },
        .smag => return MV{ .int = smagValue(bits, ln.blen) },
        .smscale => {
            const v: f64 = @floatFromInt(smagValue(bits, ln.blen));
            return MV{ .float = t.factor.mul(v) + t.offset };
        },
        .f32scale, .f64scale => {
            const v: f64 = if (t.kind == .f32scale) @as(f32, @bitCast(@as(u32, @intCast(bits)))) else @bitCast(bits);
            const r = t.factor.mul(v) + t.offset;
            if (!std.math.isFinite(r)) return E.@"transform-decode";
            return MV{ .float = r };
        },
        .code, .codenum => return codeBitsDecode(alloc, t, bits),
        .octal => {
            const nd = ln.blen / 3;
            const out = try alloc.alloc(u8, nd);
            for (0..nd) |j| out[nd - 1 - j] = '0' + @as(u8, @intCast((bits >> @as(u6, @intCast(3 * j))) & 7));
            return MV{ .str = out };
        },
        else => return E.@"transform-decode",
    }
}

// ---------------------------------------------------------------------------
// Version 0.15: value transforms on `bits`
// ---------------------------------------------------------------------------

fn charWidth(c: CharSet) usize {
    return switch (c) {
        .ascii7 => 7,
        .ascii8 => 8,
        .icao6, .ais6 => 6,
    };
}

// `ascii7` and `ascii8` (Version 0.22): NUL is code 0, codes 32 to 126 are
// themselves.
fn isAsciiSet(c: CharSet) bool {
    return c == .ascii7 or c == .ascii8;
}

// The code of a `stop` or `until:` parameter: plain decimal digits (leading
// zeros allowed) of a value below 2^w (rulings 16 and 23 of 0.22).
fn charCodeParam(raw: []const u8, c: CharSet) ?u64 {
    if (!allDigits(raw)) return null;
    const v = parseUnsigned(raw) orelse return null;
    if (v >= (@as(u64, 1) << @as(u6, @intCast(charWidth(c))))) return null;
    return v;
}

// `stop <code>` (Version 0.22): on a fixed-size `chars` field only, with a
// code of the set's width.
fn stopCheck(alloc: std.mem.Allocator, ln: *Line, lineno: usize, diag: *Diag) anyerror!void {
    const raw = ln.stop_raw orelse return;
    const bd = E.@"bad-directive";
    if (ln.transform.kind != .chars) return bad(diag, alloc, bd, "line {d}: stop is for a chars field", .{lineno});
    ln.stop_code = charCodeParam(raw, ln.transform.cset) orelse return bad(diag, alloc, bd, "line {d}: stop {s} is not a code of the set", .{ lineno, raw });
}

// The code of a character in a terminated field: as `codeOf`, and with a
// terminator other than 0 NUL is an ordinary character of `ascii7` and
// `ascii8` (rulings 20 and 21 of 0.22).
fn codeOfTerm(c: CharSet, ch: u8, term: u64) ?u8 {
    if (ch == 0 and term != 0 and isAsciiSet(c)) return 0;
    return codeOf(c, ch);
}

// The code a set writes as padding.
fn charPadCode(c: CharSet) u8 {
    return switch (c) {
        .icao6 => 32,
        .ais6, .ascii7, .ascii8 => 0,
    };
}

// The character of a code; null: the set does not hold the code.
fn charOf(c: CharSet, code: u8) ?u8 {
    return switch (c) {
        .icao6 => if (code >= 1 and code <= 26) 'A' + code - 1 else if (code == 32) ' ' else if (code >= 48 and code <= 57) code else null,
        .ais6 => if (code < 32) code + 64 else code,
        .ascii7, .ascii8 => if (code == 0 or (code >= 32 and code <= 126)) code else null,
    };
}

// The code of a character; null: the set cannot hold it (NUL in `ascii7`
// text included, ruling 17).
fn codeOf(c: CharSet, ch: u8) ?u8 {
    return switch (c) {
        .icao6 => if (ch >= 'A' and ch <= 'Z') ch - 'A' + 1 else if (ch == ' ' or (ch >= '0' and ch <= '9')) ch else null,
        .ais6 => if (ch >= 64 and ch <= 95) ch - 64 else if (ch >= 32 and ch <= 63) ch else null,
        .ascii7, .ascii8 => if (ch >= 32 and ch <= 126) ch else null,
    };
}

// `chars:<set>` decode: character i is the `w` bits at bit `i * w` of the
// field, read as `uint` reads them; trailing padding (and with `icao6` and
// `ais6` trailing spaces) removed.
fn charsDecode(alloc: std.mem.Allocator, c: CharSet, buf: []const u8, msb: BitOrd, start: usize, blen: usize, stop: ?u64) ![]const u8 {
    const w = charWidth(c);
    const n = blen / w;
    const out = try alloc.alloc(u8, n);
    // `stop` (Version 0.22): the characters before the first terminator,
    // exactly (ruling 18); with none, the field decodes as without `stop`
    if (stop) |term| {
        for (0..n) |i| {
            if (getBits(buf, msb, start + i * w, w) != term) continue;
            for (0..i) |k| {
                const code: u8 = @intCast(getBits(buf, msb, start + k * w, w));
                out[k] = charOf(c, code) orelse return E.@"transform-decode";
            }
            return out[0..i];
        }
    }
    for (0..n) |i| {
        const code: u8 = @intCast(getBits(buf, msb, start + i * w, w));
        out[i] = charOf(c, code) orelse return E.@"transform-decode";
    }
    const pad: u8 = charOf(c, charPadCode(c)).?;
    var end = n;
    while (end > 0 and (out[end - 1] == pad or (!isAsciiSet(c) and out[end - 1] == ' '))) end -= 1;
    // ascii7 and ascii8: a NUL before a character that is not NUL
    if (isAsciiSet(c)) {
        for (out[0..end]) |ch| if (ch == 0) return E.@"transform-decode";
    }
    return out[0..end];
}

fn charsEncode(c: CharSet, out: []u8, msb: BitOrd, start: usize, blen: usize, mv: MV, stop: ?u64) !void {
    const w = charWidth(c);
    const n = blen / w;
    if (stop) |term| {
        // the text, the terminator, then padding (Version 0.22)
        if (mv != .str or mv.str.len + 1 > n) return E.@"transform-encode";
        for (mv.str) |ch| {
            const code = codeOfTerm(c, ch, term) orelse return E.@"transform-encode";
            if (code == term) return E.@"transform-encode";
        }
        for (0..n) |i| {
            const code: u64 = if (i < mv.str.len) codeOfTerm(c, mv.str[i], term).? else if (i == mv.str.len) term else charPadCode(c);
            setBits(out, msb, start + i * w, w, code);
        }
        return;
    }
    if (mv != .str or mv.str.len > n) return E.@"transform-encode";
    for (mv.str) |ch| _ = codeOf(c, ch) orelse return E.@"transform-encode";
    for (0..n) |i| {
        const code = if (i < mv.str.len) codeOf(c, mv.str[i]).? else charPadCode(c);
        setBits(out, msb, start + i * w, w, code);
    }
}

// round-half-away-from-zero of n / d, d not 0
fn roundDiv(n: i128, d: i128) i128 {
    const neg = (n < 0) != (d < 0);
    const an: u128 = @abs(n);
    const ad: u128 = @abs(d);
    var q = an / ad;
    const r = an % ad;
    if (r >= ad - r) q += 1; // 2r >= d
    const qi: i128 = @intCast(q);
    return if (neg) -qi else qi;
}

// `round(v * factor) + offset`, within the signed 64-bit range.
fn exactBitsDecode(t: Transform, v: i128) !i64 {
    const r = roundDiv(v * t.num, t.den) + t.ioff;
    if (r < std.math.minInt(i64) or r > std.math.maxInt(i64)) return E.@"transform-decode";
    return @intCast(r);
}

// `round((x - offset) / factor)`
fn exactBitsEncode(t: Transform, mv: MV) !i128 {
    if (mv != .int) return E.@"transform-encode";
    const n: i128 = (@as(i128, mv.int) - t.ioff) * t.den;
    return roundDiv(n, t.num);
}

// `smag`: the top bit of the field the sign, the other bits the magnitude.
fn smagValue(bits: u64, len: usize) i64 {
    const sh: u6 = @intCast(len - 1);
    const mag: i64 = @intCast(bits & ((@as(u64, 1) << sh) - 1));
    return if ((bits >> sh) & 1 == 1) -mag else mag;
}

// An integer as `smag` writes it in `len` bits.
fn smagBits(v: i128, len: usize) !u64 {
    const sh: u7 = @intCast(len - 1);
    const mag: u128 = @abs(v);
    if (mag >= (@as(u128, 1) << sh)) return E.@"transform-encode";
    const sign: u64 = if (v < 0) 1 else 0;
    return (sign << @as(u6, @intCast(sh))) | @as(u64, @intCast(mag));
}

// The raw value of a field of at most 64 bits (Version 0.9): its `len` bits as
// an unsigned integer, as `uint` reads them, after `swap`.
fn bitsRaw(p: *const Pack, buf: []const u8, base: usize, ln: *const Line) u64 {
    if (!ln.swap) return getBits(buf, p.msb, base + ln.bstart, ln.blen);
    const n = ln.blen / 8;
    var tmp: [8]u8 = undefined;
    for (0..n) |j| setBits(tmp[0..n], p.msb, 8 * (n - 1 - j), 8, getBits(buf, p.msb, base + ln.bstart + 8 * j, 8));
    return getBits(tmp[0..n], p.msb, 0, ln.blen);
}

// Write a raw value (a sentinel) into a field's bits: the low `len` bits, then
// `swap`.
fn bitsWriteRaw(p: *const Pack, out: []u8, base: usize, ln: *const Line, v: u64) void {
    if (!ln.swap) return setBits(out, p.msb, base + ln.bstart, ln.blen, v);
    const n = ln.blen / 8;
    var tmp = [_]u8{0} ** 8;
    setBits(tmp[0..n], p.msb, 0, ln.blen, v);
    for (0..n) |j| setBits(out, p.msb, base + ln.bstart + 8 * j, 8, getBits(tmp[0..n], p.msb, 8 * (n - 1 - j), 8));
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
        .uiscale => {
            const q = try exactBitsEncode(t, mv);
            if (q < 0 or q >= (@as(i128, 1) << @as(u7, @intCast(ln.blen)))) return E.@"transform-encode";
            return @intCast(q);
        },
        .siscale => {
            const q = try exactBitsEncode(t, mv);
            const hi = @as(i128, 1) << @as(u7, @intCast(ln.blen - 1));
            if (q < -hi or q >= hi) return E.@"transform-encode";
            return @truncate(@as(u128, @bitCast(q)));
        },
        .smag => {
            if (mv != .int) return E.@"transform-encode";
            return smagBits(mv.int, ln.blen);
        },
        .smscale => {
            const x = try mvFloat(mv);
            const r = @round(t.factor.div(x - t.offset)); // as sscale computes it
            const hi = std.math.ldexp(@as(f64, 1.0), @as(i32, @intCast(ln.blen - 1)));
            if (!(@abs(r) < hi)) return E.@"transform-encode"; // NaN and infinities too
            // the sign of the rounded integer: -0.0 writes sign 0 (ruling 15)
            return smagBits(@as(i64, @intFromFloat(r)), ln.blen);
        },
        .f32scale => {
            const y = t.factor.div(try mvFloat(mv) - t.offset);
            return @as(u64, @as(u32, @bitCast(try narrowF32(y))));
        },
        .f64scale => {
            const y = t.factor.div(try mvFloat(mv) - t.offset);
            if (!std.math.isFinite(y)) return E.@"transform-encode";
            return @bitCast(y);
        },
        .code, .codenum => return codeBitsEncode(t, mv),
        .octal => {
            if (mv != .str or mv.str.len != ln.blen / 3) return E.@"transform-encode";
            var v: u64 = 0;
            for (mv.str) |ch| {
                if (ch < '0' or ch > '7') return E.@"transform-encode";
                v = (v << 3) | (ch - '0');
            }
            return v;
        },
        else => return E.@"transform-encode",
    }
}

// Write one field's `blen` bits at absolute bit `start` of `out`.
fn bitsPutField(out: []u8, msb: BitOrd, start: usize, ln: *const Line, mv: MV) !void {
    if (ln.transform.kind == .chars) return charsEncode(ln.transform.cset, out, msb, start, ln.blen, mv, ln.stop_code);
    if (ln.transform.kind == .hex) {
        // Version 0.22: `len / 4` hex digits, either case, each as a 4-bit field
        const nd = ln.blen / 4;
        if (mv != .str or mv.str.len != nd) return E.@"transform-encode";
        for (mv.str) |ch| _ = std.fmt.charToDigit(ch, 16) catch return E.@"transform-encode";
        for (mv.str, 0..) |ch, k| setBits(out, msb, start + 4 * k, 4, std.fmt.charToDigit(ch, 16) catch unreachable);
        return;
    }
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
    if (ln.transform.kind == .sixbit) {
        const n = ln.blen / 6;
        if (mv != .str or mv.str.len > n) return E.@"transform-encode"; // longer text
        for (mv.str) |c| if (c < 0x20 or c > 0x5f) return E.@"transform-encode";
        for (0..n) |j| {
            // padded with `@` (value 0)
            const v: u8 = if (j < mv.str.len) mv.str[j] & 0x3f else 0;
            setBits(out, msb, start + 6 * j, 6, v);
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
    for (0..n) |j| setBits(out, p.msb, base + ln.bstart + 8 * j, 8, getBits(tmp, p.msb, 8 * (n - 1 - j), 8));
}

// The message being written: it grows as items are added, zero-filled.
const BitsOut = struct {
    buf: std.ArrayList(u8),
    // one past the furthest bit the items of any group reach, or the start of
    // a group with none (0: no group)
    items_end: usize = 0,

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
const BitsDoc = struct { buf: []const u8, nbits: usize, base: usize = 0 };

// A JSON message or one element of an array. `geo`: read with the `geojson`
// value types.
const JItem = struct {
    v: JValue,
    geo: bool = false,
    // json: the numbers a field line has read, by the address of their text
    // (ruling 27 of 0.15)
    reads: ?*NumReads = null,
};

const NumReads = std.AutoHashMapUnmanaged(usize, void);

// The parsed wire message, or one item of a group.
const Doc = union(enum) {
    xml: *XmlNode,
    geojson: GeoDoc,
    json: JItem,
    bits: BitsDoc,
    protobuf: PbDoc,
    text: TextDoc,
    tlv: []TlvItem,
    // the top item, or one element of a group; tags are passed over
    cbor: *const CNode,
};

fn parseDoc(alloc: std.mem.Allocator, p: *const Pack, bytes: []const u8, diag: *Diag) anyerror!Doc {
    switch (p.wire) {
        .xml => { if (comptime !built(.xml)) unreachable;
            const root = parseXml(alloc, bytes) catch |err| return bad(diag, alloc, err, "the input is not well-formed xml", .{});
            return .{ .xml = root };
        },
        .geojson => { if (comptime !built(.geojson)) unreachable;
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
        .json => { if (comptime !built(.json)) unreachable;
            // numbers as written: `iscale` reads the digits (ruling 7 of 0.15)
            const obj = parseJsonObject(alloc, bytes, true) catch |err| return bad(diag, alloc, err, "the input is not one JSON object", .{});
            jsonCheckNoDuplicates(alloc, bytes) catch |err| return bad(diag, alloc, err, "a member name appears twice in one object", .{});
            const reads = try alloc.create(NumReads);
            reads.* = .{};
            return .{ .json = .{ .v = .{ .object = obj }, .reads = reads } };
        },
        .bits => { if (comptime !built(.bits)) unreachable;
            const in = bitsInput(alloc, p, bytes) catch |err| return bad(diag, alloc, err, "{s}", .{if (p.armor) "the input is not six-bit armored text" else "the input is not hex of even length"});
            return .{ .bits = .{ .buf = in.buf, .nbits = in.nbits } };
        },
        .protobuf => { if (comptime !built(.protobuf)) unreachable;
            const buf = hexDecode(alloc, bytes) catch |err| return bad(diag, alloc, err, "the input is not hex of even length", .{});
            const entries = parsePb(alloc, buf) catch |err| return bad(diag, alloc, err, "the input is not a protobuf message", .{});
            const cache = try alloc.create(PbCache);
            cache.* = PbCache.init(alloc);
            return .{ .protobuf = .{ .entries = entries, .cache = cache } };
        },
        .text => if (comptime !built(.text)) unreachable else return .{ .text = try textParse(alloc, p, bytes, diag) },
        .tlv => if (comptime !built(.tlv)) unreachable else return .{ .tlv = try tlvParse(alloc, p, bytes, diag) },
        .cbor => if (comptime !built(.cbor)) unreachable else return .{ .cbor = try cborParseDoc(alloc, p, bytes, diag) },
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
        .xml => |root| { if (comptime !built(.xml)) unreachable;
            // `present` on `#text`: the element exists (ruling 1m of 0.11)
            if (ln.wpresent and std.mem.endsWith(u8, ln.locator, "#text")) {
                const t = xmlTarget(root, ln.locator) orelse return false;
                return std.mem.eql(u8, t.last, "#text");
            }
            const got = xmlGet(root, ln.locator) orelse return false;
            if (ln.wpresent) return true;
            for (ln.walts) |a| if (std.mem.eql(u8, got, a.text)) return true;
            return false;
        },
        .geojson => |d| if (comptime !built(.geojson)) unreachable else return whenJsonHoldsAny(alloc, ln, geoLookup(d, ln.locator)),
        // (also an item of a geojson group)
        .json => |it| if (comptime !built(.json) and !built(.geojson)) unreachable else return whenJsonHoldsAny(alloc, ln, jitemLookup(it, ln)),
        .bits => |bd| { if (comptime !built(.bits)) unreachable;
            // a `when` that lies beyond the input does not hold
            if (bd.base + ln.bstart + ln.blen > bd.nbits) return false;
            return inRanges(ln.wranges, getBits(bd.buf, p.msb, bd.base + ln.bstart, ln.blen));
        },
        .protobuf => |pd| { if (comptime !built(.protobuf)) unreachable;
            const leaf = (resolvePb(alloc, pd, ln.ppath) catch return false) orelse return false;
            if (ln.wpresent) return true;
            return leaf.wt == 0 and inRanges(ln.wranges, leaf.uval);
        },
        .text => |td| { if (comptime !built(.text)) unreachable;
            // a `when` on a column its field does not reach does not hold
            const got = textRead(td, ln, ln.ti, false) orelse return false;
            if (ln.wpresent) return true;
            return std.mem.eql(u8, got, ln.wtext);
        },
        .tlv => |items| if (comptime !built(.tlv)) unreachable else return tlvWhenHolds(alloc, p, items, ln),
        .cbor => |node| if (comptime !built(.cbor)) unreachable else return cborWhenHolds(node, ln),
    }
}

// ---------------------------------------------------------------------------
// Version 0.15: `scale` and `iscale` on the text wires
// ---------------------------------------------------------------------------

const BigInt = std.math.big.int.Managed;

// The number text a JSON member holds; null when the member is not a number.
fn jsonNumberRaw(alloc: std.mem.Allocator, v: JValue) !?[]const u8 {
    return switch (v) {
        .number_string => |s| s,
        .integer => |i| try intToStr(alloc, i),
        .float => |f| try floatToStr(alloc, f),
        else => null,
    };
}

// json, geojson: the member must be a number (rulings 7 and 23).
fn jsonScaleDecode(alloc: std.mem.Allocator, t: Transform, v: JValue) !MV {
    const text = (try jsonNumberRaw(alloc, v)) orelse return E.@"transform-decode";
    return textScaleDecode(alloc, t, text);
}

// Decode a number's text through `scale` or `iscale`.
fn textScaleDecode(alloc: std.mem.Allocator, t: Transform, text: []const u8) !MV {
    if (t.kind == .tscale) {
        const v = try parseDecimal(text);
        const r = t.factor.mul(v) + t.offset;
        if (!std.math.isFinite(r)) return E.@"transform-decode"; // ruling 14
        return MV{ .float = r };
    }
    return MV{ .int = try iscaleDecode(alloc, t, text) };
}

fn bigPow10(alloc: std.mem.Allocator, e: usize) !BigInt {
    var r = try BigInt.initSet(alloc, 1);
    if (e == 0) return r;
    var ten = try BigInt.initSet(alloc, 10);
    defer ten.deinit();
    try r.pow(&ten, @intCast(e));
    return r;
}

// `iscale` decode: the text `-?digits(.digits)?([eE][+-]?digits)?` as an
// exact decimal r, then round(r * factor) + offset, within 64 bits. An
// exponent above 400 in absolute value is `transform-decode`.
fn iscaleDecode(alloc: std.mem.Allocator, t: Transform, text: []const u8) !i64 {
    const td = E.@"transform-decode";
    var i: usize = 0;
    const neg = text.len > 0 and text[0] == '-';
    if (neg) i += 1;
    const ip_from = i;
    while (i < text.len and isDigit(text[i])) i += 1;
    const ip = text[ip_from..i];
    if (ip.len == 0) return td;
    var fp: []const u8 = "";
    if (i < text.len and text[i] == '.') {
        i += 1;
        const from = i;
        while (i < text.len and isDigit(text[i])) i += 1;
        fp = text[from..i];
        if (fp.len == 0) return td;
    }
    var exp: i64 = 0;
    if (i < text.len and (text[i] == 'e' or text[i] == 'E')) {
        i += 1;
        var eneg = false;
        if (i < text.len and (text[i] == '+' or text[i] == '-')) {
            eneg = text[i] == '-';
            i += 1;
        }
        const from = i;
        while (i < text.len and isDigit(text[i])) i += 1;
        if (i == from) return td;
        var ed = text[from..i];
        while (ed.len > 1 and ed[0] == '0') ed = ed[1..];
        if (ed.len > 3) return td;
        exp = std.fmt.parseInt(i64, ed, 10) catch return td;
        if (exp > 400) return td;
        if (eneg) exp = -exp;
    }
    if (i != text.len) return td;

    // r = M * 10^(exp - len(fp))
    const digits = try std.mem.concat(alloc, u8, &.{ ip, fp });
    var m = try BigInt.init(alloc);
    defer m.deinit();
    try m.setString(10, digits);
    var rounded: i128 = 0;
    if (!m.eqlZero()) {
        const e10: i64 = exp - @as(i64, @intCast(fp.len));
        var num = try BigInt.initSet(alloc, t.num);
        defer num.deinit();
        var n = try BigInt.init(alloc);
        defer n.deinit();
        try n.mul(&m, &num);
        var d = try BigInt.initSet(alloc, t.den);
        defer d.deinit();
        var p10 = try bigPow10(alloc, @intCast(@abs(e10)));
        defer p10.deinit();
        var tmp = try BigInt.init(alloc);
        defer tmp.deinit();
        if (e10 >= 0) {
            try tmp.mul(&n, &p10);
            try n.copy(tmp.toConst());
        } else {
            try tmp.mul(&d, &p10);
            try d.copy(tmp.toConst());
        }
        if (neg) n.negate();
        // round half away from zero: q = trunc(n / d), then |r| * 2 >= d
        var q = try BigInt.init(alloc);
        defer q.deinit();
        var r = try BigInt.init(alloc);
        defer r.deinit();
        try q.divTrunc(&r, &n, &d);
        r.abs();
        var r2 = try BigInt.init(alloc);
        defer r2.deinit();
        try r2.add(&r, &r);
        if (r2.order(d) != .lt) {
            var one = try BigInt.initSet(alloc, 1);
            defer one.deinit();
            if (n.isPositive()) try tmp.add(&q, &one) else try tmp.sub(&q, &one);
            try q.copy(tmp.toConst());
        }
        rounded = q.to(i128) catch return td;
    }
    const res = std.math.add(i128, rounded, t.ioff) catch return td;
    if (res < std.math.minInt(i64) or res > std.math.maxInt(i64)) return td;
    return @intCast(res);
}

// `iscale` encode: (x - offset) / factor exactly, in plain decimal notation
// with at most 18 fraction digits.
fn iscaleEncode(alloc: std.mem.Allocator, t: Transform, mv: MV) ![]const u8 {
    const te = E.@"transform-encode";
    if (mv != .int) return te;
    // (x - offset) * den / num, as p / q with q > 0
    var p: i128 = (@as(i128, mv.int) - t.ioff) * t.den;
    var q: i128 = t.num;
    if (q < 0) {
        q = -q;
        p = -p;
    }
    const g: i128 = @intCast(std.math.gcd(@as(u128, @abs(p)), @as(u128, @intCast(q))));
    if (g > 1) {
        p = @divExact(p, g);
        q = @divExact(q, g);
    }
    // q = 2^a 5^b: the quotient has max(a, b) fraction digits
    var rest: i128 = q;
    var a: usize = 0;
    var b: usize = 0;
    while (@rem(rest, 2) == 0) : (a += 1) rest = @divExact(rest, 2);
    while (@rem(rest, 5) == 0) : (b += 1) rest = @divExact(rest, 5);
    if (rest != 1) return te; // does not terminate
    const k = @max(a, b);
    if (k > 18) return te; // ruling 21
    const ap: u128 = @abs(p);
    const uq: u128 = @intCast(q);
    const ipart = ap / uq;
    var buf = std.ArrayList(u8).init(alloc);
    if (p < 0) try buf.append('-');
    try buf.writer().print("{d}", .{ipart});
    if (k > 0) {
        // the fraction digits: (rem / q) * 10^k, an integer below 10^k
        const fr = (ap % uq) * std.math.pow(u128, 10, k) / uq;
        var digs: [18]u8 = undefined;
        _ = std.fmt.formatIntBuf(digs[0..k], fr, 10, .lower, .{ .width = k, .fill = '0' });
        var end = k;
        while (end > 0 and digs[end - 1] == '0') end -= 1;
        try buf.append('.');
        try buf.appendSlice(digs[0..end]);
    }
    return buf.toOwnedSlice();
}

// Encode a model value through `scale` or `iscale`: the text of the number.
fn textScaleEncode(alloc: std.mem.Allocator, t: Transform, mv: MV) ![]const u8 {
    if (t.kind == .tscale) {
        const y = t.factor.div(try mvFloat(mv) - t.offset);
        if (!std.math.isFinite(y)) return E.@"transform-encode"; // ruling 14
        return floatToStr(alloc, y);
    }
    return iscaleEncode(alloc, t, mv);
}

// Text through a text transform (xml, geojson).
fn textToMV(t: TKind, raw: []const u8) !MV {
    return switch (t) {
        .string => MV{ .str = raw },
        .float => MV{ .float = try parseDecimal(raw) },
        .int => MV{ .int = try parseDecimalInt(raw) },
        .iso8601_ms, .iso8601_short, .iso8601_s => MV{ .int = try isoToMs(raw) },
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
    // a part line reads the token, as `string` does (Version 0.64)
    const t = if (ln.isPart()) TKind.string else ln.transform.kind;
    switch (doc) {
        .xml => |root| { if (comptime !built(.xml)) unreachable;
            const raw = xmlGet(root, ln.locator) orelse return null;
            if (ln.abs_set and absentText(ln, raw)) return null; // not trimmed (ruling 14)
            if (t == .tscale or t == .iscale) return try textScaleDecode(alloc, ln.transform, raw);
            if (isCode(t)) return try codeTextDecode(alloc, ln.transform, raw);
            return try textToMV(t, raw);
        },
        .geojson => |d| { if (comptime !built(.geojson)) unreachable;
            // 0.1 behaviour (ruling 28 of 0.5): a scalar is read as its text,
            // whatever its JSON type
            const v = geoLookup(d, ln.locator) orelse return null;
            if (v == .null) return null;
            if (try jsonIsSentinel(alloc, ln, v)) return null;
            if (t == .tscale or t == .iscale) return try jsonScaleDecode(alloc, ln.transform, v);
            if (isCode(t)) return try codeJsonDecode(alloc, ln.transform, v);
            const raw = (try geoText(alloc, v)) orelse return E.@"transform-decode";
            return try textToMV(t, raw);
        },
        .json => |it| { if (comptime !built(.json) and !built(.geojson)) unreachable; // also an item of a geojson group
            const v = jitemLookup(it, ln) orelse return null;
            if (it.reads) |r| {
                if (v == .number_string) try r.put(alloc, @intFromPtr(v.number_string.ptr), {});
            }
            if (v == .null) return null; // a member whose value is null is absent
            if (try jsonIsSentinel(alloc, ln, v)) return null;
            if (t == .tscale or t == .iscale) return try jsonScaleDecode(alloc, ln.transform, v);
            if (isCode(t)) return try codeJsonDecode(alloc, ln.transform, v);
            if (it.geo) {
                // an item of a geojson group: the json locators and null
                // rule, the geojson value types (ruling 7 of 0.7)
                const raw = (try geoText(alloc, v)) orelse return E.@"transform-decode";
                return try textToMV(t, raw);
            }
            return try jsonToMV(t, v); // `.` on an object or array fails here
        },
        .bits => |bd| { if (comptime !built(.bits)) unreachable;
            // an `optional` field any of whose bits lies beyond the input is absent
            if (ln.optional and bd.base + ln.bstart + ln.blen > bd.nbits) return null;
            if (ln.abs_set and absentInt(ln, bitsRaw(p, bd.buf, bd.base, ln))) return null;
            return try bitsDecodeField(alloc, p, bd.buf, bd.base, ln);
        },
        .protobuf => |pd| { if (comptime !built(.protobuf)) unreachable;
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
        .text => |td| { if (comptime !built(.text)) unreachable;
            if (ln.tloc == .pair) {
                // absent when either field is absent
                const a = textRead(td, ln, ln.ti, false) orelse return null;
                const b = textRead(td, ln, ln.tj, false) orelse return null;
                return try textDecodePair(ln.transform, a, b);
            }
            const raw = textRead(td, ln, ln.ti, textNumeric(t)) orelse return null;
            if (isCode(t)) return try codeTextDecode(alloc, ln.transform, raw);
            return try textDecode(ln.transform, raw);
        },
        .tlv => |items| if (comptime !built(.tlv)) unreachable else return try tlvReadField(alloc, p, items, ln),
        .cbor => |node| if (comptime !built(.cbor)) unreachable else return try cborReadField(alloc, node, ln),
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
// json: the first number outside the double range that no field line read
// (ruling 27 of 0.15); null when there is none.
fn jsonUnreadOverflow(v: JValue, reads: *const NumReads) ?[]const u8 {
    switch (v) {
        .number_string => |s| {
            const f = std.fmt.parseFloat(f64, s) catch return null;
            if (std.math.isInf(f) and !reads.contains(@intFromPtr(s.ptr))) return s;
            return null;
        },
        .array => |arr| {
            for (arr.items) |it| if (jsonUnreadOverflow(it, reads)) |s| return s;
            return null;
        },
        .object => |obj| {
            var it = obj.iterator();
            while (it.next()) |en| if (jsonUnreadOverflow(en.value_ptr.*, reads)) |s| return s;
            return null;
        },
        else => return null,
    }
}

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

// Ruling 26 of 0.64: a `via` line of a key that an earlier line set. false:
// its transform succeeds and its table refuses the value.
fn laterTableOk(alloc: std.mem.Allocator, p: *const Pack, doc: Doc, ln: *const Line) !bool {
    // the line reads no number for ruling 27 of 0.15
    var d = doc;
    if (d == .json) d.json.reads = null;
    const got = readField(alloc, p, d, ln) catch |err| switch (err) {
        error.OutOfMemory, E.@"malformed-wire" => return err,
        else => return true,
    };
    const mv = got orelse return true;
    if (ln.isPart()) {
        const text = partOf(mv.str, ln.transform.psep, ln.transform.pn) orelse return true;
        const v = partValue(ln, text) catch return false;
        return v != null or ln.unlisted;
    }
    _ = tableDecode(ln.via.?, mv, ln.kty) catch return false;
    return true;
}

// Decode the lines of one scope into `e`: the fields, then each group as a
// list. A key takes its value from the earliest line whose locator is present
// on the wire and whose transform succeeds; a key that some line failed on and
// no line filled fails the decode. On `bits` the result is one past the
// furthest bit the scope's items reach (0 when it has none).
fn decodeScope(alloc: std.mem.Allocator, p: *const Pack, sc: *const Scope, doc: Doc, e: *Entity, diag: *Diag) anyerror!usize {
    var failed = std.StringArrayHashMap([]const u8).init(alloc);
    // inner decode (Version 0.34): keys whose table has no entry for the value
    var dead = std.ArrayListUnmanaged([]const u8){};
    var end: usize = 0;
    // Version 0.17: the gate blocks that hold; a held block's fields and
    // `const` lines that are not `optional` must be in the input
    var held: []bool = &.{};
    if (built(.bits) and sc.gates.len > 0 and doc == .bits) {
        const bd = doc.bits;
        held = try alloc.alloc(bool, sc.gates.len);
        evalGates(p, sc.gates, bd.buf, bd.nbits, bd.base, held);
        var hreq: usize = 0;
        for (sc.lines) |*ln| {
            const gt = ln.gate orelse continue;
            if (!held[gt.idx] or ln.optional) continue;
            if (ln.tag == .field or ln.tag == .constant) hreq = @max(hreq, ln.bstart + ln.blen);
        }
        if (hreq > 0) {
            if (bd.base + hreq > bd.nbits) {
                return bad(diag, alloc, E.@"malformed-wire", "a field of a block that holds lies beyond the input", .{});
            }
            end = bd.base + hreq;
        }
    }
    for (sc.lines) |*ln| {
        if (ln.tag == .group) {
            end = @max(end, try decodeGroup(alloc, p, ln.grp.?, doc, e, diag));
            continue;
        }
        const part_const = ln.tag == .constant and ln.isPart();
        if (ln.tag != .field and !part_const) continue;
        if (diag.count_only) continue;
        if (part_const) {
            // Version 0.64, ruling 4: never forgiven
            const token = (readField(alloc, p, doc, ln) catch |err| switch (err) {
                error.OutOfMemory, E.@"malformed-wire" => return err,
                else => return bad(diag, alloc, E.@"transform-decode", "const at {s}: the place is not text", .{ln.locator}),
            }) orelse continue;
            const text = partOf(token.str, ln.transform.psep, ln.transform.pn);
            if (text == null or !std.mem.eql(u8, text.?, ln.wtext)) {
                return bad(diag, alloc, E.@"transform-decode", "const at {s}: part {d} is not {s}", .{ ln.locator, ln.transform.pn, ln.wtext });
            }
            continue;
        }
        if (listHolds(dead.items, ln.key)) continue;
        // a line of a block that does not hold counts as a line whose
        // locator is absent: decode goes on to the key's next line
        if (ln.gate) |gt| if (!held[gt.idx]) continue;
        if (e.fields.contains(ln.key)) {
            // a submessage on the line's path that does not parse is
            // `malformed-wire` all the same (9c of 0.11, ruling 27 of 0.64)
            if (built(.protobuf) and doc == .protobuf and ln.ppath.len > 1) {
                _ = pbDescend(alloc, doc.protobuf, ln.ppath[0 .. ln.ppath.len - 1]) catch |err| switch (err) {
                    error.OutOfMemory => return err,
                    else => return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator }),
                };
            }
            // the earliest line's value stands; a later line whose transform
            // succeeds and whose table has no entry for a value of another
            // type still fails the decode (ruling 26 of 0.64)
            if (ln.via != null and !try laterTableOk(alloc, p, doc, ln)) {
                const err = bad(diag, alloc, E.@"transform-decode", "field {s} at {s}: the table {s} has no entry for the value", .{ ln.key, ln.locator, ln.via_name });
                const sf = diag.soft orelse return err;
                if (sf.msg == null) sf.msg = diag.msg;
            }
            continue;
        }
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
        if (ok and ln.isPart()) {
            // Version 0.64: a missing part fails the line; a part without a
            // table entry fails the decode, or is absent with `unlisted`
            const token = got orelse continue;
            if (partOf(token.str, ln.transform.psep, ln.transform.pn)) |text| {
                mv = (try partValue(ln, text)) orelse {
                    if (ln.unlisted) continue;
                    return bad(diag, alloc, E.@"transform-decode", "field {s} at {s}: the table {s} has no entry for the part", .{ ln.key, ln.locator, ln.via_name });
                };
            } else ok = false;
        } else if (ok) {
            mv = got orelse continue;
            // `via`: through the table after the transform. A line whose
            // transform succeeds and whose table has no entry for a value of
            // another type fails the decode: later lines of the key are not
            // tried (ruling 4 of 0.6, ruling 10 of 0.7).
            if (ln.via) |t| {
                mv = tableDecode(t, mv, ln.kty) catch {
                    const err = bad(diag, alloc, E.@"transform-decode", "field {s} at {s}: the table {s} has no entry for the value", .{ ln.key, ln.locator, ln.via_name });
                    const sf = diag.soft orelse return err;
                    // an error in a discarded list too (ruling 21 of 0.34)
                    if (sf.msg == null) sf.msg = diag.msg;
                    _ = failed.orderedRemove(ln.key);
                    try dead.append(alloc, ln.key);
                    if (e == diag.root) try sf.keys.append(alloc, ln.key);
                    continue;
                };
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
            if (diag.soft) |sf| if (e == diag.root) {
                try sf.keys.append(alloc, en.key_ptr.*);
                continue;
            };
            if (msg.items.len > 0) try msg.appendSlice(", ");
            try msg.writer().print("{s} at {s}", .{ en.key_ptr.*, en.value_ptr.* });
        }
        // ruling 21 of 0.34: not an error in a discarded list
        if (msg.items.len > 0 and diag.no_hold == 0) {
            const err = bad(diag, alloc, E.@"transform-decode", "failed fields: {s}", .{msg.items});
            const sf = diag.soft orelse return err;
            if (sf.msg == null) sf.msg = diag.msg;
        }
    }
    return end;
}

// Version 0.17: which of a scope's gate blocks hold on `buf`, read from bit
// `base`, in line order. A gate any of whose bits lies beyond the input's
// `nbits` bits (a whole number of bytes in hex, of six-bit characters under
// `armor sixbit`) does not hold, nor does its `!` form; a nested gate is
// evaluated only when the block enclosing it holds.
fn evalGates(p: *const Pack, gates: []const *const Gate, buf: []const u8, nbits: usize, base: usize, held: []bool) void {
    for (gates) |gt| {
        held[gt.idx] = false;
        if (gt.parent) |par| if (!held[par.idx]) continue;
        if (base + gt.bstart + gt.blen > @min(nbits, buf.len * 8)) continue;
        held[gt.idx] = gt.holds(getBits(buf, p.msb, base + gt.bstart, gt.blen));
    }
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
        .xml => |node| { if (comptime !built(.xml)) unreachable;
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
        .geojson, .json => { if (comptime !built(.geojson) and !built(.json)) unreachable;
            const found: ?JValue = switch (doc) {
                .geojson => |d| if (comptime !built(.geojson)) unreachable else geoLookup(d, g.locator),
                .json => |it| if (comptime !built(.json) and !built(.geojson)) unreachable else if (it.v == .object) jsonLookup(it.v.object, g.segs) else null,
                else => unreachable,
            };
            const v = found orelse return 0;
            if (v == .null) return 0; // `null` is absent
            if (v != .array) return bad(diag, alloc, mw, "group {s}: the member at {s} is not an array", .{ g.list, g.locator });
            try takeItems(diag, alloc, v.array.items.len, g.list);
            const items = try alloc.alloc(Entity, v.array.items.len);
            for (v.array.items, 0..) |el, i| {
                items[i] = Entity.init(alloc);
                const reads: ?*NumReads = switch (doc) {
                    .json => |it| if (comptime !built(.json) and !built(.geojson)) unreachable else it.reads,
                    else => null,
                };
                _ = try decodeScope(alloc, p, body, .{ .json = .{ .v = el, .geo = p.wire == .geojson, .reads = reads } }, &items[i], diag);
            }
            try e.putList(g.list, items);
            return 0;
        },
        .protobuf => |pd| { if (comptime !built(.protobuf)) unreachable;
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
        .bits => |bd| { if (comptime !built(.bits)) unreachable;
            const total = bd.nbits;
            // the count locator is inside the bits the scope requires
            const count: u64 = if (g.count_fixed) |n| n else getBits(bd.buf, p.msb, bd.base + g.cstart, g.clen);
            var pos = bd.base + g.gstart;
            if (diag.soft) |sf| sf.far = @max(sf.far, pos);
            // a list the outer message of an inner decode holds is discarded,
            // its nested lists with it (Version 0.34)
            const drop = diag.discard.len > 0 and e == diag.root and listHolds(diag.discard, g.list);
            if (drop) diag.no_hold += 1;
            defer if (drop) {
                diag.no_hold -= 1;
            };
            // the count against the limit, before any item is read (7d)
            try holdList(diag, alloc, count, g.list, g.count_fixed == null);
            if (count > 0 and (pos > total or count > (total - pos) / g.item_bits)) {
                return bad(diag, alloc, mw, "group {s}: the input ends before its {d} items", .{ g.list, count });
            }
            const need = @max(g.item_bits, body.nbits_req);
            const items = try alloc.alloc(Entity, @intCast(count));
            for (items) |*it| {
                if (pos + need > total) return bad(diag, alloc, mw, "group {s}: the input ends before its {d} items", .{ g.list, count });
                it.* = Entity.init(alloc);
                const iend = try decodeScope(alloc, p, body, .{ .bits = .{ .buf = bd.buf, .nbits = bd.nbits, .base = pos } }, it, diag);
                // a nested group counted by a locator may run past `item
                // <bits>`; the next item then starts where it ends
                pos = @max(pos + need, iend);
            }
            try e.putList(g.list, items);
            // a group with no items extends the message to its start (ruling
            // 18 of 0.52)
            if (pos > total) return bad(diag, alloc, mw, "group {s}: the input ends before the group's start", .{g.list});
            return pos;
        },
        .text => |td| { if (comptime !built(.text)) unreachable;
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
        .tlv => if (comptime !built(.tlv)) unreachable else return 0, // no group on `tlv`
        .cbor => |node| { if (comptime !built(.cbor)) unreachable;
            try cborDecodeGroup(alloc, p, g, node, e, diag);
            return 0;
        },
    }
}

// Version 0.34, ruling 14: one past the furthest bit of the scope's lines (an
// `optional` one too), of the blocks that hold with their gates, and of
// `far`, the furthest start of a group. The items are the caller's.
fn fixedEnd(alloc: std.mem.Allocator, p: *const Pack, sc: *const Scope, bd: BitsDoc, far: usize) !usize {
    var end = @max(sc.nbits, far);
    if (sc.gates.len == 0) return end;
    const held = try alloc.alloc(bool, sc.gates.len);
    evalGates(p, sc.gates, bd.buf, bd.nbits, 0, held);
    for (sc.gates) |gt| {
        if (held[gt.idx]) end = @max(end, gt.bstart + gt.blen);
    }
    for (sc.lines) |*ln| {
        const gt = ln.gate orelse continue;
        if (held[gt.idx] and ln.tag != .group) end = @max(end, ln.bstart + ln.blen);
    }
    return end;
}

// Version 0.34, Decode step 3: bytes of the inner input after the message.
fn leftover(diag: *Diag, alloc: std.mem.Allocator, stop: usize, have: usize) anyerror {
    return bad(diag, alloc, E.@"malformed-wire", "the message ends at byte {d}, the inner input holds {d}", .{ stop, have });
}

// Version 0.34: an inner decode that was read to its end, with values that do
// not decode: `msg` what failed for good, `keys` what an outer line may forgive.
fn innerFailed(diag: *Diag, alloc: std.mem.Allocator, e: Entity, msg: ?[]const u8, keys: []const []const u8) anyerror {
    diag.partial = e;
    diag.failed_keys = keys;
    diag.unforgiven = msg != null;
    const text = msg orelse std.mem.join(alloc, ", ", keys) catch "";
    return bad(diag, alloc, E.@"transform-decode", "failed fields: {s}", .{text});
}

fn decodePack(alloc: std.mem.Allocator, p: *const Pack, bytes: []const u8, diag: *Diag) anyerror!Entity {
    if (built(.bits) and p.seq != null) return seqDecode(alloc, p, bytes, diag);
    const mode = diag.inner;
    diag.inner = .none;
    var soft = Soft{};
    if (mode != .none) diag.soft = &soft;
    defer diag.soft = null;
    const doc = try parseDoc(alloc, p, bytes, diag);
    const held0 = diag.held;

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

    if (doc == .bits and p.armor) {
        // armored: the input reaches every bit the lines require, whatever
        // `word_bytes` is (Version 0.14)
        if (doc.bits.nbits < sc.nbits_req) {
            return bad(diag, alloc, E.@"malformed-wire", "the message is {d} bits, the input holds {d}", .{ sc.nbits_req, doc.bits.nbits });
        }
    } else if (doc == .bits) {
        // every bit a line that is not `optional` maps must be in the input
        const need = p.wordBytes(sc.nbits_req);
        if (doc.bits.buf.len < need) {
            return bad(diag, alloc, E.@"malformed-wire", "the message is {d} bytes, the input holds {d}", .{ need, doc.bits.buf.len });
        }
    }

    // tlv: every set a line of the selected scope walks into is read whole
    if (built(.tlv) and doc == .tlv) try tlvWalkScope(alloc, p, doc.tlv, lines, diag);
    // cbor: every line of the selected scope finds the containers it needs
    // (step 8 of "Reading a message", Version 0.28)
    if (built(.cbor) and doc == .cbor) try cborWalkScope(alloc, doc.cbor, lines, diag);

    var e = Entity.init(alloc);
    if (kind_idx) |k| {
        e.kind_fmt = p.format;
        e.kind_name = p.kinds.items[k].name;
    }

    diag.root = &e;
    const end = decodeScope(alloc, p, sc, doc, &e, diag) catch |err| {
        // Going over the limit wins over a field that fails (ruling 7f of
        // 0.11): the scope is read again for its items alone.
        if (err == error.OutOfMemory or err == E.@"malformed-wire") return err;
        const msg = diag.msg;
        diag.count_only = true;
        diag.held = held0;
        var scratch_e = Entity.init(alloc);
        _ = decodeScope(alloc, p, sc, doc, &scratch_e, diag) catch |err2| {
            if (err2 == error.OutOfMemory) return err2;
            if (diag.limit_hit) return err2;
        };
        diag.msg = msg;
        return err;
    };
    if (doc == .bits and p.armor) {
        if (doc.bits.nbits < @max(sc.nbits_req, end)) {
            return bad(diag, alloc, E.@"malformed-wire", "the message with its items is {d} bits, the input holds {d}", .{ @max(sc.nbits_req, end), doc.bits.nbits });
        }
    } else if (doc == .bits) {
        // the message length is extended by the items, to whole words
        const need = p.wordBytes(@max(sc.nbits_req, end));
        if (doc.bits.buf.len < need) {
            return bad(diag, alloc, E.@"malformed-wire", "the message with its items is {d} bytes, the input holds {d}", .{ need, doc.bits.buf.len });
        }
    }
    if (built(.bits) and doc == .bits and mode != .none) {
        if (mode == .strict) {
            const stop = p.wordBytes(@max(end, try fixedEnd(alloc, p, sc, doc.bits, soft.far)));
            if (doc.bits.buf.len > stop) return leftover(diag, alloc, stop, doc.bits.buf.len);
        }
        if (soft.msg != null or soft.keys.items.len > 0) return innerFailed(diag, alloc, e, soft.msg, soft.keys.items);
    }

    // residue: what no common or selected-kind `field` or `when` maps
    switch (doc) {
        .xml => |root| { if (comptime !built(.xml)) unreachable;
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
        .geojson => |d| { if (comptime !built(.geojson)) unreachable;
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
        .json => |it| { if (comptime !built(.json)) unreachable;
            // a number outside the double range that no field read, anywhere
            // in the document (ruling 27 of 0.15)
            if (jsonUnreadOverflow(it.v, it.reads.?)) |num| {
                return bad(diag, alloc, E.@"malformed-wire", "the number {s} is outside the double range and no field reads it", .{clip(num)});
            }
            jsonResidue(alloc, p, lines, it.v.object, "", &e) catch |err| switch (err) {
                E.@"malformed-wire" => return bad(diag, alloc, err, "a number no line maps lies beyond the range of a double", .{}),
                else => return err,
            };
        },
        .text => |td| if (comptime !built(.text)) unreachable else try textResidue(alloc, p, lines, td, &e),
        .tlv => |items| if (comptime !built(.tlv)) unreachable else try tlvResidue(alloc, p, lines, items, &.{}, "", &e),
        .cbor => |node| if (comptime !built(.cbor)) unreachable else try cborResidue(alloc, p, lines, node, &e),
        .bits, .protobuf => if (comptime !built(.bits) and !built(.protobuf)) unreachable else {},
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
    // Version 0.34: then Entity.inner_kind when it names this format
    if (e.inner_kind_fmt) |kf| {
        if (std.mem.eql(u8, kf, p.format)) {
            return p.kindIndex(e.inner_kind_name) orelse
                bad(diag, alloc, E.@"no-kind", "the entity records inner kind {s}, which the pack does not have", .{e.inner_kind_name});
        }
    }
    for (p.kinds.items, 0..) |k, i| {
        var all = true;
        for (k.requires.items) |t| {
            // a key that is present, or a list with at least one item; with
            // `=`, a listed value (Version 0.20)
            if (!termHolds(alloc, t, e)) {
                all = false;
                break;
            }
        }
        if (all) return i;
    }
    return bad(diag, alloc, E.@"no-kind", "the entity has the `requires` keys of no kind", .{});
}

// Version 0.94: does the entity hold a key of message kind `ki` (its index
// among the pack's message kinds)? The keys are those the common lines and
// the kind's lines map (`field`, `also`, `group` as its list, `when … as`),
// written or not, outside a group's items; the kind's own `requires` keys;
// and the `model_keys` of the pack of an `inner` line among those lines that
// passes the checks of 0.34. A key is held when the entity has it, a list
// when it has an item. A kept kind is not checked (ruling 4).
fn kindHeld(p: *const Pack, ki: usize, e: *const Entity, packs: ?*const std.StringHashMap(*Pack)) bool {
    for ([_]?[]const u8{ e.kind_fmt, e.inner_kind_fmt }) |kf_opt| {
        const kf = kf_opt orelse continue;
        if (std.mem.eql(u8, kf, p.format)) return true;
        for (p.inners.items) |im| {
            if ((im.kind == 0 or im.kind == ki + 1) and std.mem.eql(u8, im.fmt, kf)) return true;
        }
    }
    const starts = p.kind_starts.items;
    const common_end = if (starts.len > 0) starts[0] else p.key_uses.items.len;
    const kind_lo = if (ki < starts.len) starts[ki] else p.key_uses.items.len;
    const kind_hi = if (ki + 1 < starts.len) starts[ki + 1] else p.key_uses.items.len;
    for ([_][2]usize{ .{ 0, common_end }, .{ kind_lo, kind_hi } }) |r| {
        for (p.key_uses.items[r[0]..r[1]]) |ku| {
            const counts = switch (ku.use) {
                .field, .group, .as_ => ku.grp == null,
                .requires => !ku.item,
                .default, .with => false,
            };
            if (counts and e.has(ku.key)) return true;
        }
    }
    const m = packs orelse return false;
    for (p.inners.items) |im| {
        if (im.kind != 0 and im.kind != ki + 1) continue;
        const ip = m.get(im.fmt) orelse continue;
        if (innerCheck(p, ip) != null) continue;
        for (ip.key_uses.items) |ku| {
            if (!mapsKey(ku) or ku.grp != null) continue;
            if (e.has(ku.key)) return true;
        }
    }
    return false;
}

fn heldCheck(alloc: std.mem.Allocator, p: *const Pack, ki: usize, e: *const Entity, diag: *Diag) anyerror!void {
    if (kindHeld(p, ki, e, diag.packs)) return;
    return bad(diag, alloc, E.@"no-kind", "the entity holds no key of kind {s}", .{p.kindName(ki)});
}

// The value a field line writes: the entity's (or item's) value, else the
// `default` in scope; the CoT type token mapped back to the format's native
// code; then through the line's `via` table. null: nothing to write.
fn fieldValue(p: *const Pack, sc: *const Scope, e: *const Entity, ln: *const Line) !?MV {
    // a line suppressed by `with` writes nothing, its default included
    if (ln.suppressed(e)) return null;
    var mv = e.get(ln.key) orelse sc.lineDefault(ln) orelse return null;
    if (mv == .str and std.mem.eql(u8, ln.key, "type")) {
        if (p.tm_cot2nat.get(mv.str)) |nat| mv = MV{ .str = nat };
    }
    if (ln.via) |t| mv = try tableEncode(t, mv, yields(ln.transform.kind));
    return mv;
}

fn xmlText(alloc: std.mem.Allocator, tr: Transform, mv: MV) ![]const u8 {
    switch (tr.kind) {
        .codestr, .codenum => return codeTextEncode(alloc, tr, mv),
        .tscale, .iscale => return textScaleEncode(alloc, tr, mv),
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
        .iso8601_ms, .iso8601_short => {
            if (mv != .int) return E.@"transform-encode";
            return msToIso(alloc, mv.int, tr.kind == .iso8601_short);
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
// `reserve`: a line that names the place and writes nothing there; the
// place is taken at its position (ruling 23 of 0.9, rulings 1 and 13 of
// 0.18).
const WMode = enum { field, fixed, sentinel, reserve };

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
                if (mode == .reserve) return;
                if (a.unset) {
                    a.value = value;
                    a.unset = false;
                    a.weak = mode == .sentinel;
                } else if (mode == .fixed or (mode == .field and a.weak)) {
                    a.value = value;
                    a.weak = false;
                }
                return;
            }
        }
        try node.attrs.append(.{ .name = rest[1..], .value = value, .weak = mode == .sentinel, .unset = mode == .reserve });
    } else if (mode == .reserve) {
        return;
    } else if (std.mem.eql(u8, rest, "#text")) {
        if (node.text_set and !(mode == .fixed or (mode == .field and node.text_weak))) return;
        node.text = value;
        node.text_set = true;
        node.text_weak = mode == .sentinel;
    }
}

// Encode: is anything inside the element written, or is it forced? An
// element only a line that wrote nothing placed is not output.
fn xmlHas(node: *const XmlNode) bool {
    if (node.forced or node.text_set) return true;
    for (node.attrs.items) |a| if (!a.unset) return true;
    for (node.children.items) |c| if (xmlHas(c)) return true;
    return false;
}

fn xmlWrite(buf: *std.ArrayList(u8), node: *XmlNode) anyerror!void {
    try buf.append('<');
    try buf.appendSlice(node.name);
    var nkids: usize = 0;
    for (node.children.items) |c| {
        if (xmlHas(c)) nkids += 1;
    }
    for (node.attrs.items) |a| {
        if (a.unset) continue;
        try buf.append(' ');
        try buf.appendSlice(a.name);
        try buf.appendSlice("=\"");
        try xmlEscape(buf, a.value, true);
        try buf.append('"');
    }
    if (nkids == 0 and node.text.len == 0) {
        try buf.appendSlice("/>");
        return;
    }
    try buf.append('>');
    if (node.text.len > 0) try xmlEscape(buf, node.text, false);
    for (node.children.items) |c| {
        if (xmlHas(c)) try xmlWrite(buf, c);
    }
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
const Member = struct { name: []const u8, raw: []const u8, weak: bool = false, unset: bool = false };

// Add a member. A name already written keeps its value (the earliest line
// wins) unless the new value is a `when` value.
fn memberAdd(list: *std.ArrayList(Member), name: []const u8, raw: []const u8, mode: WMode) !void {
    for (list.items) |*m| {
        if (std.mem.eql(u8, m.name, name)) {
            if (mode == .reserve) return;
            if (m.unset) {
                m.raw = raw;
                m.unset = false;
                m.weak = mode == .sentinel;
            } else if (mode == .fixed or (mode == .field and m.weak)) {
                m.raw = raw;
                m.weak = false;
            }
            return;
        }
    }
    try list.append(.{ .name = name, .raw = raw, .weak = mode == .sentinel, .unset = mode == .reserve });
}

fn membersWrite(buf: *std.ArrayList(u8), list: []const Member, first_in: bool) !void {
    var first = first_in;
    for (list) |m| {
        if (m.unset) continue;
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
    reserved: bool = false, // a member a line placed without a value
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
        // a place a line took without writing (ruling 23 of 0.9)
        if (c.raw == null and c.reserved) {
            c.raw = r;
            c.reserved = false;
            c.weak = mode == .sentinel;
            return;
        }
        // `when` and `const` values are written over any field, a field's
        // value over a sentinel
        if (c.raw != null and (mode == .fixed or (mode == .field and c.weak))) {
            c.raw = r;
            c.weak = false;
        }
        return;
    }
    if (raw == null and mode != .reserve) return;
    const c = try jnodeNew(alloc, last);
    c.raw = raw;
    c.weak = mode == .sentinel;
    c.reserved = raw == null;
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
        if (sc.partGroup(ln)) |g| {
            // the token, at the group's first line (Version 0.64)
            if (g.first != ln) continue;
            const token = try partToken(alloc, p, sc, g, e, diag);
            if (token) |t| if (!xmlWritable(t)) return bad(diag, alloc, E.@"transform-encode", "the token at {s} holds a character xml cannot hold", .{ln.locator});
            try xmlSet(alloc, node, ln.locator, token orelse "", if (token == null) .reserve else .field);
            continue;
        }
        switch (ln.tag) {
            .when, .constant => {
                if (!ln.wpresent) try xmlSet(alloc, node, ln.locator, ln.wtext, .fixed);
            },
            .element => {
                // Version 0.18: the element and each one on the way to it,
                // written even when empty, at this line's position
                var cur = node;
                var it = std.mem.splitScalar(u8, ln.locator, '/');
                while (it.next()) |nm| {
                    cur = cur.child(nm) orelse blk: {
                        const c = try xmlNewNode(alloc, nm);
                        try cur.children.append(c);
                        break :blk c;
                    };
                }
                cur.forced = true;
            },
            .field => {
                const mv = (fieldValue(p, sc, e, ln) catch |err|
                    return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator })) orelse {
                    // an absent key writes its first sentinel (Version 0.9);
                    // otherwise the line still takes its place
                    if (ln.sentinelOn(e)) {
                        if (!xmlWritable(ln.abs_texts[0])) return bad(diag, alloc, E.@"transform-encode", "field {s} at {s}: the sentinel holds a character xml cannot hold", .{ ln.key, ln.locator });
                        try xmlSet(alloc, node, ln.locator, ln.abs_texts[0], .sentinel);
                    } else try xmlSet(alloc, node, ln.locator, "", .reserve);
                    continue;
                };
                const vs = xmlText(alloc, ln.transform, mv) catch |err|
                    return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator });
                // ruling 1d of 0.11
                if (!xmlWritable(vs)) return bad(diag, alloc, E.@"transform-encode", "field {s} at {s}: the value holds a character xml cannot hold", .{ ln.key, ln.locator });
                try xmlSet(alloc, node, ln.locator, vs, .field);
            },
            .group => {
                // one element per item at the group's position; an absent or
                // empty list writes nothing
                const g = ln.grp.?;
                const items: []const Entity = e.lists.get(g.list) orelse &.{};
                // the containers take their place here; with no item they
                // are written only when an `element` line forces them
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
                    c.forced = true; // an item with nothing written is an empty element
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
        if (sc.partGroup(ln)) |g| {
            // the token, at the group's first line (Version 0.64)
            if (g.first != ln) continue;
            if (try partToken(alloc, p, sc, g, e, diag)) |t| raw = try jsonStr(alloc, t) else mode = .reserve;
        } else switch (ln.tag) {
            .when, .constant => {
                // `present` writes nothing; the objects on its path keep this position
                if (!ln.wpresent) raw = try whenJsonRaw(alloc, ln.*);
                mode = .fixed;
            },
            .field => {
                const got = fieldValue(p, sc, e, ln) catch |err|
                    return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator });
                if (got) |mv| {
                    raw = jsonRaw(alloc, ln.transform, mv) catch |err|
                        return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator });
                } else if (ln.sentinelOn(e)) {
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
            .element => continue,
        }
        // a field line that writes nothing still takes its member's place
        // (ruling 23 of 0.9, ruling 1 of 0.18)
        if (raw == null and ln.tag == .field) mode = .reserve;
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
                        } else if (dl.sentinelOn(it)) {
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
                        } else if (dl.sentinelOn(it)) {
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
                try writeVarint(&fb, if (ln.isWhen()) try whenPbValue(alloc, p, sc, e, ln) else ln.wint);
            }
        } else if (fieldValue(p, sc, e, ln) catch |err|
            return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator })) |mv|
        {
            encodeProtoField(&fb, ln.transform.kind, number, mv) catch |err|
                return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator });
        } else if (ln.sentinelOn(e)) {
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
// Version 0.17: is a line written, given the blocks that are held? A line
// outside any block always is; `held` empty: only those.
fn lineOn(ln: *const Line, held: []const bool) bool {
    const gt = ln.gate orelse return true;
    return held.len > 0 and held[gt.idx];
}

// The sentinels of absent keys, then the fields over them, of the lines of
// one scope that `lineOn` keeps. The caller then writes the gate values, the
// items, and `bitsWriteFixed`.
fn bitsWriteLines(alloc: std.mem.Allocator, p: *const Pack, sc: *const Scope, buf: []u8, base: usize, e: *const Entity, held: []const bool, diag: *Diag) anyerror!void {
    const lines = sc.lines;
    // Version 0.9: first the sentinels of the absent keys, so that a line
    // whose key is present, or has a default, wins over a sentinel whatever
    // their order (ruling 16); of two sentinels on one bit, the earlier line's
    var si: usize = lines.len;
    while (si > 0) {
        si -= 1;
        const ln = &lines[si];
        if (ln.tag != .field or !ln.sentinelOn(e) or !lineOn(ln, held)) continue;
        if (e.get(ln.key) != null or sc.lineDefault(ln) != null) continue;
        bitsWriteRaw(p, buf, base, ln, ln.abs_ints[0]);
    }
    // The earlier line takes precedence where two fields cover the same
    // bits: write in reverse line order, each over the last.
    var i: usize = lines.len;
    while (i > 0) {
        i -= 1;
        const ln = &lines[i];
        if (ln.tag != .field or !lineOn(ln, held)) continue;
        const mv = (fieldValue(p, sc, e, ln) catch |err|
            return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator })) orelse continue;
        bitsWriteField(alloc, p, buf, base, ln, mv) catch |err|
            return bad(diag, alloc, err, "field {s} at {s}: the value does not encode", .{ ln.key, ln.locator });
    }
}

// `when` and `const` values over any field, then each count locator with
// the number of items.
fn bitsWriteFixed(alloc: std.mem.Allocator, p: *const Pack, sc: *const Scope, buf: []u8, base: usize, e: *const Entity, held: []const bool, diag: *Diag) anyerror!void {
    for (sc.lines) |*ln| {
        if (ln.isFixed() and lineOn(ln, held)) setBits(buf, p.msb, base + ln.bstart, ln.blen, try whenBitsValue(alloc, p, sc, e, ln, held));
    }
    for (sc.lines) |*ln| {
        if (ln.tag != .group) continue;
        const g = ln.grp.?;
        if (g.count_fixed != null) continue;
        const n: u64 = if (e.lists.get(g.list)) |items| items.len else 0;
        if (g.clen < 64 and (n >> @as(u6, @intCast(g.clen))) != 0) {
            return bad(diag, alloc, E.@"transform-encode", "group {s}: {d} items do not fit the {d} bits of the count", .{ g.list, n, g.clen });
        }
        setBits(buf, p.msb, base + g.cstart, g.clen, n);
    }
}

// The value a `when` or `const` line writes on a fixed layout. Ruling 3 of
// 0.20: for a `when` list, the value of the first field line whose key the
// entity holds and that covers exactly the `when`'s bits, when it matches
// the list; otherwise the first value.
fn whenBitsValue(alloc: std.mem.Allocator, p: *const Pack, sc: *const Scope, e: *const Entity, ln: *const Line, held: []const bool) !u64 {
    if (!ln.isWhen() or !isWhenList(ln.wranges)) return ln.wint;
    for (sc.lines) |*f| {
        if (f.tag != .field or !lineOn(f, held)) continue;
        if (f.bstart != ln.bstart or f.blen != ln.blen or f.heldValue(e) == null) continue;
        const mv = (fieldValue(p, sc, e, f) catch return ln.wint) orelse return ln.wint;
        const tmp = try alloc.alloc(u8, (f.bstart + f.blen + 7) / 8);
        @memset(tmp, 0);
        bitsWriteField(alloc, p, tmp, 0, f, mv) catch return ln.wint;
        const v = getBits(tmp, p.msb, ln.bstart, ln.blen);
        return if (inRanges(ln.wranges, v)) v else ln.wint;
    }
    return ln.wint;
}

// The varint a protobuf `when` writes. Ruling 3 of 0.20: for a list, the
// value of the first field line on the same path whose key the entity
// holds, when it is a varint the list matches; otherwise the first value.
fn whenPbValue(alloc: std.mem.Allocator, p: *const Pack, sc: *const Scope, e: *const Entity, ln: *const Line) !u64 {
    if (!isWhenList(ln.wranges)) return ln.wint;
    for (sc.lines) |*f| {
        if (f.tag != .field or !std.mem.eql(usize, f.ppath, ln.ppath) or f.heldValue(e) == null) continue;
        const mv = (fieldValue(p, sc, e, f) catch return ln.wint) orelse return ln.wint;
        var fb = std.ArrayList(u8).init(alloc);
        encodeProtoField(&fb, f.transform.kind, 1, mv) catch return ln.wint;
        const ents = parsePb(alloc, fb.items) catch return ln.wint;
        if (ents.len != 1 or ents[0].wt != 0) return ln.wint;
        return if (inRanges(ln.wranges, ents[0].uval)) ents[0].uval else ln.wint;
    }
    return ln.wint;
}

// One gated scope or item, for the check of step 6 once the whole message
// is written.
const GateCheck = struct { sc: *const Scope, base: usize, held: []const bool };

fn markRange(m: []bool, start: usize, len: usize) void {
    @memset(m[start .. start + len], true);
}

fn anyMarked(m: []const bool, start: usize, len: usize) bool {
    return std.mem.indexOfScalar(bool, m[start .. start + len], true) != null;
}

// Encode one scope at bit `base`; the result is one past the furthest bit it
// and its items reach.
fn bitsEncodeScope(alloc: std.mem.Allocator, p: *const Pack, sc: *const Scope, out: *BitsOut, base: usize, e: *const Entity, checks: *std.ArrayList(GateCheck), diag: *Diag) anyerror!usize {
    const te = E.@"transform-encode";
    const lines = sc.lines;
    const ng = sc.gates.len;
    var held: []bool = &.{};
    var gval: []?u64 = &.{};
    var nbits = sc.nbits;
    if (ng > 0) {
        // Version 0.17, Encode. The scratch message is read relative to
        // the scope's first bit, and covers every gate.
        var tbits = sc.nbits;
        for (sc.gates) |gt| tbits = @max(tbits, gt.bstart + gt.blen);
        for (lines) |*ln| {
            if (ln.tag != .group) tbits = @max(tbits, ln.bstart + ln.blen);
        }
        held = try alloc.alloc(bool, ng);
        gval = try alloc.alloc(?u64, ng);
        @memset(gval, null);
        // 1. the open blocks: a field line of the block, or of a block
        // nested in it, maps a key the entity holds
        const open = try alloc.alloc(bool, ng);
        @memset(open, false);
        for (lines) |*ln| {
            if (ln.tag != .field or ln.heldValue(e) == null) continue;
            var g = ln.gate;
            while (g) |gt| : (g = gt.parent) open[gt.idx] = true;
        }
        // 2. the lines outside any block, and the bits they wrote: a present
        // key's, a `const`'s, a `when`'s and a count's (ruling 11)
        const tbuf = try alloc.alloc(u8, (tbits + 7) / 8);
        @memset(tbuf, 0);
        try bitsWriteLines(alloc, p, sc, tbuf, 0, e, &.{}, diag);
        try bitsWriteFixed(alloc, p, sc, tbuf, 0, e, &.{}, diag);
        const written = try alloc.alloc(bool, tbits);
        @memset(written, false);
        for (lines) |*ln| {
            if (ln.gate != null) continue;
            switch (ln.tag) {
                .field => if (ln.heldValue(e) != null) markRange(written, ln.bstart, ln.blen),
                .when, .constant => markRange(written, ln.bstart, ln.blen),
                .group => {
                    const g = ln.grp.?;
                    if (g.count_fixed == null) markRange(written, g.cstart, g.clen);
                },
                .element => {}, // xml only
            }
        }
        // 3. each open block none of whose gate bits is written gets its gate
        // value, in line order; those bits are then written
        for (sc.gates) |gt| {
            if (!open[gt.idx] or anyMarked(written, gt.bstart, gt.blen)) continue;
            const v = gt.encodeValue() orelse continue;
            setBits(tbuf, p.msb, gt.bstart, gt.blen, v);
            markRange(written, gt.bstart, gt.blen);
            gval[gt.idx] = v;
        }
        // 4. the held blocks, evaluated on those bits; bits nothing wrote
        // read as 0
        evalGates(p, sc.gates, tbuf, tbuf.len * 8, 0, held);
        // 6, second half: a key the entity holds mapped only by lines of
        // blocks that are not held
        for (lines) |*ln| {
            if (ln.tag != .field or ln.gate == null or lineOn(ln, held) or ln.heldValue(e) == null) continue;
            var mapped = false;
            for (lines) |*l2| {
                if (l2.tag == .field and lineOn(l2, held) and !l2.suppressed(e) and std.mem.eql(u8, l2.key, ln.key)) {
                    mapped = true;
                    break;
                }
            }
            if (!mapped) return bad(diag, alloc, te, "field {s}: every line of the key is in a gate block that does not hold", .{ln.key});
        }
        // the length: the held blocks' lines and their gate locators
        for (lines) |*ln| {
            if (ln.tag != .group and ln.gate != null and lineOn(ln, held)) nbits = @max(nbits, ln.bstart + ln.blen);
        }
        for (sc.gates) |gt| {
            if (held[gt.idx]) nbits = @max(nbits, gt.bstart + gt.blen);
        }
    }
    try out.ensure(base + nbits);
    // 5. the lines outside any block and those of the held blocks
    try bitsWriteLines(alloc, p, sc, out.buf.items, base, e, held, diag);
    if (ng > 0) {
        // each held block's gate value over the bits that only a default or
        // a sentinel wrote (ruling 7)
        const strong = try alloc.alloc(bool, nbits);
        @memset(strong, false);
        for (lines) |*ln| {
            if (ln.tag == .field and lineOn(ln, held) and ln.heldValue(e) != null) markRange(strong, ln.bstart, ln.blen);
        }
        for (sc.gates) |gt| {
            if (!held[gt.idx]) continue;
            const v = gval[gt.idx] orelse continue;
            for (0..gt.blen) |k| {
                if (strong[gt.bstart + k]) continue;
                const bit = if (p.msb == .msb) (v >> @as(u6, @intCast(gt.blen - 1 - k))) & 1 else (v >> @as(u6, @intCast(k))) & 1;
                setBits(out.buf.items, p.msb, base + gt.bstart + k, 1, bit);
            }
        }
    }
    // the items of each group, back to back
    var end: usize = base + nbits;
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
        // a group with no items extends the message to its start (ruling 18
        // of 0.52)
        try out.ensure(pos);
        for (items) |*it| {
            try out.ensure(pos + size);
            const iend = try bitsEncodeScope(alloc, p, &g.body, out, pos, it, checks, diag);
            pos = @max(pos + size, iend);
        }
        end = @max(end, pos);
        out.items_end = @max(out.items_end, pos);
    }
    // `when` and `const` values are written over any field, and a count
    // locator with the number of items
    try bitsWriteFixed(alloc, p, sc, out.buf.items, base, e, held, diag);
    if (ng > 0) try checks.append(.{ .sc = sc, .base = base, .held = held });
    return end;
}

// The length `L` of an armored fixed-layout message (Version 0.14): one past
// the highest bit of any `field`, `when` or `const` line of the scope, of a
// count locator, or of the items (`end`), except an `optional` field with no
// value and no default, unless it has `absent`. With gate blocks (0.17) the
// lines of a block count only when it is held (`held`, by gate index; empty:
// the scope has no gate), and so does a held block's gate locator.
fn armorLength(p: *const Pack, sc: *const Scope, e: *const Entity, end: usize, held: []const bool) !usize {
    var l: usize = end;
    for (sc.gates) |gt| {
        if (held.len > 0 and held[gt.idx]) l = @max(l, gt.bstart + gt.blen);
    }
    for (sc.lines) |*ln| {
        if (ln.tag == .group) {
            const g = ln.grp.?;
            if (g.count_fixed == null) l = @max(l, g.cstart + g.clen);
            continue;
        }
        if (!lineOn(ln, held)) continue;
        // a field with `absent` writes its first sentinel (ruling 12 of 0.14)
        if (ln.isField() and ln.optional and !ln.sentinelOn(e) and (try fieldValue(p, sc, e, ln)) == null) continue;
        l = @max(l, ln.bstart + ln.blen);
    }
    return l;
}

fn encodePack(alloc: std.mem.Allocator, p: *const Pack, e: *const Entity, diag: *Diag) anyerror![]u8 {
    const held_check = diag.held_check;
    diag.held_check = false;
    if (built(.bits) and p.seq != null) return seqEncode(alloc, p, e, diag, held_check);
    const kind_idx = try selectKindEncode(alloc, p, e, diag);
    if (held_check) if (kind_idx) |ki| try heldCheck(alloc, p, ki, e, diag);
    const sc = p.scope(kind_idx);
    const lines = sc.lines;

    switch (p.wire) {
        .xml => { if (comptime !built(.xml)) unreachable;
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
        .geojson => { if (comptime !built(.geojson)) unreachable;
            var coords = [3]?[]const u8{ null, null, null };
            var coords_weak = [3]bool{ false, false, false };
            var props = std.ArrayList(Member).init(alloc);
            var top = std.ArrayList(Member).init(alloc);
            for (lines) |*ln| {
                var raw: []const u8 = undefined;
                var mode: WMode = .field;
                if (sc.partGroup(ln)) |g| {
                    if (g.first != ln) continue;
                    raw = "";
                    if (try partToken(alloc, p, sc, g, e, diag)) |t| raw = try jsonStr(alloc, t) else mode = .reserve;
                } else if (ln.tag == .group) {
                    // an array at the member; an absent list writes nothing
                    raw = (try jsonGroupRaw(alloc, p, ln.grp.?, e, diag)) orelse continue;
                } else if (ln.isFixed()) {
                    if (ln.wpresent) continue;
                    raw = try whenJsonRaw(alloc, ln.*);
                    mode = .fixed;
                } else if (fieldValue(p, sc, e, ln) catch |err|
                    return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator })) |mv|
                {
                    raw = jsonRaw(alloc, ln.transform, mv) catch |err|
                        return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator });
                } else if (ln.sentinelOn(e)) {
                    // an absent key writes its first sentinel; for `lon` and
                    // `lat` it counts as a value (ruling 10 of 0.9)
                    raw = ln.abs_json;
                    mode = .sentinel;
                } else if (ln.isField()) {
                    // writes nothing, and takes its member's place (ruling
                    // 23 of 0.9, ruling 1 of 0.18)
                    raw = "";
                    mode = .reserve;
                } else continue;
                const loc = ln.locator;
                if (std.mem.startsWith(u8, loc, geom_prefix)) {
                    const comp = loc[geom_prefix.len..];
                    const idx: usize = if (std.mem.eql(u8, comp, "lon")) 0 else if (std.mem.eql(u8, comp, "lat")) 1 else if (std.mem.eql(u8, comp, "alt")) 2 else continue;
                    if (mode == .reserve) continue;
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
        .json => { if (comptime !built(.json)) unreachable;
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
        .bits => { if (comptime !built(.bits)) unreachable;
            // the whole message, `optional` fields included, then the items;
            // padded with zero bits to whole words
            var out = BitsOut{ .buf = std.ArrayList(u8).init(alloc) };
            try out.ensure(p.wordBytes(sc.nbits) * 8);
            var checks = std.ArrayList(GateCheck).init(alloc);
            const end = try bitsEncodeScope(alloc, p, sc, &out, 0, e, &checks, diag);
            // armored (Version 0.14): the first `L` bits, padded to a whole
            // character; the held blocks of the selected scope give `L`
            var top_held: []const bool = &.{};
            for (checks.items) |ck| {
                if (ck.sc == sc and ck.base == 0) top_held = ck.held;
            }
            const l_armor = if (p.armor) try armorLength(p, sc, e, out.items_end, top_held) else 0;
            try out.ensure(p.wordBytes(@max(sc.nbits, end)) * 8);
            // the bits the output holds, as decode will see them
            const out_bits = if (p.armor) (l_armor + 5) / 6 * 6 else out.buf.items.len * 8;
            if (p.armor) try out.ensure(out_bits);
            // Version 0.17, step 6: on the final output, every held block
            // holds and every other block does not, for every scope and item
            for (checks.items) |ck| {
                const now = try alloc.alloc(bool, ck.held.len);
                evalGates(p, ck.sc.gates, out.buf.items, out_bits, ck.base, now);
                if (!std.mem.eql(bool, now, ck.held)) {
                    return bad(diag, alloc, E.@"transform-encode", "the output does not decode to the gate blocks chosen", .{});
                }
            }
            if (p.armor) return armorEncode(alloc, out.buf.items, l_armor);
            return hexEncode(alloc, out.buf.items);
        },
        .protobuf => { if (comptime !built(.protobuf)) unreachable;
            const root = try alloc.create(PbNode);
            root.* = .{ .number = 0, .children = std.ArrayList(*PbNode).init(alloc) };
            try pbEncodeScope(alloc, p, sc, root, e, diag);
            var buf = std.ArrayList(u8).init(alloc);
            try encodeProtoNode(alloc, root, &buf);
            return hexEncode(alloc, buf.items);
        },
        .text => if (comptime !built(.text)) unreachable else return textEncode(alloc, p, sc, e, diag),
        .tlv => if (comptime !built(.tlv)) unreachable else return tlvEncode(alloc, p, sc, e, diag),
        .cbor => if (comptime !built(.cbor)) unreachable else return cborEncode(alloc, p, sc, e, diag),
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
    const text_dirs = p.delim_raw != null or p.start_raw != null;
    const tlv_dirs = p.tag_raw != null or p.len_raw != null or p.key_raw != null;
    if (!text_dirs and !tlv_dirs and p.cksum_raw == null) return;
    if (text_dirs and p.wire != .text) return bad(diag, alloc, bd, "delimiter and start are directives of the text wire, not {s}", .{@tagName(p.wire)});
    // `tag <n>` names two forms: on `tlv` (0.13) and on `cbor` (ruling 5 of 0.28)
    const cbor_tag = p.wire == .cbor and p.len_raw == null and p.key_raw == null;
    if (tlv_dirs and p.wire != .tlv and !cbor_tag) return bad(diag, alloc, bd, "tag, length and key are directives of the tlv wire, not {s}", .{@tagName(p.wire)});
    if (p.cksum_raw != null and p.wire != .text and p.wire != .tlv) return bad(diag, alloc, bd, "checksum is a directive of the text and tlv wires, not {s}", .{@tagName(p.wire)});
    if (p.tdir_bad != 0) return bad(diag, alloc, bd, "line {d}: a directive of the wire appears at most once, before the first kind", .{p.tdir_bad});
    if (isW(p.wire, .tlv)) return tlvDirectives(alloc, p, diag);
    if (isW(p.wire, .cbor)) {
        const t = p.tag_raw orelse return;
        p.cbor_tag = cParseTagNum(t) orelse
            return bad(diag, alloc, bd, "tag {s} is not a decimal integer from 0 to 2^64-1 with no leading zero", .{t});
        return;
    }
    // the wire is `text` from here
    if (comptime !built(.text)) unreachable;
    if (p.cksum_arg != null) return bad(diag, alloc, bd, "checksum {s} {s} is not none or nmea", .{ p.cksum_raw.?, p.cksum_arg.? });
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
        .string, .part => MV{ .str = raw },
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

fn textAddressed(lines: []const Line, idx: usize) bool {
    for (lines) |*ln| if (textAddresses(ln, idx)) return true;
    return false;
}

fn textGroup(lines: []const Line) ?*const Group {
    for (lines) |*ln| if (ln.tag == .group) return ln.grp.?;
    return null;
}

fn textResidue(alloc: std.mem.Allocator, p: *const Pack, lines: []const Line, td: TextDoc, e: *Entity) anyerror!void {
    const g = textGroup(lines);
    const end = if (g) |gr| @min(gr.tstart, td.fields.len) else td.fields.len;
    // A record may hold a field per input byte: the room is taken once, as
    // a list grown in an arena leaves every smaller copy behind.
    var count: usize = 0;
    for (td.fields[0..end], 0..) |f, idx| {
        if (f.len > 0 and !textAddressed(lines, idx)) count += 1;
    }
    try e.residue.ensureTotalCapacityPrecise(e.alloc, e.residue.items.len + count);
    for (td.fields[0..end], 0..) |f, idx| {
        if (f.len == 0 or textAddressed(lines, idx)) continue;
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
        .string, .float, .int, .iso8601_ms, .iso8601_s, .codestr, .codenum => return .{ .a = try xmlText(alloc, t, mv) },
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
// characters stand), then `when` and `const` values over both. A record may
// have a field per input byte, so a field costs three words; what only
// columns and fixed values need is held apart, for the fields that have them.
const TField = struct {
    whole_ptr: ?[*]const u8 = null,
    whole_len: usize = 0,
    over: ?*TOver = null,

    // The text, after `compose` and before it where no fixed value is written.
    fn result(self: *const TField) []const u8 {
        if (self.over) |o| if (o.composed) return o.text.items;
        if (self.whole_ptr) |w| return w[0..self.whole_len];
        return if (self.over) |o| o.cols.items else "";
    }
    fn overlay(self: *TField, alloc: std.mem.Allocator) !*TOver {
        if (self.over == null) {
            const o = try alloc.create(TOver);
            o.* = .{};
            self.over = o;
        }
        return self.over.?;
    }
};

const TOver = struct {
    cols: std.ArrayListUnmanaged(u8) = .{},
    cmask: std.ArrayListUnmanaged(bool) = .{},
    text: std.ArrayListUnmanaged(u8) = .{},
    fmask: std.ArrayListUnmanaged(bool) = .{},
    fixed_whole: bool = false,
    // `text` and `fmask` are in use: a fixed value is written over the field
    composed: bool = false,
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

    // Room for every field the residue and the items write, taken once.
    fn reserve(self: *TextEnc, sc: *const Scope, e: *const Entity, g: ?*const Group) !void {
        var n: usize = 0;
        for (e.residue.items) |r| {
            if (textResidueField(self.p, sc, g, r)) |idx| n = @max(n, idx + 1);
        }
        if (g) |gr| if (e.lists.get(gr.list)) |items| {
            if (items.len > 0) n = @max(n, gr.tstart + items.len * gr.titem);
        };
        try self.fields.ensureTotalCapacityPrecise(self.alloc, n);
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
        if (f.whole_ptr != null) return;
        f.whole_ptr = s.ptr;
        f.whole_len = s.len;
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
        const f = try (try self.field(idx)).overlay(self.alloc);
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
            if (sc.partGroup(ln)) |g| {
                // the token, at the group's first line (Version 0.64)
                if (g.first != ln) continue;
                if (try partToken(self.alloc, self.p, sc, g, e, self.diag)) |t| {
                    try self.check(ln, t);
                    try self.whole(base + ln.ti, t);
                }
                continue;
            }
            switch (ln.tag) {
                .when, .constant => try self.fixed.append(self.alloc, .{ .ln = ln, .base = base }),
                .element => {}, // xml only (Version 0.18)
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
        for (self.fixed.items) |fx| {
            const ln = fx.ln;
            if (ln.wpresent) continue;
            const tf = try self.field(fx.base + ln.ti);
            const f = try tf.overlay(self.alloc);
            if (!f.composed) {
                const from_lines = tf.result();
                try f.text.appendSlice(self.alloc, from_lines);
                try f.fmask.appendNTimes(self.alloc, false, from_lines.len);
                f.composed = true;
            }
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

// The field a residue entry is written at; null: it is not written.
fn textResidueField(p: *const Pack, sc: *const Scope, g: ?*const Group, r: Residue) ?usize {
    if (!std.mem.eql(u8, r.fmt, p.format)) return null;
    const idx = parseIdx(r.locator) orelse return null;
    if (g) |gr| if (idx >= gr.tstart) return null;
    return if (textAddressed(sc.lines, idx)) null else idx;
}

fn textEncode(alloc: std.mem.Allocator, p: *const Pack, sc: *const Scope, e: *const Entity, diag: *Diag) anyerror![]u8 {
    var enc = TextEnc{ .alloc = alloc, .p = p, .diag = diag };
    const g = textGroup(sc.lines);
    try enc.reserve(sc, e, g);
    try enc.scope(sc, e, 0);
    // the record's length: the fields the lines address, the items wrote,
    // and the residue written
    var n: usize = enc.fields.items.len;
    for (sc.lines) |*ln| {
        if (ln.tag == .group or !ln.maps()) continue;
        n = @max(n, ln.ti + 1);
        if (ln.tloc == .pair) n = @max(n, ln.tj + 1);
    }
    for (e.residue.items) |r| {
        const idx = textResidueField(p, sc, g, r) orelse continue;
        try enc.whole(idx, r.value);
        n = @max(n, idx + 1);
    }
    _ = try enc.field(if (n > 0) n - 1 else 0);
    try enc.compose();
    // trailing empty fields that only `optional` lines address are removed
    while (n > 0) {
        const last = n - 1;
        if (enc.fields.items[last].result().len > 0) break;
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
    const count = if (p.delim == null) @min(n, 1) else n;
    var size: usize = p.start.len + count + 3; // delimiters, and `*hh`
    for (enc.fields.items[0..count]) |*f| size += f.result().len;
    var buf = try std.ArrayList(u8).initCapacity(alloc, size);
    try buf.appendSlice(p.start);
    const body_at = buf.items.len;
    for (enc.fields.items[0..count], 0..) |*f, i| {
        if (i > 0) try buf.append(p.delim.?);
        try buf.appendSlice(f.result());
    }
    if (p.nmea) {
        var x: u8 = 0;
        for (buf.items[body_at..]) |c| x ^= c;
        try buf.writer().print("*{X:0>2}", .{x});
    }
    return buf.toOwnedSlice();
}

// ---------------------------------------------------------------------------
// Version 0.13: the `tlv` wire. A set of items, each a tag, a length and a
// value; a value may itself be a set. The set may follow a fixed key and a
// length, and may end with a `sum16` checksum item. Hex text in and out.
// ---------------------------------------------------------------------------

const tlv_max_tag: u64 = (1 << 28) - 1;

// A tag of a path or of `checksum sum16 <tag>`: decimal with no leading
// zero, at most 2^28-1, and under `tag <n>` below 2^(8n). null: not a tag.
fn tlvTagNum(p: *const Pack, s: []const u8) ?u32 {
    if (s.len == 0 or s.len > 9 or !allDigits(s)) return null;
    if (s.len > 1 and s[0] == '0') return null;
    const v = std.fmt.parseInt(u64, s, 10) catch return null;
    if (v > tlv_max_tag) return null;
    if (p.tlv_tag != 0 and p.tlv_tag < 4 and v >= (@as(u64, 1) << @as(u6, @intCast(8 * @as(u32, p.tlv_tag))))) return null;
    return @intCast(v);
}

// `tag`, `length`, `key` and `checksum` on the `tlv` wire, after the file is
// read (the wire and the repeats are checked before).
fn tlvDirectives(alloc: std.mem.Allocator, p: *Pack, diag: *Diag) anyerror!void {
    const bd = E.@"bad-directive";
    const width = struct {
        fn f(s: []const u8, ber: []const u8) ?u8 {
            if (std.mem.eql(u8, s, ber)) return 0;
            if (std.mem.eql(u8, s, "1")) return 1;
            if (std.mem.eql(u8, s, "2")) return 2;
            if (std.mem.eql(u8, s, "4")) return 4;
            return null;
        }
    }.f;
    if (p.tag_raw) |t| p.tlv_tag = width(t, "ber-oid") orelse
        return bad(diag, alloc, bd, "tag {s} is not ber-oid, 1, 2 or 4", .{t});
    if (p.len_raw) |l| p.tlv_len = width(l, "ber") orelse
        return bad(diag, alloc, bd, "length {s} is not ber, 1, 2 or 4", .{l});
    if (p.key_raw) |k| {
        var ok = k.len >= 2 and k.len <= 128 and k.len % 2 == 0;
        for (k) |c| {
            if (!((c >= '0' and c <= '9') or (c >= 'a' and c <= 'f'))) ok = false;
        }
        if (!ok) return bad(diag, alloc, bd, "key {s} is not 1 to 64 bytes as an even number of lowercase hex digits", .{k});
        p.tlv_key = try hexDecode(alloc, k);
    }
    if (p.cksum_raw) |c| {
        const crc = std.mem.eql(u8, c, "crc32");
        if (!crc and !std.mem.eql(u8, c, "sum16")) return bad(diag, alloc, bd, "checksum {s} on the tlv wire; it takes sum16 <tag> or crc32 <tag>", .{c});
        const a = p.cksum_arg orelse return bad(diag, alloc, bd, "checksum {s} takes a tag", .{c});
        p.tlv_sum = tlvTagNum(p, a) orelse
            return bad(diag, alloc, bd, "checksum {s} {s}: not a tag from 0 to 2^28-1 with no leading zero that fits the tag size", .{ c, a });
        p.tlv_crc = crc;
    }
}

// One line's path, size and `when` or `const` value on the `tlv` wire.
fn tlvFinalizeLine(alloc: std.mem.Allocator, p: *Pack, ln: *Line, diag: *Diag) anyerror!void {
    const bd = E.@"bad-directive";
    var loc = ln.locator;
    if (std.mem.indexOfScalar(u8, loc, ':')) |c| {
        const st = loc[c + 1 ..];
        if (st.len != 1 or st[0] < '1' or st[0] > '8') return bad(diag, alloc, bd, "line {d}: the size in {s} is not one digit from 1 to 8", .{ ln.lineno, ln.locator });
        ln.tsize = st[0] - '0';
        loc = loc[0..c];
    }
    var tags = std.ArrayList(u32).init(alloc);
    var it = std.mem.splitScalar(u8, loc, '.');
    while (it.next()) |seg| {
        const t = tlvTagNum(p, seg) orelse
            return bad(diag, alloc, bd, "line {d}: {s} is not a path of tags from 0 to 2^28-1 with no leading zero that fit the tag size", .{ ln.lineno, ln.locator });
        try tags.append(t);
    }
    ln.tpath = try tags.toOwnedSlice();
    if (p.tlv_sum) |ck| {
        if (ln.tpath[0] == ck) return bad(diag, alloc, bd, "line {d}: the path {s} begins with the checksum tag", .{ ln.lineno, ln.locator });
    }
    const n = ln.tsize;
    if (ln.isField()) {
        const ok = switch (ln.transform.kind) {
            .uint, .twos, .uscale, .sscale => n != 0,
            .f32_ => n == 0 or n == 4,
            .f64_ => n == 0 or n == 8,
            .utf8, .hex => n == 0,
            else => false,
        };
        if (!ok) return bad(diag, alloc, bd, "line {d}: the size of {s} does not fit its transform", .{ ln.lineno, ln.locator });
        return;
    }
    if (std.mem.eql(u8, ln.wraw, "present")) {
        if (n != 0) return bad(diag, alloc, bd, "line {d}: present with a size", .{ln.lineno});
        ln.wpresent = true;
        return;
    }
    if (n == 0) return bad(diag, alloc, bd, "line {d}: {s} {s} {s} needs a size", .{ ln.lineno, @tagName(ln.tag), ln.locator, ln.wraw });
    const v = parseUnsigned(ln.wraw) orelse
        return bad(diag, alloc, bd, "line {d}: value {s} is not `present` or an unsigned decimal integer", .{ ln.lineno, ln.wraw });
    if (n < 8 and (v >> @as(u6, @intCast(8 * @as(u32, n)))) != 0) {
        return bad(diag, alloc, bd, "line {d}: value {d} does not fit {d} bytes", .{ ln.lineno, v, n });
    }
    ln.wint = v;
}

fn tlvPrefix(a: []const u32, b: []const u32) bool {
    return a.len < b.len and std.mem.eql(u32, a, b[0..a.len]);
}

// Ruling 5 of 0.13: no line at a path and another at a path under it, in
// one scope.
fn tlvCheckScope(alloc: std.mem.Allocator, a: []const Line, b: []const Line, diag: *Diag) anyerror!void {
    const both = [2][]const Line{ a, b };
    for (both) |xs| for (xs) |*x| {
        if (x.tag == .group) continue;
        for (both) |ys| for (ys) |*y| {
            if (y.tag == .group) continue;
            if (tlvPrefix(x.tpath, y.tpath)) {
                return bad(diag, alloc, E.@"bad-directive", "line {d}: {s} is a value, and line {d} reads it as a set", .{ x.lineno, x.locator, y.lineno });
            }
        };
    };
}

// ---- decode

const TlvItem = struct {
    tag: u32,
    val: []const u8,
    // the value read as a set, once a line walks into it
    sub: ?[]TlvItem = null,
    sub_bad: bool = false,
};

// `n` bytes at `pos` as an unsigned big-endian integer (n at most 8).
fn tlvBE(buf: []const u8, pos: *usize, n: usize) !u64 {
    if (buf.len - pos.* < n) return E.@"malformed-wire";
    var v: u64 = 0;
    for (buf[pos.*..][0..n]) |b| v = (v << 8) | b;
    pos.* += n;
    return v;
}

fn beU64(b: []const u8) u64 {
    var v: u64 = 0;
    for (b) |c| v = (v << 8) | c;
    return v;
}

fn tlvReadTag(p: *const Pack, buf: []const u8, pos: *usize) !u32 {
    const mw = E.@"malformed-wire";
    if (p.tlv_tag != 0) return @intCast(try tlvBE(buf, pos, p.tlv_tag));
    var v: u32 = 0;
    var k: usize = 0;
    while (k < 4) : (k += 1) {
        if (pos.* >= buf.len) return mw;
        const b = buf[pos.*];
        pos.* += 1;
        if (k == 0 and b == 0x80) return mw; // a group of zero before others
        v = (v << 7) | (b & 0x7f);
        if (b & 0x80 == 0) return v;
    }
    return mw; // a fifth byte
}

fn tlvReadLen(p: *const Pack, buf: []const u8, pos: *usize) !u64 {
    if (p.tlv_len != 0) return tlvBE(buf, pos, p.tlv_len);
    if (pos.* >= buf.len) return E.@"malformed-wire";
    const b = buf[pos.*];
    pos.* += 1;
    if (b < 0x80) return b;
    if (b == 0x80 or b > 0x88) return E.@"malformed-wire";
    return tlvBE(buf, pos, b - 0x80);
}

// A set read whole: items to its last byte. A length is compared with the
// bytes left, never added to the offset first.
fn tlvParseSet(alloc: std.mem.Allocator, p: *const Pack, buf: []const u8) ![]TlvItem {
    var items = std.ArrayList(TlvItem).init(alloc);
    errdefer items.deinit();
    var pos: usize = 0;
    while (pos < buf.len) {
        const tag = try tlvReadTag(p, buf, &pos);
        const len = try tlvReadLen(p, buf, &pos);
        if (len > buf.len - pos) return E.@"malformed-wire";
        const l: usize = @intCast(len);
        try items.append(.{ .tag = tag, .val = buf[pos..][0..l] });
        pos += l;
    }
    return items.toOwnedSlice();
}

fn sum16(b: []const u8) u16 {
    var s: u16 = 0;
    for (b, 0..) |c, i| s +%= if (i % 2 == 0) @as(u16, c) << 8 else c;
    return s;
}

// The CRC-32 of ISO/IEC 13818-1 (Version 0.27, "The CRC"): polynomial
// 0x04C11DB7, register from 0xFFFFFFFF, most significant bit first, no
// reflection, no final XOR. (Not std.hash.Crc32, which is reflected.)
fn crc32Mpeg(b: []const u8) u32 {
    var r: u32 = 0xFFFFFFFF;
    for (b) |c| {
        r ^= @as(u32, c) << 24;
        var i: usize = 0;
        while (i < 8) : (i += 1) {
            r = if (r & 0x80000000 != 0) (r << 1) ^ 0x04C11DB7 else r << 1;
        }
    }
    return r;
}

test "crc32Mpeg check values of 0.27" {
    try std.testing.expectEqual(@as(u32, 0x0376E6E7), crc32Mpeg("123456789"));
    try std.testing.expectEqual(@as(u32, 0xFFFFFFFF), crc32Mpeg(""));
}

// The checksum of the bytes it covers, and its width in bytes.
fn tlvCheck(p: *const Pack, b: []const u8) u32 {
    return if (p.tlv_crc) crc32Mpeg(b) else sum16(b);
}
fn tlvCheckLen(p: *const Pack) usize {
    return if (p.tlv_crc) 4 else 2;
}

// Steps 1, 2, 4 and the top set of step 3 of "Reading a message". The
// checksum item is left out of the items.
fn tlvParse(alloc: std.mem.Allocator, p: *const Pack, bytes: []const u8, diag: *Diag) anyerror![]TlvItem {
    const mw = E.@"malformed-wire";
    const buf = hexDecode(alloc, bytes) catch |err| return bad(diag, alloc, err, "the input is not hex of even length", .{});
    var set = buf;
    if (p.tlv_key.len > 0) {
        if (!std.mem.startsWith(u8, buf, p.tlv_key)) return bad(diag, alloc, mw, "the input does not begin with the key", .{});
        var pos: usize = p.tlv_key.len;
        const len = tlvReadLen(p, buf, &pos) catch return bad(diag, alloc, mw, "the length after the key is cut short or not a length", .{});
        if (len > buf.len - pos) return bad(diag, alloc, mw, "the set states {d} bytes, {d} follow its length", .{ len, buf.len - pos });
        set = buf[pos..][0..@intCast(len)];
    }
    var items = tlvParseSet(alloc, p, set) catch |err| {
        if (err == error.OutOfMemory) return err;
        return bad(diag, alloc, mw, "the set is not a sequence of whole items", .{});
    };
    if (p.tlv_sum) |t| {
        if (items.len == 0) return bad(diag, alloc, mw, "no checksum item", .{});
        const last = items[items.len - 1];
        const w = tlvCheckLen(p);
        if (last.tag != t or last.val.len != w) return bad(diag, alloc, mw, "the last item is not the checksum item: tag {d} with a value of {d} bytes", .{ t, w });
        for (items[0 .. items.len - 1]) |it| {
            if (it.tag == t) return bad(diag, alloc, mw, "an item of the checksum tag {d} before the last", .{t});
        }
        const end = @intFromPtr(last.val.ptr) - @intFromPtr(buf.ptr);
        const got = tlvCheck(p, buf[0..end]);
        const want = beU64(last.val);
        if (got != want) return bad(diag, alloc, mw, "the checksum is {x}, the message's is {x}", .{ want, got });
        items = items[0 .. items.len - 1];
    }
    return items;
}

// The value of an item read as a set, read whole the first time.
fn tlvSub(alloc: std.mem.Allocator, p: *const Pack, it: *TlvItem) ![]TlvItem {
    if (it.sub) |s| return s;
    if (it.sub_bad) return E.@"malformed-wire";
    const s = tlvParseSet(alloc, p, it.val) catch |err| {
        if (err == error.OutOfMemory) return err;
        it.sub_bad = true;
        return E.@"malformed-wire";
    };
    it.sub = s;
    return s;
}

fn tlvFirst(items: []TlvItem, tag: u32) ?*TlvItem {
    for (items) |*it| if (it.tag == tag) return it;
    return null;
}

// The first occurrence at a path, each set on the way read whole; null:
// absent. A set on the way that is not well formed is `malformed-wire`.
fn tlvAt(alloc: std.mem.Allocator, p: *const Pack, top: []TlvItem, path: []const u32) !?*TlvItem {
    var cur = top;
    for (path[0 .. path.len - 1]) |t| {
        const it = tlvFirst(cur, t) orelse return null;
        cur = try tlvSub(alloc, p, it);
    }
    return tlvFirst(cur, path[path.len - 1]);
}

fn tlvWhenHolds(alloc: std.mem.Allocator, p: *const Pack, items: []TlvItem, ln: *const Line) bool {
    const it = (tlvAt(alloc, p, items, ln.tpath) catch return false) orelse return false;
    if (ln.wpresent) return true;
    if (it.val.len == 0 or it.val.len > 8) return false;
    return beU64(it.val) == ln.wint;
}

// One value through its transform. null: absent (an empty value but under
// `utf8` and `hex`).
fn tlvDecodeValue(alloc: std.mem.Allocator, ln: *const Line, val: []const u8) !?MV {
    const td = E.@"transform-decode";
    const t = ln.transform;
    switch (t.kind) {
        .utf8 => {
            if (!std.unicode.utf8ValidateSlice(val)) return td;
            return MV{ .str = val };
        },
        .hex => return MV{ .str = try hexEncode(alloc, val) },
        else => {},
    }
    if (val.len == 0) return null;
    switch (t.kind) {
        .uint, .twos, .uscale, .sscale => {
            if (val.len > 8) return td;
            const u = beU64(val);
            const s = signExtend(u, val.len * 8);
            return switch (t.kind) {
                .uint => MV{ .int = @bitCast(u) },
                .twos => MV{ .int = s },
                .uscale => MV{ .float = t.factor.mul(@floatFromInt(u)) + t.offset },
                else => MV{ .float = t.factor.mul(@floatFromInt(s)) + t.offset },
            };
        },
        .f32_ => {
            if (val.len != 4) return td;
            const f: f32 = @bitCast(@as(u32, @intCast(beU64(val))));
            if (!std.math.isFinite(f)) return td;
            return MV{ .float = @as(f64, f) };
        },
        .f64_ => {
            if (val.len != 8) return td;
            const f: f64 = @bitCast(beU64(val));
            if (!std.math.isFinite(f)) return td;
            return MV{ .float = f };
        },
        else => return td,
    }
}

fn tlvReadField(alloc: std.mem.Allocator, p: *const Pack, items: []TlvItem, ln: *const Line) !?MV {
    const it = (try tlvAt(alloc, p, items, ln.tpath)) orelse return null;
    return tlvDecodeValue(alloc, ln, it.val);
}

// Every set on the path of a line of the selected scope, read whole.
fn tlvWalkScope(alloc: std.mem.Allocator, p: *const Pack, items: []TlvItem, lines: []const Line, diag: *Diag) anyerror!void {
    for (lines) |*ln| {
        if (ln.tag == .group or ln.tpath.len < 2) continue;
        _ = tlvAt(alloc, p, items, ln.tpath) catch |err| {
            if (err == error.OutOfMemory) return err;
            return bad(diag, alloc, err, "a set on the path {s} is not a sequence of whole items", .{ln.locator});
        };
    }
}

// Residue of one set at `prefix`: every item whose tag no line of the scope
// names there, every occurrence; a later occurrence of a named tag is
// dropped; a set a line walks into gives the residue of its own items.
fn tlvResidue(alloc: std.mem.Allocator, p: *const Pack, lines: []const Line, items: []TlvItem, prefix: []const u32, pstr: []const u8, e: *Entity) anyerror!void {
    var seen = std.ArrayList(u32).init(alloc);
    defer seen.deinit();
    for (items) |*it| {
        var names = false;
        var walks = false;
        for (lines) |*ln| {
            if (ln.tag == .group) continue;
            const tp = ln.tpath;
            if (tp.len <= prefix.len or tp[prefix.len] != it.tag or !std.mem.eql(u32, tp[0..prefix.len], prefix)) continue;
            if (tp.len > prefix.len + 1) {
                walks = true;
            } else if (ln.maps()) names = true;
        }
        const path = if (pstr.len == 0) try intToStr(alloc, it.tag) else try std.fmt.allocPrint(alloc, "{s}.{d}", .{ pstr, it.tag });
        if (!names and !walks) {
            try e.addResidue(.{ .fmt = p.format, .locator = path, .value = try hexEncode(alloc, it.val) });
            continue;
        }
        if (std.mem.indexOfScalar(u32, seen.items, it.tag) != null) continue;
        try seen.append(it.tag);
        if (walks) {
            const sub = try tlvSub(alloc, p, it);
            const np = try alloc.alloc(u32, prefix.len + 1);
            @memcpy(np[0..prefix.len], prefix);
            np[prefix.len] = it.tag;
            try tlvResidue(alloc, p, lines, sub, np, path, e);
        }
    }
}

// ---- encode

const TlvNode = struct {
    slots: std.ArrayListUnmanaged(TlvSlot) = .{},
    residue: std.ArrayListUnmanaged(TlvRes) = .{},
};

// An item a line writes, at the position of the first line that names it:
// a nested set, or a value (a `when` or `const` value over a field's).
const TlvSlot = struct {
    tag: u32,
    set: ?*TlvNode = null,
    fixed: ?[]const u8 = null,
    field: ?[]const u8 = null,
    want_empty: bool = false,
};

const TlvRes = struct { tag: u32, val: []const u8 };

fn tlvSlot(alloc: std.mem.Allocator, node: *TlvNode, tag: u32) !*TlvSlot {
    for (node.slots.items) |*s| if (s.tag == tag) return s;
    try node.slots.append(alloc, .{ .tag = tag });
    return &node.slots.items[node.slots.items.len - 1];
}

// The set holding the last tag of a path, its nested sets made on the way.
fn tlvNodeFor(alloc: std.mem.Allocator, root: *TlvNode, path: []const u32) !*TlvNode {
    var node = root;
    for (path[0 .. path.len - 1]) |t| {
        const s = try tlvSlot(alloc, node, t);
        if (s.set == null) {
            const n = try alloc.create(TlvNode);
            n.* = .{};
            s.set = n;
        }
        node = s.set.?;
    }
    return node;
}

fn tlvUint(alloc: std.mem.Allocator, v: u64, n: usize) ![]u8 {
    const out = try alloc.alloc(u8, n);
    for (0..n) |i| out[n - 1 - i] = @truncate(v >> @as(u6, @intCast(8 * i)));
    return out;
}

// A value through its transform into its bytes.
fn tlvEncodeValue(alloc: std.mem.Allocator, ln: *const Line, mv: MV) ![]u8 {
    const te = E.@"transform-encode";
    const n: usize = ln.tsize;
    switch (ln.transform.kind) {
        .utf8 => {
            if (mv != .str) return te;
            return alloc.dupe(u8, mv.str);
        },
        .hex => {
            if (mv != .str or mv.str.len % 2 != 0) return te;
            const out = try alloc.alloc(u8, mv.str.len / 2);
            for (out, 0..) |*b, i| {
                const hi = hexVal(mv.str[2 * i]) orelse return te;
                const lo = hexVal(mv.str[2 * i + 1]) orelse return te;
                b.* = hi * 16 + lo;
            }
            return out;
        },
        .uint, .twos => {
            if (mv != .int) return te;
            const v = mv.int;
            if (n < 8) {
                const bits: u6 = @intCast(8 * n);
                if (ln.transform.kind == .uint) {
                    if (v < 0 or v >= (@as(i64, 1) << bits)) return te;
                } else {
                    const half = @as(i64, 1) << (bits - 1);
                    if (v < -half or v >= half) return te;
                }
            }
            return tlvUint(alloc, @bitCast(v), n);
        },
        .uscale, .sscale => {
            var tmp = ln.*;
            tmp.blen = 8 * n;
            return tlvUint(alloc, try bitsEncodeField(&tmp, mv), n);
        },
        .f32_ => return tlvUint(alloc, try bitsEncodeField(ln, mv), 4),
        .f64_ => return tlvUint(alloc, try bitsEncodeField(ln, mv), 8),
        else => return te,
    }
}

fn tlvPutTag(p: *const Pack, out: *std.ArrayList(u8), tag: u32) !void {
    if (p.tlv_tag == 0) {
        if (tag > tlv_max_tag) return E.@"transform-encode";
        var n: u5 = 1;
        while (n < 4 and (tag >> (7 * n)) != 0) n += 1;
        var i: u5 = n;
        while (i > 0) {
            i -= 1;
            var b: u8 = @truncate((tag >> (7 * i)) & 0x7f);
            if (i > 0) b |= 0x80;
            try out.append(b);
        }
        return;
    }
    const n = p.tlv_tag;
    if (n < 4 and tag >= (@as(u32, 1) << @as(u5, @intCast(8 * @as(u32, n))))) return E.@"transform-encode";
    for (0..n) |i| try out.append(@truncate(tag >> @as(u5, @intCast(8 * (n - 1 - i)))));
}

fn tlvPutLen(p: *const Pack, out: *std.ArrayList(u8), len: usize) !void {
    const v: u64 = len;
    var n: usize = p.tlv_len;
    if (n == 0) {
        if (v < 128) return out.append(@intCast(v));
        n = 1;
        while (n < 8 and (v >> @as(u6, @intCast(8 * n))) != 0) n += 1;
        try out.append(@intCast(0x80 + n));
    } else if (n < 8 and (v >> @as(u6, @intCast(8 * n))) != 0) return E.@"transform-encode";
    for (0..n) |i| try out.append(@truncate(v >> @as(u6, @intCast(8 * (n - 1 - i)))));
}

fn tlvPutItem(p: *const Pack, out: *std.ArrayList(u8), tag: u32, val: []const u8) !void {
    try tlvPutTag(p, out, tag);
    try tlvPutLen(p, out, val.len);
    try out.appendSlice(val);
}

// A set: the items of the lines in their order, then the residue in input
// order. A nested set with no items is not written.
fn tlvWriteSet(alloc: std.mem.Allocator, p: *const Pack, node: *const TlvNode, out: *std.ArrayList(u8)) anyerror!void {
    slots: for (node.slots.items) |s| {
        if (s.set) |sub| {
            var inner = std.ArrayList(u8).init(alloc);
            try tlvWriteSet(alloc, p, sub, &inner);
            if (inner.items.len > 0) try tlvPutItem(p, out, s.tag, inner.items);
            continue;
        }
        const v: []const u8 = s.fixed orelse s.field orelse blk: {
            if (!s.want_empty) continue;
            // `when … present`: residue of that tag stands for the item
            for (node.residue.items) |r| if (r.tag == s.tag) continue :slots;
            break :blk "";
        };
        try tlvPutItem(p, out, s.tag, v);
    }
    for (node.residue.items) |r| try tlvPutItem(p, out, r.tag, r.val);
}

// The tags of a residue locator; null: not a path of tags.
fn tlvResiduePath(alloc: std.mem.Allocator, loc: []const u8) !?[]const u32 {
    var tags = std.ArrayList(u32).init(alloc);
    var it = std.mem.splitScalar(u8, loc, '.');
    while (it.next()) |seg| {
        const v = parseUnsigned(seg) orelse return null;
        if (v > tlv_max_tag) return null;
        try tags.append(@intCast(v));
    }
    return try tags.toOwnedSlice();
}

fn tlvEncode(alloc: std.mem.Allocator, p: *const Pack, sc: *const Scope, e: *const Entity, diag: *Diag) anyerror![]u8 {
    const root = try alloc.create(TlvNode);
    root.* = .{};
    // the positions of the items, and the `when` and `const` values
    for (sc.lines) |*ln| {
        if (ln.tag == .group) continue;
        const node = try tlvNodeFor(alloc, root, ln.tpath);
        const s = try tlvSlot(alloc, node, ln.tpath[ln.tpath.len - 1]);
        if (!ln.isFixed()) continue;
        if (ln.wpresent) {
            s.want_empty = true;
        } else if (s.fixed == null) {
            s.fixed = try tlvUint(alloc, ln.wint, ln.tsize);
        }
    }
    // the fields: the earliest present key of a path, unless a `when` or
    // `const` names it
    for (sc.lines) |*ln| {
        if (!ln.isField()) continue;
        const node = try tlvNodeFor(alloc, root, ln.tpath);
        const s = try tlvSlot(alloc, node, ln.tpath[ln.tpath.len - 1]);
        if (s.fixed != null or s.field != null) continue;
        const mv = (fieldValue(p, sc, e, ln) catch |err|
            return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator })) orelse continue;
        s.field = tlvEncodeValue(alloc, ln, mv) catch |err|
            return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator });
    }
    // residue of this format, each in its set
    for (e.residue.items) |r| {
        if (!std.mem.eql(u8, r.fmt, p.format)) continue;
        const path = (try tlvResiduePath(alloc, r.locator)) orelse continue;
        const val = hexDecode(alloc, r.value) catch |err| {
            if (err == error.OutOfMemory) return err;
            return bad(diag, alloc, E.@"transform-encode", "residue {s}: the value is not hex", .{r.locator});
        };
        const node = try tlvNodeFor(alloc, root, path);
        try node.residue.append(alloc, .{ .tag = path[path.len - 1], .val = val });
    }
    var set = std.ArrayList(u8).init(alloc);
    tlvWriteSet(alloc, p, root, &set) catch |err| {
        if (err == error.OutOfMemory) return err;
        return bad(diag, alloc, err, "a tag or a length does not fit its size", .{});
    };
    if (p.tlv_sum) |t| {
        try tlvPutTag(p, &set, t);
        try tlvPutLen(p, &set, tlvCheckLen(p));
        try set.appendNTimes(0, tlvCheckLen(p));
    }
    var out = std.ArrayList(u8).init(alloc);
    if (p.tlv_key.len > 0) {
        try out.appendSlice(p.tlv_key);
        tlvPutLen(p, &out, set.items.len) catch |err| {
            if (err == error.OutOfMemory) return err;
            return bad(diag, alloc, err, "the length of the set, {d}, does not fit its size", .{set.items.len});
        };
    }
    try out.appendSlice(set.items);
    if (p.tlv_sum != null) {
        const n = out.items.len;
        const w = tlvCheckLen(p);
        const s = tlvCheck(p, out.items[0 .. n - w]);
        for (0..w) |i| out.items[n - 1 - i] = @truncate(s >> @as(u5, @intCast(8 * i)));
    }
    return hexEncode(alloc, out.items);
}

// ---------------------------------------------------------------------------
// Version 0.28: the `cbor` wire. A message is one CBOR data item (RFC 8949),
// a map or an array at the top, maps, arrays and scalars at any depth. Paths
// of integer keys, text keys and `[i]` positions; every tag is passed over on
// decode and none is written on encode, but the head of `tag <n>` before the
// top item. Output is the core deterministic encoding of RFC 8949 4.2.1. Hex
// text in and out.
// ---------------------------------------------------------------------------

// Arrays, maps and tags count one level each, the top item level 1.
const cbor_max_depth: usize = 64;
const cbor_max_pos: u64 = 65535;

const CStepKind = enum(u8) { uint, nint, pos, text, raw };

// One step of a path: an integer key (`uint` n, or `nint` with the argument
// n of the value -1-n), a position n, a text key s; `raw` is the `#<hex>` of
// a residue key no path can write, s its hex.
const CStep = struct { kind: CStepKind, n: u64 = 0, s: []const u8 = "" };

// A `when` or `const` value on `cbor`, with its type.
const CValKind = enum(u8) { uint, nint, bool_, text };
const CVal = struct { kind: CValKind = .text, n: u64 = 0, s: []const u8 = "" };

const CKind = enum(u8) { uint, nint, bytes, text, array, map, simple, float };

// One data item as read. `raw` is the item as it stood in the input, its
// tags included; the rest describes the item inside the tags. `arg`: the
// value of `uint`, the argument of `nint`, the simple value, or a float as
// the bits of a double. `kids`: the elements of an array; the keys and
// values of a map, alternately.
const CNode = struct {
    raw: []const u8 = "",
    ntags: u32 = 0,
    tag0: u64 = 0, // the outermost tag
    kind: CKind = .uint,
    arg: u64 = 0,
    str: []const u8 = "",
    kids: []CNode = &.{},

    // `null` and `undefined`
    fn isNil(self: *const CNode) bool {
        return self.kind == .simple and (self.arg == 22 or self.arg == 23);
    }
};

fn cIsAlpha(c: u8) bool {
    return (c >= 'a' and c <= 'z') or (c >= 'A' and c <= 'Z');
}

// A text key the step grammar can write: ASCII letters, digits, `_` and
// `-`, not beginning with a digit or `-`.
fn cTextStepOk(s: []const u8) bool {
    if (s.len == 0) return false;
    if (!(cIsAlpha(s[0]) or s[0] == '_')) return false;
    for (s) |c| if (!(cIsAlpha(c) or isDigit(c) or c == '_' or c == '-')) return false;
    return true;
}

// One step of a path; null: not a step. `residue`: a residue key, which may
// also be `#<hex>`.
fn cParseStep(seg: []const u8, residue: bool) ?CStep {
    if (seg.len == 0) return null;
    if (seg[0] == '[') {
        if (seg.len < 3 or seg[seg.len - 1] != ']') return null;
        const d = seg[1 .. seg.len - 1];
        if (!allDigits(d) or (d.len > 1 and d[0] == '0') or d.len > 5) return null;
        const v = std.fmt.parseInt(u64, d, 10) catch return null;
        if (v > cbor_max_pos) return null;
        return .{ .kind = .pos, .n = v };
    }
    if (seg[0] == '-' or isDigit(seg[0])) {
        const neg = seg[0] == '-';
        const d = if (neg) seg[1..] else seg;
        if (!allDigits(d) or (d.len > 1 and d[0] == '0')) return null;
        if (neg and std.mem.eql(u8, d, "0")) return null;
        const v = std.fmt.parseInt(u64, d, 10) catch return null;
        if (!neg) return .{ .kind = .uint, .n = v };
        if (v > (@as(u64, 1) << 63)) return null;
        return .{ .kind = .nint, .n = v - 1 };
    }
    if (residue and seg[0] == '#') {
        const h = seg[1..];
        if (h.len == 0 or h.len % 2 != 0) return null;
        for (h) |c| if (hexVal(c) == null) return null;
        return .{ .kind = .raw, .s = h };
    }
    if (!cTextStepOk(seg)) return null;
    return .{ .kind = .text, .s = seg };
}

// The steps of a path; null: not a path.
fn cParsePath(alloc: std.mem.Allocator, loc: []const u8, residue: bool) !?[]const CStep {
    var steps = std.ArrayList(CStep).init(alloc);
    var it = std.mem.splitScalar(u8, loc, '.');
    while (it.next()) |seg| try steps.append(cParseStep(seg, residue) orelse return null);
    return try steps.toOwnedSlice();
}

// The locator form on `cbor`, a line check (step 8 of 5b of 0.11): a path,
// or `.` where `dot_ok` (ruling 22 of 0.28).
fn cborLocOk(loc: []const u8, dot_ok: bool) bool {
    if (std.mem.eql(u8, loc, ".")) return dot_ok;
    var it = std.mem.splitScalar(u8, loc, '.');
    while (it.next()) |seg| if (cParseStep(seg, false) == null) return false;
    return true;
}

// `tag <n>` on `cbor`: decimal from 0 to 2^64-1 with no leading zero.
fn cParseTagNum(s: []const u8) ?u64 {
    if (!allDigits(s) or (s.len > 1 and s[0] == '0')) return null;
    return std.fmt.parseInt(u64, s, 10) catch null;
}

// A `when` or `const` value: an integer when 2a of 0.11 reads it and it lies
// in -2^63 to 2^64-1 (rulings 8 and 19), `true` or `false` a bool, any other
// value a text string with one leading `=` stripped.
fn cParseVal(raw: []const u8) CVal {
    if (std.mem.eql(u8, raw, "true")) return .{ .kind = .bool_, .n = 1 };
    if (std.mem.eql(u8, raw, "false")) return .{ .kind = .bool_, .n = 0 };
    const neg = raw.len > 0 and raw[0] == '-';
    var d = if (neg) raw[1..] else raw;
    if (allDigits(d)) {
        while (d.len > 1 and d[0] == '0') d = d[1..];
        if (std.fmt.parseInt(u64, d, 10)) |v| {
            if (!neg or v == 0) return .{ .kind = .uint, .n = v };
            if (v <= (@as(u64, 1) << 63)) return .{ .kind = .nint, .n = v - 1 };
        } else |_| {}
    }
    const t = if (raw.len > 0 and raw[0] == '=') raw[1..] else raw;
    return .{ .kind = .text, .s = t };
}

// One line's path and `when` or `const` value on the `cbor` wire.
fn cborFinalizeLine(alloc: std.mem.Allocator, ln: *Line, diag: *Diag) anyerror!void {
    if (std.mem.eql(u8, ln.locator, ".")) {
        ln.dot = true;
    } else {
        ln.cpath = (try cParsePath(alloc, ln.locator, false)) orelse
            return bad(diag, alloc, E.@"bad-locator", "line {d}: {s} is not a cbor path", .{ ln.lineno, ln.locator });
    }
    if (ln.isFixed()) {
        if (std.mem.eql(u8, ln.wraw, "present")) {
            ln.wpresent = true;
        } else ln.cval = cParseVal(ln.wraw);
    }
}

// The path of a line: a group's own path for a `group` line.
fn cLinePath(ln: *const Line) []const CStep {
    return if (ln.tag == .group) ln.grp.?.cpath else ln.cpath;
}

fn cStepEq(a: CStep, b: CStep) bool {
    return a.kind == b.kind and a.n == b.n and std.mem.eql(u8, a.s, b.s);
}

// Types and ruling 13 over one scope, the lines `a` then `b` (common plus one
// kind, or one group body): an item used both as a map and as an array; a
// line at a proper prefix of another's path, but a `when … present`; a line
// at a group's path, a group at another's.
fn cborCheckScope(alloc: std.mem.Allocator, a: []const Line, b: []const Line, diag: *Diag) anyerror!void {
    const bd = E.@"bad-directive";
    const both = [2][]const Line{ a, b };
    for (both) |xs| for (xs) |*x| {
        if (x.tag == .element) continue;
        const px = cLinePath(x);
        for (both) |ys| for (ys) |*y| {
            if (x == y or y.tag == .element) continue;
            const py = cLinePath(y);
            var k: usize = 0;
            while (k < px.len and k < py.len and cStepEq(px[k], py[k])) k += 1;
            if (k < px.len and k < py.len) {
                if ((px[k].kind == .pos) != (py[k].kind == .pos)) {
                    return bad(diag, alloc, bd, "lines {d} and {d}: {s} and {s} use one item both as a map and as an array", .{ x.lineno, y.lineno, x.locator, y.locator });
                }
                continue;
            }
            if (k == px.len and px.len < py.len) {
                if (x.tag == .when and x.wpresent) continue; // it tests and writes nothing
                return bad(diag, alloc, bd, "line {d}: the path {s} holds a value or a list, and line {d} reads under it", .{ x.lineno, x.locator, y.lineno });
            }
            if (px.len == py.len and (x.tag == .group or y.tag == .group)) {
                return bad(diag, alloc, bd, "lines {d} and {d}: a line at the path {s} of a group", .{ x.lineno, y.lineno, x.locator });
            }
        };
    };
}

fn cborCheckBodies(alloc: std.mem.Allocator, lines: []const Line, diag: *Diag) anyerror!void {
    for (lines) |*ln| {
        if (ln.tag != .group) continue;
        const g = ln.grp.?;
        try cborCheckScope(alloc, g.lines, &.{}, diag);
        try cborCheckBodies(alloc, g.lines, diag);
    }
}

// After the file is read: the type of the top item, which the first step of
// every path outside a group body decides, and the checks of each scope.
fn cborCheckPack(alloc: std.mem.Allocator, p: *Pack, diag: *Diag) anyerror!void {
    var lists = std.ArrayList([]const Line).init(alloc);
    try lists.append(p.common.items);
    for (p.kinds.items) |*k| try lists.append(k.lines.items);
    var decided: ?bool = null;
    var first: usize = 0;
    for (lists.items) |ls| for (ls) |*ln| {
        if (ln.tag == .element) continue;
        const cp = cLinePath(ln);
        const arr = cp.len == 0 or cp[0].kind == .pos;
        if (decided) |dv| {
            if (dv != arr) return bad(diag, alloc, E.@"bad-directive", "lines {d} and {d}: one path makes the top item a map, the other an array", .{ first, ln.lineno });
        } else {
            decided = arr;
            first = ln.lineno;
        }
    };
    p.cbor_array = decided orelse false;
    if (p.kinds.items.len == 0) try cborCheckScope(alloc, p.common.items, &.{}, diag);
    for (p.kinds.items) |*k| try cborCheckScope(alloc, p.common.items, k.lines.items, diag);
    for (lists.items) |ls| try cborCheckBodies(alloc, ls, diag);
}

// ---- reading

const CParser = struct {
    alloc: std.mem.Allocator,
    buf: []const u8,
    pos: usize = 0,

    const Head = struct { major: u8, ai: u8, arg: u64, indef: bool = false };

    // A head in any length. A reserved additional information (28 to 30),
    // and an indefinite length on a major type that has none, are not well
    // formed.
    fn head(self: *CParser) !Head {
        const mw = E.@"malformed-wire";
        if (self.pos >= self.buf.len) return mw;
        const b = self.buf[self.pos];
        self.pos += 1;
        var h = Head{ .major = b >> 5, .ai = b & 0x1f, .arg = b & 0x1f };
        switch (h.ai) {
            0...23 => {},
            24...27 => {
                const s = try self.take(@as(u64, 1) << @intCast(h.ai - 24));
                var v: u64 = 0;
                for (s) |c| v = (v << 8) | c;
                h.arg = v;
            },
            28...30 => return mw,
            else => switch (h.major) {
                2, 3, 4, 5, 7 => h.indef = true,
                else => return mw,
            },
        }
        return h;
    }

    // `n` bytes; a length greater than the bytes left is refused before any
    // memory is taken.
    fn take(self: *CParser, n: u64) ![]const u8 {
        if (n > self.buf.len - self.pos) return E.@"malformed-wire";
        const s = self.buf[self.pos..][0..@intCast(n)];
        self.pos += @intCast(n);
        return s;
    }

    // The break that ends an indefinite item, taken when it stands next.
    fn atBreak(self: *CParser) !bool {
        if (self.pos >= self.buf.len) return E.@"malformed-wire";
        if (self.buf[self.pos] != 0xff) return false;
        self.pos += 1;
        return true;
    }

    // One well-formed data item (RFC 8949 Appendix C), its tags first, at
    // `depth` levels below the top.
    fn item(self: *CParser, depth: usize) anyerror!CNode {
        const mw = E.@"malformed-wire";
        const start = self.pos;
        var d = depth;
        var n = CNode{};
        var h = try self.head();
        while (h.major == 6) {
            d += 1;
            if (d > cbor_max_depth) return mw;
            if (n.ntags == 0) n.tag0 = h.arg;
            n.ntags += 1;
            h = try self.head();
        }
        switch (h.major) {
            0 => {
                n.kind = .uint;
                n.arg = h.arg;
            },
            1 => {
                n.kind = .nint;
                n.arg = h.arg;
            },
            2, 3 => {
                n.kind = if (h.major == 2) .bytes else .text;
                if (!h.indef) {
                    n.str = try self.take(h.arg);
                    if (h.major == 3 and !std.unicode.utf8ValidateSlice(n.str)) return mw;
                } else {
                    // chunks: definite strings of the same major type, each
                    // chunk of a text string valid UTF-8 on its own
                    var acc = std.ArrayListUnmanaged(u8){};
                    while (!try self.atBreak()) {
                        const ch = try self.head();
                        if (ch.major != h.major or ch.indef) return mw;
                        const s = try self.take(ch.arg);
                        if (h.major == 3 and !std.unicode.utf8ValidateSlice(s)) return mw;
                        try acc.appendSlice(self.alloc, s);
                    }
                    n.str = acc.items;
                }
            },
            4, 5 => {
                n.kind = if (h.major == 4) .array else .map;
                d += 1;
                if (d > cbor_max_depth) return mw;
                const per: u64 = if (h.major == 4) 1 else 2;
                if (!h.indef) {
                    // every item takes a byte at least: a count is compared
                    // with the bytes left before any memory is taken for it
                    if (h.arg > (self.buf.len - self.pos) / per) return mw;
                    const kids = try self.alloc.alloc(CNode, @intCast(h.arg * per));
                    for (kids) |*k| k.* = try self.item(d);
                    n.kids = kids;
                } else {
                    var list = std.ArrayListUnmanaged(CNode){};
                    while (!try self.atBreak()) {
                        try list.append(self.alloc, try self.item(d));
                        // a break after a key is a break where a value stands
                        if (per == 2) try list.append(self.alloc, try self.item(d));
                    }
                    n.kids = list.items;
                }
                if (h.major == 5) try cCheckKeys(self.alloc, n.kids);
            },
            7 => {
                if (h.indef) return mw; // a break where an item stands
                n.kind = .simple;
                n.arg = h.arg;
                switch (h.ai) {
                    24 => if (h.arg < 32) return mw, // a two-byte simple value below 32
                    25 => {
                        n.kind = .float;
                        n.arg = cHalfBits(@intCast(h.arg));
                    },
                    26 => {
                        n.kind = .float;
                        n.arg = cSingleBits(@intCast(h.arg));
                    },
                    27 => n.kind = .float,
                    else => {},
                }
            },
            else => unreachable,
        }
        n.raw = self.buf[start..self.pos];
        return n;
    }
};

// Exactly one well-formed data item, nothing after it.
fn cParseAll(alloc: std.mem.Allocator, buf: []const u8) !CNode {
    var ps = CParser{ .alloc = alloc, .buf = buf };
    const n = try ps.item(0);
    if (ps.pos != buf.len) return E.@"malformed-wire";
    return n;
}

// A half as the bits of the double of the same value; an infinity or a NaN
// keeps its payload.
fn cHalfBits(h: u16) u64 {
    const sign: u64 = @as(u64, h >> 15) << 63;
    const m: u64 = h & 0x3ff;
    if ((h >> 10) & 0x1f == 0x1f) return sign | (@as(u64, 0x7ff) << 52) | (m << 42);
    const f: f16 = @bitCast(h);
    return @bitCast(@as(f64, f));
}

fn cSingleBits(w: u32) u64 {
    const sign: u64 = @as(u64, w >> 31) << 63;
    const m: u64 = w & 0x7fffff;
    if ((w >> 23) & 0xff == 0xff) return sign | (@as(u64, 0x7ff) << 52) | (m << 29);
    const f: f32 = @bitCast(w);
    return @bitCast(@as(f64, f));
}

// Reading step 4: two equal keys in one map. Keys are equal when their core
// deterministic encodings are: so are integers by value, text by its bytes,
// and keys of different major types never.
fn cCheckKeys(alloc: std.mem.Allocator, kids: []const CNode) !void {
    const mw = E.@"malformed-wire";
    const n = kids.len / 2;
    if (n < 2) return;
    const keys = try alloc.alloc([]const u8, n);
    for (keys, 0..) |*k, i| k.* = try cCanonOf(alloc, &kids[2 * i]);
    if (n <= 8) {
        for (0..n) |i| {
            for (i + 1..n) |j| if (std.mem.eql(u8, keys[i], keys[j])) return mw;
        }
        return;
    }
    var set = std.StringHashMapUnmanaged(void){};
    try set.ensureTotalCapacity(alloc, @intCast(n));
    for (keys) |k| {
        if (set.getOrPutAssumeCapacity(k).found_existing) return mw;
    }
}

// ---- the core deterministic encoding (RFC 8949 4.2.1)

fn cPutBE(out: *std.ArrayList(u8), v: u64, n: usize) !void {
    var i: usize = n;
    while (i > 0) {
        i -= 1;
        try out.append(@truncate(v >> @as(u6, @intCast(8 * i))));
    }
}

// A head in its shortest form.
fn cHead(out: *std.ArrayList(u8), major: u8, v: u64) !void {
    const m: u8 = major << 5;
    if (v < 24) return out.append(m | @as(u8, @intCast(v)));
    if (v <= 0xff) {
        try out.append(m | 24);
        return cPutBE(out, v, 1);
    }
    if (v <= 0xffff) {
        try out.append(m | 25);
        return cPutBE(out, v, 2);
    }
    if (v <= 0xffffffff) {
        try out.append(m | 26);
        return cPutBE(out, v, 4);
    }
    try out.append(m | 27);
    return cPutBE(out, v, 8);
}

// A float, given as the bits of a double, at the shortest of half, single
// and double that holds it exactly, subnormal halves included (4.2.2).
fn cFloat(out: *std.ArrayList(u8), bits: u64) !void {
    const sign = bits >> 63;
    const mant = bits & ((@as(u64, 1) << 52) - 1);
    if ((bits >> 52) & 0x7ff == 0x7ff) {
        if (mant & ((@as(u64, 1) << 42) - 1) == 0) {
            try out.append(0xf9);
            return cPutBE(out, (sign << 15) | 0x7c00 | (mant >> 42), 2);
        }
        if (mant & ((@as(u64, 1) << 29) - 1) == 0) {
            try out.append(0xfa);
            return cPutBE(out, (sign << 31) | 0x7f800000 | (mant >> 29), 4);
        }
        try out.append(0xfb);
        return cPutBE(out, bits, 8);
    }
    const f: f64 = @bitCast(bits);
    if (@abs(f) <= 65504.0) {
        const h: f16 = @floatCast(f);
        if (@as(u64, @bitCast(@as(f64, h))) == bits) {
            try out.append(0xf9);
            return cPutBE(out, @as(u16, @bitCast(h)), 2);
        }
    }
    if (@abs(f) <= std.math.floatMax(f32)) {
        const s: f32 = @floatCast(f);
        if (@as(u64, @bitCast(@as(f64, s))) == bits) {
            try out.append(0xfa);
            return cPutBE(out, @as(u32, @bitCast(s)), 4);
        }
    }
    try out.append(0xfb);
    return cPutBE(out, bits, 8);
}

const CEnt = struct { key: []const u8, val: []const u8 };

fn cEntLess(_: void, a: CEnt, b: CEnt) bool {
    return std.mem.order(u8, a.key, b.key) == .lt;
}

// An item re-encoded: its tags (each head shortest), then the item with
// every length definite and every map's members in the bytewise order of
// their encoded keys.
fn cCanon(alloc: std.mem.Allocator, n: *const CNode, out: *std.ArrayList(u8)) anyerror!void {
    if (n.ntags > 0) {
        var tp = CParser{ .alloc = alloc, .buf = n.raw };
        var i: u32 = 0;
        while (i < n.ntags) : (i += 1) try cHead(out, 6, (try tp.head()).arg);
    }
    switch (n.kind) {
        .uint => try cHead(out, 0, n.arg),
        .nint => try cHead(out, 1, n.arg),
        .bytes, .text => {
            try cHead(out, if (n.kind == .bytes) 2 else 3, n.str.len);
            try out.appendSlice(n.str);
        },
        .array => {
            try cHead(out, 4, n.kids.len);
            for (n.kids) |*k| try cCanon(alloc, k, out);
        },
        .map => {
            const cnt = n.kids.len / 2;
            const ents = try alloc.alloc(CEnt, cnt);
            for (ents, 0..) |*en, i| {
                en.key = try cCanonOf(alloc, &n.kids[2 * i]);
                en.val = try cCanonOf(alloc, &n.kids[2 * i + 1]);
            }
            std.mem.sort(CEnt, ents, {}, cEntLess);
            try cHead(out, 5, cnt);
            for (ents) |en| {
                try out.appendSlice(en.key);
                try out.appendSlice(en.val);
            }
        },
        .simple => {
            if (n.arg < 24) {
                try out.append(0xe0 | @as(u8, @intCast(n.arg)));
            } else {
                try out.append(0xf8);
                try out.append(@intCast(n.arg));
            }
        },
        .float => try cFloat(out, n.arg),
    }
}

fn cCanonOf(alloc: std.mem.Allocator, n: *const CNode) ![]const u8 {
    var out = std.ArrayList(u8).init(alloc);
    try cCanon(alloc, n, &out);
    return out.toOwnedSlice();
}

// ---- decode

// Steps 1 to 6 of "Reading a message": the hex text, one well-formed item,
// the outermost tag under `tag <n>`, the type of the top item.
fn cborParseDoc(alloc: std.mem.Allocator, p: *const Pack, bytes: []const u8, diag: *Diag) anyerror!*const CNode {
    const mw = E.@"malformed-wire";
    const buf = hexDecode(alloc, bytes) catch |err| return bad(diag, alloc, err, "the input is not hex of even length", .{});
    const top = try alloc.create(CNode);
    top.* = cParseAll(alloc, buf) catch |err| {
        if (err == error.OutOfMemory) return err;
        return bad(diag, alloc, mw, "the input is not exactly one well-formed CBOR data item of at most {d} levels, with no equal keys in a map and valid UTF-8 text", .{cbor_max_depth});
    };
    if (p.cbor_tag) |t| {
        if (top.ntags == 0 or top.tag0 != t) return bad(diag, alloc, mw, "the outermost tag of the input is not {d}", .{t});
    }
    const want: CKind = if (p.cbor_array) .array else .map;
    if (top.kind != want) return bad(diag, alloc, mw, "the top item is not {s}", .{if (p.cbor_array) "an array" else "a map"});
    return top;
}

const CWalk = union(enum) { found: *const CNode, absent, wrong };

// Does a map key (tags not passed over) match a step?
fn cKeyMatches(key: *const CNode, st: CStep) bool {
    if (key.ntags != 0) return false;
    return switch (st.kind) {
        .uint => key.kind == .uint and key.arg == st.n,
        .nint => key.kind == .nint and key.arg == st.n,
        .text => key.kind == .text and std.mem.eql(u8, key.str, st.s),
        .pos, .raw => false,
    };
}

// The item at a path from `root`: absent when a step finds nothing, or
// passes through `null` or `undefined` (ruling 12); `wrong` when an item on
// the way is not the map or array its next step needs.
fn cWalk(root: *const CNode, steps: []const CStep) CWalk {
    var cur = root;
    for (steps) |st| {
        if (cur.isNil()) return .absent;
        if (st.kind == .pos) {
            if (cur.kind != .array) return .wrong;
            if (st.n >= cur.kids.len) return .absent;
            cur = &cur.kids[@intCast(st.n)];
            continue;
        }
        if (cur.kind != .map) return .wrong;
        var found: ?*const CNode = null;
        var i: usize = 0;
        while (i + 1 < cur.kids.len) : (i += 2) {
            if (cKeyMatches(&cur.kids[i], st)) {
                found = &cur.kids[i + 1];
                break;
            }
        }
        cur = found orelse return .absent;
    }
    return .{ .found = cur };
}

fn cborWhenHolds(node: *const CNode, ln: *const Line) bool {
    const it = switch (cWalk(node, ln.cpath)) {
        .found => |f| f,
        else => return false,
    };
    if (it.isNil()) return false;
    if (ln.wpresent) return true;
    const v = ln.cval;
    return switch (v.kind) {
        .uint => it.kind == .uint and it.arg == v.n,
        .nint => it.kind == .nint and it.arg == v.n,
        .bool_ => it.kind == .simple and it.arg == 20 + v.n,
        .text => it.kind == .text and std.mem.eql(u8, it.str, v.s),
    };
}

// One item through a transform of the `cbor` table; null: `null` or
// `undefined`, absent.
fn cDecodeValue(alloc: std.mem.Allocator, k: TKind, it: *const CNode) !?MV {
    if (it.isNil()) return null;
    const td = E.@"transform-decode";
    const max: u64 = std.math.maxInt(i64);
    switch (k) {
        .uint => {
            if (it.kind != .uint or it.arg > max) return td;
            return MV{ .int = @intCast(it.arg) };
        },
        .int => {
            if (it.kind == .uint and it.arg <= max) return MV{ .int = @intCast(it.arg) };
            if (it.kind == .nint and it.arg <= max) return MV{ .int = -1 - @as(i64, @intCast(it.arg)) };
            return td;
        },
        .epoch_s => {
            // the range applies to the product (ruling 7)
            const v: i128 = switch (it.kind) {
                .uint => @as(i128, it.arg),
                .nint => -1 - @as(i128, it.arg),
                else => return td,
            };
            const ms = v * 1000;
            if (ms < std.math.minInt(i64) or ms > std.math.maxInt(i64)) return td;
            return MV{ .int = @intCast(ms) };
        },
        .float => switch (it.kind) {
            .float => {
                const f: f64 = @bitCast(it.arg);
                if (!std.math.isFinite(f)) return td;
                return MV{ .float = f };
            },
            // an integer item to the nearest double, ties to even
            .uint => return MV{ .float = @floatFromInt(it.arg) },
            .nint => return MV{ .float = -@as(f64, @floatFromInt(@as(u128, it.arg) + 1)) },
            else => return td,
        },
        .text_ => {
            if (it.kind != .text) return td;
            return MV{ .str = it.str };
        },
        .bytes => {
            if (it.kind != .bytes) return td;
            return MV{ .str = try hexEncode(alloc, it.str) };
        },
        .bool_ => {
            if (it.kind != .simple or (it.arg != 20 and it.arg != 21)) return td;
            return MV{ .int = @intCast(it.arg - 20) };
        },
        else => return td,
    }
}

fn cborReadField(alloc: std.mem.Allocator, node: *const CNode, ln: *const Line) !?MV {
    const it = switch (cWalk(node, ln.cpath)) {
        .found => |f| f,
        .absent => return null,
        .wrong => return E.@"malformed-wire",
    };
    return cDecodeValue(alloc, ln.transform.kind, it);
}

// Step 8 of "Reading a message": each line of the selected scope finds the
// map or array each step needs where an item exists, and a group's path
// holds an array, `null` or `undefined`.
fn cborWalkScope(alloc: std.mem.Allocator, node: *const CNode, lines: []const Line, diag: *Diag) anyerror!void {
    const mw = E.@"malformed-wire";
    for (lines) |*ln| {
        if (ln.tag == .element) continue;
        switch (cWalk(node, cLinePath(ln))) {
            .wrong => return bad(diag, alloc, mw, "line {d}: an item on the path {s} is not the map or array its next step needs", .{ ln.lineno, ln.locator }),
            .found => |it| if (ln.tag == .group and !it.isNil() and it.kind != .array) {
                return bad(diag, alloc, mw, "line {d}: the item at the group path {s} is not an array", .{ ln.lineno, ln.locator });
            },
            .absent => {},
        }
    }
}

// The items of one group: each element of the array at its path.
fn cborDecodeGroup(alloc: std.mem.Allocator, p: *const Pack, g: *const Group, node: *const CNode, e: *Entity, diag: *Diag) anyerror!void {
    const mw = E.@"malformed-wire";
    const arr = switch (cWalk(node, g.cpath)) {
        .found => |f| f,
        .absent => return,
        .wrong => return bad(diag, alloc, mw, "group {s}: an item on the path {s} is not the map or array its next step needs", .{ g.list, g.locator }),
    };
    if (arr.isNil()) return; // an absent list
    if (arr.kind != .array) return bad(diag, alloc, mw, "group {s}: the item at {s} is not an array", .{ g.list, g.locator });
    const body = &g.body;
    try takeItems(diag, alloc, arr.kids.len, g.list);
    const items = try alloc.alloc(Entity, arr.kids.len);
    const want: CKind = if (g.cbody_array) .array else .map;
    for (arr.kids, 0..) |*el, i| {
        items[i] = Entity.init(alloc);
        if (body.needs_sub) {
            // an element of another type than the body's is an item with
            // no keys (ruling 12 of 0.7)
            if (el.kind != want) continue;
            try cborWalkScope(alloc, el, body.lines, diag);
        }
        _ = try decodeScope(alloc, p, body, .{ .cbor = el }, &items[i], diag);
    }
    try e.putList(g.list, items);
}

// The step text of a map key in a residue path: the integer or the text a
// path can write, else `#` and the key's bytes as they stood (ruling 16).
fn cKeyStepText(alloc: std.mem.Allocator, key: *const CNode) ![]const u8 {
    if (key.ntags == 0) {
        switch (key.kind) {
            .uint => return std.fmt.allocPrint(alloc, "{d}", .{key.arg}),
            // below -2^63 a key is not addressable (ruling 17)
            .nint => if (key.arg < (@as(u64, 1) << 63)) return std.fmt.allocPrint(alloc, "-{d}", .{@as(u128, key.arg) + 1}),
            .text => if (cTextStepOk(key.str)) return key.str,
            else => {},
        }
    }
    return std.fmt.allocPrint(alloc, "#{s}", .{try hexEncode(alloc, key.raw)});
}

fn cJoin(alloc: std.mem.Allocator, prefix: []const u8, step: []const u8) ![]const u8 {
    if (prefix.len == 0) return step;
    return std.fmt.allocPrint(alloc, "{s}.{s}", .{ prefix, step });
}

// Residue: every member or element that no line of the selected scope maps
// and no such line walks into, keyed by its path, the hex of the item as it
// stood, tags included.
fn cborResidue(alloc: std.mem.Allocator, p: *const Pack, lines: []const Line, node: *const CNode, e: *Entity) anyerror!void {
    var ls = std.ArrayList(*const Line).init(alloc);
    for (lines) |*ln| if (ln.tag != .element) try ls.append(ln);
    try cResidueIn(alloc, p, ls.items, 0, node, "", e);
}

// The members or elements of a container the lines walk into; `lines` are
// those whose first `k` steps lead here.
fn cResidueIn(alloc: std.mem.Allocator, p: *const Pack, lines: []const *const Line, k: usize, node: *const CNode, prefix: []const u8, e: *Entity) anyerror!void {
    var sub = std.ArrayList(*const Line).init(alloc);
    defer sub.deinit();
    if (node.kind == .map) {
        var i: usize = 0;
        while (i + 1 < node.kids.len) : (i += 2) {
            const key = &node.kids[i];
            sub.clearRetainingCapacity();
            for (lines) |ln| {
                const cp = cLinePath(ln);
                if (cp.len > k and cKeyMatches(key, cp[k])) try sub.append(ln);
            }
            const path = try cJoin(alloc, prefix, try cKeyStepText(alloc, key));
            try cResidueAt(alloc, p, sub.items, k, &node.kids[i + 1], path, e);
        }
    } else if (node.kind == .array) {
        for (node.kids, 0..) |*el, i| {
            if (i > cbor_max_pos) break; // no key a path can write (ruling 18)
            sub.clearRetainingCapacity();
            for (lines) |ln| {
                const cp = cLinePath(ln);
                if (cp.len > k and cp[k].kind == .pos and cp[k].n == i) try sub.append(ln);
            }
            const path = try cJoin(alloc, prefix, try std.fmt.allocPrint(alloc, "[{d}]", .{i}));
            try cResidueAt(alloc, p, sub.items, k, el, path, e);
        }
    }
}

// One member or element whose place the lines `matched` name at step `k`.
fn cResidueAt(alloc: std.mem.Allocator, p: *const Pack, matched: []const *const Line, k: usize, val: *const CNode, path: []const u8, e: *Entity) anyerror!void {
    if (matched.len == 0) return e.addResidue(.{ .fmt = p.format, .locator = path, .value = try hexEncode(alloc, val.raw) });
    var deeper = std.ArrayList(*const Line).init(alloc);
    for (matched) |ln| {
        if (cLinePath(ln).len == k + 1) {
            // mapped: a field, a `when` with a value, a `const`, a group's
            // own path (ruling 24)
            if (!(ln.tag == .when and ln.wpresent)) return;
        } else try deeper.append(ln);
    }
    // only a `when … present` names it: residue whole (ruling 15)
    if (deeper.items.len == 0) return e.addResidue(.{ .fmt = p.format, .locator = path, .value = try hexEncode(alloc, val.raw) });
    if (val.isNil()) return; // walked into (ruling 12)
    const want: CKind = if (cLinePath(deeper.items[0])[k + 1].kind == .pos) .array else .map;
    if (val.kind != want) return;
    try cResidueIn(alloc, p, deeper.items, k + 1, val, path, e);
}

// ---- encode

const COutKind = enum(u8) { none, map, array, value };

// A place of the output: nothing yet, a map, an array, or an encoded value.
// `forced`: written also when empty (the top item, a present list, a list
// item).
const COut = struct {
    kind: COutKind = .none,
    val: []const u8 = "",
    forced: bool = false,
    members: std.StringHashMapUnmanaged(*COut) = .{},
    elems: std.ArrayListUnmanaged(?*COut) = .{},
};

fn cNewOut(alloc: std.mem.Allocator) !*COut {
    const n = try alloc.create(COut);
    n.* = .{};
    return n;
}

// The encoded key of a map step; null for a `#<hex>` that is not one
// well-formed item.
fn cStepKey(alloc: std.mem.Allocator, st: CStep) !?[]const u8 {
    var out = std.ArrayList(u8).init(alloc);
    switch (st.kind) {
        .uint => try cHead(&out, 0, st.n),
        .nint => try cHead(&out, 1, st.n),
        .text => {
            try cHead(&out, 3, st.s.len);
            try out.appendSlice(st.s);
        },
        .raw => {
            const b = hexDecode(alloc, st.s) catch |err| {
                if (err == error.OutOfMemory) return err;
                return null;
            };
            const n = cParseAll(alloc, b) catch |err| {
                if (err == error.OutOfMemory) return err;
                return null;
            };
            try cCanon(alloc, &n, &out);
        },
        .pos => unreachable,
    }
    return out.items;
}

// The place under `node` at one step, `node` made a map or an array on the
// way; null when it holds a value or is of the other type.
fn cChild(alloc: std.mem.Allocator, node: *COut, st: CStep) !?*COut {
    const want: COutKind = if (st.kind == .pos) .array else .map;
    if (node.kind == .none) node.kind = want;
    if (node.kind != want) return null;
    if (want == .array) {
        const i: usize = @intCast(st.n);
        while (node.elems.items.len <= i) try node.elems.append(alloc, null);
        if (node.elems.items[i] == null) node.elems.items[i] = try cNewOut(alloc);
        return node.elems.items[i].?;
    }
    const key = (try cStepKey(alloc, st)) orelse return null;
    const gop = try node.members.getOrPut(alloc, key);
    if (!gop.found_existing) gop.value_ptr.* = try cNewOut(alloc);
    return gop.value_ptr.*;
}

fn cPlace(alloc: std.mem.Allocator, root: *COut, steps: []const CStep) !?*COut {
    var node = root;
    for (steps) |st| node = (try cChild(alloc, node, st)) orelse return null;
    return node;
}

// A model value through a transform of the `cbor` table.
fn cEncodeValue(alloc: std.mem.Allocator, k: TKind, mv: MV) ![]const u8 {
    const te = E.@"transform-encode";
    var out = std.ArrayList(u8).init(alloc);
    switch (k) {
        .uint => {
            if (mv != .int or mv.int < 0) return te;
            try cHead(&out, 0, @intCast(mv.int));
        },
        .int, .epoch_s => {
            if (mv != .int) return te;
            var v = mv.int;
            if (k == .epoch_s) {
                // `time_ms` divided by 1000 exactly, rounded half away from zero
                const r = @rem(v, 1000);
                v = @divTrunc(v, 1000);
                if (r >= 500) v += 1 else if (r <= -500) v -= 1;
            }
            if (v >= 0) try cHead(&out, 0, @intCast(v)) else try cHead(&out, 1, @intCast(-1 - v));
        },
        .float => {
            const f: f64 = switch (mv) {
                .float => |x| x,
                .int => |i| @floatFromInt(i),
                else => return te,
            };
            if (!std.math.isFinite(f)) return te; // ruling 20
            try cFloat(&out, @bitCast(f));
        },
        .text_ => {
            if (mv != .str or !std.unicode.utf8ValidateSlice(mv.str)) return te;
            try cHead(&out, 3, mv.str.len);
            try out.appendSlice(mv.str);
        },
        .bytes => {
            // an even number of lowercase hex digits
            if (mv != .str or mv.str.len % 2 != 0) return te;
            for (mv.str) |c| if (!((c >= '0' and c <= '9') or (c >= 'a' and c <= 'f'))) return te;
            try cHead(&out, 2, mv.str.len / 2);
            var i: usize = 0;
            while (i < mv.str.len) : (i += 2) try out.append(hexVal(mv.str[i]).? * 16 + hexVal(mv.str[i + 1]).?);
        },
        .bool_ => {
            if (mv != .int or (mv.int != 0 and mv.int != 1)) return te;
            try out.append(if (mv.int == 1) 0xf5 else 0xf4);
        },
        else => return te,
    }
    return out.items;
}

// A `when` or `const` value, written with its type.
fn cValBytes(alloc: std.mem.Allocator, v: CVal) ![]const u8 {
    var out = std.ArrayList(u8).init(alloc);
    switch (v.kind) {
        .uint => try cHead(&out, 0, v.n),
        .nint => try cHead(&out, 1, v.n),
        .bool_ => try out.append(if (v.n == 1) 0xf5 else 0xf4),
        .text => {
            try cHead(&out, 3, v.s.len);
            try out.appendSlice(v.s);
        },
    }
    return out.items;
}

// The lines of one scope into `root`: the places every line walks into, the
// `when` and `const` values, then the fields (the earliest line whose key
// is present, a `when` or `const` value over a field), then the lists.
fn cEncodeScope(alloc: std.mem.Allocator, p: *const Pack, sc: *const Scope, root: *COut, e: *const Entity, diag: *Diag) anyerror!void {
    for (sc.lines) |*ln| {
        switch (ln.tag) {
            .when, .constant => {
                const cp = ln.cpath;
                if (ln.wpresent) {
                    // writes nothing, and walks into the containers on its path
                    if (cp.len == 0) continue;
                    const node = (try cPlace(alloc, root, cp[0 .. cp.len - 1])) orelse continue;
                    if (node.kind == .none) node.kind = if (cp[cp.len - 1].kind == .pos) .array else .map;
                    continue;
                }
                const node = (try cPlace(alloc, root, cp)) orelse continue;
                if (node.kind == .none) {
                    node.kind = .value;
                    node.val = try cValBytes(alloc, ln.cval);
                }
            },
            .field => if (!ln.dot) {
                _ = try cPlace(alloc, root, ln.cpath);
            },
            .group => if (ln.grp.?.cpath.len > 0) {
                _ = try cPlace(alloc, root, ln.grp.?.cpath);
            },
            .element => {},
        }
    }
    for (sc.lines) |*ln| {
        if (!ln.isField() or ln.dot) continue;
        const node = (try cPlace(alloc, root, ln.cpath)) orelse continue;
        if (node.kind != .none) continue;
        const mv = (fieldValue(p, sc, e, ln) catch |err|
            return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator })) orelse continue;
        node.val = cEncodeValue(alloc, ln.transform.kind, mv) catch |err|
            return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator });
        node.kind = .value;
    }
    for (sc.lines) |*ln| {
        if (ln.tag != .group) continue;
        const g = ln.grp.?;
        const items = e.lists.get(g.list) orelse continue; // an absent list writes nothing
        const node = if (g.cpath.len == 0) root else ((try cPlace(alloc, root, g.cpath)) orelse continue);
        if (node != root and node.kind != .none) continue;
        node.kind = .array;
        node.forced = true;
        try node.elems.ensureTotalCapacity(alloc, items.len);
        for (items) |*it| node.elems.appendAssumeCapacity(try cEncodeItem(alloc, p, g, it, diag));
    }
}

// One list item: a map or an array, written also when empty; for a body of
// `.` only, the element itself, `null` when it has no value.
fn cEncodeItem(alloc: std.mem.Allocator, p: *const Pack, g: *const Group, it: *const Entity, diag: *Diag) anyerror!?*COut {
    const body = &g.body;
    const n = try cNewOut(alloc);
    if (!body.needs_sub and body.dot != null) {
        n.kind = .value;
        n.val = "\xf6";
        for (body.lines) |*ln| {
            if (!ln.isField() or !ln.dot) continue;
            const mv = (fieldValue(p, body, it, ln) catch |err|
                return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator })) orelse continue;
            n.val = cEncodeValue(alloc, ln.transform.kind, mv) catch |err|
                return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator });
            break;
        }
        return n;
    }
    n.kind = if (g.cbody_array) .array else .map;
    n.forced = true;
    try cEncodeScope(alloc, p, body, n, it, diag);
    return n;
}

fn cHasContent(n: *const COut) bool {
    switch (n.kind) {
        .value => return true,
        .none => return false,
        .map => {
            if (n.forced) return true;
            var it = n.members.valueIterator();
            while (it.next()) |v| if (cHasContent(v.*)) return true;
            return false;
        },
        .array => {
            if (n.forced) return true;
            for (n.elems.items) |el| {
                if (el) |x| if (cHasContent(x)) return true;
            }
            return false;
        },
    }
}

const COEnt = struct { key: []const u8, node: *const COut };

fn coEntLess(_: void, a: COEnt, b: COEnt) bool {
    return std.mem.order(u8, a.key, b.key) == .lt;
}

// Writing steps 1 to 4: members in the bytewise order of their encoded keys;
// an array up to its highest present position, a gap below it written as
// an empty map or array where the lines walk into it as one, else `null`
// (ruling 23); a map or array with nothing in it is not written.
fn cWriteOut(alloc: std.mem.Allocator, n: *const COut, out: *std.ArrayList(u8)) anyerror!void {
    switch (n.kind) {
        .value => try out.appendSlice(n.val),
        .none => try out.append(0xf6),
        .map => {
            var ents = std.ArrayList(COEnt).init(alloc);
            var it = n.members.iterator();
            while (it.next()) |en| {
                if (cHasContent(en.value_ptr.*)) try ents.append(.{ .key = en.key_ptr.*, .node = en.value_ptr.* });
            }
            std.mem.sort(COEnt, ents.items, {}, coEntLess);
            try cHead(out, 5, ents.items.len);
            for (ents.items) |en| {
                try out.appendSlice(en.key);
                try cWriteOut(alloc, en.node, out);
            }
        },
        .array => {
            var count: usize = 0;
            for (n.elems.items, 0..) |el, i| {
                if (el) |x| {
                    if (cHasContent(x)) count = i + 1;
                }
            }
            try cHead(out, 4, count);
            for (n.elems.items[0..count]) |el| {
                const x = el orelse {
                    try out.append(0xf6);
                    continue;
                };
                if (cHasContent(x)) {
                    try cWriteOut(alloc, x, out);
                    continue;
                }
                try out.append(switch (x.kind) {
                    .map => 0xa0,
                    .array => 0x80,
                    else => 0xf6,
                });
            }
        },
    }
}

fn cborEncode(alloc: std.mem.Allocator, p: *const Pack, sc: *const Scope, e: *const Entity, diag: *Diag) anyerror![]u8 {
    const root = try cNewOut(alloc);
    root.kind = if (p.cbor_array) .array else .map;
    root.forced = true;
    try cEncodeScope(alloc, p, sc, root, e, diag);
    // residue of this format into its map or array, re-encoded; at a place a
    // line writes it is not written (ruling 21)
    for (e.residue.items) |r| {
        if (!std.mem.eql(u8, r.fmt, p.format)) continue;
        const steps = (try cParsePath(alloc, r.locator, true)) orelse continue;
        if (steps.len == 0) continue;
        const parent = (try cPlace(alloc, root, steps[0 .. steps.len - 1])) orelse continue;
        const node = (try cChild(alloc, parent, steps[steps.len - 1])) orelse continue;
        if (cHasContent(node)) continue;
        const b = hexDecode(alloc, r.value) catch |err| {
            if (err == error.OutOfMemory) return err;
            continue;
        };
        const item = cParseAll(alloc, b) catch |err| {
            if (err == error.OutOfMemory) return err;
            continue;
        };
        node.val = try cCanonOf(alloc, &item);
        node.kind = .value;
    }
    var out = std.ArrayList(u8).init(alloc);
    if (p.cbor_tag) |t| try cHead(&out, 6, t);
    try cWriteOut(alloc, root, &out);
    return hexEncode(alloc, out.items);
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
    // named[i - 1]: some `if` block outside every `case` names bit i, with
    // or without `!`
    named: std.ArrayListUnmanaged(bool) = .{},
    // Version 0.20: the bits named by an `if` inside a case, with the id of
    // the innermost case it sits in (ruling 21)
    case_named: std.ArrayListUnmanaged(SCaseName) = .{},

    fn namedInCase(self: *const SPres, bit: usize) bool {
        for (self.case_named.items) |cn| if (cn.bit == bit) return true;
        return false;
    }
};

const SCaseName = struct { bit: usize, case_id: u32 };

// Version 0.20: a `switch <key>` block. Its node's body holds one `.case_`
// node per `case` or `else`, in line order.
const SSwitch = struct {
    key: []const u8,
    lineno: usize,
    kty: KeyType = .string,
    cases: std.ArrayListUnmanaged(*SCase) = .{},
    has_else: bool = false,
    // the first line of the scope that maps the key before the switch, and
    // which of its keys (0: its own, i: its i-th `also`)
    key_src: ?*const SNode = null,
    key_idx: usize = 0,
};

// One `case <value>[,<value>…]` or `else` of a switch.
const SCase = struct {
    id: u32,
    lineno: usize,
    is_else: bool = false,
    vals: []const []const u8 = &.{}, // as written
    canon: []const []const u8 = &.{}, // canonical texts, set at load
    defaults: std.ArrayListUnmanaged(Default) = .{},
    dmap: DMap = .{},
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

const SMode = enum { count, while_, more, fx, size_c, size_u, cref, rest, last };
const STag = enum { field, constant, when, pad, align_, presence, if_, opt, group, chain, fx, length, whole, ext, choice, alt, switch_, case_, count, inner };

// Version 0.21: a `count <name> <len> [plus <n>]` line.
// `sized`: a `length @<name>` line names it (Version 0.83).
const SCount = struct { name: []const u8, len: usize, plus: i64, lineno: usize, sized: bool = false };

// Version 0.19: a UPER locator. `int:<lb>:<ub>[:ext]`, `int:<lb>:`, `int::`,
// `enum:<n>[:ext]` (lb 0, ub n - 1), `chars:<lb>:<ub>`, `chars:`,
// `octets:<lb>:<ub>`, `octets:`.
const UForm = enum { int_c, int_semi, int_un, enum_, chars_c, chars_u, octets_c, octets_u };
const ULoc = struct { form: UForm, lb: i64 = 0, ub: i64 = 0, ext: bool = false };

fn isUperLocator(loc: []const u8) bool {
    for ([_][]const u8{ "int:", "enum:", "chars:", "octets:" }) |pre| {
        if (std.mem.startsWith(u8, loc, pre)) return true;
    }
    return false;
}

// A number of a UPER line (ruling 15 of 0.19): an optional `-` and digits
// with no leading zero; `-0` is refused.
fn uperNum(s: []const u8) ?i128 {
    var t = s;
    var neg = false;
    if (t.len > 0 and t[0] == '-') {
        neg = true;
        t = t[1..];
    }
    if (t.len == 0 or t.len > 20) return null;
    for (t) |c| if (!isDigit(c)) return null;
    if (t[0] == '0' and (t.len > 1 or neg)) return null;
    var v: i128 = 0;
    for (t) |c| v = v * 10 + (c - '0');
    return if (neg) -v else v;
}

// A number of a `choice`, `alt` or `group … size` line: digits with no
// leading zero, no sign (ruling 15 of 0.19).
fn uperCount(s: []const u8) ?i128 {
    if (s.len == 0 or s[0] == '-') return null;
    return uperNum(s);
}

// null: not a UPER locator; `bad-directive`: one that does not parse.
fn parseULoc(loc: []const u8) !?ULoc {
    const bd = E.@"bad-directive";
    if (!isUperLocator(loc)) return null;
    const colon = std.mem.indexOfScalar(u8, loc, ':').?;
    const head = loc[0..colon];
    const rest = loc[colon + 1 ..];
    var parts: [4][]const u8 = undefined;
    var np: usize = 0;
    var it = std.mem.splitScalar(u8, rest, ':');
    while (it.next()) |x| {
        if (np == parts.len) return bd;
        parts[np] = x;
        np += 1;
    }
    const min64: i128 = std.math.minInt(i64);
    const max64: i128 = std.math.maxInt(i64);
    if (std.mem.eql(u8, head, "int")) {
        if (np == 2 and parts[0].len == 0 and parts[1].len == 0) return .{ .form = .int_un };
        const lb = uperNum(parts[0]) orelse return bd;
        if (lb < min64 or lb > max64) return bd;
        if (np == 2 and parts[1].len == 0) return .{ .form = .int_semi, .lb = @intCast(lb) };
        if (np != 2 and np != 3) return bd;
        if (np == 3 and !std.mem.eql(u8, parts[2], "ext")) return bd;
        const ub = uperNum(parts[1]) orelse return bd;
        if (ub < lb or ub > max64) return bd;
        return .{ .form = .int_c, .lb = @intCast(lb), .ub = @intCast(ub), .ext = np == 3 };
    }
    if (std.mem.eql(u8, head, "enum")) {
        if (np != 1 and np != 2) return bd;
        if (np == 2 and !std.mem.eql(u8, parts[1], "ext")) return bd;
        const n = uperNum(parts[0]) orelse return bd;
        if (n < 1 or n > 65536) return bd;
        return .{ .form = .enum_, .lb = 0, .ub = @intCast(n - 1), .ext = np == 2 };
    }
    const chars = std.mem.eql(u8, head, "chars");
    if (np == 1 and parts[0].len == 0) return .{ .form = if (chars) .chars_u else .octets_u };
    if (np != 2) return bd;
    const lb = uperNum(parts[0]) orelse return bd;
    const ub = uperNum(parts[1]) orelse return bd;
    if (lb < 0 or lb > ub or ub >= 65536) return bd;
    return .{ .form = if (chars) .chars_c else .octets_c, .lb = @intCast(lb), .ub = @intCast(ub) };
}

// Does the locator take the transform (the table of 0.19)?
fn uperTakes(form: UForm, k: TKind) bool {
    return switch (form) {
        .int_c, .int_semi, .int_un => k == .uint or k == .twos or k == .uscale or k == .sscale,
        .enum_ => k == .uint,
        .chars_c, .chars_u => k == .ascii,
        .octets_c, .octets_u => k == .hex or k == .utf8,
    };
}

// The fewest bits that hold `range` (0 for 0).
fn uperBits(range: u64) usize {
    return if (range == 0) 0 else 64 - @as(usize, @clz(range));
}

fn uperRange(lb: i64, ub: i64) u64 {
    return @intCast(@as(i128, ub) - @as(i128, lb));
}
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
    partial: bool = false, // inner (Version 0.34)
    run: bool = false, // inner (Version 0.92)
    pres: ?*SPres = null, // presence
    conds: []const SCond = &.{}, // if
    body: []SNode = &.{}, // if, opt, chain, length
    list: []const u8 = "", // group
    mode: SMode = .count,
    gbody: ?*SBody = null,
    in_bits: bool = false, // length: counted in bits
    // `length @<name> units <u>` (Version 0.83): the bits of a unit, its count
    // in `cnt`; 0: another length
    units: u32 = 0,
    plus: i64 = 0, // length, whole
    // Version 0.19: a field's UPER locator; `choice <n> ext` (n in `value`,
    // the alts in `body`); an `alt`'s index in `value`; `group … size
    // <lb> <ub>`
    uloc: ?ULoc = null,
    ext: bool = false,
    lb: i64 = 0,
    ub: i64 = 0,
    ranges: []const WRange = &.{}, // when: the values and ranges (Version 0.20)
    // when: the key `as <key>` binds its bits to (Version 0.30); "" for none
    as_key: []const u8 = "",
    as_opt: bool = false, // `as <key> optional` (Version 0.52)
    // when: `at <offset>`, a look-ahead from kind start (Version 0.33)
    at_off: ?u64 = null,
    sw: ?*SSwitch = null, // switch
    cs: ?*SCase = null, // case
    // Version 0.21: a count line, or the count a `count @<name>` group names
    cnt: ?*SCount = null,
    // Version 0.31: the second count of `group <list> count @<a> @<b>`
    cnt2: ?*SCount = null,
};

const SKind = struct {
    name: []const u8,
    whens: []SNode = &.{},
    lines: []SNode = &.{},
    requires: std.ArrayListUnmanaged(*ReqTerm) = .{},
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
fn bitsLenOk(t: Transform, blen: usize) bool {
    return switch (t.kind) {
        .f32_, .f32scale => blen == 32,
        .f64_, .f64scale => blen == 64,
        .ascii => blen >= 8 and blen <= 2040 and blen % 8 == 0,
        .sixbit => blen >= 6 and blen <= 1530 and blen % 6 == 0,
        .smag, .smscale => blen >= 2 and blen <= 64,
        .chars => blk: {
            const w = charWidth(t.cset);
            break :blk blen >= w and blen <= 2040 and blen % w == 0;
        },
        .octal => blen >= 3 and blen <= 63 and blen % 3 == 0,
        .hex => blen >= 4 and blen <= 2040 and blen % 4 == 0, // Version 0.22
        // Version 0.46: the sum of the positions' widths
        .code, .codenum => blk: {
            var sum: usize = 0;
            for (t.sets) |c| sum += c.width;
            break :blk blen == sum and blen <= 64;
        },
        else => blen >= 1 and blen <= 64,
    };
}

fn fitsBits(v: u64, len: usize) bool {
    return len >= 64 or (v >> @as(u6, @intCast(len))) == 0;
}

// Version 0.33: does a `when` line hold the token `at` after its values? The
// token after the first `as` is a key, `at` included (rulings 4 and 14 of
// 0.52).
fn holdsAt(toks: []const []const u8) bool {
    var as_seen = false;
    var i: usize = 3;
    while (i < toks.len) : (i += 1) {
        if (std.mem.eql(u8, toks[i], "at")) return true;
        if (!as_seen and std.mem.eql(u8, toks[i], "as")) {
            as_seen = true;
            if (i + 1 < toks.len and std.mem.eql(u8, toks[i + 1], "at")) i += 1;
        }
    }
    return false;
}

// Version 0.33: an `at` offset: plain digits (leading zeros allowed) that fit
// in 64 bits.
fn parseOffset(t: []const u8) ?u64 {
    if (t.len == 0) return null;
    for (t) |c| if (c < '0' or c > '9') return null;
    var v: u64 = 0;
    for (t) |c| {
        v = std.math.mul(u64, v, 10) catch return null;
        v = std.math.add(u64, v, c - '0') catch return null;
    }
    return v;
}

// Version 0.33: is every window of a `when … at` fixed in its kind? Walk the
// kind's lines from its first, skipping those that occupy no bits, summing
// the others until the sum reaches the window's end; each line walked is a
// plain `when`, `const`, `pad` or a `field` with a bit-length locator.
fn seqCheckWindows(alloc: std.mem.Allocator, p: *Pack, b: *const SBody) anyerror!void {
    for (b.kinds) |*k| {
        for (k.whens) |*w| {
            const off = w.at_off orelse continue;
            const end: u128 = @as(u128, off) + w.len;
            var sum: u128 = 0;
            var bad_line: ?usize = null;
            walk: {
                for (k.whens) |*x| {
                    if (x.at_off != null) continue;
                    sum += x.len;
                    if (sum >= end) break :walk;
                }
                for (k.lines) |*n| {
                    const width: ?usize = switch (n.tag) {
                        .constant, .pad => n.len,
                        .field => if (n.uloc == null and n.ln.until_raw == null) n.ln.blen else null,
                        else => null,
                    };
                    if (width) |wd| {
                        sum += wd;
                        if (sum >= end) break :walk;
                    } else {
                        bad_line = n.lineno;
                        break :walk;
                    }
                }
                bad_line = 0;
            }
            if (bad_line) |bl| {
                if (p.win_err == null) {
                    p.win_err = if (bl == 0)
                        try std.fmt.allocPrint(alloc, "line {d}: when … at {d}: the window ends past the last line of kind {s}", .{ w.lineno, off, k.name })
                    else
                        try std.fmt.allocPrint(alloc, "line {d}: when … at {d}: the window is not fixed in kind {s} (line {d} has no fixed width)", .{ w.lineno, off, k.name, bl });
                }
            }
        }
    }
    // the group bodies, each a scope of its own
    for (b.common) |*n| try seqWindowsIn(alloc, p, n);
    for (b.kinds) |*k| for (k.lines) |*n| try seqWindowsIn(alloc, p, n);
}

fn seqWindowsIn(alloc: std.mem.Allocator, p: *Pack, n: *const SNode) anyerror!void {
    if (n.gbody) |gb| try seqCheckWindows(alloc, p, gb);
    for (n.body) |*c| try seqWindowsIn(alloc, p, c);
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

const SFrameTag = enum { body, if_, opt, chain, length, ext, choice, alt, switch_, case_ };

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
    // body frames: the keys mapped by `field` and `also` lines read so far
    // in the scope (Version 0.20); `common_mapped`: how many of them are the
    // common lines'
    mapped: std.ArrayListUnmanaged([]const u8) = .{},
    common_mapped: usize = 0,
};

// A presence or count name (they share one namespace, ruling 15 of 0.21);
// `body`: the index of the frame of the message or group body it belongs to.
const SName = struct { name: []const u8, pres: ?*SPres = null, cnt: ?*SCount = null, depth: usize, body: usize = 0 };

const SParser = struct {
    alloc: std.mem.Allocator,
    p: *Pack,
    diag: *Diag,
    frames: std.ArrayListUnmanaged(SFrame) = .{},
    names: std.ArrayListUnmanaged(SName) = .{},
    lineno: usize = 0,
    hdr: HeaderSeen = .{},
    // a `kind` line has been read, in any body; the line of the first
    // `length … whole`
    kind_seen: bool = false,
    whole_line: usize = 0,
    next_case: u32 = 0,

    const bd = E.@"bad-directive";

    // Version 0.33: an `at` error, reported after the key checks (rulings
    // 10 and 14); the first in line order is kept.
    fn lateAt(self: *SParser, comptime fmt: []const u8, args: anytype) void {
        if (self.p.at_err != null) return;
        const detail = std.fmt.allocPrint(self.alloc, fmt, args) catch "an `at` error";
        self.p.at_err = std.fmt.allocPrint(self.alloc, "line {d}: {s}", .{ self.lineno, detail }) catch detail;
    }

    // length @<name> units <u> (Version 0.83). Every error is a check after
    // the file (ruling 13); the block is opened in either case, so its lines
    // and `end` match.
    fn unitsLine(self: *SParser, toks: []const []const u8) !void {
        var n = SNode{ .tag = .length, .lineno = self.lineno };
        var pending: ?anyerror = null;
        if (toks.len != 4 or toks[1].len == 0 or toks[1][0] != '@' or !std.mem.eql(u8, toks[2], "units")) {
            pending = self.err(bd, "the line is not `length @<name> units <u>`", .{});
        } else {
            const u = if (allDigits(toks[3])) parseUnsigned(toks[3]) orelse 0 else 0;
            if (u < 1 or u > 65535) {
                pending = self.err(bd, "length: units {s} is not 1 to 65535", .{toks[3]});
            } else if (self.countRef(toks[1])) |c| {
                c.sized = true;
                n.cnt = c;
                n.units = @intCast(u);
                n.in_bits = u % 8 != 0;
            } else |e| pending = e;
        }
        try self.open(.length, n);
        if (pending) |e| return e;
    }

    // The count a `@<name>` of a group line names: a `count` line visible
    // here, in the same group body (Version 0.21, rulings 9 and 12).
    fn countRef(self: *SParser, tok: []const u8) !*SCount {
        const name = tok[1..];
        if (name.len == 0) return self.err(bd, "count @ names no count", .{});
        var ni = self.names.items.len;
        const nm = while (ni > 0) {
            ni -= 1;
            if (std.mem.eql(u8, self.names.items[ni].name, name)) break self.names.items[ni];
        } else return self.err(bd, "count @{s}: no count of that name is visible here", .{name});
        const c = nm.cnt orelse return self.err(bd, "count @{s}: {s} names a presence, not a count", .{ name, name });
        // the reference stays in the count's group body (ruling 9)
        if (nm.body != self.bodyIndex()) return self.err(bd, "count @{s}: the count is in another group body", .{name});
        return c;
    }

    // A key a `field` or `also` line maps, in its scope (Version 0.20).
    fn mapKey(self: *SParser, key: []const u8) !void {
        try self.bodyFrame().mapped.append(self.alloc, key);
    }

    // Close the open `case` or `else`: its lines join the switch.
    fn closeCase(self: *SParser) !void {
        var f = self.frames.pop();
        self.names.shrinkRetainingCapacity(f.names_base);
        var n = f.node;
        n.body = try f.nodes.toOwnedSlice(self.alloc);
        try self.top().nodes.append(self.alloc, n);
    }

    fn top(self: *SParser) *SFrame {
        return &self.frames.items[self.frames.items.len - 1];
    }

    // The index of the nearest enclosing message or group body.
    fn bodyIndex(self: *SParser) usize {
        var i = self.frames.items.len;
        while (i > 0) {
            i -= 1;
            if (self.frames.items[i].tag == .body) return i;
        }
        unreachable;
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

    // A line only a UPER pack takes: refused after the file is read when the
    // pack has no `encoding uper` (ruling 9 of 0.19).
    fn uperLine(self: *SParser) void {
        if (self.p.uper_line == 0) self.p.uper_line = self.lineno;
    }

    // The open `alt` ends: it joins its `choice`.
    fn closeAlt(self: *SParser) !void {
        var f = self.frames.pop();
        self.names.shrinkRetainingCapacity(f.names_base);
        var n = f.node;
        n.body = try f.nodes.toOwnedSlice(self.alloc);
        try self.top().nodes.append(self.alloc, n);
    }

    fn bitLen(self: *SParser, text: []const u8, what: []const u8, max: usize) !usize {
        const v = parseUnsigned(text) orelse
            return self.err(bd, "{s}: {s} is not a bit length (a sequential pack takes no positional locator)", .{ what, text });
        if (v < 1 or v > max) return self.err(bd, "{s}: the bit length {d} is not 1..{d}", .{ what, v, max });
        return @intCast(v);
    }

    fn line(self: *SParser, toks: []const []const u8) anyerror!void {
        const alloc = self.alloc;
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
        // between `switch` and its first `case`: only `case`, `else` or
        // `end` (ruling 20 of 0.20)
        if (self.top().tag == .switch_ and !(is(kw, "case") or is(kw, "else") or is(kw, "end"))) {
            return self.err(bd, "{s} between a switch and its first case", .{kw});
        }
        // header and table directives belong to the pack, not to a block
        // (ruling 24 of 0.8)
        if (self.frames.items.len > 1) {
            for ([_][]const u8{ "format", "version", "distribution", "source", "uses", "wire", "layout", "bit_order", "armor", "encoding", "framing", "map", "typemap", "charset" }) |h| {
                if (is(kw, h)) return self.err(bd, "{s} inside a block", .{kw});
            }
        }
        // a `choice` holds `alt` lines only (Version 0.19): another line
        // there is `bad-directive` after the file (ruling 26), and is read
        // still, so its line checks run and its blocks match their `end`
        if (self.top().tag == .choice and !is(kw, "alt")) {
            const e = self.err(bd, "{s} between `choice` and its first `alt` (a choice needs an `alt` line)", .{kw});
            const msg = self.diag.msg;
            self.lineBody(toks) catch |e2| {
                if (e2 == error.OutOfMemory or self.diag.line_err) return e2;
            };
            self.diag.msg = msg;
            return e;
        }
        return self.lineBody(toks);
    }

    // A line after the checks every line has.
    fn lineBody(self: *SParser, toks: []const []const u8) anyerror!void {
        const alloc = self.alloc;
        const p = self.p;
        const kw = toks[0];
        const is = struct {
            fn f(a: []const u8, b: []const u8) bool {
                return std.mem.eql(u8, a, b);
            }
        }.f;
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
            p.msb = bitOrdOf(toks[1]) orelse return self.err(bd, "bit_order {s} is not lsb, msb or msb-lsb", .{toks[1]});
            p.bit_order_set = true;
        } else if (is(kw, "armor")) {
            // armor <hex | sixbit>, checked after the file is read
            if ((toks.len != 2 or p.armor_raw != null or self.kind_seen) and p.armor_bad == 0) p.armor_bad = self.lineno;
            p.armor_raw = toks[toks.len - 1];
        } else if (is(kw, "framing")) {
            // framing self (Version 0.92), checked after the file is read; only
            // a kind of the message ends its place, not one of an item
            if ((toks.len != 2 or p.framing_line != 0 or self.frames.items[0].kinds.items.len > 0 or !is(toks[1], "self")) and p.framing_bad == 0) p.framing_bad = self.lineno;
            p.framing_line = self.lineno;
        } else if (is(kw, "encoding")) {
            // encoding <none | uper>, checked after the file is read
            if ((toks.len != 2 or p.enc_raw != null or self.kind_seen) and p.enc_bad == 0) p.enc_bad = self.lineno;
            p.enc_raw = toks[toks.len - 1];
        } else if (is(kw, "ext")) {
            if (toks.len != 1) return self.err(bd, "ext takes no argument", .{});
            self.uperLine();
            try self.open(.ext, .{ .tag = .ext, .lineno = self.lineno });
        } else if (is(kw, "choice")) {
            // the count of arguments is a line check; the values are
            // checked after the file (rulings 23 and 26 of 0.19). The block
            // is opened in either case, so its `alt` and `end` lines match.
            self.uperLine();
            var pending: ?anyerror = null;
            var n: i128 = 1;
            if (toks.len == 3 and !is(toks[2], "ext")) {
                pending = self.err(bd, "choice takes a number of alternatives and an optional `ext`", .{});
            } else if (uperCount(toks[1])) |v| {
                n = v;
                if (n < 1 or n > 65536) {
                    pending = self.err(bd, "choice {s}: not 1 to 65536", .{toks[1]});
                    n = 65536;
                }
            } else pending = self.err(bd, "choice {s}: not a number", .{toks[1]});
            try self.open(.choice, .{ .tag = .choice, .lineno = self.lineno, .value = @intCast(n), .ext = toks.len == 3 });
            if (pending) |e| return e;
        } else if (is(kw, "alt")) {
            if (toks.len != 2) return self.err(bd, "alt takes an index", .{});
            self.uperLine();
            if (self.top().tag == .alt) try self.closeAlt();
            if (self.top().tag != .choice) return self.err(bd, "alt outside a choice", .{});
            const cf = self.top();
            // an index out of range or repeated is `bad-directive` after the
            // file (ruling 26 of 0.19); the `alt` block is opened still
            var pending: ?anyerror = null;
            var i: i128 = 0;
            if (uperCount(toks[1])) |v| {
                i = v;
                if (i < 0 or i >= cf.node.value) {
                    pending = self.err(bd, "alt {s}: not 0 to {d}", .{ toks[1], cf.node.value - 1 });
                } else for (cf.nodes.items) |a| {
                    if (a.value == i) {
                        pending = self.err(bd, "alt {s} is given twice", .{toks[1]});
                        break;
                    }
                }
            } else pending = self.err(bd, "alt {s}: not an index", .{toks[1]});
            try self.open(.alt, .{ .tag = .alt, .lineno = self.lineno, .value = if (pending == null) @intCast(i) else std.math.maxInt(u64) });
            if (pending) |e| return e;
        } else if (is(kw, "word_bytes") or is(kw, "root")) {
            return self.err(bd, "{s} is not used in a sequential pack", .{kw});
        } else if (is(kw, "delimiter") or is(kw, "start") or is(kw, "checksum")) {
            return self.err(bd, "{s} is a directive of the text wire", .{kw});
        } else if (is(kw, "charset")) {
            // Version 0.46: before the first message kind, checked after the
            // file is read (ruling 16)
            try p.addCharset(alloc, toks, self.lineno, self.frames.items[0].kinds.items.len > 0);
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
                f.common_mapped = f.mapped.items.len;
            } else {
                // the presence names of the kind before are no longer visible
                self.names.shrinkRetainingCapacity(f.kind_names_base);
            }
            // nor its mapped keys (a switch key is mapped in its scope)
            f.mapped.shrinkRetainingCapacity(f.common_mapped);
            try f.kinds.append(alloc, .{ .name = toks[1] });
            if (!f.is_group) try p.kind_starts.append(alloc, p.key_uses.items.len);
            self.kind_seen = true;
            f.in_whens = true;
            f.last_field = false;
        } else if (is(kw, "requires")) {
            const f = self.top();
            if (f.tag != .body or f.kinds.items.len == 0) return self.err(bd, "requires outside a kind", .{});
            if (toks.len < 2) return self.err(bd, "requires takes at least one key", .{});
            const k = &f.kinds.items[f.kinds.items.len - 1];
            for (toks[1..]) |tok| {
                const t = (try parseReqTerm(alloc, tok, self.lineno)) orelse
                    return self.err(bd, "requires {s}: a key and a non-empty value list around `=`", .{tok});
                try k.requires.append(alloc, t);
                try p.key_uses.append(.{ .key = t.key, .tkind = null, .use = .requires, .eq = t.vals != null, .item = f.is_group });
                if (t.vals != null) try p.vchecks.append(alloc, .{ .req = t });
            }
            f.last_field = false;
        } else if (is(kw, "default")) {
            if (toks.len != 3) return self.err(bd, "default takes a key and a value", .{});
            const d = Default{ .key = toks[1], .text = toks[2] };
            // inside a case: the case's (ruling 7 of 0.20)
            var fi = self.frames.items.len;
            const owner = while (fi > 0) {
                fi -= 1;
                const t = self.frames.items[fi].tag;
                if (t == .case_ or t == .body) break &self.frames.items[fi];
            } else unreachable;
            if (owner.tag == .case_) {
                try owner.node.cs.?.defaults.append(alloc, d);
                try p.key_uses.append(.{ .key = toks[1], .tkind = null, .use = .default });
                self.top().last_field = false;
                return;
            }
            const f = self.bodyFrame();
            if (f.kinds.items.len == 0) {
                try f.sbody.?.defaults.append(alloc, d);
            } else {
                try f.kinds.items[f.kinds.items.len - 1].defaults.append(alloc, d);
            }
            try p.key_uses.append(.{ .key = toks[1], .tkind = null, .use = .default });
            self.top().last_field = false;
        } else if (is(kw, "when") or is(kw, "const")) {
            const is_when = is(kw, "when");
            // Version 0.30: `when <len> <values> as <key>`. A syntax error of
            // `as` (no key, a token after the key, `as` twice) is a check
            // after the file (ruling 16); the line's own checks run first.
            var as_key: []const u8 = "";
            var as_err: ?anyerror = null;
            // Version 0.33: `when <len> <values> at <n> [as <k>]`. Every
            // `at` error is reported after the key checks (rulings 10, 14);
            // a line whose tokens are out of order has no key read
            // (rulings 27 and 28).
            // Version 0.52: `as <k> optional`
            var as_opt = false;
            var at_off: ?u64 = null;
            if (is_when and toks.len > 3 and holdsAt(toks)) {
                // a word of the line in the place of the offset
                const kwd = struct {
                    fn f(t: []const u8) bool {
                        return std.mem.eql(u8, t, "at") or std.mem.eql(u8, t, "as") or std.mem.eql(u8, t, "optional");
                    }
                }.f;
                const keyed = (toks.len == 7 or (toks.len == 8 and is(toks[7], "optional"))) and is(toks[5], "as") and !is(toks[6], "as");
                const ordered = is(toks[3], "at") and toks.len >= 5 and !kwd(toks[4]) and (toks.len == 5 or keyed);
                if (ordered) {
                    if (keyed) as_key = toks[6];
                    as_opt = toks.len == 8;
                    at_off = parseOffset(toks[4]);
                    if (at_off == null) self.lateAt("when … at {s}: the offset is not plain digits that fit 64 bits", .{toks[4]});
                } else self.lateAt("when … at: the tokens are not `when <len> <values> at <n> [as <key> [optional]]`", .{});
                if (at_off == null) at_off = 0;
            } else if (is_when and toks.len > 3 and is(toks[3], "as")) {
                if (toks.len == 4) {
                    as_err = self.err(bd, "when … as: `as` names no key", .{});
                } else if (toks.len == 6 and is(toks[5], "optional") and !is(toks[4], "as")) {
                    as_key = toks[4];
                    as_opt = true;
                } else if (toks.len > 5) {
                    if (is(toks[5], "as")) {
                        as_err = self.err(bd, "when … as: `as` is given twice", .{});
                    } else as_err = self.err(bd, "when … as {s}: the token {s} after the key", .{ toks[4], toks[5] });
                } else if (is(toks[4], "as")) {
                    // ruling 31: any second `as` token, not a key named `as`
                    as_err = self.err(bd, "when … as: `as` is given twice", .{});
                } else as_key = toks[4];
            } else if (!is_when and toks.len == 4) {
                // Version 0.64: a part is for the text wires; its parameters
                // are a line check on every wire (ruling 23)
                _ = parsePart(toks[2]) catch |e| return self.lineErr(e, "the parameters of {s} are not valid", .{toks[2]});
                as_err = self.err(bd, "const … part on the bits wire", .{});
            } else if (toks.len != 3) return self.err(bd, "{s} takes a bit length and a value", .{kw});
            if (!locatorFormOk(.bits, true, toks[1], false)) return self.lineErr(E.@"bad-locator", "{s}: {s} is not a bit length", .{ kw, toks[1] });
            if (as_err) |e| return e;
            const len = try self.bitLen(toks[1], kw, 64);
            var ranges: []const WRange = &.{};
            var v: u64 = 0;
            if (is_when) {
                // a list of values and ranges (Version 0.20)
                ranges = (try parseWhenInts(alloc, toks[2], len)) orelse
                    return self.err(bd, "when: {s} is not a list of unsigned values and ranges that fit {d} bits", .{ toks[2], len });
                v = ranges[0].lo;
            } else {
                v = parseUnsigned(toks[2]) orelse return self.err(bd, "{s}: the value {s} is not an unsigned decimal integer", .{ kw, toks[2] });
                if (!fitsBits(v, len)) return self.err(bd, "{s}: the value {d} does not fit {d} bits", .{ kw, v, len });
            }
            const n = SNode{ .tag = if (is_when) .when else .constant, .lineno = self.lineno, .len = len, .value = v, .ranges = ranges, .as_key = as_key, .as_opt = as_opt, .at_off = at_off };
            if (!is_when) return self.add(n);
            const f = self.top();
            if (f.tag != .body) return self.err(bd, "when inside a block", .{});
            // Version 0.33: `at` is for a kind's `when`, not a common one (a
            // group body's common lines included)
            if (at_off != null and f.kinds.items.len == 0) self.lateAt("when … at: `at` on a common `when`", .{});
            // Version 0.52: nor is `optional`; without `at` an error with the
            // `as` syntax checks, before the key is read (rulings 3 and 13)
            if (as_opt and at_off == null and f.kinds.items.len == 0) return self.err(bd, "when … as {s} optional on a common `when`", .{as_key});
            if (as_key.len > 0) {
                // the key is a mapped key, listed by `model_keys` at this
                // line (ruling 5 of 0.30)
                try p.key_uses.append(.{ .key = as_key, .tkind = null, .use = .as_, .grp = f.grp });
            }
            if (f.kinds.items.len == 0) {
                // before the first kind: a common `when`. Its `as` key counts
                // as mapped from this line on for a `switch` (ruling 2).
                f.common_when = true;
                if (as_key.len > 0) try self.mapKey(as_key);
                try self.add(n);
                // `also` follows a `field` line only (ruling 14)
                f.last_field = false;
                return;
            }
            if (!f.in_whens) return self.err(bd, "when after another line of its kind", .{});
            // a kind's `as` key counts as mapped from the start of its kind
            // (ruling 2); its `when` lines are its first lines
            if (as_key.len > 0) try self.mapKey(as_key);
            try f.whens.append(alloc, n);
            f.last_field = false;
        } else if (is(kw, "field")) {
            if (toks.len < 4) return self.err(E.@"bad-directive", "field takes a key, a bit length and a transform", .{});
            const t = parseTransform(alloc, toks[3]) catch |e| switch (e) {
                error.OutOfMemory => return e,
                error.@"unknown-transform" => return self.lineErr(e, "unknown transform {s}", .{toks[3]}),
                else => return self.lineErr(e, "the parameters of transform {s} are not valid", .{toks[3]}),
            };
            if (!locatorFormOk(.bits, true, toks[2], false)) return self.lineErr(E.@"bad-locator", "field {s}: {s} is not a bit length", .{ toks[1], toks[2] });
            // A UPER locator (Version 0.19) or a bit length. A locator that
            // does not parse is `bad-directive` after the file is read; the
            // options of the line are still checked first (steps 9 and 10
            // of ruling 5b of 0.11).
            var pending: ?anyerror = null;
            const uloc = parseULoc(toks[2]) catch |e| blk: {
                pending = self.err(e, "field {s}: the locator {s} is not a UPER locator of 0.19", .{ toks[1], toks[2] });
                break :blk null;
            };
            // `until:<code>` (Version 0.22): its code and transform are
            // checked after the file is read
            const until = std.mem.startsWith(u8, toks[2], "until:");
            if (uloc != null) {
                self.uperLine();
            } else if (pending == null and !until and !allDigits(toks[2])) {
                pending = self.err(bd, "field {s}: {s} is not a bit length (a sequential pack takes no positional locator)", .{ toks[1], toks[2] });
            }
            // the transform against the wire or the UPER locator, and the
            // bit length against the transform, are checked after the file
            // (ruling 5b of 0.11)
            const blen: usize = if (uloc != null or pending != null or until) 0 else @intCast(@min(parseUnsigned(toks[2]) orelse (1 << 20), 1 << 20));
            var ln = Line{ .key = toks[1], .locator = toks[2], .transform = t, .lineno = self.lineno, .blen = blen };
            if (until) ln.until_raw = toks[2]["until:".len..];
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
                } else if (is(o, "unlisted")) {
                    again = ln.unlisted;
                    ln.unlisted = true;
                } else if (is(o, "optional")) {
                    return self.err(bd, "the field option optional is not for a sequential pack", .{});
                } else if (is(o, "absent")) {
                    oi += 1;
                    if (oi >= toks.len) return self.lineErr(bd, "absent takes one or more values", .{});
                    again = ln.absent_raw != null;
                    ln.absent_raw = toks[oi];
                } else if (is(o, "stop")) {
                    // stop <code> (Version 0.22), checked after the file is read
                    oi += 1;
                    if (oi >= toks.len) return self.lineErr(bd, "stop takes a code", .{});
                    again = ln.stop_raw != null;
                    ln.stop_raw = toks[oi];
                } else if (is(o, "with")) {
                    // with <other-key> (Version 0.18)
                    oi += 1;
                    if (oi >= toks.len or toks[oi].len == 0) return self.lineErr(bd, "with takes a key", .{});
                    again = ln.with_key != null;
                    ln.with_key = toks[oi];
                } else return self.lineErr(bd, "unknown field option {s}", .{o});
                if (again) return self.lineErr(bd, "field option {s} is repeated", .{o});
            }
            if (pending) |e| return e;
            // the values of `absent` are a line check, except above 64 bits
            // (ruling 4d of 0.11) and on a UPER locator, which takes no
            // `absent` (ruling 22 of 0.19, checked after the file is read)
            if (blen <= 64 and uloc == null and !until) {
                try parseAbsent(alloc, .bits, &ln, false, self.diag);
                ln.abs_checked = true;
            }
            try p.key_uses.append(.{ .key = toks[1], .tkind = t.kind, .via = ln.via_name, .grp = self.bodyFrame().grp });
            if (ln.with_key) |wk| try p.key_uses.append(.{ .key = wk, .tkind = null, .use = .with, .grp = self.bodyFrame().grp });
            try self.mapKey(toks[1]);
            try self.add(.{ .tag = .field, .lineno = self.lineno, .ln = ln, .uloc = uloc });
        } else if (is(kw, "also")) {
            // also <key> [via <table>], directly after a `field` line
            const f = self.top();
            if (!f.last_field) return self.err(bd, "also is not directly after a field line", .{});
            if (toks.len != 2 and !(toks.len == 4 and is(toks[2], "via") and toks[3].len > 0)) return self.err(bd, "also takes a key and an optional `via <table>`", .{});
            const fld = &f.nodes.items[f.nodes.items.len - 1];
            const via_name: []const u8 = if (toks.len == 4) toks[3] else "";
            try fld.also.append(alloc, .{ .key = toks[1], .via_name = via_name, .lineno = self.lineno });
            try p.key_uses.append(.{ .key = toks[1], .tkind = fld.ln.transform.kind, .via = via_name, .grp = self.bodyFrame().grp });
            try self.mapKey(toks[1]);
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
            if (self.top().tag == .ext and self.top().nodes.items.len > 0) return self.err(bd, "presence {s}: inside an `ext` block a presence line is the first line", .{name});
            const depth = self.frames.items.len;
            for (self.names.items) |nm| {
                if (nm.depth == depth and is(nm.name, name)) return self.err(bd, "presence {s} is declared twice in one block", .{name});
            }
            const pr = try alloc.create(SPres);
            pr.* = .{ .name = name, .n = if (is(toks[2], "fx")) 0 else try self.bitLen(toks[2], kw, 64) };
            try self.names.append(alloc, .{ .name = name, .pres = pr, .depth = depth, .body = self.bodyIndex() });
            try self.add(.{ .tag = .presence, .lineno = self.lineno, .pres = pr });
        } else if (is(kw, "count")) {
            // count <name> <len> [plus <n>] (Version 0.21)
            if (toks.len < 3) return self.err(bd, "count takes a name and a bit length", .{});
            const name = toks[1];
            // a name as a presence name is: no `.`, `!` or `@` (ruling 24)
            if (name.len == 0 or std.mem.indexOfAny(u8, name, ".!@") != null) return self.err(bd, "count name {s}", .{name});
            const len = try self.bitLen(toks[2], kw, 64);
            var plus: i64 = 0;
            if (toks.len > 3) {
                if (!is(toks[3], "plus")) return self.err(bd, "count: the option {s} is not `plus`", .{toks[3]});
                if (toks.len < 5) return self.err(bd, "count: plus takes a value", .{});
                if (toks.len > 5) return self.err(bd, "count: {s} after `plus {s}`", .{ toks[5], toks[4] });
                // an optional `-` then digits, within signed 64 bits (ruling 16)
                const t = toks[4];
                const digits = if (t.len > 0 and t[0] == '-') t[1..] else t;
                if (!allDigits(digits)) return self.err(bd, "count: plus {s} is not an integer", .{t});
                plus = std.fmt.parseInt(i64, t, 10) catch return self.err(bd, "count: plus {s} is outside signed 64 bits", .{t});
            }
            const depth = self.frames.items.len;
            for (self.names.items) |nm| {
                if (nm.depth == depth and is(nm.name, name)) return self.err(bd, "{s} is declared twice in one block", .{name});
            }
            const c = try alloc.create(SCount);
            c.* = .{ .name = name, .len = len, .plus = plus, .lineno = self.lineno };
            try self.names.append(alloc, .{ .name = name, .cnt = c, .depth = depth, .body = self.bodyIndex() });
            try self.add(.{ .tag = .count, .lineno = self.lineno, .len = len, .cnt = c });
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
                        // a count name is not a presence (ruling 15 of 0.21)
                        found = self.names.items[ni].pres orelse
                            return self.err(bd, "if {s}: {s} names a count, not a presence", .{ tk, ref[0..dot] });
                        break;
                    }
                }
                const pr = found orelse return self.err(bd, "if {s}: no presence of that name is visible here", .{tk});
                if (idx < 1 or idx > 4096 or (pr.n > 0 and idx > pr.n)) return self.err(bd, "if {s}: the bit is beyond the size of the presence", .{tk});
                const bit: usize = @intCast(idx);
                // inside a case: the bit is named only when the innermost
                // case is read (ruling 21 of 0.20)
                var in_case: ?u32 = null;
                var fi = self.frames.items.len;
                while (fi > 0) {
                    fi -= 1;
                    if (self.frames.items[fi].tag == .case_) {
                        in_case = self.frames.items[fi].node.cs.?.id;
                        break;
                    }
                }
                if (in_case) |cid| {
                    try pr.case_named.append(alloc, .{ .bit = bit, .case_id = cid });
                } else {
                    while (pr.named.items.len < bit) try pr.named.append(alloc, false);
                    pr.named.items[bit - 1] = true;
                }
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
            if ((toks[1].len > 0 and toks[1][0] == '@') or listHolds(toks[1..], "units")) return self.unitsLine(toks);
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
                if (self.whole_line == 0) self.whole_line = self.lineno;
                return self.add(n);
            }
            try self.open(.length, n);
        } else if (is(kw, "group")) {
            // group <list> count <len> | count @<name> | while | more | fx |
            // rest | last
            var n = SNode{ .tag = .group, .lineno = self.lineno };
            var pending: ?anyerror = null;
            if (toks.len == 4 and is(toks[2], "count") and toks[3].len > 0 and toks[3][0] == '@') {
                // a count named earlier in the same group body (Version 0.21)
                n.mode = .cref;
                n.cnt = try self.countRef(toks[3]);
            } else if (toks.len >= 5 and is(toks[2], "count")) {
                // Version 0.31: `count @<a> @<b>`, one list counted from two
                // places. Checked after the file (ruling 7); the group is
                // opened still, so its lines and `end` match.
                n.mode = .cref;
                pending = blk: {
                    for (toks[3..]) |t| {
                        if (t.len < 2 or t[0] != '@') break :blk self.err(bd, "group {s}: count {s}: not `@<name>`", .{ toks[1], t });
                    }
                    if (toks.len > 5) break :blk self.err(bd, "group {s}: count takes at most two names", .{toks[1]});
                    if (is(toks[3], toks[4])) break :blk self.err(bd, "group {s}: count names {s} twice", .{ toks[1], toks[3] });
                    n.cnt = self.countRef(toks[3]) catch |e| break :blk e;
                    n.cnt2 = self.countRef(toks[4]) catch |e| break :blk e;
                    break :blk null;
                };
                if (pending != null) n.mode = .count;
            } else if (toks.len == 4 and is(toks[2], "count")) {
                n.mode = .count;
                n.len = try self.bitLen(toks[3], "group count", 64);
            } else if (toks.len == 3 and is(toks[2], "rest")) {
                n.mode = .rest;
            } else if (toks.len == 3 and is(toks[2], "last")) {
                n.mode = .last;
            } else if (toks.len == 3 and is(toks[2], "while")) {
                n.mode = .while_;
            } else if (toks.len == 3 and is(toks[2], "more")) {
                n.mode = .more;
            } else if (toks.len == 3 and is(toks[2], "fx")) {
                n.mode = .fx;
            } else if (toks.len == 3 and is(toks[2], "size")) {
                n.mode = .size_u;
                self.uperLine();
            } else if (toks.len == 5 and is(toks[2], "size")) {
                n.mode = .size_c;
                const lb = uperCount(toks[3]) orelse return self.err(bd, "group size {s}: not a number", .{toks[3]});
                const ub = uperCount(toks[4]) orelse return self.err(bd, "group size {s}: not a number", .{toks[4]});
                if (lb > ub or ub >= 65536) return self.err(bd, "group size {s} {s}: not 0 <= lb <= ub < 65536", .{ toks[3], toks[4] });
                n.lb = @intCast(lb);
                n.ub = @intCast(ub);
                self.uperLine();
            } else return self.err(bd, "a group of a sequential pack is `group <list>` and one of `count <len>`, `count @<name>`, `while`, `more`, `fx`, `rest`, `last` or `size [<lb> <ub>]`", .{});
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
            if (pending) |e| return e;
        } else if (is(kw, "switch")) {
            // switch <model-key> (Version 0.20): the key is mapped by a
            // `field` or `also` line of the scope before this line
            if (toks.len != 2) return self.err(bd, "switch takes one model key", .{});
            const bf = self.bodyFrame();
            if (!listHolds(bf.mapped.items, toks[1])) {
                return self.err(bd, "switch {s}: no field or also line of the scope maps the key before the switch", .{toks[1]});
            }
            const sw = try alloc.create(SSwitch);
            sw.* = .{ .key = toks[1], .lineno = self.lineno };
            p.seq_switch = true;
            try self.open(.switch_, .{ .tag = .switch_, .lineno = self.lineno, .sw = sw });
        } else if (is(kw, "case") or is(kw, "else")) {
            const is_else = is(kw, "else");
            if (is_else and toks.len != 1) return self.err(bd, "else takes no argument", .{});
            if (!is_else and toks.len != 2) return self.err(bd, "case takes one value list", .{});
            if (self.top().tag == .case_) {
                try self.closeCase();
            } else if (self.top().tag != .switch_) {
                return self.err(bd, "{s} outside a switch", .{kw});
            }
            const sw = self.top().node.sw.?;
            if (sw.has_else) return self.err(bd, "{s} after the else of the switch", .{kw});
            if (is_else and sw.cases.items.len == 0) return self.err(bd, "else before a case", .{});
            const cs = try alloc.create(SCase);
            self.next_case += 1;
            cs.* = .{ .id = self.next_case, .lineno = self.lineno, .is_else = is_else };
            if (!is_else) {
                // a lone `""` is the empty text (ruling 16)
                cs.vals = if (toks[1].len == 0)
                    try alloc.dupe([]const u8, &.{""})
                else
                    (try splitValueList(alloc, toks[1])) orelse return self.err(bd, "case {s}: an empty value in the list", .{toks[1]});
                try p.vchecks.append(alloc, .{ .case_ = .{ .sw = sw, .cs = cs } });
            }
            sw.has_else = is_else;
            try sw.cases.append(alloc, cs);
            try self.frames.append(alloc, .{ .tag = .case_, .node = .{ .tag = .case_, .lineno = self.lineno, .cs = cs }, .names_base = self.names.items.len });
        } else if (is(kw, "end")) {
            if (toks.len != 1) return self.err(bd, "end takes no argument", .{});
            if (self.frames.items.len < 2) return self.err(bd, "end with no open block", .{});
            if (self.top().tag == .alt) try self.closeAlt();
            if (self.top().tag == .switch_) return self.err(bd, "a switch with no case", .{});
            if (self.top().tag == .case_) try self.closeCase();
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
        } else if (is(kw, "inner")) {
            // Version 0.34: `inner <format>`, in the common lines, a kind or
            // `length` blocks; under any other block it is `bad-directive`
            // after the file is read. The format is not looked up here.
            if (toks.len != 2 and toks.len != 3) return self.err(bd, "inner takes a format name and the word partial or run", .{});
            // Version 0.92: `run`
            const run = toks.len == 3 and is(toks[2], "run");
            if (run) p.has_run = true;
            try p.inners.append(alloc, .{ .fmt = toks[1], .pos = p.key_uses.items.len, .lineno = self.lineno, .kind = self.frames.items[0].kinds.items.len, .run = run });
            var pending: ?anyerror = null;
            if (toks.len == 3 and !run and !is(toks[2], "partial")) pending = self.err(bd, "inner {s}: the word {s} is not `partial` or `run`", .{ toks[1], toks[2] });
            for (self.frames.items[1..]) |f| {
                if (pending != null) break;
                if (f.tag == .length) continue;
                const what: []const u8 = if (f.tag == .body) "group" else @tagName(f.tag);
                pending = self.err(bd, "inner {s} inside a {s} block; it stands in the common lines, a kind or `length` blocks only", .{ toks[1], what });
                break;
            }
            try self.add(.{ .tag = .inner, .lineno = self.lineno, .list = toks[1], .partial = toks.len == 3 and !run, .run = run });
            if (pending) |e| return e;
        } else if (is(kw, "element")) {
            return self.err(E.@"bad-directive", "element is for the xml wire only", .{});
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
            if (n.ln.unlisted) return bad(diag, alloc, bd, "line {d}: unlisted is an option of a part line", .{n.lineno});
            if (n.uloc) |u| {
                // Version 0.19: the transforms a UPER locator takes; `swap`,
                // `trim` (ruling 10) and `absent` (ruling 22) are refused
                if (!uperTakes(u.form, t.kind)) return bad(diag, alloc, bd, "line {d}: the locator {s} does not take the transform of {s}", .{ n.lineno, n.ln.locator, n.ln.key });
                if (n.ln.swap or n.ln.trim) return bad(diag, alloc, bd, "line {d}: swap and trim are not options of a UPER locator", .{n.lineno});
                if (n.ln.absent_raw != null) return bad(diag, alloc, bd, "line {d}: absent is not an option of a UPER locator", .{n.lineno});
            } else if (n.ln.until_raw) |raw| {
                // Version 0.22: `until:<code>` with `chars:<set>` only; no
                // `absent`, `swap`, `trim` or `stop` (ruling 16)
                if (t.kind != .chars) return bad(diag, alloc, bd, "line {d}: until: takes chars:<set>, not the transform of {s}", .{ n.lineno, n.ln.key });
                if (n.ln.swap or n.ln.trim or n.ln.absent_raw != null or n.ln.stop_raw != null) return bad(diag, alloc, bd, "line {d}: until: takes no absent, swap, trim or stop", .{n.lineno});
                n.ln.until_code = charCodeParam(raw, t.cset) orelse return bad(diag, alloc, bd, "line {d}: until:{s} is not a code of the set", .{ n.lineno, raw });
            } else {
                if (!bitsTransform(t.kind)) return bad(diag, alloc, bd, "line {d}: the transform of {s} does not belong to wire bits", .{ n.lineno, n.ln.key });
                try resolveCodeSets(alloc, p, &n.ln, diag);
                if (!bitsLenOk(n.ln.transform, n.ln.blen)) return bad(diag, alloc, bd, "line {d}: bit length {d} is not allowed for the transform of {s}", .{ n.lineno, n.ln.blen, n.ln.key });
                try stopCheck(alloc, &n.ln, n.lineno, diag);
                if (n.ln.swap and t.kind == .hex) return bad(diag, alloc, bd, "line {d}: swap on hex", .{n.lineno});
                if (n.ln.trim and t.kind != .ascii and t.kind != .sixbit) return bad(diag, alloc, bd, "line {d}: trim is for the ascii and sixbit transforms", .{n.lineno});
                if (n.ln.swap and t.kind == .sixbit) return bad(diag, alloc, bd, "line {d}: swap on sixbit", .{n.lineno});
                if (n.ln.swap and n.ln.blen % 8 != 0) return bad(diag, alloc, bd, "line {d}: swap needs a bit length that is a multiple of 8, not {d}", .{ n.lineno, n.ln.blen });
                if (n.ln.swap and (t.kind == .chars or t.kind == .octal)) return bad(diag, alloc, bd, "line {d}: swap with {s}", .{ n.lineno, @tagName(t.kind) });
                if (!n.ln.abs_checked) try parseAbsent(alloc, .bits, &n.ln, false, diag);
            }
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
            // an `alt` separates as an `if` or `opt` block does (ruling 20
            // of 0.19), and two cases are different blocks (ruling 10 of
            // 0.20)
            .if_, .opt, .alt, .case_ => {
                try blocks.append(alloc, n);
                try seqCollectGroups(alloc, n.body, blocks, out);
                _ = blocks.pop();
            },
            .chain, .length, .ext, .choice, .switch_ => try seqCollectGroups(alloc, n.body, blocks, out),
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
// sit in different `if`, `opt` or `alt` blocks (ruling 20 of 0.19): each has such a block around it, and
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
                    return bad(diag, alloc, E.@"bad-directive", "line {d}: the list {s} is mapped by a second group of its scope (line {d}), and the two do not sit in different `if`, `opt` or `alt` blocks", .{ g.node.lineno, g.node.list, f.node.lineno });
                }
            }
        }
        // each group body is a scope of its own
        for (all.items[if (ki == 0) 0 else common.items.len..]) |g| try seqCheckLists(alloc, g.node.gbody.?, diag);
    }
}

// Version 0.30, rulings 9 and 33: in one reading path of a scope (its common
// lines plus one kind, every block of the scope included, a group body being
// a scope of its own) a key is bound by one `when … as` line at most, and a
// key so bound is mapped by no `field` or `also` line.
fn seqCollectAs(alloc: std.mem.Allocator, nodes: []const SNode, as_keys: *std.ArrayListUnmanaged(*const SNode), mapped: *std.ArrayListUnmanaged([]const u8), groups: *std.ArrayListUnmanaged(*const SBody)) anyerror!void {
    for (nodes) |*n| {
        switch (n.tag) {
            .when => if (n.as_key.len > 0) try as_keys.append(alloc, n),
            .field => {
                try mapped.append(alloc, n.ln.key);
                for (n.also.items) |a| try mapped.append(alloc, a.key);
            },
            .group => try groups.append(alloc, n.gbody.?),
            else => {},
        }
        try seqCollectAs(alloc, n.body, as_keys, mapped, groups);
    }
}

fn seqCheckAsBody(alloc: std.mem.Allocator, b: *const SBody, diag: *Diag) anyerror!void {
    const bd = E.@"bad-directive";
    var c_as = std.ArrayListUnmanaged(*const SNode){};
    var c_mapped = std.ArrayListUnmanaged([]const u8){};
    var groups = std.ArrayListUnmanaged(*const SBody){};
    try seqCollectAs(alloc, b.common, &c_as, &c_mapped, &groups);
    var ki: usize = 0;
    while (ki == 0 or ki < b.kinds.len) : (ki += 1) {
        var as_keys = std.ArrayListUnmanaged(*const SNode){};
        var mapped = std.ArrayListUnmanaged([]const u8){};
        try as_keys.appendSlice(alloc, c_as.items);
        try mapped.appendSlice(alloc, c_mapped.items);
        if (ki < b.kinds.len) {
            const k = &b.kinds[ki];
            try seqCollectAs(alloc, k.whens, &as_keys, &mapped, &groups);
            try seqCollectAs(alloc, k.lines, &as_keys, &mapped, &groups);
        }
        for (as_keys.items, 0..) |w, i| {
            for (as_keys.items[0..i]) |o| {
                if (std.mem.eql(u8, o.as_key, w.as_key)) {
                    return bad(diag, alloc, bd, "line {d}: when … as {s}: line {d} binds the same key in one reading path", .{ w.lineno, w.as_key, o.lineno });
                }
            }
            if (listHolds(mapped.items, w.as_key)) {
                return bad(diag, alloc, bd, "line {d}: when … as {s}: a field or also line of the same reading path maps the key", .{ w.lineno, w.as_key });
            }
        }
    }
    for (groups.items) |g| try seqCheckAsBody(alloc, g, diag);
}

// Version 0.20: each switch's key source, the first line of its scope that
// maps the key before the switch in reading order.
const SKeySrc = struct { node: *const SNode, idx: usize };

fn seqLinkNodes(nodes: []SNode, map: *std.StringHashMap(SKeySrc)) anyerror!void {
    for (nodes) |*n| {
        switch (n.tag) {
            .field => {
                if (!map.contains(n.ln.key)) try map.put(n.ln.key, .{ .node = n, .idx = 0 });
                for (n.also.items, 0..) |a, i| {
                    if (!map.contains(a.key)) try map.put(a.key, .{ .node = n, .idx = i + 1 });
                }
            },
            .switch_ => {
                if (map.get(n.sw.?.key)) |src| {
                    n.sw.?.key_src = src.node;
                    n.sw.?.key_idx = src.idx;
                }
                try seqLinkNodes(n.body, map);
            },
            .group => try seqLinkBody(map.allocator, n.gbody.?),
            // Version 0.30: a `when … as` line is the key's line (ruling 19)
            .when => if (n.as_key.len > 0 and !map.contains(n.as_key)) try map.put(n.as_key, .{ .node = n, .idx = 0 }),
            else => try seqLinkNodes(n.body, map),
        }
    }
}

fn seqLinkBody(alloc: std.mem.Allocator, b: *SBody) anyerror!void {
    var common = std.StringHashMap(SKeySrc).init(alloc);
    try seqLinkNodes(b.common, &common);
    for (b.kinds) |*k| {
        var m = try common.clone();
        try seqLinkNodes(k.whens, &m);
        try seqLinkNodes(k.lines, &m);
    }
}

// Version 0.21, ruling 2: the fewest and the most references to a count
// along the reading paths of some lines. Paths split at kinds and at the
// cases of a switch only (ruling 33); a group body is another body (ruling 9).
const SRefs = struct {
    min: usize = 0,
    max: usize = 0,

    fn add(self: *SRefs, o: SRefs) void {
        self.min += o.min;
        self.max += o.max;
    }
};

fn seqRefs(list: []const SNode, c: *const SCount) SRefs {
    var r = SRefs{};
    for (list) |*n| {
        switch (n.tag) {
            .group => if (n.mode == .cref and (n.cnt == c or n.cnt2 == c)) r.add(.{ .min = 1, .max = 1 }),
            .switch_ => {
                var alt: ?SRefs = null;
                for (n.body) |*cn| alt = seqAlt(alt, seqRefs(cn.body, c));
                r.add(alt orelse .{});
            },
            .length => {
                // `length @<name>` is a reference (ruling 1 of 0.83)
                if (n.units > 0 and n.cnt == c) r.add(.{ .min = 1, .max = 1 });
                r.add(seqRefs(n.body, c));
            },
            else => r.add(seqRefs(n.body, c)),
        }
    }
    return r;
}

fn seqAlt(a: ?SRefs, b: SRefs) SRefs {
    const x = a orelse return b;
    return .{ .min = @min(x.min, b.min), .max = @max(x.max, b.max) };
}

// Every count is referenced exactly once in each reading path from its line
// to the end of its block (a body's common lines reach into every kind).
fn seqCheckCountList(alloc: std.mem.Allocator, list: []const SNode, kinds: []const SKind, diag: *Diag) anyerror!void {
    for (list, 0..) |*n, i| {
        switch (n.tag) {
            .count => {
                const c = n.cnt.?;
                var r = seqRefs(list[i + 1 ..], c);
                var alt: ?SRefs = null;
                for (kinds) |*k| alt = seqAlt(alt, seqRefs(k.lines, c));
                if (alt) |a| r.add(a);
                if (r.min == 0) return bad(diag, alloc, E.@"bad-directive", "line {d}: count {s} is not referenced by a `count @{s}` group or a `length @{s}` block in some reading path", .{ n.lineno, c.name, c.name, c.name });
                if (r.max > 1) return bad(diag, alloc, E.@"bad-directive", "line {d}: count {s} is referenced twice in one reading path", .{ n.lineno, c.name });
            },
            .group => try seqCheckCountBody(alloc, n.gbody.?, diag),
            else => try seqCheckCountList(alloc, n.body, &.{}, diag),
        }
    }
}

fn seqCheckCountBody(alloc: std.mem.Allocator, b: *const SBody, diag: *Diag) anyerror!void {
    try seqCheckCountList(alloc, b.common, b.kinds, diag);
    for (b.kinds) |*k| try seqCheckCountList(alloc, k.lines, &.{}, diag);
}

// Does a line read or write bits (rulings 26 and 32 of 0.21)? An `if`,
// `switch` or `chain` is one only when its body holds one.
// Ruling 41: an `ext` always is (its extension bit); a `choice` is one when
// it has `ext`, more than one root alternative, or an `alt` holding a wire
// line; an `alt` when it holds one.
fn seqWire(n: *const SNode) bool {
    return switch (n.tag) {
        .if_, .chain, .switch_, .case_, .alt => seqAnyWire(n.body),
        .choice => n.ext or n.value > 1 or seqAnyWire(n.body),
        else => true,
    };
}

fn seqAnyWire(list: []const SNode) bool {
    for (list) |*n| if (seqWire(n)) return true;
    return false;
}

// Rulings 10, 11 and 27 of 0.21: a `rest` group is the last wire line of its
// extent in every reading path; inside an item it sits in a `length` block of
// the item's body, or last in an item of an outer `rest` group. `after`: a
// wire line follows the lines in their extent; `forbid`: the lines are in
// the item body of a group that is not `rest`, outside any `length`.
fn seqCheckRestList(alloc: std.mem.Allocator, list: []const SNode, after_in: bool, forbid: bool, diag: *Diag) anyerror!void {
    const bd = E.@"bad-directive";
    var after = after_in;
    var i = list.len;
    while (i > 0) {
        i -= 1;
        const n = &list[i];
        switch (n.tag) {
            // Version 0.34: an `inner` line is the last wire line of its
            // extent, as a `rest` group is
            .inner => if (after) return bad(diag, alloc, bd, "line {d}: an inner line is not the last line of its extent", .{n.lineno}),
            .group => {
                if (n.mode == .rest) {
                    if (forbid) return bad(diag, alloc, bd, "line {d}: a rest group inside an item, neither within a `length` block of the item's body nor last in an item of a rest group", .{n.lineno});
                    if (after) return bad(diag, alloc, bd, "line {d}: a rest group is not the last line of its extent", .{n.lineno});
                }
                try seqCheckRestBody(alloc, n.gbody.?, n.mode != .rest, diag);
            },
            .length => try seqCheckRestList(alloc, n.body, false, false, diag),
            .switch_ => for (n.body) |*cn| try seqCheckRestList(alloc, cn.body, after, forbid, diag),
            // each `alt` is checked as a `switch` case is (ruling 42)
            .choice => for (n.body) |*a| try seqCheckRestList(alloc, a.body, after, forbid, diag),
            else => try seqCheckRestList(alloc, n.body, after, forbid, diag),
        }
        if (seqWire(n)) after = true;
    }
}

fn seqCheckRestBody(alloc: std.mem.Allocator, b: *const SBody, forbid: bool, diag: *Diag) anyerror!void {
    // a kind's `when` lines are wire lines (ruling 32)
    var kind_wire = false;
    for (b.kinds) |*k| {
        if (k.whens.len > 0 or seqAnyWire(k.lines)) kind_wire = true;
    }
    try seqCheckRestList(alloc, b.common, kind_wire, forbid, diag);
    for (b.kinds) |*k| try seqCheckRestList(alloc, k.lines, false, forbid, diag);
}

// Version 0.34, after the file is read: at most one `inner` line on any
// reading path (the common lines with one kind), and none in a pack with
// `armor` or `encoding uper`.
fn seqCheckInner(alloc: std.mem.Allocator, p: *const Pack, root: *const SBody, diag: *Diag) anyerror!void {
    if (p.inners.items.len == 0) return;
    const bd = E.@"bad-directive";
    const first = p.inners.items[0].lineno;
    if (p.armor) return bad(diag, alloc, bd, "line {d}: inner in a pack with armor", .{first});
    if (p.uper) return bad(diag, alloc, bd, "line {d}: inner in a pack with encoding uper", .{first});
    const c = seqInnerCount(root.common);
    if (c > 1) return bad(diag, alloc, bd, "two inner lines in the common lines", .{});
    for (root.kinds) |*k| {
        if (c + seqInnerCount(k.lines) > 1) return bad(diag, alloc, bd, "kind {s}: two inner lines on one reading path", .{k.name});
    }
}

// Version 0.92, ruling 16: `framing self`, after the file is read.
fn framingCheck(alloc: std.mem.Allocator, p: *Pack, root: *const SBody, diag: *Diag) anyerror!void {
    const bd = E.@"bad-directive";
    if (p.framing_bad != 0) return bad(diag, alloc, bd, "line {d}: framing is given as `framing self`, once, before the first kind", .{p.framing_bad});
    if (p.framing_line == 0) return;
    if (p.armor or p.uper) return bad(diag, alloc, bd, "line {d}: framing with armor sixbit or encoding uper", .{p.framing_line});
    var whole = false;
    var lost = restWithoutWhole(root.common, &whole);
    for (root.kinds) |*k| {
        if (lost != 0) break;
        var w = whole;
        lost = restWithoutWhole(k.lines, &w);
    }
    if (lost != 0) return bad(diag, alloc, bd, "line {d}: framing self, and a rest group to the end of the message with no `length … whole` read before it", .{lost});
}

// The line of a `rest` group of the message's extent that no `length … whole`
// always read before it bounds; 0: none. `whole`: one has been read, on entry
// and at the end of the lines; one inside a block counts in that block only.
fn restWithoutWhole(list: []const SNode, whole: *bool) usize {
    for (list) |*n| {
        switch (n.tag) {
            .whole => whole.* = true,
            .group => if (n.mode == .rest and !whole.*) return n.lineno,
            // the extent of a `rest` in it is the block
            .length => {},
            else => {
                var w = whole.*;
                const lost = restWithoutWhole(n.body, &w);
                if (lost != 0) return lost;
            },
        }
    }
    return 0;
}

// The `run` lines of a list (Version 0.92), in `length` blocks too.
fn seqRunCount(list: []const SNode) usize {
    var n: usize = 0;
    for (list) |*x| {
        if (x.tag == .inner and x.run) n += 1;
        n += seqRunCount(x.body);
    }
    return n;
}

// The `inner` lines of a list, in `length` blocks too (the only block that
// may hold one).
fn seqInnerCount(list: []const SNode) usize {
    var n: usize = 0;
    for (list) |*x| {
        if (x.tag == .inner) n += 1;
        n += seqInnerCount(x.body);
    }
    return n;
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
    // Version 0.30: the bans of ruling 9 need only key names; they run
    // before the other checks that need the whole file (rulings 16 and 29)
    try seqCheckAsBody(alloc, root, diag);
    try charsetCheck(alloc, p, diag);
    try armorCheck(alloc, p, diag);
    // `encoding <none | uper>` (Version 0.19)
    if (p.enc_raw) |raw| {
        if (p.enc_bad != 0) return bad(diag, alloc, E.@"bad-directive", "line {d}: encoding is repeated, given after a kind, or not given one value", .{p.enc_bad});
        if (std.mem.eql(u8, raw, "uper")) {
            if (!p.bit_order_set or p.msb != .msb) return bad(diag, alloc, E.@"bad-directive", "encoding uper needs bit_order msb", .{});
            if (p.armor) return bad(diag, alloc, E.@"bad-directive", "encoding uper with armor sixbit", .{});
            p.uper = true;
        } else if (!std.mem.eql(u8, raw, "none")) {
            return bad(diag, alloc, E.@"bad-directive", "encoding {s} is not none or uper", .{raw});
        }
    }
    if (!p.uper and p.uper_line != 0) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: a line of a pack with `encoding uper`", .{p.uper_line});
    }
    // the armored text has no whole-byte length (ruling 3 of 0.14)
    if (p.armor and sp.whole_line != 0) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: length … whole with armor sixbit", .{sp.whole_line});
    }
    setTableTypes(p);
    try seqResolveVia(alloc, p, root.common, diag);
    for (root.kinds) |*k| try seqResolveVia(alloc, p, k.lines, diag);
    try seqCheckLists(alloc, root, diag);
    try seqCheckCountBody(alloc, root, diag);
    try seqCheckRestBody(alloc, root, false, diag);
    // Version 0.33: reported after the key checks (ruling 10)
    try seqCheckWindows(alloc, p, root);
    try seqCheckInner(alloc, p, root, diag);
    try framingCheck(alloc, p, root, diag);
    if (p.seq_switch) try seqLinkBody(alloc, root);
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

// The `default` values in scope: those of the cases the line sits in,
// innermost first (rulings 7 and 22 of 0.20), then a kind's, then the common
// ones of its body.
const DLink = struct { map: *const DMap, parent: ?*const DLink };

const DS = struct {
    a: ?*const DMap = null,
    b: ?*const DMap = null,
    c: ?*const DLink = null,

    fn get(self: DS, key: []const u8) ?MV {
        var l = self.c;
        while (l) |x| : (l = x.parent) {
            if (x.map.count() > 0) {
                if (x.map.get(key)) |v| return v;
            }
        }
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
    // inside a `length` block: the end of its extent. It lies beyond
    // `hard_end` when a whole length read in the block cuts it (ruling 16 of
    // 0.83)
    soft_end: usize,
    in_extent: bool = false,
    // the first field that failed (`transform-decode`), reported at the end
    failed_msg: ?[]const u8 = null,
    // Version 0.21: the innermost extent is counted in bits (a `length …
    // bits` block), not bytes
    ext_bits: bool = false,
    // the number of items each count line read; null: the line lay at or
    // past the end of its extent
    // (exact: value minus `plus`, which may pass 2^64 - 1, Version 0.31
    // ruling 5)
    cvals: std.AutoHashMapUnmanaged(*const SCount, ?i128) = .{},
    // > 0: in the first pass of a `rest` or `last` group, which only
    // counts its items
    counting: usize = 0,
    // Version 0.20: the cases read so far, and the presence bits that are 1
    // and named only by `if` lines in cases, checked at the end of the
    // presence's block (ruling 21)
    read_cases: std.ArrayListUnmanaged(u32) = .{},
    pending: std.ArrayListUnmanaged(SPending) = .{},
    // Version 0.83: the counts read that state units and that a `length @`
    // block names, with whether one was read and where `read_cases` and
    // `choices` (the choices read, with the `alt` chosen) stood
    sized: std.ArrayListUnmanaged(SizedCount) = .{},
    choices: std.ArrayListUnmanaged(ReadChoice) = .{},
    // the cases being read, outermost first
    open_cases: std.ArrayListUnmanaged(u32) = .{},
    // Version 0.34: the lists an inner message gave the entity
    inner_lists: []const []const u8 = &.{},
    // Version 0.34, an inner decode: the message's entity, the lists the
    // outer entity holds (discarded from this one by step 4)
    root: ?*const Entity = null,
    discard: []const []const u8 = &.{},
    // Version 0.34, ruling 13: a `length … whole` line was read
    whole_read: bool = false,
    // Version 0.34: the decode is an inner one; the keys an inner message gave
    is_inner: bool = false,
    // Version 0.92: it is a message of a run; the run operation whose outer
    // decode this is
    in_run: bool = false,
    run: ?*RunRead = null,
    inner_keys: std.ArrayListUnmanaged([]const u8) = .{},

    const mw = E.@"malformed-wire";
    const SPending = struct { pres: *const SPres, bit: usize, start: usize };
    const SizedCount = struct { cnt: *const SCount, cases: usize, choices: usize, read: bool = false };
    const ReadChoice = struct { choice: *const SNode, alt: ?*const SNode };

    // The pending bits from `mark` on: each needs a case that names it read
    // since its presence was.
    fn checkPending(self: *SDec, mark: usize) !void {
        if (self.pending.items.len <= mark) return;
        for (self.pending.items[mark..]) |pd| {
            var ok = false;
            for (pd.pres.case_named.items) |cn| {
                if (cn.bit != pd.bit) continue;
                if (std.mem.indexOfScalar(u32, self.read_cases.items[pd.start..], cn.case_id) != null) ok = true;
            }
            if (!ok) return bad(self.diag, self.alloc, mw, "presence bit {s}.{d} is 1 and no `if` of the lines read names it", .{ pd.pres.name, pd.bit });
        }
        self.pending.shrinkRetainingCapacity(mark);
    }
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
            if (self.atExtentEnd()) return .absent;
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
        if (self.atExtentEnd()) return 0;
        try self.need(1, what);
        return self.take(1);
    }

    fn take(self: *SDec, len: usize) u64 {
        const v = getBits(self.buf, self.p.msb, self.pos, len);
        self.pos += len;
        return v;
    }

    // Version 0.22: a `until:<code> chars:<set>` field. The terminator is
    // found from the codes alone (ruling 5): none before the extent ends,
    // or more than floor(2040 / w) characters before it, is
    // `malformed-wire`. Then the characters decode; a bad one fails the key
    // and the cursor stays after the terminator. Nothing is removed.
    fn untilField(self: *SDec, n: *const SNode, se: *SEnt) !void {
        const alloc = self.alloc;
        const ln = &n.ln;
        const c = ln.transform.cset;
        const w = charWidth(c);
        const term = ln.until_code.?;
        // at or past the end of a `length` extent: absent (ruling 4)
        if (self.atExtentEnd()) return;
        const at = self.pos;
        var cnt: usize = 0;
        while (true) {
            try self.need(w, ln.key);
            if (self.take(w) == term) break;
            cnt += 1;
            if (cnt > 2040 / w) return bad(self.diag, alloc, mw, "field {s}: no terminator {d} within {d} characters", .{ ln.key, term, 2040 / w });
        }
        const out = try alloc.alloc(u8, cnt);
        for (0..cnt) |k| {
            const code: u8 = @intCast(getBits(self.buf, self.p.msb, at + k * w, w));
            out[k] = charOf(c, code) orelse {
                try se.failed.append(alloc, ln.key);
                for (n.also.items) |a| try se.failed.append(alloc, a.key);
                return;
            };
        }
        const raw = MV{ .str = out };
        try self.setKey(se, ln.key, ln.via, ln.via_name, ln.kty, raw);
        for (n.also.items) |a| try self.setKey(se, a.key, a.via, a.via_name, a.kty, raw);
    }

    // Version 0.33: does the window of a `when … at` hold? Its bits lie at
    // kind start plus the offset; any of them beyond the input, `length …
    // whole` or the enclosing extent: it does not (rulings 6 and 7).
    fn windowHolds(self: *const SDec, kstart: usize, off: u64, w: *const SNode) bool {
        const end: u128 = @as(u128, kstart) + off + w.len;
        if (end > self.limit()) return false;
        const at: usize = @intCast(@as(u128, kstart) + off);
        return inRanges(w.ranges, getBits(self.buf, self.p.msb, at, w.len));
    }

    // Version 0.30: the key of a `when … as` line holds the bits at `at` read
    // as `uint` does: with 64 bits, a value of 2^63 or more is the negative
    // integer of the same bits (ruling 7).
    fn setAs(self: *SDec, se: *SEnt, n: *const SNode, at: usize) !void {
        if (n.as_key.len == 0) return;
        const v = getBits(self.buf, self.p.msb, at, n.len);
        try self.setKey(se, n.as_key, null, "", .int, MV{ .int = @bitCast(v) });
    }

    fn setKey(self: *SDec, se: *SEnt, key: []const u8, via: ?*const Table, via_name: []const u8, kty: KeyType, raw: MV) !void {
        if (se.e.fields.contains(key)) { // the earliest line of a key wins
            // a table with no entry is an error also when an earlier line,
            // or the inner message, gave the key (ruling 23 of 0.34, ruling
            // 26 of 0.64)
            if (via) |t| {
                _ = tableDecode(t, raw, kty) catch
                    return self.fieldFailed("field {s}: the table {s} has no entry for the value", .{ key, via_name });
            }
            return;
        }
        var mv = raw;
        if (via) |t| {
            mv = tableDecode(t, mv, kty) catch {
                // the key failed: a `switch` on it fails the decode
                // (ruling 35 of 0.20)
                try se.failed.append(self.alloc, key);
                return self.fieldFailed("field {s}: the table {s} has no entry for the value", .{ key, via_name });
            };
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
        const mark = self.pending.items.len;
        try self.nodes(list, se, &inner);
        try self.checkPending(mark);
    }

    fn node(self: *SDec, n: *const SNode, se: *SEnt, env: *?*const PEnv) anyerror!void {
        const alloc = self.alloc;
        switch (n.tag) {
            .field => {
                if (n.uloc) |u| return self.uperField(n, u, se);
                if (n.ln.until_code != null) return self.untilField(n, se);
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
                const at = self.pos;
                if (!self.fits(n.len) or !inRanges(n.ranges, self.take(n.len))) {
                    return bad(self.diag, alloc, E.@"no-kind", "the common `when {d} {d}` does not hold", .{ n.len, n.value });
                }
                // Version 0.30: a common `when … as` sets its key whenever
                // the message (or item, ruling 11) decodes
                try self.setAs(se, n, at);
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
                // holds a part the pack does not describe. A bit named only
                // inside cases waits for the cases read (ruling 21 of 0.20).
                for (bits.items, 0..) |b, i| {
                    if (b and (i >= pr.named.items.len or !pr.named.items[i])) {
                        if (pr.namedInCase(i + 1)) {
                            // named in a case being read: it is read
                            var open_named = false;
                            for (pr.case_named.items) |cn| {
                                if (cn.bit == i + 1 and std.mem.indexOfScalar(u32, self.open_cases.items, cn.case_id) != null) open_named = true;
                            }
                            if (!open_named) try self.pending.append(alloc, .{ .pres = pr, .bit = i + 1, .start = self.read_cases.items.len });
                            continue;
                        }
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
                const mark = self.pending.items.len;
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
                try self.checkPending(mark);
            },
            .switch_ => {
                // Version 0.20: the key's decoded value selects the case
                const sw = n.sw.?;
                // a key line that failed its transform fails the decode
                // (ruling 35 of 0.20)
                // in a message of a run also when another line gave the key
                // (ruling 3 of 0.92)
                if (se.e.get(sw.key) == null or self.in_run) {
                    for (se.failed.items) |fk| {
                        if (std.mem.eql(u8, fk, sw.key)) return bad(self.diag, alloc, E.@"transform-decode", "switch {s}: its line fails its transform", .{sw.key});
                    }
                }
                const idx = try caseIndex(alloc, n, se.e.get(sw.key)) orelse
                    return bad(self.diag, alloc, E.@"no-kind", "switch {s}: no case holds the value, and there is no else", .{sw.key});
                const c = &n.body[idx];
                try self.read_cases.append(alloc, c.cs.?.id);
                try self.open_cases.append(alloc, c.cs.?.id);
                try self.block(c.body, se, env.*);
                _ = self.open_cases.pop();
            },
            .case_ => unreachable, // a case is read by its switch
            .length => {
                if (n.units > 0) return self.unitsBlock(n, se, env.*);
                if (try self.avail(n.len, "length") == .absent) return self.absentBlock(n);
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
                const save_bits = self.ext_bits;
                self.soft_end = end;
                self.in_extent = true;
                self.ext_bits = n.in_bits;
                try self.block(n.body, se, env.*);
                // content of the extent no line read is skipped
                self.pos = end;
                self.soft_end = save_end;
                self.in_extent = save_in;
                self.ext_bits = save_bits;
            },
            .whole => {
                if (try self.avail(n.len, "length") == .absent) return;
                const stated: i128 = self.take(n.len);
                const total = (stated - n.plus) * 8;
                if (total < @as(i128, self.pos)) return bad(self.diag, alloc, mw, "the stated length of the message is shorter than what was already read", .{});
                if (total > @as(i128, self.hard_end)) return bad(self.diag, alloc, mw, "the stated length of the message is {d} bits, the input holds {d}", .{ total, self.hard_end });
                self.hard_end = @intCast(total);
                self.whole_read = true;
                if (!self.in_extent) self.soft_end = self.hard_end;
            },
            .group => try self.group(n, se, env.*),
            .inner => try self.innerNode(n, se),
            .ext => {
                if (self.atExtentEnd()) return;
                const bit = try self.rd(1, "ext");
                try self.block(n.body, se, env.*);
                if (bit == 1) try self.additions();
            },
            .choice => {
                if (self.atExtentEnd()) return;
                if (n.ext and try self.rd(1, "choice") == 1) {
                    // an extension alternative: its index and an open type,
                    // skipped
                    if (try self.small("choice") == null) {
                        return bad(self.diag, alloc, E.@"transform-decode", "choice: the index of an extension alternative does not fit 64 bits", .{});
                    }
                    try self.skipOpen("choice");
                    if (self.sized.items.len > 0) try self.choices.append(alloc, .{ .choice = n, .alt = null });
                    return;
                }
                const i = try self.cwn(0, @intCast(n.value - 1), "choice");
                for (n.body) |*a| {
                    if (a.value == @as(u64, @intCast(i))) {
                        if (self.sized.items.len > 0) try self.choices.append(alloc, .{ .choice = n, .alt = a });
                        return self.block(a.body, se, env.*);
                    }
                }
                return bad(self.diag, alloc, mw, "choice: the index {d} has no `alt`", .{i});
            },
            .alt => unreachable, // an `alt` is read by its `choice`
            .count => {
                // Version 0.21: the count is read here, its items when the
                // group is reached
                const c = n.cnt.?;
                if (try self.avail(c.len, c.name) == .absent) {
                    try self.cvals.put(alloc, c, null);
                    return;
                }
                const v: i128 = self.take(c.len);
                if (v < c.plus) return bad(self.diag, alloc, mw, "count {s}: the value {d} is below its `plus {d}`", .{ c.name, v, c.plus });
                // kept exact, for the comparison of two counts (0.31 ruling 5)
                try self.cvals.put(alloc, c, v - c.plus);
                if (c.sized and v != c.plus) try self.sized.append(alloc, .{ .cnt = c, .cases = self.read_cases.items.len, .choices = self.choices.items.len });
            },
            .fx => unreachable, // an `fx` line is a line of a chain
        }
    }

    // Version 0.19 ----------------------------------------------------------

    // At or after the end of a `length` extent a line reads as absent.
    fn atExtentEnd(self: *const SDec) bool {
        return self.in_extent and self.pos >= self.soft_end;
    }

    fn rd(self: *SDec, len: usize, what: []const u8) !u64 {
        try self.need(len, what);
        return if (len == 0) 0 else self.take(len);
    }

    // A constrained whole number in lb..ub; a value above ub is
    // `malformed-wire`.
    fn cwn(self: *SDec, lb: i64, ub: i64, what: []const u8) !i64 {
        const range = uperRange(lb, ub);
        const v = try self.rd(uperBits(range), what);
        if (v > range) return bad(self.diag, self.alloc, mw, "{s}: the value {d} above the lower bound is beyond the constraint {d}..{d}", .{ what, v, lb, ub });
        return @intCast(@as(i128, lb) + v);
    }

    // A length determinant; a fragmented length is `malformed-wire`.
    fn lenDet(self: *SDec, what: []const u8) !u64 {
        if (try self.rd(1, what) == 0) return self.rd(7, what);
        if (try self.rd(1, what) == 0) return self.rd(14, what);
        return bad(self.diag, self.alloc, mw, "{s}: a fragmented length (first bits 11)", .{what});
    }

    // `n` octets the input holds, at the cursor: their value when n <= 8,
    // else skipped and null (`transform-decode` for the caller).
    fn octetsBE(self: *SDec, n: u64, what: []const u8) !?u64 {
        try self.need(@intCast(n * 8), what);
        if (n > 8) {
            self.pos += @intCast(n * 8);
            return null;
        }
        return self.take(@intCast(n * 8));
    }

    // A length determinant of an octet count, then that many octets: the
    // count and the value. A count of 0 is `malformed-wire`.
    const Octs = struct { n: usize, v: ?u64 };
    fn intOctets(self: *SDec, what: []const u8) !Octs {
        const n = try self.lenDet(what);
        if (n == 0) return bad(self.diag, self.alloc, mw, "{s}: an integer of 0 octets", .{what});
        return .{ .n = @intCast(n), .v = try self.octetsBE(n, what) };
    }

    // A normally small non-negative whole number; null when its long form
    // holds more than 8 octets.
    fn small(self: *SDec, what: []const u8) !?u64 {
        if (try self.rd(1, what) == 0) return try self.rd(6, what);
        const o = try self.intOctets(what);
        return o.v;
    }

    fn skipOpen(self: *SDec, what: []const u8) !void {
        const n = try self.lenDet(what);
        try self.need(@intCast(n * 8), what);
        self.pos += @intCast(n * 8);
    }

    // The extension additions of a SEQUENCE whose extension bit is 1: their
    // number, the presence bits, an open type for each bit that is 1; all
    // skipped.
    fn additions(self: *SDec) !void {
        const what = "extension additions";
        const m: u64 = if (try self.rd(1, what) == 0) try self.rd(6, what) + 1 else try self.lenDet(what);
        try self.need(@intCast(m), what);
        var ones: usize = 0;
        for (0..@as(usize, @intCast(m))) |_| ones += @intCast(self.take(1));
        for (0..ones) |_| try self.skipOpen(what);
    }

    fn uperField(self: *SDec, n: *const SNode, u: ULoc, se: *SEnt) !void {
        if (self.atExtentEnd()) return;
        const alloc = self.alloc;
        const ln = &n.ln;
        const what = ln.key;
        var val: ?MV = null; // null: the value does not decode
        switch (u.form) {
            .int_c, .int_semi, .int_un, .enum_ => {
                var v: ?i128 = null;
                switch (u.form) {
                    .int_c, .enum_ => {
                        if (u.ext and try self.rd(1, what) == 1) {
                            if (u.form == .int_c) {
                                const o = try self.intOctets(what);
                                if (o.v) |x| v = signExtend(x, o.n * 8);
                            } else if (try self.small(what)) |x| {
                                v = @as(i128, u.ub) + 1 + x;
                            }
                        } else v = try self.cwn(u.lb, u.ub, what);
                    },
                    .int_semi => {
                        const o = try self.intOctets(what);
                        if (o.v) |x| v = @as(i128, u.lb) + x;
                    },
                    else => {
                        const o = try self.intOctets(what);
                        if (o.v) |x| v = signExtend(x, o.n * 8);
                    },
                }
                if (v) |x| {
                    if (x >= std.math.minInt(i64) and x <= std.math.maxInt(i64)) {
                        const iv: i64 = @intCast(x);
                        const t = ln.transform;
                        val = switch (t.kind) {
                            .uscale, .sscale => MV{ .float = t.factor.mul(@floatFromInt(iv)) + t.offset },
                            else => MV{ .int = iv },
                        };
                    }
                }
            },
            .chars_c, .chars_u => {
                const cnt: u64 = if (u.form == .chars_c) @intCast(try self.cwn(u.lb, u.ub, what)) else try self.lenDet(what);
                try self.need(@intCast(cnt * 7), what);
                const b = try alloc.alloc(u8, @intCast(cnt));
                for (b) |*c| c.* = @intCast(self.take(7));
                val = MV{ .str = b };
            },
            .octets_c, .octets_u => {
                const cnt: u64 = if (u.form == .octets_c) @intCast(try self.cwn(u.lb, u.ub, what)) else try self.lenDet(what);
                try self.need(@intCast(cnt * 8), what);
                const b = try alloc.alloc(u8, @intCast(cnt));
                for (b) |*c| c.* = @intCast(self.take(8));
                if (ln.transform.kind == .hex) {
                    val = MV{ .str = try hexEncode(alloc, b) };
                } else if (std.unicode.utf8ValidateSlice(b)) {
                    val = MV{ .str = b };
                }
            },
        }
        const mv = val orelse {
            // forgiven when another line of the key succeeds
            try se.failed.append(alloc, ln.key);
            for (n.also.items) |a| try se.failed.append(alloc, a.key);
            return;
        };
        try self.setKey(se, ln.key, ln.via, ln.via_name, ln.kty, mv);
        for (n.also.items) |a| try self.setKey(se, a.key, a.via, a.via_name, a.kty, mv);
    }

    // Version 0.83: `length @<name> units <u>`. A line at or past the end of
    // the enclosing extent is absent, whatever its count states; an extent
    // beyond that end, the input, or a whole length read before is
    // `malformed-wire` before anything in it is read (rulings 4 and 5).
    fn unitsBlock(self: *SDec, n: *const SNode, se: *SEnt, env: ?*const PEnv) anyerror!void {
        if (self.atExtentEnd()) return self.absentBlock(n);
        // the count line lay at or past the end of its extent
        const count = (self.cvals.get(n.cnt.?) orelse null) orelse return self.absentBlock(n);
        const stop = @as(i128, self.pos) + count * n.units;
        if (stop > self.limit()) {
            return bad(self.diag, self.alloc, mw, "a block of {d} units of {d} bits at bit {d} runs past the end at bit {d}", .{ count, n.units, self.pos, self.limit() });
        }
        // its units are read (ruling 9)
        var i = self.sized.items.len;
        while (i > 0) {
            i -= 1;
            if (self.sized.items[i].cnt != n.cnt.?) continue;
            self.sized.items[i].read = true;
            break;
        }
        const end: usize = @intCast(stop);
        const save_end = self.soft_end;
        const save_in = self.in_extent;
        const save_bits = self.ext_bits;
        self.soft_end = end;
        self.in_extent = true;
        self.ext_bits = n.in_bits;
        try self.block(n.body, se, env);
        self.pos = end;
        self.soft_end = save_end;
        self.in_extent = save_in;
        self.ext_bits = save_bits;
    }

    // Version 0.92: a message whose `run` line lies in an absent block is an
    // ordinary one.
    fn absentBlock(self: *SDec, n: *const SNode) void {
        if (self.run) |r| if (seqRunCount(n.body) > 0) {
            r.ordinary = true;
        };
    }

    // Ruling 9 of 0.83, when a message or an item has been read: a count that
    // states units, and a `length @` block of it in the lines of its scope
    // (the common ones and the selected kind's) that was not read.
    fn checkSized(self: *SDec, mark: usize, common: []const SNode, kind: []const SNode) !void {
        if (self.sized.items.len <= mark) return;
        for (self.sized.items[mark..]) |x| {
            if (!x.read and (self.holdsSized(common, x) or self.holdsSized(kind, x))) {
                return bad(self.diag, self.alloc, mw, "count {s} states units, and no block of it is read", .{x.cnt.name});
            }
        }
        self.sized.shrinkRetainingCapacity(mark);
    }

    // Do the lines hold a block of the count? A `switch` or `choice` that was
    // read counts by its selected case or chosen `alt`, one that was not by
    // any.
    fn holdsSized(self: *const SDec, list: []const SNode, x: SizedCount) bool {
        for (list) |*n| {
            switch (n.tag) {
                .group => {}, // a group body is another scope
                .switch_ => {
                    const cases = self.read_cases.items[x.cases..];
                    const sel = for (n.body) |*cn| {
                        if (std.mem.indexOfScalar(u32, cases, cn.cs.?.id) != null) break cn;
                    } else null;
                    if (sel) |cn| {
                        if (self.holdsSized(cn.body, x)) return true;
                    } else for (n.body) |*cn| if (self.holdsSized(cn.body, x)) return true;
                },
                .choice => {
                    const read = for (self.choices.items[x.choices..]) |ch| {
                        if (ch.choice == n) break ch;
                    } else null;
                    if (read) |ch| {
                        if (ch.alt) |alt| if (self.holdsSized(alt.body, x)) return true;
                    } else for (n.body) |*alt| if (self.holdsSized(alt.body, x)) return true;
                },
                else => {
                    if (n.tag == .length and n.units > 0 and n.cnt == x.cnt) return true;
                    if (self.holdsSized(n.body, x)) return true;
                },
            }
        }
        return false;
    }

    // Version 0.34: the `inner` line. The checks of the line, then the inner
    // input (the whole bytes from the cursor to the end of the enclosing
    // extent) decoded by the inner pack; its keys join the entity, the first
    // value read in reading order kept.
    fn innerNode(self: *SDec, n: *const SNode, se: *SEnt) anyerror!void {
        const alloc = self.alloc;
        const ip = try innerLookup(alloc, self.diag, self.p, n);
        if (self.pos % 8 != 0) return bad(self.diag, alloc, mw, "inner {s}: the cursor at bit {d} is not on a whole byte", .{ ip.format, self.pos });
        if (self.in_extent and self.soft_end > self.hard_end) return bad(self.diag, alloc, mw, "inner {s}: the enclosing extent ends beyond the input", .{ip.format});
        const end = self.limit();
        if (end % 8 != 0) return bad(self.diag, alloc, mw, "inner {s}: the enclosing extent ends at bit {d}, not on a whole byte", .{ ip.format, end });
        const at = @min(self.pos, end);
        const input = self.buf[at / 8 .. end / 8];
        if (n.run) {
            if (self.run) |r| {
                try self.runMessages(r, ip, input);
                self.pos = end;
                return;
            }
            // `decode` and `convert` read a carrier of one message (ruling 1
            // of 0.92)
            if (input.len == 0) return bad(self.diag, alloc, E.@"message-count", "inner {s} run: the run holds no message", .{ip.format});
        }
        const hex = if (n.run) "" else try hexEncode(alloc, input);
        // the lists the entity holds: the inner lists of those names are
        // discarded, and a sequential inner decode holds none of their items
        var held_lists = std.ArrayListUnmanaged([]const u8){};
        for (se.e.lists.ptr[0..se.e.lists.len]) |en| try held_lists.append(alloc, en.key);
        self.diag.discard = held_lists.items;
        defer self.diag.discard = &.{};
        self.diag.inner = if (n.run) .run else if (n.partial) .partial else .strict;
        self.diag.partial = null;
        const sub = (if (n.run) seqDecodeBits(alloc, ip, input, input.len * 8, self.diag) else decodePack(alloc, ip, hex, self.diag)) catch |err| failed: {
            if (err == error.OutOfMemory) return err;
            const msg = try std.fmt.allocPrint(alloc, "inner {s}: {s}", .{ ip.format, self.diag.msg });
            // a value that does not decode does not stop the decode (ruling
            // 9 of 0.1.1); a failure of the wire, a `switch` on a key that
            // failed (ruling 35 of 0.20) and every other kind does. What was
            // read joins the entity (ruling 19 of 0.34).
            if (err == E.@"transform-decode") if (self.diag.partial) |got| {
                if (self.diag.unforgiven) try self.fieldFailed("{s}", .{msg});
                // forgiven when an outer line of the key succeeds, before or
                // after this one (ruling 23 of 0.34)
                try se.failed.appendSlice(alloc, self.diag.failed_keys);
                break :failed got;
            };
            self.diag.msg = msg;
            return err;
        };
        if (n.run and self.diag.run_end < input.len) return bad(self.diag, alloc, E.@"message-count", "inner {s} run: bytes remain after the first message", .{ip.format});
        self.pos = end;
        for (sub.fields.ptr[0..sub.fields.len]) |en| {
            if (se.e.fields.contains(en.key)) continue;
            try se.e.put(en.key, en.value);
            try self.inner_keys.append(alloc, en.key);
        }
        var names = std.ArrayListUnmanaged([]const u8){};
        try names.appendSlice(alloc, self.inner_lists);
        for (sub.lists.ptr[0..sub.lists.len]) |en| {
            // an outer list read first is kept whole: the inner items, which
            // were not held, are discarded
            if (se.e.lists.contains(en.key)) continue;
            try se.e.putList(en.key, en.value);
            try names.append(alloc, en.key);
        }
        self.inner_lists = names.items;
        if (sub.kind_fmt) |kf| {
            se.e.inner_kind_fmt = kf;
            se.e.inner_kind_name = sub.kind_name;
        }
    }

    // Version 0.92: the messages of a run, in the outer decode of a run
    // operation. Each is decoded to find where it ends and whether it fails;
    // its entity is not kept, only its place and its failure.
    fn runMessages(self: *SDec, r: *RunRead, ip: *const Pack, input: []const u8) anyerror!void {
        r.reached = true;
        r.ip = ip;
        r.input = input;
        r.held = self.diag.held;
        r.max_items = self.diag.max_items;
        r.packs = self.diag.packs;
        var at: usize = 0;
        while (at < input.len) {
            // one message more than the limit (ruling 5)
            if (r.msgs.items.len >= r.max_items) return bad(self.diag, self.alloc, mw, "inner {s} run: more than {d} messages", .{ ip.format, r.max_items });
            _ = r.arena.reset(.retain_capacity);
            var md = r.messageDiag();
            var m = RunMsg{ .at = at };
            const got = seqDecodeBits(r.arena.allocator(), ip, input[at..], (input.len - at) * 8, &md) catch |err| got: {
                if (err == error.OutOfMemory) return err;
                const msg = try std.fmt.allocPrint(self.alloc, "inner {s}: message {d}: {s}", .{ ip.format, r.msgs.items.len + 1, md.msg });
                // a `transform-decode` does not stop the message's decode
                const goes_on = err == E.@"transform-decode" and md.partial != null;
                if (!goes_on and r.to_carrier) {
                    self.diag.msg = msg;
                    return err;
                }
                const f = try self.alloc.create(RunFail);
                f.* = .{ .kind = err, .msg = msg };
                m.fail = f;
                if (!goes_on) {
                    // the run ends, with this as its last result (ruling 3)
                    try r.msgs.append(self.alloc, m);
                    return;
                }
                break :got md.partial.?;
            };
            // a message whose decode came to its end, a `transform-decode`
            // included: its own items join the sum of ruling 5
            r.done += 1;
            r.own_items += entityItems(&got);
            try r.msgs.append(self.alloc, m);
            at += md.run_end;
        }
    }

    fn group(self: *SDec, n: *const SNode, se: *SEnt, env: ?*const PEnv) anyerror!void {
        // Version 0.34: a list the inner message gave is not replaced by a
        // later group of the outer pack; its items are read and not held
        if (self.discard.len > 0 and se.e == self.root and listHolds(self.discard, n.list)) {
            self.diag.no_hold += 1;
            defer self.diag.no_hold -= 1;
            return self.groupRead(n, se, env);
        }
        if (self.inner_lists.len > 0 and se.e == self.root and listHolds(self.inner_lists, n.list)) {
            var tmp = Entity.init(self.alloc);
            var st = SEnt{ .e = &tmp };
            self.diag.no_hold += 1;
            defer self.diag.no_hold -= 1;
            return self.groupRead(n, &st, env);
        }
        return self.groupRead(n, se, env);
    }

    fn groupRead(self: *SDec, n: *const SNode, se: *SEnt, env: ?*const PEnv) anyerror!void {
        var items = ItemList{ .alloc = self.alloc };
        switch (n.mode) {
            .count => {
                if (try self.avail(n.len, n.list) == .absent) return;
                const cnt = self.take(n.len);
                // the count against the limit, less the items of the list it
                // replaces (rulings 7d and 7g of 0.11), before any item is read
                try self.replaceList(se, n.list);
                try self.holdItems(cnt, n.list, true);
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
                if (self.atExtentEnd()) return;
                try self.replaceList(se, n.list);
                while (true) {
                    try self.item(n, &items, env);
                    if (try self.indicator(n.list) == 0) break;
                }
            },
            .size_c, .size_u => {
                if (self.atExtentEnd()) return;
                const cnt: u64 = if (n.mode == .size_c) @intCast(try self.cwn(n.lb, n.ub, n.list)) else try self.lenDet(n.list);
                // a count larger than the bits left, before any item is read
                if (cnt > self.left()) {
                    return bad(self.diag, self.alloc, mw, "group {s}: a count of {d} is larger than the {d} bits left", .{ n.list, cnt, self.left() });
                }
                for (0..@as(usize, @intCast(cnt))) |_| try self.item(n, &items, env);
            },
            .cref => {
                // Version 0.21: the count read at its line; absent when that
                // line, or this group, lay at or past the end of the extent
                const exact = (self.cvals.get(n.cnt.?) orelse null) orelse return;
                var exact2: ?i128 = null;
                if (n.cnt2) |c2| exact2 = (self.cvals.get(c2) orelse null) orelse return;
                if (self.atExtentEnd()) return;
                // Version 0.31: the two numbers of items agree, compared as
                // exact integers, before the bits left (rulings 4 and 5)
                if (exact2) |x2| if (x2 != exact) {
                    return bad(self.diag, self.alloc, mw, "group {s}: count {s} gives {d} items, count {s} gives {d}", .{ n.list, n.cnt.?.name, exact, n.cnt2.?.name, x2 });
                };
                // at most 2^64 - 1 - (-2^63) items: clamped, as a count above
                // the bits left fails anyway
                const cnt: u64 = if (exact > std.math.maxInt(u64)) std.math.maxInt(u64) else @intCast(exact);
                // the count against the limit, less the items of the list it
                // replaces (rulings 7d and 7g of 0.11), before any item is read
                try self.replaceList(se, n.list);
                try self.holdItems(cnt, n.list, true);
                // compared with the bits left at the group (ruling 20)
                if (cnt > self.left()) {
                    return bad(self.diag, self.alloc, mw, "group {s}: a count of {d} is larger than the {d} bits left", .{ n.list, cnt, self.left() });
                }
                for (0..@as(usize, @intCast(cnt))) |_| try self.item(n, &items, env);
            },
            .rest, .last => {
                // the first indicator of `last` at the end of the extent: an
                // absent list (ruling 34 of 0.8)
                if (n.mode == .last and self.atExtentEnd()) return;
                // Two passes: the first counts the items into one reused
                // entity, the second reads them into a list of that size, so
                // a list of many small items is not held twice while it grows.
                // Inside a first pass the items are only counted.
                // The first pass counts nothing against the limit on list
                // items (ruling 7 of 0.11): the second pass holds the items.
                const save = self.state();
                const held = self.diag.held;
                var sink = Sink{ .scratch = Entity.init(self.alloc) };
                self.counting += 1;
                try self.extentItems(n, &sink, env);
                self.counting -= 1;
                // the items of a discarded list (Version 0.34) are not kept either
                if (self.counting > 0 or self.diag.no_hold > 0) return se.e.putList(n.list, &[0]Entity{});
                self.restore(save);
                self.diag.held = held;
                try self.replaceList(se, n.list);
                try self.holdItems(sink.n, n.list, false);
                const slots = try self.alloc.alloc(Entity, sink.n);
                sink = .{ .scratch = sink.scratch, .slots = slots };
                try self.extentItems(n, &sink, env);
                try se.e.putList(n.list, slots[0..sink.n]);
                return;
            },
        }
        // two groups of one list both on the wire: the later group's items
        // are kept (ruling 33 of 0.8)
        try se.e.putList(n.list, try items.finish());
    }

    // A later group of a list the entity holds replaces its items (ruling 33
    // of 0.8): they are no longer counted (ruling 7g of 0.11).
    fn replaceList(self: *SDec, se: *SEnt, list: []const u8) !void {
        if (self.diag.no_hold > 0) return; // those items were not held either
        if (se.e.lists.get(list)) |old| self.diag.held -= itemsHeld(old);
    }

    fn holdItems(self: *SDec, n: u64, list: []const u8, counted: bool) !void {
        return holdList(self.diag, self.alloc, n, list, counted);
    }

    // Where the items of a `rest` or `last` group go: counted into a reused
    // entity (`slots` null), or read into `slots`.
    const Sink = struct { scratch: Entity, slots: ?[]Entity = null, n: usize = 0, failed: std.ArrayListUnmanaged([]const u8) = .{} };

    const State = struct { pos: usize, hard_end: usize, soft_end: usize, in_extent: bool, ext_bits: bool, read_cases: usize, pending: usize, open_cases: usize, sized: usize, choices: usize };

    fn state(self: *const SDec) State {
        return .{ .pos = self.pos, .hard_end = self.hard_end, .soft_end = self.soft_end, .in_extent = self.in_extent, .ext_bits = self.ext_bits, .read_cases = self.read_cases.items.len, .pending = self.pending.items.len, .open_cases = self.open_cases.items.len, .sized = self.sized.items.len, .choices = self.choices.items.len };
    }

    fn restore(self: *SDec, st: State) void {
        self.pos = st.pos;
        self.hard_end = st.hard_end;
        self.soft_end = st.soft_end;
        self.in_extent = st.in_extent;
        self.ext_bits = st.ext_bits;
        self.read_cases.shrinkRetainingCapacity(st.read_cases);
        self.pending.shrinkRetainingCapacity(st.pending);
        self.open_cases.shrinkRetainingCapacity(st.open_cases);
        self.sized.shrinkRetainingCapacity(st.sized);
        self.choices.shrinkRetainingCapacity(st.choices);
    }

    fn sinkItem(self: *SDec, n: *const SNode, sink: *Sink, env: ?*const PEnv) anyerror!void {
        if (sink.slots) |slots| {
            // the first pass counted them; a second pass reads the same bits
            if (sink.n >= slots.len) return bad(self.diag, self.alloc, mw, "group {s}: the items do not read back alike", .{n.list});
            var it = Entity.init(self.alloc);
            var sit = SEnt{ .e = &it };
            try self.body(n.gbody.?, &sit, env);
            slots[sink.n] = it;
        } else {
            const sc = &sink.scratch;
            sc.fields.len = 0;
            sc.lists.len = 0;
            sc.clearKind();
            // one list of failed keys for all the items counted
            sink.failed.clearRetainingCapacity();
            var sit = SEnt{ .e = sc, .failed = sink.failed };
            try self.body(n.gbody.?, &sit, env);
            sink.failed = sit.failed;
        }
        sink.n += 1;
    }

    // The items of a `rest` or `last` group.
    fn extentItems(self: *SDec, n: *const SNode, sink: *Sink, env: ?*const PEnv) anyerror!void {
        if (n.mode == .rest) {
            // items while bits remain in the extent: 8 in one counted in
            // bytes, 1 in one counted in bits; fewer are padding
            const least: usize = if (self.in_extent and self.ext_bits) 1 else 8;
            // in a block to its stated end, also beyond a whole length read in
            // it (ruling 16 of 0.83)
            while (if (self.in_extent) self.soft_end -| self.pos >= least else self.left() >= least) {
                const at = self.pos;
                try self.sinkItem(n, sink, env);
                if (self.pos == at) return bad(self.diag, self.alloc, mw, "group {s}: an item of a rest group reads no bits", .{n.list});
            }
            return;
        }
        // `last`: an indicator after the first that starts at the extent end
        // is `malformed-wire` (ruling 13 of 0.21)
        var first = true;
        while (true) {
            if (!first and self.atExtentEnd()) {
                return bad(self.diag, self.alloc, mw, "group {s}: the item before said another follows, and the extent ends at bit {d}", .{ n.list, self.pos });
            }
            try self.need(1, n.list);
            const last = self.take(1);
            try self.sinkItem(n, sink, env);
            first = false;
            if (last == 1) break;
        }
    }

    fn item(self: *SDec, n: *const SNode, items: *ItemList, env: ?*const PEnv) anyerror!void {
        // a counted group took its items before the first was read
        if (n.mode != .count and n.mode != .cref) try self.holdItems(1, n.list, false);
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
        const mark = self.pending.items.len;
        const smark = self.sized.items.len;
        var kind_lines: []const SNode = &.{};
        try self.nodes(b.common, se, &env);
        if (b.kinds.len > 0) {
            var sel: ?*const SKind = null;
            for (b.kinds) |*k| {
                const save = self.pos;
                var ok = true;
                for (k.whens) |*w| {
                    if (w.at_off) |off| {
                        // Version 0.33: a look-ahead reads at kind start
                        // plus its offset and does not move the cursor; a
                        // window beyond the input or extent does not hold
                        if (!self.windowHolds(save, off, w)) {
                            ok = false;
                            break;
                        }
                        continue;
                    }
                    // a `when` any of whose bits lies beyond the input does not hold
                    if (!self.fits(w.len) or !inRanges(w.ranges, self.take(w.len))) {
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
            // Version 0.30: the selected kind's `when … as` lines set their
            // keys; a kind tested and not selected set nothing (ruling 12)
            var cur = self.pos;
            for (k.whens) |*w| {
                if (w.at_off == null) cur -= w.len;
            }
            const kstart = cur;
            for (k.whens) |*w| {
                if (w.at_off) |off| {
                    try self.setAs(se, w, kstart + @as(usize, @intCast(off)));
                } else {
                    try self.setAs(se, w, cur);
                    cur += w.len;
                }
            }
            kind_lines = k.lines;
            // Version 0.92: no `run` line is left to reach
            if (self.run) |r| if (se.e == self.root and seqRunCount(b.common) + seqRunCount(k.lines) == 0) {
                r.ordinary = true;
            };
            try self.nodes(k.lines, se, &env);
        }
        try self.checkPending(mark);
        try self.checkSized(smark, b.common, kind_lines);
        // a failed item of a discarded list is not an error (ruling 21 of 0.34)
        if (self.diag.no_hold > 0) return;
        // an inner message's own keys: the outer decode judges them (ruling 23)
        if (self.is_inner and se.e == self.root) return;
        for (se.failed.items) |key| {
            if (!se.e.fields.contains(key)) return self.fieldFailed("failed fields: {s}", .{key});
        }
    }

    // A field that fails is reported when the message has been read: going
    // over the limit on list items, later in the message too, wins over it
    // (ruling 7f of 0.11). The first such failure is kept.
    fn fieldFailed(self: *SDec, comptime fmt: []const u8, args: anytype) !void {
        if (self.failed_msg == null) self.failed_msg = try std.fmt.allocPrint(self.alloc, fmt, args);
    }
};

fn inBitRanges(rs: []const SEnc.BitRange, b: usize) bool {
    for (rs) |r| if (b >= r.at and b < r.at + r.len) return true;
    return false;
}

// Version 0.30: the value of a `when … as <k>` line's key in the entity:
// absent; held, with the unsigned 64-bit pattern the `when` matches; or held
// with a value it does not match (ruling 7: the value read as an unsigned
// 64-bit pattern, so a negative value never matches a `when` shorter than 64
// bits). Only what the entity holds counts, not a `default` (ruling 6).
const AsVal = union(enum) { absent, match: u64, nomatch };

fn asValue(n: *const SNode, ent: *const Entity) AsVal {
    const mv = ent.get(n.as_key) orelse return .absent;
    const i: i64 = switch (mv) {
        .int => |x| x,
        .float => |f| if (f == @trunc(f) and f >= -9223372036854775808.0 and f < 9223372036854775808.0) @intFromFloat(f) else return .nomatch,
        .str => |t| std.fmt.parseInt(i64, t, 10) catch return .nomatch,
    };
    const u: u64 = @bitCast(i);
    return if (inRanges(n.ranges, u)) .{ .match = u } else .nomatch;
}

// Version 0.20: the case of a switch node (an index into its body) that a
// value of its key selects: the first case listing its canonical text, else
// the `else`; null: none (`no-kind`). An absent key selects the `else`.
fn caseIndex(alloc: std.mem.Allocator, n: *const SNode, val: ?MV) !?usize {
    if (val) |mv| {
        const c = try canonOfMV(alloc, n.sw.?.kty, mv);
        for (n.body, 0..) |*cn, i| {
            if (!cn.cs.?.is_else and listHolds(cn.cs.?.canon, c)) return i;
        }
    }
    for (n.body, 0..) |*cn, i| if (cn.cs.?.is_else) return i;
    return null;
}

// Version 0.34: the checks made when decode or encode reaches an `inner`
// line, in order: the inner format is loaded; its wire is `bits` with no
// `armor` and no `encoding uper`; it has no `inner` line and is not the
// outer pack; a public outer pack has a public inner pack.
fn innerCheck(outer: *const Pack, ip: *const Pack) ?anyerror {
    if (ip.wire != .bits or ip.armor or ip.uper) return E.@"bad-directive";
    if (ip.inners.items.len > 0 or ip == outer or std.mem.eql(u8, ip.format, outer.format)) return E.@"bad-directive";
    if (outer.distribution == .public and ip.distribution != .public) return E.@"distribution-violation";
    return null;
}

// Do two key uses give one entry of `model_keys`?
fn sameEntry(a: KeyUse, b: KeyUse) bool {
    if ((a.use == .group) != (b.use == .group) or !std.mem.eql(u8, a.key, b.key)) return false;
    var x = a.grp;
    var y = b.grp;
    while (x != null and y != null) {
        if (!std.mem.eql(u8, x.?.list, y.?.list)) return false;
        x = x.?.parent;
        y = y.?.parent;
    }
    return x == null and y == null;
}

// A use that maps its key: a `field`, `also`, `group` or `when … as` line.
fn mapsKey(ku: KeyUse) bool {
    return ku.use == .field or ku.use == .group or ku.use == .as_;
}

// Version 0.52, ruling 20: a key that the lines in reach of the `inner` line
// map and the inner pack maps too; null: none. In reach are the common lines
// and, for a line in a kind, that kind's; for one in the common lines, every
// kind's.
fn innerClash(outer: *const Pack, im: InnerMark, ip: *const Pack) ?KeyUse {
    var kind: usize = 0;
    for (outer.key_uses.items, 0..) |ku, i| {
        while (kind < outer.kind_starts.items.len and outer.kind_starts.items[kind] <= i) kind += 1;
        if (kind != 0 and im.kind != 0 and kind != im.kind) continue;
        // at a `run` line a key the outer `with` names, too (ruling 9 of 0.92)
        const named = im.run and ku.use == .with;
        if (!mapsKey(ku) and !named) continue;
        for (ip.key_uses.items) |other| {
            if (!mapsKey(other)) continue;
            // `with` may name a list
            const as_use = KeyUse{ .key = ku.key, .tkind = null, .use = if (named) other.use else ku.use, .grp = ku.grp };
            if (sameEntry(as_use, other)) return ku;
        }
    }
    return null;
}

// The checks of an `inner` line, when decode or encode reaches it.
fn innerLookup(alloc: std.mem.Allocator, diag: *Diag, outer: *const Pack, n: *const SNode) anyerror!*const Pack {
    const fmt = n.list;
    const ip: *const Pack = (if (diag.packs) |m| m.get(fmt) else null) orelse
        return bad(diag, alloc, E.@"unknown-format", "inner {s}: no loaded pack has format {s}", .{ fmt, fmt });
    // between checks 2 and 3, at a `run` line (ruling 16 of 0.92)
    if (n.run and ip.wire == .bits and !ip.armor and !ip.uper and (ip.seq == null or ip.framing_line == 0)) {
        return bad(diag, alloc, E.@"bad-directive", "inner {s} run: the inner pack is not `layout sequential` with `framing self`", .{fmt});
    }
    if (innerCheck(outer, ip)) |err| {
        const why: []const u8 = switch (err) {
            E.@"distribution-violation" => "the outer pack is public and the inner pack is not",
            else => if (ip.wire != .bits or ip.armor or ip.uper)
                "the inner pack is not on the bits wire without armor and encoding uper"
            else
                "the inner pack has an inner line of its own, or is the outer pack (one layer only)",
        };
        return bad(diag, alloc, err, "inner {s}: {s}", .{ fmt, why });
    }
    // the fifth check (ruling 20 of 0.52)
    for (outer.inners.items) |im| {
        if (im.lineno != n.lineno) continue;
        if (innerClash(outer, im, ip)) |ku| return bad(diag, alloc, E.@"bad-directive", "inner {s}: the key {s} is mapped by both packs", .{ fmt, ku.key });
    }
    return ip;
}

// Version 0.92: what the outer decode of a run operation finds. A message is
// held as its place in the input and, when it fails, its failure; its entity
// is decoded again when its result is made, into an arena reset for each
// message. So memory grows with the results, not with the entities.
const RunFail = struct { kind: anyerror, msg: []const u8 };
const RunMsg = struct { at: usize, fail: ?*const RunFail = null };

const RunRead = struct {
    to_carrier: bool,
    arena: std.heap.ArenaAllocator,
    // a `run` line was reached; the decode came to its end; no `run` line can
    // be reached any more
    reached: bool = false,
    ended: bool = false,
    ordinary: bool = false,
    ip: *const Pack = undefined,
    input: []const u8 = "",
    held: usize = 0,
    max_items: usize = 0,
    packs: ?*const std.StringHashMap(*Pack) = null,
    msgs: std.ArrayListUnmanaged(RunMsg) = .{},
    // ruling 5: the messages whose decode came to its end, and the sum of
    // their own items
    done: usize = 0,
    own_items: u128 = 0,

    // Ruling 5: the items of all joined entities of the run, the outer
    // entity's once for each message whose decode came to its end and each
    // such message's own, may reach `max_items`; one more is `malformed-wire`
    // of the call. Made when the carrier's decode has ended, after its other
    // decode errors and before context and encode.
    fn checkSum(self: *const RunRead, diag: *Diag, alloc: std.mem.Allocator, outer: *const Entity) anyerror!void {
        const sum = @as(u128, entityItems(outer)) * self.done + self.own_items;
        if (sum > self.max_items) {
            diag.limit_hit = true;
            return bad(diag, alloc, E.@"malformed-wire", "inner {s} run: the joined entities hold {d} list items, more than the limit of {d}", .{ self.ip.format, sum, self.max_items });
        }
    }

    // A message's items start from the budget the outer lines before it left
    // (ruling 5).
    fn messageDiag(self: *const RunRead) Diag {
        return .{ .max_items = self.max_items, .held = self.held, .packs = self.packs, .inner = .run };
    }

    // The outer entity and one message that decodes, joined (step 4 of 0.34;
    // the two packs share no key).
    fn joined(self: *const RunRead, alloc: std.mem.Allocator, outer: *const Entity, m: RunMsg) anyerror!Entity {
        var md = self.messageDiag();
        const buf = self.input[m.at..];
        const sub = try seqDecodeBits(alloc, self.ip, buf, buf.len * 8, &md);
        var e = Entity.init(alloc);
        e.kind_fmt = outer.kind_fmt;
        e.kind_name = outer.kind_name;
        for ([_]*const Entity{ outer, &sub }) |x| {
            for (x.fields.ptr[0..x.fields.len]) |en| if (!e.fields.contains(en.key)) try e.put(en.key, en.value);
            for (x.lists.ptr[0..x.lists.len]) |en| if (!e.lists.contains(en.key)) try e.putList(en.key, en.value);
        }
        if (sub.kind_fmt) |kf| {
            e.inner_kind_fmt = kf;
            e.inner_kind_name = sub.kind_name;
        }
        return e;
    }
};

// Version 0.92, ruling 6: the messages a carrier is written with. Written
// once, also when the outer encode runs several times (0.20).
const RunWrite = struct {
    eng: *Engine,
    read: *RunRead,
    outer: *const Entity,
    from: []const u8,
    to: []const u8,
    context: ?[]const KV,
    done: ?[]const u8 = null,

    fn bytes(self: *RunWrite, alloc: std.mem.Allocator, ip: *const Pack, diag: *Diag) anyerror![]const u8 {
        if (self.done) |b| return b;
        const r = self.read;
        const a = r.arena.allocator();
        const same_inner = std.mem.eql(u8, ip.format, r.ip.format);
        var out = std.ArrayList(u8).init(alloc);
        for (r.msgs.items, 0..) |m, i| {
            _ = r.arena.reset(.retain_capacity);
            var e = try r.joined(a, self.outer, m);
            self.eng.clearKinds(&e, self.from, self.to);
            if (!same_inner or self.context != null) try self.eng.finish(a, &e, self.context);
            innerKind(&e, ip);
            var ed = Diag{ .packs = diag.packs };
            const hex = encodePack(a, ip, &e, &ed) catch |err| {
                if (err == error.OutOfMemory) return err;
                return bad(diag, alloc, err, "message {d}: {s}", .{ i + 1, ed.msg });
            };
            if (hex.len == 0) return bad(diag, alloc, E.@"transform-encode", "message {d} of the run writes no byte", .{i + 1});
            const b = hexDecode(a, hex) catch return bad(diag, alloc, E.@"transform-encode", "message {d}: its encoding is not bytes", .{i + 1});
            try out.appendSlice(b);
        }
        self.done = out.items;
        return out.items;
    }
};

// The kind an inner message is written with (Version 0.34): Entity.inner_kind
// when it names the inner format, else Entity.kind.
fn innerKind(e: *Entity, ip: *const Pack) void {
    const kf = e.inner_kind_fmt orelse return;
    if (!std.mem.eql(u8, kf, ip.format)) return;
    e.kind_fmt = kf;
    e.kind_name = e.inner_kind_name;
}

fn seqDecode(alloc: std.mem.Allocator, p: *const Pack, bytes: []const u8, diag: *Diag) anyerror!Entity {
    const in = bitsInput(alloc, p, bytes) catch |err| return bad(diag, alloc, err, "{s}", .{if (p.armor) "the input is not six-bit armored text" else "the input is not hex of even length"});
    return seqDecodeBits(alloc, p, in.buf, in.nbits, diag);
}

fn seqDecodeBits(alloc: std.mem.Allocator, p: *const Pack, buf: []const u8, nbits: usize, diag: *Diag) anyerror!Entity {
    var d = SDec{ .alloc = alloc, .p = p, .buf = buf, .diag = diag, .hard_end = nbits, .soft_end = nbits };
    d.run = diag.run;
    diag.run = null;
    var e = Entity.init(alloc);
    var se = SEnt{ .e = &e };
    d.root = &e;
    d.discard = diag.discard;
    diag.discard = &.{};
    const mode = diag.inner;
    diag.inner = .none;
    d.is_inner = mode != .none;
    d.in_run = mode == .run;
    try d.body(p.seq.?, &se, null);
    if (mode == .strict) {
        // rulings 13 and 17 of 0.34: ahead of a `transform-decode`
        const stop = ((if (d.whole_read) d.hard_end else d.pos) + 7) / 8;
        if (buf.len > stop) return leftover(diag, alloc, stop, buf.len);
    }
    if (mode == .run) {
        // Version 0.92: the message's end (ruling 13 of 0.34)
        const stop = ((if (d.whole_read) d.hard_end else d.pos) + 7) / 8;
        if (stop > buf.len) return bad(diag, alloc, E.@"malformed-wire", "a message of a run ends at byte {d}, its extent holds {d}", .{ stop, buf.len });
        if (stop == 0) return bad(diag, alloc, E.@"malformed-wire", "a message of a run reads no byte", .{});
        diag.run_end = stop;
    }
    if (d.run) |r| r.ended = true;
    if (mode != .none) {
        var keys = std.ArrayListUnmanaged([]const u8){};
        for (se.failed.items) |key| if (!e.fields.contains(key)) try keys.append(alloc, key);
        if (d.failed_msg != null or keys.items.len > 0) return innerFailed(diag, alloc, e, d.failed_msg, keys.items);
    }
    if (d.failed_msg) |m| return bad(diag, alloc, E.@"transform-decode", "{s}", .{m});
    return e;
}

const SWhole = struct { at: usize, len: usize, plus: i64 };
// Version 0.21: a count field at `at`, and the value it holds (items + n)
const SCountAt = struct { at: usize, cnt: *const SCount, value: i128 };
// An extent being laid out: counted in bits or bytes, where the last item of
// a `rest` group in it starts (the one with the fewest bits left), and how
// many `rest` groups were written in it.
const SExt = struct { bits: bool, last_start: ?usize = null, rests: usize = 0 };

// Version 0.20: the case each switch selects for one entity or item (an
// index into the switch node's body; `no_case`: none). Encode runs until
// the cases it assumed ahead (for presence, `opt` and `fx` bits) are the
// cases the written bits select.
const SwKey = struct { n: usize, e: usize };
const SwTable = std.AutoHashMapUnmanaged(SwKey, u32);
const no_case = std.math.maxInt(u32);

// The encoder lays out a scope in two passes: the presence bits and `fx` bits
// are computed from the entity (`scan`, `hasContent`) before they are written.
const SEnc = struct {
    alloc: std.mem.Allocator,
    p: *const Pack,
    diag: *Diag,
    out: std.ArrayList(u8), // zero beyond the cursor
    pos: usize = 0,
    wholes: std.ArrayListUnmanaged(SWhole) = .{},
    // Version 0.20: the switch cases, assumed or found; a dry run settles
    // them and raises no `no-kind` for a switch
    table: ?*SwTable = null,
    dry: bool = false,
    changed: bool = false,
    // the values decode would read back from the lines written so far in
    // the current message or item, by key (the earliest line wins)
    kv: ?*std.StringHashMapUnmanaged(MV) = null,
    // keys whose line wrote bits that do not read back
    kv_failed: ?*std.StringHashMapUnmanaged(void) = null,
    // Version 0.64, ruling 31: the lines of the message or item whose table
    // refuses what they wrote, with their key, and the keys a `switch` read
    kv_dead: ?*DeadLines = null,
    kv_switched: ?*std.StringHashMapUnmanaged(void) = null,
    // Version 0.92: the messages of a run to write; null: the entity itself
    run_write: ?*RunWrite = null,
    // Version 0.21: the count fields written, filled in when the message is
    // finished; the latest of each count line
    cpend: std.ArrayListUnmanaged(SCountAt) = .{},
    ccur: std.AutoHashMapUnmanaged(*const SCount, usize) = .{},
    // the extents being laid out, innermost last, with where each item of a
    // `rest` group in them starts
    exts: std.ArrayListUnmanaged(SExt) = .{},
    // Version 0.94: the message's chosen kind must hold one of its keys
    held_check: bool = false,

    const te = E.@"transform-encode";

    // Ruling 4 of 0.21, checked once the extent is laid out (ruling 21):
    // every item of a `rest` group starts with at least 8 bits (1 in an
    // extent counted in bits) left before the extent's byte-padded end.
    fn checkExt(self: *SEnc, x: SExt, end: usize) !void {
        const least: usize = if (x.bits) 1 else 8;
        if (x.last_start) |st| {
            if (end -| st < least) {
                return bad(self.diag, self.alloc, te, "an item of a rest group starts at bit {d}, {d} bits before the end of its extent at bit {d}: the output would not decode it", .{ st, end -| st, end });
            }
        }
    }

    // The value decode would read for key `j` of a field (0: its own, i: its
    // i-th `also`) from the bits at `at`; null: a sentinel or a failure.
    fn readBack(self: *SEnc, buf: []const u8, at: usize, n: *const SNode, j: usize) ?MV {
        return switch (self.readBackR(buf, at, n, j)) {
            .val => |v| v,
            else => null,
        };
    }

    // As `readBack`, telling a sentinel (`absent`) from a value that fails
    // its transform or table (`failed`, ruling 31 of 0.20).
    // `no_entry`: its transform succeeds and its table refuses the value,
    // which fails the decode whatever other lines give (ruling 26 of 0.64).
    const RB = union(enum) { val: MV, absent, failed, no_entry };
    const LineKey = struct { n: usize, j: usize };
    const DeadLines = std.AutoHashMapUnmanaged(LineKey, []const u8);

    // What decode reads for key `j` of a line from the bits it wrote, for a
    // `switch`: the earliest line's value is kept, and a line whose table
    // refuses its value is noted, also after the key has one (ruling 31 of
    // 0.64).
    fn noteRead(self: *SEnc, n: *const SNode, j: usize, rb: RB) !void {
        const alloc = self.alloc;
        const key = if (j == 0) n.ln.key else n.also.items[j - 1].key;
        const lk = LineKey{ .n = @intFromPtr(n), .j = j };
        if (rb == .no_entry) {
            try self.kv_dead.?.put(alloc, lk, key);
            // a line after a `switch` on its key
            if (!self.dry and self.kv_switched.?.contains(key)) {
                return bad(self.diag, alloc, te, "field {s}: the bits its line wrote have no entry in its table, and a switch reads the key", .{key});
            }
        } else _ = self.kv_dead.?.remove(lk);
        const m = self.kv.?;
        if (m.contains(key)) return;
        switch (rb) {
            .val => |mv| try m.put(alloc, key, mv),
            .failed, .no_entry => try self.kv_failed.?.put(alloc, key, {}),
            .absent => {},
        }
    }

    fn hasDead(self: *const SEnc, key: []const u8) bool {
        var it = (self.kv_dead orelse return false).valueIterator();
        while (it.next()) |k| if (std.mem.eql(u8, k.*, key)) return true;
        return false;
    }

    fn readBackR(self: *SEnc, buf: []const u8, at: usize, n: *const SNode, j: usize) RB {
        const ln = &n.ln;
        if (ln.abs_set and absentInt(ln, bitsRaw(self.p, buf, at, ln))) return .absent;
        var mv = bitsDecodeField(self.alloc, self.p, buf, at, ln) catch return .failed;
        const key = if (j == 0) ln.key else n.also.items[j - 1].key;
        const via = if (j == 0) ln.via else n.also.items[j - 1].via;
        const kty = if (j == 0) ln.kty else n.also.items[j - 1].kty;
        if (via) |t| mv = tableDecode(t, mv, kty) catch return .no_entry;
        if (mv == .str and std.mem.eql(u8, key, "type")) {
            if (self.p.tm_nat2cot.get(mv.str)) |cot| mv = MV{ .str = cot };
        }
        return .{ .val = mv };
    }

    // The case a switch selects, assumed before its key's line is written:
    // the one recorded, else the one the key's line would select if it were
    // written (a run that reaches the switch corrects it).
    fn predictCase(self: *SEnc, n: *const SNode, ent: *const Entity, ds: DS) !u32 {
        const k = SwKey{ .n = @intFromPtr(n), .e = @intFromPtr(ent) };
        const tbl = self.table.?;
        if (tbl.get(k)) |v| return v;
        const sw = n.sw.?;
        var val: ?MV = null;
        if (sw.key_src) |src| if (src.uloc) |u| {
            // a UPER key line (0.19): its bits depend on its value; write
            // it alone and read it back
            var tmp = SEnc{ .alloc = self.alloc, .p = self.p, .diag = self.diag, .out = std.ArrayList(u8).init(self.alloc), .dry = true };
            const save = self.diag.msg;
            const wrote = if (tmp.uperField(src, u, ent, ds)) true else |err| blk: {
                if (err == error.OutOfMemory) return err;
                break :blk false;
            };
            self.diag.msg = save;
            if (wrote) val = switch (tmp.uperReadBackR(tmp.out.items, 0, tmp.pos, src, u, sw.key_idx)) {
                .val => |v| v,
                else => null,
            };
            const idx: u32 = if (try caseIndex(self.alloc, n, val)) |i| @intCast(i) else no_case;
            try tbl.put(self.alloc, k, idx);
            return idx;
        };
        if (sw.key_src) |src| if (src.tag == .when) {
            // Version 0.30: the key's line is a `when … as` (ruling 19): the
            // value it writes, the first listed one when the key is absent
            val = switch (asValue(src, ent)) {
                .match => |x| MV{ .int = @bitCast(x) },
                .absent => MV{ .int = @bitCast(src.value) },
                .nomatch => null,
            };
            const idx: u32 = if (try caseIndex(self.alloc, n, val)) |i| @intCast(i) else no_case;
            try tbl.put(self.alloc, k, idx);
            return idx;
        };
        if (sw.key_src) |src| {
            const ln = &src.ln;
            const tmp = try self.alloc.alloc(u8, (ln.blen + 7) / 8);
            @memset(tmp, 0);
            const mv = self.fieldValueQuiet(src, ent, ds);
            if (mv) |v| {
                bitsWriteField(self.alloc, self.p, tmp, 0, ln, v) catch {};
            } else if (ln.sentinelOn(ent)) {
                bitsWriteRaw(self.p, tmp, 0, ln, ln.abs_ints[0]);
            }
            val = self.readBack(tmp, 0, src, sw.key_idx);
        }
        const idx: u32 = if (try caseIndex(self.alloc, n, val)) |i| @intCast(i) else no_case;
        try tbl.put(self.alloc, k, idx);
        return idx;
    }

    // As `readBackR` for a field with a UPER locator (Version 0.19): decode
    // its bits `buf[at..end)` as decode would read them.
    fn uperReadBackR(self: *SEnc, buf: []const u8, at: usize, end: usize, n: *const SNode, u: ULoc, j: usize) RB {
        const save = self.diag.msg;
        defer self.diag.msg = save;
        var e = Entity.init(self.alloc);
        var se = SEnt{ .e = &e };
        var d = SDec{ .alloc = self.alloc, .p = self.p, .buf = buf, .diag = self.diag, .pos = at, .hard_end = end, .soft_end = end };
        d.uperField(n, u, &se) catch return .failed;
        const key = if (j == 0) n.ln.key else n.also.items[j - 1].key;
        // a table failure sets the message, a transform failure does not
        for (se.failed.items) |fk| if (std.mem.eql(u8, fk, key)) return if (d.failed_msg != null) .no_entry else .failed;
        if (d.failed_msg != null) return .failed;
        return if (e.get(key)) |v| .{ .val = v } else .absent;
    }

    fn fieldValueQuiet(self: *SEnc, n: *const SNode, ent: *const Entity, ds: DS) ?MV {
        const save = self.diag.msg;
        defer self.diag.msg = save;
        return self.fieldValue(n, ent, ds) catch null;
    }

    // The defaults in scope inside a case.
    fn caseDS(ds: DS, c: *const SNode, link: *DLink) DS {
        link.* = .{ .map = &c.cs.?.dmap, .parent = ds.c };
        return .{ .a = ds.a, .b = ds.b, .c = link };
    }

    fn ensure(self: *SEnc, nbits: usize) !void {
        const nb = (nbits + 7) / 8;
        if (nb > self.out.items.len) try self.out.appendNTimes(0, nb - self.out.items.len);
    }

    // Version 0.22: a `until:<code> chars:<set>` field: the text's
    // characters, then the terminator; an absent key with no default writes
    // the terminator alone (ruling 10).
    fn untilField(self: *SEnc, n: *const SNode, ent: *const Entity, ds: DS) !void {
        const ln = &n.ln;
        const c = ln.transform.cset;
        const w = charWidth(c);
        const term = ln.until_code.?;
        const fv = if (self.dry) self.fieldValueQuiet(n, ent, ds) else try self.fieldValue(n, ent, ds);
        var text: []const u8 = "";
        if (fv) |mv| {
            const ok = mv == .str and mv.str.len <= 2040 / w and blk: {
                for (mv.str) |ch| {
                    const code = codeOfTerm(c, ch, term) orelse break :blk false;
                    if (code == term) break :blk false;
                }
                break :blk true;
            };
            if (!ok) {
                if (!self.dry) return bad(self.diag, self.alloc, te, "field {s}: the text does not encode before terminator {d}", .{ ln.key, term });
            } else text = mv.str;
        }
        for (text) |ch| try self.put(w, codeOfTerm(c, ch, term).?);
        try self.put(w, term);
    }

    // As `readBackR` for a `until:` field: decode its bits `buf[at..end)`.
    fn untilReadBackR(self: *SEnc, buf: []const u8, at: usize, end: usize, n: *const SNode, j: usize) RB {
        const save = self.diag.msg;
        defer self.diag.msg = save;
        var e = Entity.init(self.alloc);
        var se = SEnt{ .e = &e };
        var d = SDec{ .alloc = self.alloc, .p = self.p, .buf = buf, .diag = self.diag, .pos = at, .hard_end = end, .soft_end = end };
        d.untilField(n, &se) catch return .failed;
        const key = if (j == 0) n.ln.key else n.also.items[j - 1].key;
        // a table failure sets the message, a transform failure does not
        for (se.failed.items) |fk| if (std.mem.eql(u8, fk, key)) return if (d.failed_msg != null) .no_entry else .failed;
        if (d.failed_msg != null) return .failed;
        return if (e.get(key)) |v| .{ .val = v } else .absent;
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
        // Version 0.34: a message then selects by Entity.inner_kind when it
        // names this format (an item records none)
        if (!is_item) if (ent.inner_kind_fmt) |kf| {
            if (std.mem.eql(u8, kf, self.p.format)) {
                for (b.kinds) |*k| if (std.mem.eql(u8, k.name, ent.inner_kind_name)) return k;
                return bad(self.diag, self.alloc, E.@"no-kind", "the entity records inner kind {s}, which the body does not have", .{ent.inner_kind_name});
            }
        };
        for (b.kinds) |*k| {
            var all = true;
            for (k.requires.items) |t| {
                if (!termHolds(self.alloc, t, ent)) {
                    all = false;
                    break;
                }
            }
            // Version 0.30: each `when … as <k>` line of the kind is an
            // implicit term: the entity holds <k> with a value the `when`
            // matches; with `optional` (Version 0.52), or does not hold <k>
            for (k.whens) |*w| {
                if (w.as_key.len == 0) continue;
                switch (asValue(w, ent)) {
                    .match => {},
                    .absent => if (!w.as_opt) {
                        all = false;
                    },
                    .nomatch => all = false,
                }
            }
            if (all) return k;
        }
        return bad(self.diag, self.alloc, E.@"no-kind", "the entity has the `requires` keys of no kind", .{});
    }

    // Version 0.30: write a `when` line. With `as <k>`: the value of <k> when
    // the entity holds it and the `when` matches it; the first listed value
    // when the entity does not hold <k> (a `default` has no effect, ruling
    // 6); `transform-encode` for a held value the `when` does not match.
    // What decode reads back is kept for a `switch` on the key.
    fn writeWhen(self: *SEnc, n: *const SNode, ent: *const Entity) !void {
        var v = n.value;
        if (n.as_key.len > 0) {
            switch (asValue(n, ent)) {
                .match => |x| v = x,
                .absent => {},
                .nomatch => if (!self.dry) return bad(self.diag, self.alloc, te, "when … as {s}: the entity holds a value the `when` does not match; the output would decode another value", .{n.as_key}),
            }
            if (self.kv) |m| {
                if (!m.contains(n.as_key)) try m.put(self.alloc, n.as_key, MV{ .int = @bitCast(v) });
            }
        }
        try self.put(n.len, v);
    }

    // The value a field writes: that of the earliest of its keys that the
    // entity holds; when it holds none, the default of the earliest key that
    // has one (ruling 16 of 0.8).
    fn fieldValue(self: *SEnc, n: *const SNode, ent: *const Entity, ds: DS) !?MV {
        const ln = &n.ln;
        const wire_ty = yields(ln.transform.kind);
        const nkeys = n.also.items.len + 1;
        // a line suppressed by `with`: its own key is not a candidate, its
        // `also` keys stay ones (ruling 5 of 0.18)
        const own = !ln.suppressed(ent);
        var i: usize = 0;
        while (i < 2 * nkeys) : (i += 1) {
            const j = i % nkeys;
            if (j == 0 and !own) continue;
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

    // In a UPER pack no `default` counts as content (rulings 2 and 19 of
    // 0.19).
    fn keyPresent(self: *const SEnc, n: *const SNode, ent: *const Entity, ds_in: DS) bool {
        const ds = if (self.p.uper) DS{} else ds_in;
        if (!n.ln.suppressed(ent) and (ent.fields.contains(n.ln.key) or ds.get(n.ln.key) != null)) return true;
        for (n.also.items) |a| if (ent.fields.contains(a.key) or ds.get(a.key) != null) return true;
        return false;
    }

    // Would the lines write a present key, a non-empty list, or a nested
    // presence that is not all zero?
    fn hasContent(self: *SEnc, list: []const SNode, ent: *const Entity, ds: DS) anyerror!bool {
        for (list) |*n| {
            switch (n.tag) {
                .field => if (self.keyPresent(n, ent, ds)) return true,
                .group => {
                    if (ent.lists.get(n.list)) |items| {
                        if (items.len > 0) return true;
                    }
                },
                .if_, .opt, .chain, .length, .ext, .choice, .alt => if (try self.hasContent(n.body, ent, ds)) return true,
                // the selected case only (Version 0.20)
                .switch_ => {
                    const idx = try self.predictCase(n, ent, ds);
                    if (idx == no_case) continue;
                    var link: DLink = undefined;
                    const c = &n.body[idx];
                    if (try self.hasContent(c.body, ent, caseDS(ds, c, &link))) return true;
                },
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
                .opt, .chain, .length, .ext, .choice, .alt => try self.scan(pres, n.body, ent, ds, bits),
                // the selected case only (Version 0.20)
                .switch_ => {
                    const idx = try self.predictCase(n, ent, ds);
                    if (idx == no_case) continue;
                    var link: DLink = undefined;
                    const c = &n.body[idx];
                    try self.scan(pres, c.body, ent, caseDS(ds, c, &link), bits);
                },
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
        // the values read back are per message or item
        var kv = std.StringHashMapUnmanaged(MV){};
        var kvf = std.StringHashMapUnmanaged(void){};
        const save_kv = self.kv;
        const save_kvf = self.kv_failed;
        var kvd = DeadLines{};
        var kvs = std.StringHashMapUnmanaged(void){};
        const save_kvd = self.kv_dead;
        const save_kvs = self.kv_switched;
        if (self.table != null) {
            self.kv = &kv;
            self.kv_failed = &kvf;
            self.kv_dead = &kvd;
            self.kv_switched = &kvs;
        }
        defer {
            self.kv = save_kv;
            self.kv_failed = save_kvf;
            self.kv_dead = save_kvd;
            self.kv_switched = save_kvs;
        }
        const k = try self.selectKind(b, ent, is_item);
        // Version 0.94: the message's kind, between choosing and the first
        // line; not an item's (ruling 4)
        if (self.held_check and !is_item) if (k) |kk| {
            const ki = (@intFromPtr(kk) - @intFromPtr(b.kinds.ptr)) / @sizeOf(SKind);
            try heldCheck(self.alloc, self.p, ki, ent, self.diag);
        };
        const ds = DS{ .a = if (k) |kk| &kk.dmap else null, .b = &b.dmap };
        var env = env_in;
        const tail: []const SNode = if (k) |kk| kk.lines else &.{};
        try self.nodes(b.common, tail, ent, ds, &env);
        if (k) |kk| {
            const kstart = self.pos;
            var windows = false;
            for (kk.whens) |*w| {
                // a look-ahead writes nothing here; it settles its window
                // once the kind's lines are written (Version 0.33)
                if (w.at_off != null) {
                    windows = true;
                    continue;
                }
                try self.writeWhen(w, ent);
            }
            if (windows) {
                try self.kindWithWindows(kk, kstart, ent, ds, &env);
            } else try self.nodes(kk.lines, &.{}, ent, ds, &env);
        }
    }

    // Version 0.33: the lines of a kind with `when … at` lines. Each window
    // is settled, in line order, as soon as the lines written reach its end:
    // before any later line (a `switch` reading its key back) is written.
    const BitRange = struct { at: usize, len: usize };
    const FieldAt = struct { n: *const SNode, at: usize };
    const WhenAt = struct { n: *const SNode, at: usize };
    // What the windows of one kind settle against: the bits that keys the
    // entity holds wrote (ruling 12 of 0.33, ruling 16 of 0.52), the fields
    // and the `when … as` lines written, with their positions, and the keys
    // a line before the kind's set.
    const WinState = struct {
        held: std.ArrayListUnmanaged(BitRange) = .{},
        fields: std.ArrayListUnmanaged(FieldAt) = .{},
        whens: std.ArrayListUnmanaged(WhenAt) = .{},
        before: std.StringHashMapUnmanaged(void) = .{},
        before_failed: std.StringHashMapUnmanaged(void) = .{},
    };

    fn kindWithWindows(self: *SEnc, kk: *const SKind, kstart: usize, ent: *const Entity, ds: DS, env: *?*const PEnv) anyerror!void {
        const alloc = self.alloc;
        var st = WinState{};
        if (self.kv) |m| {
            var it = m.keyIterator();
            while (it.next()) |k| try st.before.put(alloc, k.*, {});
            var fit = self.kv_failed.?.keyIterator();
            while (fit.next()) |k| try st.before_failed.put(alloc, k.*, {});
        }
        // the plain `when … as` lines, written before any window settles
        var at0 = kstart;
        for (kk.whens) |*w| {
            if (w.at_off != null) continue;
            if (w.as_key.len > 0) {
                try st.whens.append(alloc, .{ .n = w, .at = at0 });
                _ = st.before.remove(w.as_key);
                if (ent.get(w.as_key) != null) try st.held.append(alloc, .{ .at = at0, .len = w.len });
            }
            at0 += w.len;
        }
        var wi: usize = 0;
        for (kk.lines, 0..) |*n, i| {
            // before the line: a window may lie over the `when` lines alone
            try self.settleReady(kk, &wi, kstart, ent, &st);
            const at = self.pos;
            try self.node(n, kk.lines[i + 1 ..], &.{}, ent, ds, env);
            if (n.tag == .field and n.uloc == null and n.ln.until_code == null) {
                try st.fields.append(alloc, .{ .n = n, .at = at });
                if (heldWrote(n, ent) and self.pos == at + n.ln.blen) try st.held.append(alloc, .{ .at = at, .len = n.ln.blen });
            }
        }
        // the windows that end at or within the last line
        try self.settleReady(kk, &wi, kstart, ent, &st);
    }

    // Settle, in line order, each window whose end the lines written reach. A
    // window ends within its kind's lines, or the pack does not load.
    fn settleReady(self: *SEnc, kk: *const SKind, wi: *usize, kstart: usize, ent: *const Entity, st: *WinState) !void {
        while (nextWindow(kk, wi)) |w| {
            const end: u128 = @as(u128, kstart) + w.at_off.? + w.len;
            if (end > self.pos) return;
            try self.settleWindow(w, kstart, ent, st);
            wi.* += 1;
        }
    }

    // The next `when … at` of the kind from index `wi` on (moved to it).
    fn nextWindow(kk: *const SKind, wi: *usize) ?*const SNode {
        while (wi.* < kk.whens.len) : (wi.* += 1) {
            if (kk.whens[wi.*].at_off != null) return &kk.whens[wi.*];
        }
        return null;
    }

    // Did a field line write a value of a key the entity holds (not a
    // default, a sentinel, or zero bits of a line `with` suppressed)?
    fn heldWrote(n: *const SNode, ent: *const Entity) bool {
        if (!n.ln.suppressed(ent) and ent.get(n.ln.key) != null) return true;
        for (n.also.items) |a| if (ent.get(a.key) != null) return true;
        return false;
    }

    // Version 0.33, Encode and rulings 1, 12, 13, 26: the bits of the window
    // as written stand when they match the `when` (and equal a held `as`
    // key); else the window takes the `as` key's value or the first listed
    // value, and a bit of it that differs from a bit a held key wrote is
    // `transform-encode`. Raw stream bits in the pack's bit order (ruling 8).
    // A window takes no bit away from a held key, and the bits of one whose
    // `as` key is held are bits that key wrote (ruling 16 of 0.52).
    fn settleWindow(self: *SEnc, w: *const SNode, kstart: usize, ent: *const Entity, st: *WinState) !void {
        const alloc = self.alloc;
        const pos: usize = kstart + @as(usize, @intCast(w.at_off.?));
        try self.ensure(pos + w.len);
        const cur = getBits(self.out.items, self.p.msb, pos, w.len);
        var stand = false;
        var val: u64 = w.value;
        const av: AsVal = if (w.as_key.len > 0) asValue(w, ent) else .absent;
        switch (av) {
            .match => |x| {
                if (cur == x) stand = true else val = x;
            },
            .absent => stand = inRanges(w.ranges, cur),
            .nomatch => if (!self.dry) return bad(self.diag, alloc, te, "when … at {d} as {s}: the entity holds a value the `when` does not match; the output would decode another value", .{ w.at_off.?, w.as_key }),
        }
        if (!stand) {
            const tmp = try alloc.dupe(u8, self.out.items);
            setBits(tmp, self.p.msb, pos, w.len, val);
            for (0..w.len) |i| {
                const b = pos + i;
                if (!inBitRanges(st.held.items, b)) continue;
                if (getBits(self.out.items, self.p.msb, b, 1) != getBits(tmp, self.p.msb, b, 1)) {
                    if (self.dry) break;
                    return bad(self.diag, alloc, te, "when … at {d}: the window's value {d} changes bit {d}, which a held key wrote; the output would decode another value", .{ w.at_off.?, val, b });
                }
            }
            setBits(self.out.items, self.p.msb, pos, w.len, val);
        }
        if (w.as_key.len > 0) {
            try st.whens.append(alloc, .{ .n = w, .at = pos });
            if (av != .absent) try st.held.append(alloc, .{ .at = pos, .len = w.len });
        }
        // what decode reads back, for a `switch` on a key of these bits
        const m = self.kv orelse return;
        for (st.whens.items) |x| {
            try m.put(alloc, x.n.as_key, MV{ .int = @bitCast(getBits(self.out.items, self.p.msb, x.at, x.n.len)) });
        }
        if (stand) return;
        for (st.fields.items) |f| {
            if (f.at >= pos + w.len or f.at + f.n.ln.blen <= pos) continue;
            for (0..f.n.also.items.len + 1) |j| try self.rereadKey(fieldKey(f.n, j), st);
        }
    }

    fn fieldKey(n: *const SNode, j: usize) []const u8 {
        return if (j == 0) n.ln.key else n.also.items[j - 1].key;
    }

    // The value decode reads for a key of the kind's fixed fields from the
    // bits as they stand: that of the earliest line that yields one. A key
    // that a line before the kind's set keeps that value.
    fn rereadKey(self: *SEnc, key: []const u8, st: *const WinState) !void {
        // every line of the key is read again: one whose table refuses its
        // bits fails the decode whatever the others give (ruling 31 of 0.64)
        var got = st.before.contains(key);
        const m = self.kv.?;
        if (!got) {
            _ = m.remove(key);
            if (!st.before_failed.contains(key)) _ = self.kv_failed.?.remove(key);
        }
        for (st.fields.items) |f| {
            for (0..f.n.also.items.len + 1) |j| {
                if (!std.mem.eql(u8, fieldKey(f.n, j), key)) continue;
                const rb = self.readBackR(self.out.items, f.at, f.n, j);
                const lk = LineKey{ .n = @intFromPtr(f.n), .j = j };
                if (rb == .no_entry) try self.kv_dead.?.put(self.alloc, lk, key) else _ = self.kv_dead.?.remove(lk);
                if (got) continue;
                switch (rb) {
                    .val => |mv| {
                        try m.put(self.alloc, key, mv);
                        got = true;
                    },
                    .failed, .no_entry => try self.kv_failed.?.put(self.alloc, key, {}),
                    .absent => {},
                }
            }
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
                if (n.uloc) |u| {
                    const at = self.pos;
                    try self.uperField(n, u, ent, ds);
                    // Version 0.20 beside 0.19: what decode reads back from
                    // the bits the UPER field wrote, for a switch
                    if (self.kv != null) {
                        for (0..n.also.items.len + 1) |j| try self.noteRead(n, j, self.uperReadBackR(self.out.items, at, self.pos, n, u, j));
                    }
                    return;
                }
                if (n.ln.until_code != null) {
                    const at = self.pos;
                    try self.untilField(n, ent, ds);
                    // what decode reads back from these bits, for a switch
                    if (self.kv != null) {
                        for (0..n.also.items.len + 1) |j| try self.noteRead(n, j, self.untilReadBackR(self.out.items, at, self.pos, n, j));
                    }
                    return;
                }
                const ln = &n.ln;
                try self.ensure(self.pos + ln.blen);
                // an absent key writes zero bits, or with `absent` its first
                // sentinel (Version 0.9), which is not content (ruling 4)
                const fv = if (self.dry) self.fieldValueQuiet(n, ent, ds) else try self.fieldValue(n, ent, ds);
                if (fv) |mv| {
                    bitsWriteField(alloc, self.p, self.out.items, self.pos, ln, mv) catch |err| {
                        if (!self.dry) return bad(self.diag, alloc, err, "field {s}: the value does not encode in {d} bits", .{ ln.key, ln.blen });
                    };
                } else if (ln.sentinelOn(ent)) {
                    bitsWriteRaw(self.p, self.out.items, self.pos, ln, ln.abs_ints[0]);
                }
                // Version 0.20: what decode reads back, for a switch
                if (self.kv != null) {
                    for (0..n.also.items.len + 1) |j| try self.noteRead(n, j, self.readBackR(self.out.items, self.pos, n, j));
                }
                self.pos += ln.blen;
            },
            .switch_ => {
                // Version 0.20: the case decode would select from the bits
                // the key's line wrote
                const sw = n.sw.?;
                const val = if (self.kv) |m| m.get(sw.key) else null;
                if (self.kv_switched) |ks| try ks.put(alloc, sw.key, {});
                // a line of the key whose table refuses what it wrote, beside
                // another line's value (ruling 31 of 0.64)
                if (!self.dry and self.hasDead(sw.key)) {
                    return bad(self.diag, alloc, te, "switch {s}: a line of the key wrote bits that have no entry in its table", .{sw.key});
                }
                // a key whose line wrote bits that do not decode (ruling 31)
                if (val == null and !self.dry and self.kv_failed != null and self.kv_failed.?.contains(sw.key)) {
                    return bad(self.diag, alloc, te, "switch {s}: the bits its line wrote do not read back", .{sw.key});
                }
                const found: u32 = if (try caseIndex(alloc, n, val)) |i| @intCast(i) else no_case;
                const k = SwKey{ .n = @intFromPtr(n), .e = @intFromPtr(ent) };
                const tbl = self.table.?;
                if (tbl.get(k)) |was| {
                    if (was != found) self.changed = true;
                }
                try tbl.put(alloc, k, found);
                if (found == no_case) {
                    if (self.dry) return;
                    return bad(self.diag, alloc, E.@"no-kind", "switch {s}: no case holds the value its line wrote, and there is no else", .{sw.key});
                }
                const c = &n.body[found];
                var link: DLink = undefined;
                try self.block(c.body, ent, caseDS(ds, c, &link), env.*);
            },
            .case_ => unreachable, // a case is written by its switch
            .constant => try self.put(n.len, n.value),
            .when => try self.writeWhen(n, ent),
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
                // the block, then the length (a `length @` block has no field
                // of its own, Version 0.83)
                const lpos = self.pos;
                if (n.units == 0) try self.zeros(n.len);
                const start = self.pos;
                try self.exts.append(alloc, .{ .bits = n.in_bits });
                try self.block(n.body, ent, ds, env.*);
                if (!n.in_bits) {
                    const r = (self.pos - start) % 8;
                    if (r != 0) try self.zeros(8 - r);
                }
                try self.checkExt(self.exts.pop(), self.pos);
                const size = self.pos - start;
                if (n.units > 0) {
                    // whole units (ruling 10 of 0.83); a discarded run settles
                    // its switches first
                    if (size % n.units != 0 and !self.dry) return bad(self.diag, alloc, te, "a block of {d} bits is not a whole number of units of {d} bits", .{ size, n.units });
                    if (self.ccur.get(n.cnt.?)) |ci| self.cpend.items[ci].value = @as(i128, size / n.units) + n.cnt.?.plus;
                    return;
                }
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
                    .size_c, .size_u => {
                        if (ent.lists.get(n.list)) |its| {
                            if (n.mode == .size_c) {
                                if (its.len < n.lb or its.len > n.ub) {
                                    return bad(self.diag, alloc, te, "group {s}: {d} items, the size is {d}..{d}", .{ n.list, its.len, n.lb, n.ub });
                                }
                                try self.ecwn(@intCast(its.len), n.lb, n.ub);
                            } else try self.elenDet(its.len, n.list);
                            for (its) |*it| try self.body(b, it, env.*, true);
                        } else if (n.mode == .size_c) {
                            // an absent list: lb items with no keys
                            try self.ecwn(n.lb, n.lb, n.ub);
                            const empty = Entity.init(alloc);
                            for (0..@as(usize, @intCast(n.lb))) |_| try self.body(b, &empty, env.*, true);
                        } else try self.elenDet(0, n.list);
                    },
                    .more, .fx, .last => {
                        // a list has at least one item on the wire
                        if (items.len == 0) {
                            return bad(self.diag, alloc, te, "group {s}: the list is absent or empty, and the wire holds at least one item", .{n.list});
                        }
                        for (items, 0..) |*it, i| {
                            const more = @intFromBool(i + 1 < items.len);
                            if (n.mode == .more) try self.put(1, more);
                            if (n.mode == .last) try self.put(1, 1 - more);
                            try self.body(b, it, env.*, true);
                            if (n.mode == .fx) try self.put(1, more);
                        }
                    },
                    .cref => {
                        // Version 0.21: the items here; the count, at its own
                        // line, holds their number plus n
                        for (items) |*it| try self.body(b, it, env.*, true);
                        if (self.ccur.get(n.cnt.?)) |ci| self.cpend.items[ci].value = @as(i128, items.len) + n.cnt.?.plus;
                        // Version 0.31: the second count likewise (ruling 8)
                        if (n.cnt2) |c2| if (self.ccur.get(c2)) |ci| {
                            self.cpend.items[ci].value = @as(i128, items.len) + c2.plus;
                        };
                    },
                    .rest => {
                        // back to back. An item before the last that writes a
                        // rest group in this extent would take the rest of
                        // it (rulings 10 and 35).
                        const x = &self.exts.items[self.exts.items.len - 1];
                        x.rests += 1;
                        for (items, 0..) |*it, i| {
                            const at = self.pos;
                            const rests = self.exts.items[self.exts.items.len - 1].rests;
                            try self.body(b, it, env.*, true);
                            if (self.pos == at) return bad(self.diag, alloc, te, "group {s}: an item of a rest group writes no bits", .{n.list});
                            const top = &self.exts.items[self.exts.items.len - 1];
                            if (i + 1 < items.len and top.rests != rests) {
                                return bad(self.diag, alloc, te, "group {s}: item {d} writes a rest group, which reads to the end of the extent, and another item follows it", .{ n.list, i });
                            }
                            // an inner rest item, written inside this one,
                            // starts later
                            top.last_start = @max(top.last_start orelse 0, at);
                        }
                    },
                }
            },
            .ext => {
                try self.put(1, 0);
                try self.block(n.body, ent, ds, env.*);
            },
            .choice => {
                // the first `alt` with content, else the first `alt`
                var sel = &n.body[0];
                for (n.body) |*a| {
                    if (try self.hasContent(a.body, ent, ds)) {
                        sel = a;
                        break;
                    }
                }
                if (n.ext) try self.put(1, 0);
                try self.ecwn(@intCast(sel.value), 0, @intCast(n.value - 1));
                try self.block(sel.body, ent, ds, env.*);
            },
            .alt => unreachable, // an `alt` is written by its `choice`
            .inner => try self.innerNode(n, ent),
            .count => {
                // Version 0.21: n until the group fills it in (ruling 30)
                try self.cpend.append(alloc, .{ .at = self.pos, .cnt = n.cnt.?, .value = n.cnt.?.plus });
                try self.ccur.put(alloc, n.cnt.?, self.cpend.items.len - 1);
                try self.zeros(n.cnt.?.len);
            },
            .fx => unreachable, // an `fx` line is a line of a chain
        }
    }

    // Version 0.34: the `inner` line. The checks of the line, a cursor on a
    // whole byte, then the inner pack's encoding of the same entity at the
    // cursor. The inner kind: Entity.inner_kind when it names the inner
    // format, else Entity.kind when it does, else the `requires` lines.
    fn innerNode(self: *SEnc, n: *const SNode, ent: *const Entity) anyerror!void {
        const alloc = self.alloc;
        const ip = try innerLookup(alloc, self.diag, self.p, n);
        if (self.pos % 8 != 0) return bad(self.diag, alloc, te, "inner {s}: the cursor at bit {d} is not on a whole byte", .{ ip.format, self.pos });
        if (n.run) if (self.run_write) |w| {
            const all = w.bytes(alloc, ip, self.diag) catch |err| {
                if (err == error.OutOfMemory) return err;
                self.diag.msg = try std.fmt.allocPrint(alloc, "inner {s} run: {s}", .{ ip.format, self.diag.msg });
                return err;
            };
            return self.putBytes(all);
        };
        var sub = ent.*;
        innerKind(&sub, ip);
        const hex = encodePack(alloc, ip, &sub, self.diag) catch |err| {
            if (err == error.OutOfMemory) return err;
            self.diag.msg = try std.fmt.allocPrint(alloc, "inner {s}: {s}", .{ ip.format, self.diag.msg });
            return err;
        };
        const bytes = hexDecode(alloc, hex) catch return bad(self.diag, alloc, te, "inner {s}: its encoding is not bytes", .{ip.format});
        // a message that could not be found again (ruling 8 of 0.92)
        if (n.run and bytes.len == 0) return bad(self.diag, alloc, te, "inner {s} run: the message writes no byte", .{ip.format});
        return self.putBytes(bytes);
    }

    fn putBytes(self: *SEnc, bytes: []const u8) !void {
        try self.ensure(self.pos + bytes.len * 8);
        @memcpy(self.out.items[self.pos / 8 ..][0..bytes.len], bytes);
        self.pos += bytes.len * 8;
    }

    // Version 0.19 ----------------------------------------------------------

    fn putN(self: *SEnc, len: usize, value: u64) !void {
        if (len > 0) try self.put(len, value);
    }

    // A constrained whole number; v is within lb..ub.
    fn ecwn(self: *SEnc, v: i64, lb: i64, ub: i64) !void {
        try self.putN(uperBits(uperRange(lb, ub)), uperRange(lb, v));
    }

    fn elenDet(self: *SEnc, n: usize, what: []const u8) !void {
        if (n < 128) return self.put(8, n);
        if (n < 16384) return self.put(16, 0x8000 | @as(u64, n));
        return bad(self.diag, self.alloc, te, "{s}: a length of {d} needs a fragmented length", .{ what, n });
    }

    fn minUnsigned(v: u64) usize {
        var n: usize = 1;
        while (n < 8 and (v >> @as(u6, @intCast(8 * n))) != 0) n += 1;
        return n;
    }

    fn minSigned(v: i64) usize {
        var n: usize = 1;
        while (n < 8) : (n += 1) {
            const half = @as(i64, 1) << @as(u6, @intCast(8 * n - 1));
            if (v >= -half and v < half) break;
        }
        return n;
    }

    // A length determinant of the octet count, then the octets.
    fn eoctets(self: *SEnc, v: u64, n: usize, what: []const u8) !void {
        try self.elenDet(n, what);
        try self.put(8 * n, v);
    }

    fn esmall(self: *SEnc, v: u64, what: []const u8) !void {
        if (v <= 63) return self.put(7, v);
        try self.put(1, 1);
        try self.eoctets(v, minUnsigned(v), what);
    }

    // The integer a value is on an `int:` locator: the value, or
    // round((x - o) / f).
    fn uperInt(self: *SEnc, ln: *const Line, mv: MV) !i64 {
        const t = ln.transform;
        switch (t.kind) {
            .uscale, .sscale => {
                const x = mvFloat(mv) catch return bad(self.diag, self.alloc, te, "field {s}: not a number", .{ln.key});
                const r = @round(t.factor.div(x - t.offset)); // half away from zero
                if (!(r >= -9223372036854775808.0 and r < 9223372036854775808.0)) {
                    return bad(self.diag, self.alloc, te, "field {s}: the value is beyond 64 bits", .{ln.key});
                }
                return @intFromFloat(r);
            },
            else => {
                if (mv != .int) return bad(self.diag, self.alloc, te, "field {s}: not an integer", .{ln.key});
                return mv.int;
            },
        }
    }

    fn uperField(self: *SEnc, n: *const SNode, u: ULoc, ent: *const Entity, ds: DS) !void {
        const alloc = self.alloc;
        const ln = &n.ln;
        const what = ln.key;
        const mv_opt = try self.fieldValue(n, ent, ds);
        switch (u.form) {
            .int_c => {
                const v = if (mv_opt) |mv| try self.uperInt(ln, mv) else u.lb;
                if (v >= u.lb and v <= u.ub) {
                    if (u.ext) try self.put(1, 0);
                    return self.ecwn(v, u.lb, u.ub);
                }
                if (!u.ext) return bad(self.diag, alloc, te, "field {s}: {d} is outside {d}..{d}", .{ what, v, u.lb, u.ub });
                try self.put(1, 1);
                try self.eoctets(@bitCast(v), minSigned(v), what);
            },
            .int_semi => {
                // an absent key: lb in one octet
                const v = if (mv_opt) |mv| try self.uperInt(ln, mv) else u.lb;
                if (v < u.lb) return bad(self.diag, alloc, te, "field {s}: {d} is below {d}", .{ what, v, u.lb });
                const d = uperRange(u.lb, v);
                try self.eoctets(d, minUnsigned(d), what);
            },
            .int_un => {
                const v = if (mv_opt) |mv| try self.uperInt(ln, mv) else 0;
                try self.eoctets(@bitCast(v), minSigned(v), what);
            },
            .enum_ => {
                const v = if (mv_opt) |mv| try self.uperInt(ln, mv) else 0;
                if (v < 0) return bad(self.diag, alloc, te, "field {s}: a negative index {d}", .{ what, v });
                if (v <= u.ub) {
                    if (u.ext) try self.put(1, 0);
                    return self.ecwn(v, 0, u.ub);
                }
                if (!u.ext) return bad(self.diag, alloc, te, "field {s}: the index {d} is beyond the {d} root values", .{ what, v, u.ub + 1 });
                try self.put(1, 1);
                try self.esmall(@intCast(v - u.ub - 1), what);
            },
            .chars_c, .chars_u, .octets_c, .octets_u => {
                const chars = u.form == .chars_c or u.form == .chars_u;
                var bytes: []const u8 = &.{};
                if (mv_opt) |mv| {
                    if (mv != .str) return bad(self.diag, alloc, te, "field {s}: not text", .{what});
                    if (chars) {
                        for (mv.str) |c| if (c > 127) return bad(self.diag, alloc, te, "field {s}: a character above 127", .{what});
                        bytes = mv.str;
                    } else if (ln.transform.kind == .hex) {
                        if (mv.str.len % 2 != 0) return bad(self.diag, alloc, te, "field {s}: hex text of odd length", .{what});
                        const out = try alloc.alloc(u8, mv.str.len / 2);
                        for (out, 0..) |*b, i| {
                            const hi = hexVal(mv.str[2 * i]) orelse return bad(self.diag, alloc, te, "field {s}: not hex text", .{what});
                            const lo = hexVal(mv.str[2 * i + 1]) orelse return bad(self.diag, alloc, te, "field {s}: not hex text", .{what});
                            b.* = hi * 16 + lo;
                        }
                        bytes = out;
                    } else bytes = mv.str;
                } else {
                    // an absent key: lb characters of code 0, lb zero octets
                    const z = try alloc.alloc(u8, @intCast(u.lb));
                    @memset(z, 0);
                    bytes = z;
                }
                const constrained = u.form == .chars_c or u.form == .octets_c;
                if (constrained) {
                    if (bytes.len < u.lb or bytes.len > u.ub) return bad(self.diag, alloc, te, "field {s}: a count of {d} is outside {d}..{d}", .{ what, bytes.len, u.lb, u.ub });
                    try self.ecwn(@intCast(bytes.len), u.lb, u.ub);
                } else try self.elenDet(bytes.len, what);
                for (bytes) |c| try self.put(if (chars) 7 else 8, c);
            },
        }
    }
};

fn seqEncode(alloc: std.mem.Allocator, p: *const Pack, e: *const Entity, diag: *Diag, held_check: bool) anyerror![]u8 {
    const run_write = diag.run_write;
    diag.run_write = null;
    var table = SwTable{};
    if (p.seq_switch) {
        // Version 0.20: dry runs until the cases assumed ahead are the cases
        // the written bits select
        var iter: usize = 0;
        while (true) : (iter += 1) {
            var dry = SEnc{ .alloc = alloc, .p = p, .diag = diag, .out = std.ArrayList(u8).init(alloc), .table = &table, .dry = true, .run_write = run_write, .held_check = held_check };
            try dry.exts.append(alloc, .{ .bits = false });
            dry.body(p.seq.?, e, null, false) catch |err| {
                if (err == error.OutOfMemory) return err;
                break; // the final encode reports it (ruling 34)
            };
            if (!dry.changed) break;
            // a prediction that never settles (ruling 33)
            if (iter == 32) return bad(diag, alloc, E.@"transform-encode", "the predicted switch cases do not settle", .{});
        }
    }
    var enc = SEnc{ .alloc = alloc, .p = p, .diag = diag, .out = std.ArrayList(u8).init(alloc), .table = if (p.seq_switch) &table else null, .run_write = run_write, .held_check = held_check };
    try enc.exts.append(alloc, .{ .bits = false });
    try enc.body(p.seq.?, e, null, false);
    // the message extent ends at its byte-padded end, under `armor sixbit`
    // (0.14) too (ruling 43 of 0.21)
    try enc.checkExt(enc.exts.items[0], (enc.pos + 7) / 8 * 8);
    // the count fields, in range once the groups have filled them (ruling 30)
    for (enc.cpend.items) |c| {
        if (c.value < 0 or c.value > std.math.maxInt(u64) or !fitsBits(@intCast(c.value), c.cnt.len)) {
            return bad(diag, alloc, E.@"transform-encode", "count {s}: the value {d} is outside 0 to 2^{d} - 1", .{ c.cnt.name, c.value, c.cnt.len });
        }
        setBits(enc.out.items, p.msb, c.at, c.cnt.len, @intCast(c.value));
    }
    // armored: the bits to the cursor, not rounded to a byte (Version 0.14)
    if (p.armor) return armorEncode(alloc, enc.out.items, enc.pos);
    // a message is a whole number of bytes; `length … whole` holds that
    // number plus n
    // UPER: an encoding of no bits is one octet 00 (X.691 10.1.3)
    if (p.uper and enc.out.items.len == 0) try enc.out.append(0);
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

// The text of `<dir>/<name>/pack.def`, when `name` is a directory holding a
// readable file `pack.def`; null otherwise.
fn readPackDefIn(alloc: std.mem.Allocator, dir: std.fs.Dir, name: []const u8) ?[]const u8 {
    var sub = dir.openDir(name, .{}) catch return null;
    defer sub.close();
    const st = sub.statFile("pack.def") catch return null;
    if (st.kind == .directory) return null;
    return sub.readFileAlloc(alloc, "pack.def", max_file) catch null;
}

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

// The packs `loadAllPacks` left out: on a wire this build does not have
// (Version 0.24).
var packs_left_out: usize = 0;

// Load every pack under `packs_dir` (a directory holding a pack.def), in byte
// order of directory name. Returns the directory names of the loaded packs.
// A build with fewer wires (Version 0.24) leaves out each pack on a wire it
// does not have, and counts it.
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
        if (try packOnUnbuiltWire(alloc, def_text)) {
            packs_left_out += 1;
            continue;
        }
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

// Are the `from` and `to` formats of a vector both loaded (and, in a build
// without every wire, neither an outer pack)? A vector that does not parse
// counts as loaded, so that `runVector` reports it.
// A format that is not a directory under the packs directory is not left
// out: the vector pins `unknown-format` and is run.
fn vectorFormatsLoaded(eng: *Engine, packs_dir: []const u8, text: []const u8) bool {
    const parsed = std.json.parseFromSliceLeaky(JValue, eng.scratch, text, .{}) catch return true;
    if (parsed != .object) return true;
    for ([_][]const u8{ "from", "to" }) |k| {
        const fmt = getStr(parsed.object, k) orelse return true;
        if (eng.findPack(fmt)) |p| {
            // ruling 1 of 0.34: a build without every wire runs no vector
            // of an outer pack, since whether its inner pack loads differs
            // between builds
            if (!all_wires and p.inners.items.len > 0) return false;
            continue;
        }
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
    // Version 0.92: `expect_results`, and `run` beside `expect_error`
    const results = vobj.get("expect_results");
    const whole_run = vobj.get("run") != null;
    if (vobj.get("run")) |rv| {
        if (rv != .bool or !rv.bool or expect_error == null) return "invalid vector: `run` is `true`, with `expect_error`";
    }
    const given = @as(usize, @intFromBool(expect != null)) + @intFromBool(expect_error != null) + @intFromBool(results != null);
    if (given == 0) return "neither `expect` nor `expect_error` nor `expect_results`";
    if (given > 1) return "more than one of `expect`, `expect_error` and `expect_results`";
    if (results) |rv| if (rv != .array) return "`expect_results` is not an array";
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

    // 1. convert(from, to, input[, context]); convert_run (Version 0.92)
    if (results != null or whole_run) {
        if (eng.convertRun(from_fmt, to_fmt, input, context)) |got| {
            const want = if (results) |rv| rv.array.items else
                return try std.fmt.allocPrint(alloc, "expected error {s} of convert_run, it gave {d} results", .{ expect_error.?, got.len });
            if (try checkResults(alloc, want, got)) |why| return why;
        } else |err| {
            if (err == error.OutOfMemory) return err;
            const want = expect_error orelse
                return try std.fmt.allocPrint(alloc, "convert_run failed: {s}", .{clip(eng.last_error)});
            if (!std.mem.eql(u8, @errorName(err), want) or !beginsWithKind(eng.last_error, want)) {
                return try std.fmt.allocPrint(alloc, "expected error {s} of convert_run, got: {s}", .{ want, clip(eng.last_error) });
            }
            return null;
        }
    } else if (eng.convert(from_fmt, to_fmt, input, context)) |got| {
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
        if (std.mem.eql(u8, key, "@inner_kind")) {
            // Version 0.34: the kind name Entity.inner_kind holds
            if (ent.inner_kind_fmt == null) return try std.fmt.allocPrint(alloc, "@inner_kind: expected {s}, the entity records no inner kind", .{exp});
            if (!std.mem.eql(u8, ent.inner_kind_name, exp)) {
                return try std.fmt.allocPrint(alloc, "@inner_kind: expected {s}, got ({s}, {s})", .{ exp, ent.inner_kind_fmt.?, ent.inner_kind_name });
            }
            continue;
        }
        if (try checkModelKey(alloc, &ent, key, exp, completed)) |why| return why;
    }
    return null;
}

// The results of `convert_run` against `expect_results` (Version 0.92). null:
// they agree.
fn checkResults(alloc: std.mem.Allocator, want: []const JValue, got: []const Engine.RunResult) !?[]const u8 {
    for (want) |w| {
        if (w != .object) return "an entry of `expect_results` is not an object";
        if ((getStr(w.object, "expect") == null) == (getStr(w.object, "expect_error") == null)) return "an entry of `expect_results` holds one of `expect` and `expect_error`";
    }
    if (want.len != got.len) return try std.fmt.allocPrint(alloc, "expected {d} results, convert_run gave {d}", .{ want.len, got.len });
    for (want, got, 0..) |w, g, i| {
        if (getStr(w.object, "expect")) |exp| {
            switch (g) {
                .ok => |b| if (!std.mem.eql(u8, b, exp)) return try std.fmt.allocPrint(alloc, "result {d} mismatch\n   expected: {s}\n   got:      {s}", .{ i, clip(exp), clip(b) }),
                .err => |e| return try std.fmt.allocPrint(alloc, "result {d}: expected {s}, got: {s}", .{ i, clip(exp), clip(e.msg) }),
            }
        } else {
            const kind = getStr(w.object, "expect_error").?;
            switch (g) {
                .ok => |b| return try std.fmt.allocPrint(alloc, "result {d}: expected error {s}, got: {s}", .{ i, kind, clip(b) }),
                .err => |e| if (!std.mem.eql(u8, @errorName(e.kind), kind) or !beginsWithKind(e.msg, kind)) {
                    return try std.fmt.allocPrint(alloc, "result {d}: expected error {s}, got: {s}", .{ i, kind, clip(e.msg) });
                },
            }
        }
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
    // Version 0.34: `"@inner_kind"`, an entity that records no inner kind
    if (std.mem.eql(u8, key, "@inner_kind")) {
        if (ent.inner_kind_fmt) |f| return try std.fmt.allocPrint(alloc, "@absent @inner_kind: the entity records ({s}, {s})", .{ f, ent.inner_kind_name });
        return null;
    }
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

// `relative`: a float of a completed entity compares within 1e-9 relative or
// 1e-7 absolute; otherwise within 1e-9.
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
            // of a completed entity: within 1e-9 relative, or within 1e-7
            // absolute (vector-format step 3, Version 0.16)
            if (relative) return @abs(f - e) < 1e-9 * @max(@abs(f), @abs(e)) or @abs(f - e) < 1e-7;
            return @abs(f - e) <= 1e-9;
        },
    }
}

// Run one load vector on a fresh engine. Returns null on pass, else why it
// failed.
// `runLoadVector`'s answer for a vector this build does not run.
const skip_vector: []const u8 = "skip";

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
    // a build with fewer wires (Version 0.24) does not run a load vector
    // with a pack on a wire it does not have
    for (pack_texts.items) |pt| {
        if (try packOnUnbuiltWire(alloc, pt)) return skip_vector;
    }
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
// Version 0.34 adds the kinds raised where decode or encode reaches an
// `inner` line: `unknown-format`, `bad-directive`, `distribution-violation`.
const named_kinds = [_][]const u8{ "malformed-wire", "transform-decode", "transform-encode", "no-kind", "missing-root", "unknown-format", "bad-directive", "distribution-violation", "message-count" };

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

    fn namedKind(err: anyerror, msg: []const u8) bool {
        for (named_kinds) |k| {
            if (std.mem.eql(u8, @errorName(err), k) and beginsWithKind(msg, k)) return true;
        }
        return false;
    }

    fn unnamed(self: *Fuzz, from: []const u8, to: []const u8, what: []const u8, n: usize, err: anyerror) !void {
        if (self.failures.items.len >= 200) return;
        try self.failures.append(try std.fmt.allocPrint(self.eng.alloc, "{s} -> {s}, {s} {d}: convert_run: {s} is not a named kind", .{ from, to, what, n, @errorName(err) }));
    }

    // One input through `convert`: it returns a message, or fails with a
    // named kind and a message that begins with it. A panic ends the run.
    fn one(self: *Fuzz, from: []const u8, to: []const u8, input: []const u8, what: []const u8, n: usize) !void {
        _ = self.arena.reset(.free_all);
        self.counted.peak = 0;
        self.eng.scratch = self.arena.allocator();
        defer self.eng.scratch = self.eng.alloc;
        self.inputs += 1;
        // a carrier pack's input through `convert_run` too (Version 0.92)
        const carrier = if (self.eng.findPack(from)) |fp| fp.has_run else false;
        if (carrier) if (self.eng.convertRun(from, to, input, null)) |got| {
            for (got) |g| if (g == .err and !namedKind(g.err.kind, g.err.msg)) try self.unnamed(from, to, what, n, g.err.kind);
        } else |err| {
            if (err != error.OutOfMemory and !namedKind(err, self.eng.last_error)) try self.unnamed(from, to, what, n, err);
        };
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
    // hundred thousand list items and a `tlv` pack as as many items of one
    // tag (`0100`).
    fn deep(self: *Fuzz, from: []const u8, to: []const u8) !void {
        const alloc = self.eng.alloc;
        const units = [_][]const u8{ "<a>", "<a b=\"c\">", "[", "{\"a\":", "{\"properties\":{\"a\":[", "ff", "82", "0a", "0b", "0aff", "22ffffffffffffffffff01", "0100" };
        for (units, 0..) |u, n| {
            const reps: usize = if (n < 5) 200000 else 700000 / u.len;
            const big = try alloc.alloc(u8, u.len * reps);
            defer alloc.free(big);
            for (0..reps) |r| @memcpy(big[r * u.len ..][0..u.len], u);
            try self.one(from, to, big, "repeated unit", n);
        }
        if (self.eng.findPack(from)) |fp| {
            if (isW(fp.wire, .cbor)) try self.cbor(from, to, fp);
        }
    }

    // A `cbor` format (Version 0.28): hostile items, then random ones. Deep
    // nesting through arrays, maps, tags and indefinite items; declared
    // lengths and counts far beyond the input; indefinite items that never
    // end; wide maps whose keys are all compared; and random items of every
    // major type, with heads of any length, cut short or with a byte changed.
    fn cbor(self: *Fuzz, from: []const u8, to: []const u8, fp: *const Pack) !void {
        const alloc = self.eng.alloc;
        var buf = std.ArrayList(u8).init(alloc);
        defer buf.deinit();
        const Rep = struct { head: []const u8, unit: []const u8, n: usize, tail: []const u8 };
        const reps = [_]Rep{
            .{ .head = "", .unit = "81", .n = 200000, .tail = "00" },
            .{ .head = "", .unit = "a100", .n = 100000, .tail = "00" },
            .{ .head = "", .unit = "c1", .n = 200000, .tail = "a0" },
            .{ .head = "", .unit = "d9ffff", .n = 100000, .tail = "80" },
            .{ .head = "", .unit = "9f", .n = 200000, .tail = "" },
            .{ .head = "", .unit = "bf00", .n = 100000, .tail = "" },
            .{ .head = "a1009f", .unit = "00", .n = 300000, .tail = "" },
            .{ .head = "829f", .unit = "f6", .n = 300000, .tail = "" },
            .{ .head = "a1005f", .unit = "4100", .n = 150000, .tail = "" },
            .{ .head = "a1007f", .unit = "6161", .n = 150000, .tail = "" },
            .{ .head = "a1005bffffffffffffffff", .unit = "00", .n = 1000, .tail = "" },
            .{ .head = "a1009bffffffffffffffff", .unit = "00", .n = 1000, .tail = "" },
            .{ .head = "bb7fffffffffffffff", .unit = "0000", .n = 1000, .tail = "" },
            .{ .head = "9b7fffffffffffffff", .unit = "a0", .n = 1000, .tail = "" },
            .{ .head = "a1009a000493e0", .unit = "f6", .n = 300000, .tail = "" },
            .{ .head = "829a000493e0", .unit = "a0", .n = 300000, .tail = "" },
            .{ .head = "a1007a000493e0", .unit = "61", .n = 300000, .tail = "" },
            .{ .head = "a10078ff", .unit = "c3", .n = 1000, .tail = "" },
            .{ .head = "bf", .unit = "6161", .n = 1000, .tail = "ff" },
        };
        for (reps, 0..) |rp, k| {
            buf.clearRetainingCapacity();
            try buf.appendSlice(rp.head);
            for (0..rp.n) |_| try buf.appendSlice(rp.unit);
            try buf.appendSlice(rp.tail);
            try self.one(from, to, buf.items, "hostile cbor", k);
        }
        // a map of 65536 distinct keys, and the same with its last key equal
        // to its first
        for (0..2) |k| {
            buf.clearRetainingCapacity();
            try buf.appendSlice(if (fp.cbor_array) "81ba00010000" else "ba00010000");
            for (0..65536) |i| {
                const key: u32 = if (k == 1 and i == 65535) 0 else @intCast(i);
                try buf.writer().print("1a{x:0>8}f6", .{key});
            }
            try self.one(from, to, buf.items, "wide cbor map", k);
        }
        var prng = std.Random.DefaultPrng.init(0x28cb0428);
        const r = prng.random();
        var bin = std.ArrayList(u8).init(alloc);
        defer bin.deinit();
        for (0..cbor_fuzz_items) |k| {
            bin.clearRetainingCapacity();
            if (fp.cbor_tag) |t| {
                if (r.uintLessThan(u8, 8) != 0) try fuzzHead(r, &bin, 6, t);
            }
            const top: u8 = if (r.boolean()) 4 else 5;
            const n = r.uintLessThan(u64, 12);
            try fuzzHead(r, &bin, top, if (top == 5) n else n);
            for (0..@intCast(if (top == 5) 2 * n else n)) |_| try fuzzItem(r, &bin, 1);
            // cut short, or a byte changed, now and then
            switch (r.uintLessThan(u8, 6)) {
                0 => if (bin.items.len > 0) bin.shrinkRetainingCapacity(r.uintLessThan(usize, bin.items.len)),
                1 => if (bin.items.len > 0) {
                    bin.items[r.uintLessThan(usize, bin.items.len)] = r.int(u8);
                },
                else => {},
            }
            buf.clearRetainingCapacity();
            for (bin.items) |b| try buf.writer().print("{x:0>2}", .{b});
            try self.one(from, to, buf.items, "random cbor", k);
        }
    }
};

const cbor_fuzz_items: usize = 3000;

// A head of a random length: the shortest, or longer than it needs.
fn fuzzHead(r: std.Random, out: *std.ArrayList(u8), major: u8, v: u64) !void {
    const m: u8 = major << 5;
    var w: u8 = if (v < 24) 0 else if (v <= 0xff) 1 else if (v <= 0xffff) 2 else if (v <= 0xffffffff) 3 else 4;
    if (r.uintLessThan(u8, 4) == 0) w = @max(w, 1 + r.uintLessThan(u8, 4));
    if (w == 0) return out.append(m | @as(u8, @intCast(v)));
    try out.append(m | (23 + w));
    const nb: usize = @as(usize, 1) << @intCast(w - 1);
    var i: usize = nb;
    while (i > 0) {
        i -= 1;
        try out.append(if (i >= 8) 0 else @truncate(v >> @as(u6, @intCast(8 * i))));
    }
}

// One random item: the keys and values the probe packs use, every major
// type, tags, indefinite lengths, now and then a byte that is not well formed.
fn fuzzItem(r: std.Random, out: *std.ArrayList(u8), depth: usize) anyerror!void {
    const texts = [_][]const u8{ "a", "k", "n", "m", "v", "b", "s", "name", "flag", "track", "x-app", "4" };
    const leaf = depth > 70 or r.uintLessThan(u8, 3) != 0;
    const pick = if (leaf) r.uintLessThan(u8, 8) else 8 + r.uintLessThan(u8, 5);
    switch (pick) {
        0 => try fuzzHead(r, out, 0, if (r.boolean()) r.uintLessThan(u64, 12) else r.int(u64)),
        1 => try fuzzHead(r, out, 1, if (r.boolean()) r.uintLessThan(u64, 12) else r.int(u64)),
        2 => {
            const n = r.uintLessThan(usize, 6);
            try fuzzHead(r, out, 2, n);
            for (0..n) |_| try out.append(r.int(u8));
        },
        3 => {
            const t = texts[r.uintLessThan(usize, texts.len)];
            try fuzzHead(r, out, 3, t.len);
            try out.appendSlice(t);
        },
        4 => {
            const simple = [_][]const u8{ "f4", "f5", "f6", "f7", "f820", "f813", "f93e00", "f97c00", "f97e00", "fa47c35000", "fb3fb999999999999a", "fb7ff8000000000001", "e0" };
            const sv = simple[r.uintLessThan(usize, simple.len)];
            var i: usize = 0;
            while (i < sv.len) : (i += 2) try out.append(hexVal(sv[i]).? * 16 + hexVal(sv[i + 1]).?);
        },
        5 => try out.append(r.int(u8)),
        6 => try out.append(0xff),
        7 => {
            // a chunked string
            const major: u8 = if (r.boolean()) 2 else 3;
            try out.append((major << 5) | 31);
            for (0..r.uintLessThan(usize, 3)) |_| {
                try fuzzHead(r, out, major, 1);
                try out.append(if (major == 3) 'a' else r.int(u8));
            }
            if (r.uintLessThan(u8, 8) != 0) try out.append(0xff);
        },
        8, 9 => {
            const n = r.uintLessThan(u64, 4);
            try fuzzHead(r, out, 4, n);
            for (0..@intCast(n)) |_| try fuzzItem(r, out, depth + 1);
        },
        10 => {
            const n = r.uintLessThan(u64, 4);
            try fuzzHead(r, out, 5, n);
            for (0..@intCast(2 * n)) |_| try fuzzItem(r, out, depth + 1);
        },
        11 => {
            // an indefinite array or map, ended or not
            const map = r.boolean();
            try out.append(if (map) 0xbf else 0x9f);
            const n = r.uintLessThan(usize, 4);
            for (0..if (map) 2 * n else n) |_| try fuzzItem(r, out, depth + 1);
            if (r.uintLessThan(u8, 8) != 0) try out.append(0xff);
        },
        else => {
            try fuzzHead(r, out, 6, r.uintLessThan(u64, 70000));
            try fuzzItem(r, out, depth + 1);
        },
    }
}

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
        if (eng.findPack(fmt) == null) {
            try stdout.print("error: no loaded pack has format {s}\n", .{fmt});
            try bw.flush();
            std.process.exit(2);
        }
        // with the keys of the packs its `inner` lines name (Version 0.34)
        for (try eng.modelKeysOf(fmt)) |k| try stdout.print("{s}\n", .{k});
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
            if ((only_opt != null or packs_left_out > 0) and !vectorFormatsLoaded(&eng, packs_dir, vtext)) {
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
    var lskipped: usize = 0;
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
                if (detail.ptr == skip_vector.ptr) {
                    ltotal -= 1;
                    lskipped += 1;
                    continue;
                }
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
            if ((only_opt != null or packs_left_out > 0) and !vectorFormatsLoaded(&eng, packs_dir, ctext)) {
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
    if (!all_wires) {
        try stdout.print("wires of this build:", .{});
        inline for (comptime std.enums.values(Wire)) |w| {
            if (comptime built(w)) try stdout.print(" {s}", .{@tagName(w)});
        }
        try stdout.print("\n", .{});
        try stdout.print("left out: {d} packs on a wire this build does not have, {d} load vectors with such a pack\n", .{ packs_left_out, lskipped });
    }
    try bw.flush();
    if (passed != total or lpassed != ltotal or cpassed != ctotal) std.process.exit(1);
}
