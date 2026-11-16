// gt-engines Zig engine — clean-room implementation from spec/ and packs/ only.
// Implements the format engine: decode(wire->model), encode(model->wire),
// convert(from,to[,context]) = decode, fill from context, derive, encode; plus
// a conformance harness.
//
// Wires: xml, geojson, json, bits (lsb and msb bit order), protobuf.
// Transforms: string, float, int, iso8601_ms, bool, uint, twos,
// linscale:<maxpos>:<range>, uscale/sscale:<factor>[:<offset>], f32, f64,
// ascii, pstring, pvarint, psint, pdouble, pfloat.
// Model modules and distribution (spec Version 0.4), message kinds
// (`kind` / `when` / `requires`, spec Version 0.5) and the mapping rules of
// spec Version 0.6 (`const`, `default`, `map` / `via`, the field options
// `swap` / `trim` / `optional`, a `root` per kind, `derive` lines in model
// modules, caller-supplied keys) are checked at load by `Engine`. Groups (spec
// Version 0.7): `list` lines in model modules, `group … end` blocks on every
// wire, lists in the entity. Stdlib only.
//
// Errors the specification names are Zig errors whose name IS the spec token
// (`error.@"no-kind"`); `Engine.last_error` holds `<kind>: <detail>`.

const std = @import("std");

// ---------------------------------------------------------------------------
// Model
// ---------------------------------------------------------------------------

const MV = union(enum) {
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

// An entity, and an item of a list: an item holds model keys and lists exactly
// as an entity does, without residue and without a kind.
const Entity = struct {
    fields: std.StringHashMap(MV),
    // list name -> items; a present, empty list is an entry of length 0
    lists: std.StringHashMap([]Entity),
    residue: std.ArrayList(Residue),
    // Entity.kind is the pair (format, kind name); null when no kind is recorded.
    kind_fmt: ?[]const u8 = null,
    kind_name: []const u8 = "",

    fn init(alloc: std.mem.Allocator) Entity {
        return .{
            .fields = std.StringHashMap(MV).init(alloc),
            .lists = std.StringHashMap([]Entity).init(alloc),
            .residue = std.ArrayList(Residue).init(alloc),
        };
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
    UnknownDirective,
    UnknownTransform,
    UnknownWire,
    UnknownFormat,
    WrongTransformKind,
    MalformedBitsLocator,
    @"missing-root",
    MalformedDirective,
    MalformedModule,
    UnknownDistribution,
    UnknownKeyType,
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
};

fn bad(diag: *Diag, alloc: std.mem.Allocator, err: anyerror, comptime fmt: []const u8, args: anytype) anyerror {
    diag.msg = std.fmt.allocPrint(alloc, fmt, args) catch "";
    return err;
}

// ---------------------------------------------------------------------------
// Pack model
// ---------------------------------------------------------------------------

const Wire = enum { xml, geojson, json, bits, protobuf };
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
    pstring,
    pvarint,
    psint,
    pdouble,
    pfloat,
};

const KindCat = enum { text, bits, proto };

fn kindCategory(k: TKind) KindCat {
    return switch (k) {
        .string, .float, .int, .iso8601_ms, .bool_ => .text,
        .uint, .twos, .linscale, .uscale, .sscale, .f32_, .f64_, .ascii => .bits,
        .pstring, .pvarint, .psint, .pdouble, .pfloat => .proto,
    };
}

fn wireCategory(w: Wire) KindCat {
    return switch (w) {
        .xml, .geojson, .json => .text,
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
const Dist = enum { public, controlled };

fn parseDist(s: []const u8) !Dist {
    if (std.mem.eql(u8, s, "public")) return .public;
    if (std.mem.eql(u8, s, "controlled")) return .controlled;
    return E.UnknownDistribution;
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

const DFn = enum { copy, hypot, bearing, east_of, north_of, neg, scale, offset, join };

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
        .float, .linscale, .uscale, .sscale, .f32_, .f64_, .pdouble, .pfloat => .float,
        .int, .iso8601_ms, .bool_, .uint, .twos, .pvarint, .psint => .int,
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
            try toks.append(line[start..i]);
            if (i < line.len) i += 1;
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

// Decimal number text: [sign] digits [. digits] [e [sign] digits].
fn isDecimalText(s: []const u8) bool {
    var i: usize = 0;
    if (i < s.len and (s[i] == '-' or s[i] == '+')) i += 1;
    var nd: usize = 0;
    while (i < s.len and isDigit(s[i])) : (i += 1) nd += 1;
    if (i < s.len and s[i] == '.') {
        i += 1;
        while (i < s.len and isDigit(s[i])) : (i += 1) nd += 1;
    }
    if (nd == 0) return false;
    if (i < s.len and (s[i] == 'e' or s[i] == 'E')) {
        i += 1;
        if (i < s.len and (s[i] == '-' or s[i] == '+')) i += 1;
        var ne: usize = 0;
        while (i < s.len and isDigit(s[i])) : (i += 1) ne += 1;
        if (ne == 0) return false;
    }
    return i == s.len;
}

// Decimal text to the nearest IEEE-754 double.
fn parseDecimal(s: []const u8) !f64 {
    if (!isDecimalText(s)) return E.@"transform-decode";
    const f = std.fmt.parseFloat(f64, s) catch return E.@"transform-decode";
    if (!std.math.isFinite(f)) return E.@"transform-decode"; // a model float is always finite
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

fn parseDecimalInt(s: []const u8) !i64 {
    var body = s;
    if (body.len > 0 and (body[0] == '-' or body[0] == '+')) body = body[1..];
    if (!allDigits(body)) return E.@"transform-decode";
    return std.fmt.parseInt(i64, s, 10) catch E.@"transform-decode";
}

fn parseUnsigned(s: []const u8) ?u64 {
    if (!allDigits(s)) return null;
    return std.fmt.parseInt(u64, s, 10) catch null;
}

fn parseFactor(fac: []const u8) ?Factor {
    if (std.mem.indexOfScalar(u8, fac, '/')) |slash| {
        // a fraction <num>/<den> of two decimal integers
        const ns = fac[0..slash];
        const ds = fac[slash + 1 ..];
        const nbody = if (ns.len > 0 and ns[0] == '-') ns[1..] else ns;
        if (!allDigits(nbody) or !allDigits(ds)) return null;
        return .{
            .is_frac = true,
            .num = std.fmt.parseFloat(f64, ns) catch return null,
            .den = std.fmt.parseFloat(f64, ds) catch return null,
        };
    }
    return .{ .factor = parseDecimal(fac) catch return null };
}

fn parseTransform(s: []const u8) !Transform {
    const simple = [_]struct { n: []const u8, k: TKind }{
        .{ .n = "string", .k = .string },   .{ .n = "float", .k = .float },
        .{ .n = "int", .k = .int },         .{ .n = "iso8601_ms", .k = .iso8601_ms },
        .{ .n = "bool", .k = .bool_ },      .{ .n = "uint", .k = .uint },
        .{ .n = "twos", .k = .twos },       .{ .n = "f32", .k = .f32_ },
        .{ .n = "f64", .k = .f64_ },        .{ .n = "ascii", .k = .ascii },
        .{ .n = "pstring", .k = .pstring }, .{ .n = "pvarint", .k = .pvarint },
        .{ .n = "psint", .k = .psint },     .{ .n = "pdouble", .k = .pdouble },
        .{ .n = "pfloat", .k = .pfloat },
    };
    for (simple) |e| if (std.mem.eql(u8, s, e.n)) return .{ .kind = e.k };

    var it = std.mem.splitScalar(u8, s, ':');
    const head = it.next() orelse return E.UnknownTransform;
    if (std.mem.eql(u8, head, "linscale")) {
        const mp = it.next() orelse return E.UnknownTransform;
        const rg = it.next() orelse return E.UnknownTransform;
        if (it.next() != null) return E.UnknownTransform;
        return .{
            .kind = .linscale,
            .maxpos = parseDecimal(mp) catch return E.UnknownTransform,
            .range = parseDecimal(rg) catch return E.UnknownTransform,
        };
    }
    if (std.mem.eql(u8, head, "uscale") or std.mem.eql(u8, head, "sscale")) {
        var t = Transform{ .kind = if (head[0] == 'u') .uscale else .sscale };
        const fac = it.next() orelse return E.UnknownTransform;
        t.factor = parseFactor(fac) orelse return E.UnknownTransform;
        if (it.next()) |off| {
            t.offset = parseDecimal(off) catch return E.UnknownTransform;
            if (it.next() != null) return E.UnknownTransform;
        }
        return t;
    }
    return E.UnknownTransform;
}

// The declared type of a key a `derive` line names: a key of `core` or of the
// module itself, else null.
fn deriveKeyType(m: *const Module, core: ?*const Module, text: []const u8) ?KeyType {
    const ref = splitKey(text);
    if (std.mem.eql(u8, ref.module, m.name)) {
        return if (m.key(ref.name)) |k| k.ty else null;
    }
    if (std.mem.eql(u8, ref.module, "core")) {
        const c = core orelse return null;
        return if (c.key(ref.name)) |k| k.ty else null;
    }
    return null;
}

// Check one `derive` line and resolve its function. null: the function name,
// the argument count, a key or a type does not fit.
fn resolveDerive(alloc: std.mem.Allocator, m: *const Module, core: ?*const Module, toks: []const []const u8) ?Derive {
    if (toks.len < 4) return null;
    var d = Derive{ .target = toks[1], .f = .copy, .args = toks[3..] };
    const tt = deriveKeyType(m, core, d.target) orelse return null;
    const at = alloc.alloc(KeyType, d.args.len) catch return null;
    for (d.args, 0..) |a, i| at[i] = deriveKeyType(m, core, a) orelse return null;
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
        d.factor = parseFactor(param orelse return null) orelse return null;
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
    } else return null;
    return d;
}

// Parse one model module file. Fails with `missing-distribution`,
// `missing-source`, `duplicate-key` or `bad-directive` (and the grammar
// errors) at parse. `core` is the loaded `core` module, for the keys a
// `derive` line of another module names.
fn parseModule(alloc: std.mem.Allocator, def_text: []const u8, core: ?*const Module, diag: *Diag) anyerror!*Module {
    const m = try alloc.create(Module);
    m.* = .{
        .name = "",
        .version = "",
        .sources = std.ArrayList([]const u8).init(alloc),
        .keys = std.ArrayList(ModKey).init(alloc),
        .index = std.StringHashMap(usize).init(alloc),
        .lists = std.StringHashMap(void).init(alloc),
        .derives = std.ArrayList(Derive).init(alloc),
    };
    var derive_lines = std.ArrayList([]const []const u8).init(alloc);
    var lines = std.mem.splitScalar(u8, def_text, '\n');
    var tokbuf = std.ArrayList([]const u8).init(alloc);
    while (lines.next()) |line| {
        try tokenizeInto(&tokbuf, line);
        const toks = tokbuf.items;
        if (toks.len == 0) continue;
        const kw = toks[0];
        if (std.mem.eql(u8, kw, "module")) {
            if (toks.len < 2) return E.MalformedDirective;
            m.name = toks[1];
        } else if (std.mem.eql(u8, kw, "version")) {
            if (toks.len < 2) return E.MalformedDirective;
            m.version = toks[1];
        } else if (std.mem.eql(u8, kw, "distribution")) {
            if (toks.len < 2) return E.MalformedDirective;
            m.distribution = try parseDist(toks[1]);
        } else if (std.mem.eql(u8, kw, "source")) {
            if (toks.len < 2) return E.MalformedDirective;
            try m.sources.append(toks[1]);
        } else if (std.mem.eql(u8, kw, "key")) {
            if (toks.len < 4) return E.MalformedDirective;
            const name = toks[1];
            if (name.len == 0 or std.mem.indexOfScalar(u8, name, '.') != null) return E.MalformedModule;
            const ty: KeyType = if (std.mem.eql(u8, toks[2], "string"))
                .string
            else if (std.mem.eql(u8, toks[2], "float"))
                .float
            else if (std.mem.eql(u8, toks[2], "int"))
                .int
            else
                return E.UnknownKeyType;
            if (m.index.contains(name) or m.lists.contains(name)) return bad(diag, alloc, E.@"duplicate-key", "key {s} appears twice", .{name});
            try m.index.put(name, m.keys.items.len);
            try m.keys.append(.{
                .name = name,
                .ty = ty,
                .unit = toks[3],
                .meaning = if (toks.len > 4) toks[4] else "",
            });
        } else if (std.mem.eql(u8, kw, "list")) {
            // list <name> ["meaning"]
            if (toks.len < 2 or toks.len > 3) return E.MalformedDirective;
            const name = toks[1];
            if (name.len == 0 or std.mem.indexOfScalar(u8, name, '.') != null) return E.MalformedModule;
            if (m.index.contains(name) or m.lists.contains(name)) return bad(diag, alloc, E.@"duplicate-key", "list {s}: the name appears twice", .{name});
            try m.lists.put(name, {});
        } else if (std.mem.eql(u8, kw, "derive")) {
            try derive_lines.append(try alloc.dupe([]const u8, toks));
        } else {
            return bad(diag, alloc, E.UnknownDirective, "unknown directive {s}", .{kw});
        }
    }
    if (m.name.len == 0) return E.MalformedModule;
    // `derive` lines are checked once the whole file is read: a line may name
    // a key the file declares further down.
    for (derive_lines.items) |toks| {
        const d = resolveDerive(alloc, m, core, toks) orelse
            return bad(diag, alloc, E.@"bad-directive", "derive {s}: the function, argument count, keys or types do not fit", .{if (toks.len > 1) toks[1] else ""});
        try m.derives.append(d);
    }
    if (m.distribution == null) return E.@"missing-distribution";
    if (m.sources.items.len == 0) return E.@"missing-source";
    return m;
}

// Resolve one line against the pack's wire: parse its locator, check its
// transform belongs to the wire, check the bit length its transform allows.
fn finalizeLine(alloc: std.mem.Allocator, p: *Pack, ln: *Line, in_group: bool, diag: *Diag) anyerror!void {
    // `.`: the item itself as a scalar, inside a group only
    if (std.mem.eql(u8, ln.locator, ".") and (p.wire == .json or p.wire == .geojson or p.wire == .protobuf)) {
        if (!in_group) return bad(diag, alloc, E.@"bad-directive", "line {d}: the locator `.` outside a group", .{ln.lineno});
        ln.dot = true;
    }
    if (ln.isField() and wireCategory(p.wire) != kindCategory(ln.transform.kind)) {
        return bad(diag, alloc, E.WrongTransformKind, "line {d}: transform of {s} does not belong to wire {s}", .{ ln.lineno, ln.key, @tagName(p.wire) });
    }
    if (ln.isField() and ln.transform.kind == .bool_ and p.wire != .json) {
        return bad(diag, alloc, E.WrongTransformKind, "line {d}: bool is valid only on the json wire", .{ln.lineno});
    }
    // `const <locator> present` writes nothing: refused; `=present` is the text
    if (ln.tag == .constant and std.mem.eql(u8, ln.wraw, "present")) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: const {s} present", .{ ln.lineno, ln.locator });
    }
    // field options: an option on a wire or transform it does not apply to
    if (p.wire != .bits and (ln.swap or ln.trim or ln.optional)) {
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
            if (w == null or ps_v == null or l == null or it.next() != null) {
                return bad(diag, alloc, E.MalformedBitsLocator, "line {d}: bits locator {s} is not <word>:<pos>:<len>", .{ ln.lineno, ln.locator });
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
                    else => return bad(diag, alloc, E.MalformedDirective, "line {d}: protobuf path {s} is not field numbers separated by dots", .{ ln.lineno, ln.locator }),
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
    }
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
        const n = parseUnsigned(seg) orelse return E.MalformedDirective;
        if (n == 0 or n > 0x1fffffff) return E.MalformedDirective;
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
    }
    try finalizeLines(alloc, p, g.lines, true, diag);
}

// Checks over one scope: the lines `a` then `b` (common plus one kind, or one
// group body). A list is mapped by at most one group. On `bits`: a group
// counted by a locator is the last thing in its scope, and inside an item
// nothing of fixed size reaches beyond `item <bits>`.
fn checkScope(alloc: std.mem.Allocator, p: *const Pack, a: []const Line, b: []const Line, item_bits: ?usize, diag: *Diag) anyerror!void {
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
                const n = g.count_fixed orelse continue;
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
        try checkScope(alloc, p, g.lines, &.{}, if (p.wire == .bits) g.item_bits else null, diag);
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

fn parsePack(alloc: std.mem.Allocator, def_text: []const u8, diag: *Diag) anyerror!*Pack {
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
    var any_when = false;
    var kind_root = false;
    // The open groups, innermost last. The body lines of every open group
    // collect in `gtmp`; `gfrom` is where each group's begin, `gline` the
    // group's own line, which joins the enclosing lines at its `end`.
    var gstack = std.ArrayList(*Group).init(alloc);
    var gtmp = std.ArrayList(Line).init(alloc);
    var gfrom = std.ArrayList(usize).init(alloc);
    var gline = std.ArrayList(Line).init(alloc);
    var lineno: usize = 0;
    var lines = std.mem.splitScalar(u8, def_text, '\n');
    var tokbuf = std.ArrayList([]const u8).init(alloc);
    while (lines.next()) |line| {
        lineno += 1;
        try tokenizeInto(&tokbuf, line);
        const toks = tokbuf.items;
        if (toks.len == 0) continue;
        const kw = toks[0];
        const is = struct {
            fn f(a: []const u8, b: []const u8) bool {
                return std.mem.eql(u8, a, b);
            }
        }.f;
        const in_group = gstack.items.len > 0;
        if (in_group and (is(kw, "when") or is(kw, "requires") or is(kw, "root") or is(kw, "kind") or is(kw, "map") or is(kw, "typemap"))) {
            return bad(diag, alloc, E.@"bad-directive", "line {d}: {s} inside a group", .{ lineno, kw });
        }
        if (is(kw, "group")) {
            // group <list> <locator> [item <bits>] [count <count-locator | n>]
            if (toks.len < 3) return bad(diag, alloc, E.@"bad-directive", "line {d}: group takes a list and a locator", .{lineno});
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
            try curLines(p, gstack.items.len > 0, &gtmp).append(gline.pop());
        } else if (is(kw, "format")) {
            if (toks.len != 2) return bad(diag, alloc, E.MalformedDirective, "line {d}: format takes one argument", .{lineno});
            p.format = toks[1];
        } else if (is(kw, "version")) {
            if (toks.len != 2) return bad(diag, alloc, E.MalformedDirective, "line {d}: version takes one argument", .{lineno});
            p.version = toks[1];
        } else if (is(kw, "wire")) {
            if (toks.len != 2) return bad(diag, alloc, E.MalformedDirective, "line {d}: wire takes one argument", .{lineno});
            p.wire = std.meta.stringToEnum(Wire, toks[1]) orelse
                return bad(diag, alloc, E.UnknownWire, "line {d}: unknown wire {s}", .{ lineno, toks[1] });
        } else if (is(kw, "distribution")) {
            if (toks.len != 2) return bad(diag, alloc, E.MalformedDirective, "line {d}: distribution takes one argument", .{lineno});
            p.distribution = parseDist(toks[1]) catch |err|
                return bad(diag, alloc, err, "line {d}: distribution {s} is not public or controlled", .{ lineno, toks[1] });
        } else if (is(kw, "source")) {
            if (toks.len != 2) return bad(diag, alloc, E.MalformedDirective, "line {d}: source takes one argument", .{lineno});
            try p.sources.append(toks[1]);
        } else if (is(kw, "uses")) {
            if (toks.len != 2) return bad(diag, alloc, E.MalformedDirective, "line {d}: uses takes one argument", .{lineno});
            try p.uses.append(toks[1]);
        } else if (is(kw, "root")) {
            if (toks.len != 2) return bad(diag, alloc, E.MalformedDirective, "line {d}: root takes one argument", .{lineno});
            if (p.kinds.items.len == 0) {
                p.root = toks[1];
            } else {
                // inside a kind: that kind's root element (xml)
                p.kinds.items[p.kinds.items.len - 1].root = toks[1];
                kind_root = true;
            }
        } else if (is(kw, "word_bytes")) {
            if (toks.len != 2) return bad(diag, alloc, E.MalformedDirective, "line {d}: word_bytes takes one argument", .{lineno});
            const n = parseUnsigned(toks[1]) orelse 0;
            if (n == 0 or n > 1 << 20) return bad(diag, alloc, E.MalformedDirective, "line {d}: word_bytes {s} is not a positive integer", .{ lineno, toks[1] });
            p.word_bytes = @intCast(n);
        } else if (is(kw, "bit_order")) {
            if (toks.len != 2) return bad(diag, alloc, E.@"bad-directive", "line {d}: bit_order takes one argument", .{lineno});
            if (is(toks[1], "msb")) {
                p.msb = true;
            } else if (is(toks[1], "lsb")) {
                p.msb = false;
            } else return bad(diag, alloc, E.@"bad-directive", "line {d}: bit_order {s} is not lsb or msb", .{ lineno, toks[1] });
            p.bit_order_set = true;
        } else if (is(kw, "typemap")) {
            if (toks.len != 3) return bad(diag, alloc, E.MalformedDirective, "line {d}: typemap takes two arguments", .{lineno});
            try p.tm_nat2cot.put(toks[1], toks[2]);
            try p.tm_cot2nat.put(toks[2], toks[1]);
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
            if (is_when) any_when = true;
            const ln = Line{ .tag = if (is_when) .when else .constant, .locator = toks[1], .wraw = toks[2], .lineno = lineno };
            try curLines(p, in_group, &gtmp).append(ln);
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
            if (toks.len < 4) return bad(diag, alloc, E.MalformedDirective, "line {d}: field takes a key, a locator and a transform", .{lineno});
            const t = parseTransform(toks[3]) catch |err|
                return bad(diag, alloc, err, "line {d}: unknown transform {s}", .{ lineno, toks[3] });
            var ln = Line{ .key = toks[1], .locator = toks[2], .transform = t, .lineno = lineno };
            // options, in any order
            var oi: usize = 4;
            while (oi < toks.len) : (oi += 1) {
                const o = toks[oi];
                // an unknown or repeated option is `bad-directive`
                var again = false;
                if (is(o, "via")) {
                    oi += 1;
                    if (oi >= toks.len or toks[oi].len == 0) return bad(diag, alloc, E.@"bad-directive", "line {d}: via takes a table name", .{lineno});
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
                } else return bad(diag, alloc, E.@"bad-directive", "line {d}: unknown field option {s}", .{ lineno, o });
                if (again) return bad(diag, alloc, E.@"bad-directive", "line {d}: field option {s} is repeated", .{ lineno, o });
            }
            try curLines(p, in_group, &gtmp).append(ln);
            try p.key_uses.append(.{ .key = toks[1], .tkind = t.kind, .via = ln.via_name, .grp = if (in_group) gstack.items[gstack.items.len - 1] else null });
        } else {
            return bad(diag, alloc, E.UnknownDirective, "line {d}: unknown directive {s}", .{ lineno, kw });
        }
    }

    if (gstack.items.len > 0) {
        return bad(diag, alloc, E.@"bad-directive", "line {d}: a `group` with no `end`", .{gstack.items[gstack.items.len - 1].lineno});
    }
    // Checks that need the whole file: the wire may be named after the lines
    // it governs.
    if (p.bit_order_set and p.wire != .bits) {
        return bad(diag, alloc, E.@"bad-directive", "bit_order on wire {s}; it is for the bits wire only", .{@tagName(p.wire)});
    }
    if (any_when and p.kinds.items.len == 0) {
        return bad(diag, alloc, E.@"bad-directive", "a `when` line in a pack with no `kind` line", .{});
    }
    if (kind_root and p.wire != .xml) {
        return bad(diag, alloc, E.@"bad-directive", "a `root` line inside a kind on wire {s}; it is for the xml wire only", .{@tagName(p.wire)});
    }
    if (p.wire == .bits and p.word_bytes == 0) {
        return bad(diag, alloc, E.MalformedDirective, "a bits pack needs word_bytes", .{});
    }
    // the type of each table's `<model>` side
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
    try finalizeLines(alloc, p, p.common.items, false, diag);
    for (p.kinds.items) |*k| try finalizeLines(alloc, p, k.lines.items, false, diag);
    // the group checks, scope by scope
    if (p.kinds.items.len == 0) try checkScope(alloc, p, p.common.items, &.{}, null, diag);
    for (p.kinds.items) |*k| try checkScope(alloc, p, p.common.items, k.lines.items, null, diag);
    try checkGroupBodies(alloc, p, p.common.items, diag);
    for (p.kinds.items) |*k| try checkGroupBodies(alloc, p, k.lines.items, diag);

    if (p.distribution == null) return bad(diag, alloc, E.@"missing-distribution", "the pack has no distribution line", .{});
    if (p.sources.items.len == 0) return bad(diag, alloc, E.@"missing-source", "the pack has no source line", .{});
    return p;
}

// ---------------------------------------------------------------------------
// Engine: loaded modules and packs, the distribution limit, the load-time
// checks, and decode / encode / convert by format name
// ---------------------------------------------------------------------------

// One caller-supplied key: `convert(from, to, bytes, context)`, CLI `--set`.
const KV = struct { key: []const u8, value: []const u8 };

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

const Engine = struct {
    alloc: std.mem.Allocator,
    // Where decode, encode and convert allocate their results and the failure
    // message. A caller that runs many conversions points it at an arena it
    // resets; by default it is `alloc`.
    scratch: std.mem.Allocator,
    modules: std.StringHashMap(*Module),
    // the loaded modules in byte order of name (the order derivations run in)
    module_order: std.ArrayList(*Module),
    packs: std.ArrayList(*Pack),
    pack_index: std.StringHashMap(*Pack),
    max_distribution: Dist = .controlled,
    // Message of the last failure: "<kind>: <detail>".
    last_error: []const u8 = "",

    fn init(alloc: std.mem.Allocator) Engine {
        return .{
            .alloc = alloc,
            .scratch = alloc,
            .modules = std.StringHashMap(*Module).init(alloc),
            .module_order = std.ArrayList(*Module).init(alloc),
            .packs = std.ArrayList(*Pack).init(alloc),
            .pack_index = std.StringHashMap(*Pack).init(alloc),
        };
    }

    fn setMaxDistribution(self: *Engine, d: Dist) void {
        self.max_distribution = d;
    }

    fn fail(self: *Engine, err: anyerror, comptime fmt: []const u8, args: anytype) void {
        const detail = std.fmt.allocPrint(self.scratch, fmt, args) catch "";
        self.last_error = std.fmt.allocPrint(self.scratch, "{s}: {s}", .{ @errorName(err), detail }) catch @errorName(err);
    }

    // load_model(text): load one model module.
    fn loadModel(self: *Engine, def_text: []const u8) !*Module {
        var mdiag = Diag{};
        const m = parseModule(self.alloc, def_text, self.modules.get("core"), &mdiag) catch |err| {
            self.fail(err, "model module: {s}", .{mdiag.msg});
            return err;
        };
        if (m.distribution.? == .controlled and self.max_distribution == .public) {
            const err = E.@"distribution-refused";
            self.fail(err, "module {s} is controlled; this engine's limit is public", .{m.name});
            return err;
        }
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
    fn loadPack(self: *Engine, def_text: []const u8) !*Pack {
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
        try finishPack(self.alloc, p);
        try self.packs.append(p);
        if (!self.pack_index.contains(p.format)) try self.pack_index.put(p.format, p);
        return p;
    }

    // Load every `*.def` in `models_dir`, in byte order of file name.
    fn loadModelDir(self: *Engine, models_dir: []const u8) !usize {
        var dir = std.fs.cwd().openDir(models_dir, .{ .iterate = true }) catch |err| switch (err) {
            error.FileNotFound => return 0, // no model directory: no modules
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
        // `core.def` first, whatever its name sorts as (ruling 9 of 0.6): a
        // `derive` line of another module may name a key of `core`
        for (names.items, 0..) |name, i| {
            if (!std.mem.eql(u8, name, "core.def")) continue;
            std.mem.copyBackwards([]const u8, names.items[1 .. i + 1], names.items[0..i]);
            names.items[0] = name;
            break;
        }
        for (names.items) |name| {
            const path = try std.fmt.allocPrint(self.alloc, "{s}/{s}", .{ models_dir, name });
            const text = try std.fs.cwd().readFileAlloc(self.alloc, path, max_file);
            _ = self.loadModel(text) catch |err| {
                self.last_error = try std.fmt.allocPrint(self.alloc, "{s} ({s})", .{ self.last_error, path });
                return err;
            };
        }
        return names.items.len;
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

    // A `default` value is read as its key's declared type.
    fn readDefault(self: *Engine, p: *const Pack, d: *Default) !void {
        d.value = readAs(self.keyType(d.key).?, d.text) catch {
            const err = E.@"key-type-mismatch";
            self.fail(err, "pack {s}: default {s} {s} is not of the key's type", .{ p.format, d.key, d.text });
            return err;
        };
    }

    fn findPack(self: *const Engine, fmt: []const u8) ?*Pack {
        return self.pack_index.get(fmt);
    }

    fn pack(self: *Engine, fmt: []const u8) !*Pack {
        return self.findPack(fmt) orelse {
            self.fail(E.UnknownFormat, "no loaded pack has format {s}", .{fmt});
            return E.UnknownFormat;
        };
    }

    // decode(format, bytes) -> Entity
    fn decode(self: *Engine, fmt: []const u8, bytes: []const u8) !Entity {
        const p = try self.pack(fmt);
        var diag = Diag{};
        return decodePack(self.scratch, p, bytes, &diag) catch |err| {
            self.fail(err, "decode {s}: {s}", .{ fmt, diag.msg });
            return err;
        };
    }

    // encode(format, Entity) -> bytes
    fn encode(self: *Engine, fmt: []const u8, e: *const Entity) ![]u8 {
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
    fn fillContext(self: *Engine, e: *Entity, context: []const KV) !void {
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
            if (!e.fields.contains(kv.key)) try e.fields.put(kv.key, mv);
        }
    }

    // complete(entity): apply the derivations. The loaded modules in byte
    // order of name, each module's `derive` lines in order; a line whose
    // target is absent and whose arguments are all present sets the target.
    // The pass repeats until a pass sets nothing, at most 8 times.
    fn complete(self: *Engine, e: *Entity) !void {
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
    fn convert(self: *Engine, from: []const u8, to: []const u8, bytes: []const u8, context: ?[]const KV) ![]u8 {
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
    for (d.args) |a| if (!e.fields.contains(a)) return false;
    const a0 = e.get(d.args[0]).?;
    var out: MV = undefined;
    switch (d.f) {
        .copy => out = a0,
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
    try e.fields.put(d.target, out);
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
    if (mo < 1 or mo > 12 or d < 1 or d > 31 or hh > 23 or mm > 59 or ss > 60) return E.@"transform-decode";
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
    return secs * 1000 + frac;
}

fn msToIso(alloc: std.mem.Allocator, ms: i64) ![]const u8 {
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

// ---------------------------------------------------------------------------
// XML DOM + parser
// ---------------------------------------------------------------------------

const XmlAttr = struct { name: []const u8, value: []const u8 };

const XmlNode = struct {
    name: []const u8,
    attrs: std.ArrayList(XmlAttr),
    children: std.ArrayList(*XmlNode),
    text: []const u8 = "",
    text_set: bool = false,

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

// Replace the five predefined entities and numeric character references.
fn xmlUnescape(alloc: std.mem.Allocator, s: []const u8) ![]const u8 {
    if (std.mem.indexOfScalar(u8, s, '&') == null) return s;
    var out = std.ArrayList(u8).init(alloc);
    var i: usize = 0;
    while (i < s.len) {
        if (s[i] == '&') {
            if (std.mem.indexOfScalarPos(u8, s, i, ';')) |semi| {
                const ent = s[i + 1 .. semi];
                var done = true;
                if (std.mem.eql(u8, ent, "amp")) {
                    try out.append('&');
                } else if (std.mem.eql(u8, ent, "lt")) {
                    try out.append('<');
                } else if (std.mem.eql(u8, ent, "gt")) {
                    try out.append('>');
                } else if (std.mem.eql(u8, ent, "quot")) {
                    try out.append('"');
                } else if (std.mem.eql(u8, ent, "apos")) {
                    try out.append('\'');
                } else if (ent.len > 1 and ent[0] == '#') {
                    const cp: ?u21 = if (ent[1] == 'x' or ent[1] == 'X')
                        std.fmt.parseInt(u21, ent[2..], 16) catch null
                    else
                        std.fmt.parseInt(u21, ent[1..], 10) catch null;
                    var ubuf: [4]u8 = undefined;
                    const n: ?u3 = if (cp) |c| (std.unicode.utf8Encode(c, &ubuf) catch null) else null;
                    if (n) |len| {
                        try out.appendSlice(ubuf[0..len]);
                    } else done = false;
                } else done = false;
                if (done) {
                    i = semi + 1;
                    continue;
                }
            }
        }
        try out.append(s[i]);
        i += 1;
    }
    return out.toOwnedSlice();
}

const XmlParser = struct {
    s: []const u8,
    i: usize = 0,
    alloc: std.mem.Allocator,

    fn ws(self: *XmlParser) void {
        while (self.i < self.s.len and (self.s[self.i] == ' ' or self.s[self.i] == '\t' or self.s[self.i] == '\n' or self.s[self.i] == '\r')) self.i += 1;
    }
    fn starts(self: *XmlParser, pat: []const u8) bool {
        return self.i + pat.len <= self.s.len and std.mem.eql(u8, self.s[self.i .. self.i + pat.len], pat);
    }
    fn skipMisc(self: *XmlParser) void {
        while (true) {
            self.ws();
            if (self.starts("<?")) {
                while (self.i < self.s.len and !self.starts("?>")) self.i += 1;
                if (self.starts("?>")) self.i += 2;
            } else if (self.starts("<!--")) {
                while (self.i < self.s.len and !self.starts("-->")) self.i += 1;
                if (self.starts("-->")) self.i += 3;
            } else if (self.starts("<!")) {
                while (self.i < self.s.len and self.s[self.i] != '>') self.i += 1;
                if (self.i < self.s.len) self.i += 1;
            } else break;
        }
    }
    fn readName(self: *XmlParser) []const u8 {
        const start = self.i;
        while (self.i < self.s.len) {
            const c = self.s[self.i];
            if (c == ' ' or c == '\t' or c == '\n' or c == '\r' or c == '=' or c == '>' or c == '/') break;
            self.i += 1;
        }
        return self.s[start..self.i];
    }
    fn parseElement(self: *XmlParser) anyerror!*XmlNode {
        if (self.i >= self.s.len or self.s[self.i] != '<') return E.@"malformed-wire";
        self.i += 1;
        const node = try xmlNewNode(self.alloc, self.readName());
        if (node.name.len == 0) return E.@"malformed-wire";
        // attributes
        while (true) {
            self.ws();
            if (self.i >= self.s.len) return E.@"malformed-wire";
            if (self.s[self.i] == '>' or self.s[self.i] == '/') break;
            const an = self.readName();
            if (an.len == 0) return E.@"malformed-wire";
            self.ws();
            if (self.i >= self.s.len or self.s[self.i] != '=') return E.@"malformed-wire";
            self.i += 1;
            self.ws();
            if (self.i >= self.s.len or (self.s[self.i] != '"' and self.s[self.i] != '\'')) return E.@"malformed-wire";
            const q = self.s[self.i];
            self.i += 1;
            const vstart = self.i;
            while (self.i < self.s.len and self.s[self.i] != q) self.i += 1;
            if (self.i >= self.s.len) return E.@"malformed-wire";
            const val = try xmlUnescape(self.alloc, self.s[vstart..self.i]);
            self.i += 1; // closing quote
            try node.attrs.append(.{ .name = an, .value = val });
        }
        if (self.s[self.i] == '/') {
            // self-closing "/>"
            self.i += 1;
            if (self.i >= self.s.len or self.s[self.i] != '>') return E.@"malformed-wire";
            self.i += 1;
            return node;
        }
        self.i += 1; // consume '>'
        // content
        var textbuf = std.ArrayList(u8).init(self.alloc);
        var closed = false;
        while (self.i < self.s.len) {
            if (self.starts("</")) {
                self.i += 2;
                _ = self.readName();
                self.ws();
                if (self.i < self.s.len and self.s[self.i] == '>') self.i += 1;
                closed = true;
                break;
            } else if (self.starts("<!--")) {
                while (self.i < self.s.len and !self.starts("-->")) self.i += 1;
                if (self.starts("-->")) self.i += 3;
            } else if (self.s[self.i] == '<') {
                const c = try self.parseElement();
                try node.children.append(c);
            } else {
                try textbuf.append(self.s[self.i]);
                self.i += 1;
            }
        }
        if (!closed) return E.@"malformed-wire";
        node.text = try xmlUnescape(self.alloc, try textbuf.toOwnedSlice());
        return node;
    }
};

fn parseXml(alloc: std.mem.Allocator, s: []const u8) !*XmlNode {
    var p = XmlParser{ .s = s, .alloc = alloc };
    p.skipMisc();
    return p.parseElement();
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
    if (std.mem.eql(u8, t.last, "#text")) return t.node.text;
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

// `as_written`: numbers are kept as their text (`.number_string`), for the
// geojson wire, whose residue gives a number back as it was written.
fn parseJsonObject(alloc: std.mem.Allocator, bytes: []const u8, as_written: bool) !std.json.ObjectMap {
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
                .number_string => |s| std.fmt.parseFloat(f64, s) catch return E.@"transform-decode",
                else => return E.@"transform-decode",
            };
            // any number whose value is integral (1.0, 1e3)
            if (!(f >= -9223372036854775808.0 and f < 9223372036854775808.0) or @floor(f) != f) return E.@"transform-decode";
            return MV{ .int = @intFromFloat(f) };
        },
        .iso8601_ms => {
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
        .uint, .twos => {
            if (mv != .int) return E.@"transform-encode";
            return @bitCast(mv.int);
        },
        .linscale => {
            const r = @round(try mvFloat(mv) / t.range * t.maxpos);
            if (!(r >= -9223372036854775808.0 and r < 9223372036854775808.0)) return E.@"transform-encode";
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
        if (shift >= 64) return E.@"malformed-wire";
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
            const obj = parseJsonObject(alloc, bytes, false) catch |err| return bad(diag, alloc, err, "the input is not one JSON object", .{});
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
    }
}

// Text through a text transform (xml, geojson).
fn textToMV(t: TKind, raw: []const u8) !MV {
    return switch (t) {
        .string => MV{ .str = raw },
        .float => MV{ .float = try parseDecimal(raw) },
        .int => MV{ .int = try parseDecimalInt(raw) },
        .iso8601_ms => MV{ .int = try isoToMs(raw) },
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

// Read one field through its transform. null: the field is absent.
fn readField(alloc: std.mem.Allocator, p: *const Pack, doc: Doc, ln: *const Line) anyerror!?MV {
    const t = ln.transform.kind;
    switch (doc) {
        .xml => |root| {
            const raw = xmlGet(root, ln.locator) orelse return null;
            return try textToMV(t, raw);
        },
        .geojson => |d| {
            // 0.1 behaviour (ruling 28 of 0.5): a scalar is read as its text,
            // whatever its JSON type
            const v = geoLookup(d, ln.locator) orelse return null;
            if (v == .null) return null;
            const raw = (try geoText(alloc, v)) orelse return E.@"transform-decode";
            return try textToMV(t, raw);
        },
        .json => |it| {
            const v = jitemLookup(it, ln) orelse return null;
            if (v == .null) return null; // a member whose value is null is absent
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
            return try bitsDecodeField(alloc, p, bd.buf, bd.base, ln);
        },
        .protobuf => |pd| {
            if (ln.dot) return try decodeProtoTransform(t, pd.self orelse return null);
            const leaf = (try resolvePb(alloc, pd, ln.ppath)) orelse return null;
            return try decodeProtoTransform(t, leaf);
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
                try e.residue.append(.{ .fmt = p.format, .locator = path, .value = try jsonCanonText(alloc, en.value_ptr.*, false) });
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
        try e.fields.put(ln.key, mv);
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

// One protobuf occurrence as an item.
fn pbItem(alloc: std.mem.Allocator, p: *const Pack, body: *const Scope, cache: *PbCache, items: *std.ArrayList(Entity), self: PbEntry, sub: []const PbEntry, diag: *Diag) anyerror!void {
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
            const items = try alloc.alloc(Entity, n);
            var i: usize = 0;
            for (cont.children.items) |c| {
                if (!std.mem.eql(u8, c.name, g.xname)) continue;
                items[i] = Entity.init(alloc);
                _ = try decodeScope(alloc, p, body, .{ .xml = c }, &items[i], diag);
                i += 1;
            }
            try e.lists.put(g.list, items);
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
            const items = try alloc.alloc(Entity, v.array.items.len);
            for (v.array.items, 0..) |el, i| {
                items[i] = Entity.init(alloc);
                _ = try decodeScope(alloc, p, body, .{ .json = .{ .v = el, .geo = p.wire == .geojson } }, &items[i], diag);
            }
            try e.lists.put(g.list, items);
            return 0;
        },
        .protobuf => |pd| {
            const found = pbDescend(alloc, pd, g.ppath[0 .. g.ppath.len - 1]) catch |err| switch (err) {
                error.OutOfMemory => return err,
                else => return bad(diag, alloc, mw, "group {s} at {s}: a field on the path is not a submessage", .{ g.list, g.locator }),
            };
            const entries = found orelse return 0;
            const number = g.ppath[g.ppath.len - 1];
            var items = std.ArrayList(Entity).init(alloc);
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
            if (items.items.len == 0) return 0; // no item occurs: the list is absent
            try e.lists.put(g.list, items.items);
            return 0;
        },
        .bits => |bd| {
            const total = bd.buf.len * 8;
            // the count locator is inside the bits the scope requires
            const count: u64 = if (g.count_fixed) |n| n else getBits(bd.buf, p.msb, bd.base + g.cstart, g.clen);
            var pos = bd.base + g.gstart;
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
            try e.lists.put(g.list, items);
            return if (count == 0) 0 else pos;
        },
    }
}

fn decodePack(alloc: std.mem.Allocator, p: *const Pack, bytes: []const u8, diag: *Diag) anyerror!Entity {
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

    const end = try decodeScope(alloc, p, sc, doc, &e, diag);
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
                    try e.residue.append(.{ .fmt = p.format, .locator = loc, .value = a.value });
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
                    try e.residue.append(.{ .fmt = p.format, .locator = loc, .value = val });
                }
            }
        },
        .json => |it| try jsonResidue(alloc, p, lines, it.v.object, "", &e),
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
        else => return E.@"transform-encode",
    }
}

// Write a value at an xml locator. A locator already written keeps its value
// (the earliest line wins) unless the new value is a `when` value.
fn xmlSet(alloc: std.mem.Allocator, root: *XmlNode, locator: []const u8, value: []const u8, is_when: bool) !void {
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
                if (is_when) a.value = value;
                return;
            }
        }
        try node.attrs.append(.{ .name = rest[1..], .value = value });
    } else if (std.mem.eql(u8, rest, "#text")) {
        if (node.text_set and !is_when) return;
        node.text = value;
        node.text_set = true;
    }
}

fn xmlWrite(buf: *std.ArrayList(u8), node: *XmlNode) anyerror!void {
    try buf.append('<');
    try buf.appendSlice(node.name);
    for (node.attrs.items) |a| {
        try buf.append(' ');
        try buf.appendSlice(a.name);
        try buf.appendSlice("=\"");
        try xmlEscape(buf, a.value);
        try buf.append('"');
    }
    if (node.children.items.len == 0 and node.text.len == 0) {
        try buf.appendSlice("/>");
        return;
    }
    try buf.append('>');
    if (node.text.len > 0) try xmlEscape(buf, node.text);
    for (node.children.items) |c| try xmlWrite(buf, c);
    try buf.appendSlice("</");
    try buf.appendSlice(node.name);
    try buf.append('>');
}

fn xmlEscape(buf: *std.ArrayList(u8), s: []const u8) !void {
    for (s) |c| {
        switch (c) {
            '&' => try buf.appendSlice("&amp;"),
            '<' => try buf.appendSlice("&lt;"),
            '>' => try buf.appendSlice("&gt;"),
            '"' => try buf.appendSlice("&quot;"),
            else => try buf.append(c),
        }
    }
}

// Members of one flat JSON object in output order: name and JSON text.
const Member = struct { name: []const u8, raw: []const u8 };

// Add a member. A name already written keeps its value (the earliest line
// wins) unless the new value is a `when` value.
fn memberAdd(list: *std.ArrayList(Member), name: []const u8, raw: []const u8, is_when: bool) !void {
    for (list.items) |*m| {
        if (std.mem.eql(u8, m.name, name)) {
            if (is_when) m.raw = raw;
            return;
        }
    }
    try list.append(.{ .name = name, .raw = raw });
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
fn jnodeInsert(alloc: std.mem.Allocator, root: *JNode, segs: []const []const u8, raw: ?[]const u8, is_when: bool) !void {
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
        if (is_when and c.raw != null) c.raw = r; // `when` and `const` values are written over any field
        return;
    }
    if (raw == null) return;
    const c = try jnodeNew(alloc, last);
    c.raw = raw;
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
                if (!ln.wpresent) try xmlSet(alloc, node, ln.locator, ln.wtext, true);
            },
            .field => {
                const mv = (fieldValue(p, sc, e, ln) catch |err|
                    return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator })) orelse continue;
                const vs = xmlText(alloc, ln.transform.kind, mv) catch |err|
                    return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator });
                try xmlSet(alloc, node, ln.locator, vs, false);
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
        var over = false;
        switch (ln.tag) {
            .when, .constant => {
                // `present` writes nothing; the objects on its path keep this position
                if (!ln.wpresent) raw = try whenJsonRaw(alloc, ln.*);
                over = true;
            },
            .field => {
                const got = fieldValue(p, sc, e, ln) catch |err|
                    return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator });
                if (got) |mv| {
                    raw = jsonRaw(alloc, ln.transform.kind, mv) catch |err|
                        return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator });
                }
            },
            .group => {
                const g = ln.grp.?;
                try jnodeInsert(alloc, root, g.segs, try jsonGroupRaw(alloc, p, g, e, diag), false);
                continue;
            },
        }
        if (ln.dot) {
            if (raw) |r| {
                if (root.raw == null or over) root.raw = r;
            }
        } else try jnodeInsert(alloc, root, ln.segs, raw, over);
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
                    for (items) |*it| {
                        const mv = (fieldValue(p, body, it, dl) catch |err|
                            return bad(diag, alloc, err, "field {s} in group {s}", .{ dl.key, g.list })) orelse continue;
                        encodeProtoPayload(&payload, tk, mv) catch |err|
                            return bad(diag, alloc, err, "field {s} in group {s}", .{ dl.key, g.list });
                    }
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
        if (ln.isFixed()) {
            if (!ln.wpresent) {
                try writeTag(&fb, number, 0);
                try writeVarint(&fb, ln.wint);
            }
        } else {
            const mv = (fieldValue(p, sc, e, ln) catch |err|
                return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator })) orelse continue;
            encodeProtoField(&fb, ln.transform.kind, number, mv) catch |err|
                return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator });
        }
        var node = root;
        for (ln.ppath) |n| node = try node.child(alloc, n);
        if (ln.isFixed() and ln.wpresent) {
            node.forced = true;
        } else if (node.leaf == null or ln.isFixed()) {
            // the earliest line whose key is present wins; a `when`
            // or `const` value is written over any field
            node.leaf = fb.items;
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
                try xmlSet(alloc, root, r.locator, r.value, false);
            }
            var buf = std.ArrayList(u8).init(alloc);
            try xmlWrite(&buf, root);
            return buf.toOwnedSlice();
        },
        .geojson => {
            var coords = [3]?[]const u8{ null, null, null };
            var props = std.ArrayList(Member).init(alloc);
            var top = std.ArrayList(Member).init(alloc);
            for (lines) |*ln| {
                var raw: []const u8 = undefined;
                if (ln.tag == .group) {
                    // an array at the member; an absent list writes nothing
                    raw = (try jsonGroupRaw(alloc, p, ln.grp.?, e, diag)) orelse continue;
                } else if (ln.isFixed()) {
                    if (ln.wpresent) continue;
                    raw = try whenJsonRaw(alloc, ln.*);
                } else {
                    const mv = (fieldValue(p, sc, e, ln) catch |err|
                        return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator })) orelse continue;
                    raw = jsonRaw(alloc, ln.transform.kind, mv) catch |err|
                        return bad(diag, alloc, err, "field {s} at {s}", .{ ln.key, ln.locator });
                }
                const loc = ln.locator;
                if (std.mem.startsWith(u8, loc, geom_prefix)) {
                    const comp = loc[geom_prefix.len..];
                    const idx: usize = if (std.mem.eql(u8, comp, "lon")) 0 else if (std.mem.eql(u8, comp, "lat")) 1 else if (std.mem.eql(u8, comp, "alt")) 2 else continue;
                    if (coords[idx] == null or ln.isFixed()) coords[idx] = raw;
                } else if (std.mem.startsWith(u8, loc, props_prefix)) {
                    try memberAdd(&props, loc[props_prefix.len..], raw, ln.isFixed());
                } else {
                    if (std.mem.eql(u8, loc, "type") or std.mem.eql(u8, loc, "geometry") or std.mem.eql(u8, loc, "properties")) continue;
                    try memberAdd(&top, loc, raw, ln.isFixed());
                }
            }
            // residue of this format, input order, after the mapped members
            for (e.residue.items) |r| {
                if (!std.mem.eql(u8, r.fmt, p.format)) continue;
                if (std.mem.startsWith(u8, r.locator, props_prefix)) {
                    try memberAdd(&props, r.locator[props_prefix.len..], r.value, false);
                } else {
                    try memberAdd(&top, r.locator, r.value, false);
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
                try jnodeInsert(alloc, root, segs.items, r.value, false);
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
    }
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
    if (eng.findPack(from_fmt) == null) return try std.fmt.allocPrint(alloc, "unknown from format {s}", .{from_fmt});
    if (eng.findPack(to_fmt) == null) return try std.fmt.allocPrint(alloc, "unknown to format {s}", .{to_fmt});

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
    var mit = mv.object.iterator();
    while (mit.next()) |me| {
        const key = me.key_ptr.*;
        if (std.mem.eql(u8, key, "@complete")) continue;
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
    const actual = cur.get(rest) orelse return try std.fmt.allocPrint(alloc, "model key {s} absent", .{key});
    if (!modelMatch(actual, exp, completed)) {
        return try std.fmt.allocPrint(alloc, "model key {s}: expected {s}, got {s}", .{ key, clip(exp), clip(try mvText(alloc, actual)) });
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
            const e = std.fmt.parseInt(i64, expected, 10) catch return false;
            return i == e;
        },
        .float => |f| {
            const e = std.fmt.parseFloat(f64, expected) catch return false;
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
    const pack_text = getStr(obj, "pack") orelse return "no pack";
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
        _ = eng.loadPack(pack_text) catch |err| {
            got = @errorName(err);
        };
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

pub fn main() !void {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    const alloc = arena.allocator();

    var bw = std.io.bufferedWriter(std.io.getStdOut().writer());
    const stdout = bw.writer();

    // usage: gt-engine-zig [<packs-dir>] [--models <dir>]
    //        [--max-distribution public|controlled] [--model-keys <format>]
    //        [--convert <from> <to> [--set <key>=<value>]…]
    const args = try std.process.argsAlloc(alloc);
    var packs_dir: []const u8 = "../../packs";
    var models_opt: ?[]const u8 = null;
    var keys_opt: ?[]const u8 = null;
    var conv_from: ?[]const u8 = null;
    var conv_to: []const u8 = "";
    var sets = std.ArrayList(KV).init(alloc);
    var eng = Engine.init(alloc);
    var ai: usize = 1;
    while (ai < args.len) : (ai += 1) {
        const a = args[ai];
        const eq = std.mem.eql;
        if (eq(u8, a, "--models") or eq(u8, a, "--max-distribution") or eq(u8, a, "--packs") or eq(u8, a, "--model-keys") or eq(u8, a, "--set") or eq(u8, a, "--convert")) {
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
            } else if (eq(u8, a, "--model-keys")) {
                keys_opt = args[ai];
            } else if (eq(u8, a, "--convert")) {
                conv_from = args[ai];
                ai += 1;
                conv_to = args[ai];
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

    const n_modules = eng.loadModelDir(models_dir) catch |err| {
        if (eng.last_error.len == 0) eng.fail(err, "model directory {s}", .{models_dir});
        try stdout.print("load error: {s}\n", .{eng.last_error});
        try bw.flush();
        std.process.exit(1);
    };
    const pack_dirs = loadAllPacks(&eng, packs_dir) catch |err| {
        if (eng.last_error.len == 0) eng.fail(err, "packs directory {s}", .{packs_dir});
        try stdout.print("load error: {s}\n", .{eng.last_error});
        try bw.flush();
        std.process.exit(1);
    };
    // --convert <from> <to>: the message on standard input, converted, on
    // standard output; --set supplies the context.
    if (conv_from) |from| {
        const input = try std.io.getStdIn().readToEndAlloc(alloc, max_file);
        const msg = std.mem.trim(u8, input, " \t\r\n");
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

    var failures = std.ArrayList([]const u8).init(alloc);

    // conversion vectors: <packs>/<pack>/vectors/*.json
    var total: usize = 0;
    var passed: usize = 0;
    for (pack_dirs) |dir| {
        const vdir_path = try std.fmt.allocPrint(alloc, "{s}/{s}/vectors", .{ packs_dir, dir });
        const vnames = (try sortedNames(alloc, vdir_path, .file, ".json")) orelse continue;
        for (vnames) |vn| {
            total += 1;
            // one arena per vector, so the run's memory stays bounded
            var varena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
            defer varena.deinit();
            eng.scratch = varena.allocator();
            defer eng.scratch = alloc;
            const vpath = try std.fmt.allocPrint(eng.scratch, "{s}/{s}", .{ vdir_path, vn });
            const vtext = try std.fs.cwd().readFileAlloc(eng.scratch, vpath, max_file);
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
    const ldir_path = try std.fmt.allocPrint(alloc, "{s}/conformance/load-vectors", .{packs_dir});
    if (try sortedNames(alloc, ldir_path, .file, ".json")) |lnames| {
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

    for (failures.items) |fmsg| {
        try stdout.print("FAIL {s}\n", .{fmsg});
    }
    try stdout.print("vectors: {d}/{d} passed\n", .{ passed, total });
    try stdout.print("load vectors: {d}/{d} passed\n", .{ lpassed, ltotal });
    try bw.flush();
    if (passed != total or lpassed != ltotal) std.process.exit(1);
}
