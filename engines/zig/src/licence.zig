//! Licence profiles (spec Version 0.29): the three files an engine reads
//! (ruling 1), and the profile of a licence, a module and a pack (ruling 2).
//! No TOML library: each file is read by the exact line forms of ruling 1.
//! `Engine.loadTree` (main.zig) uses this to load with a profile.

const std = @import("std");

const max_file: usize = 64 << 20;

/// The profiles in their order, `open` < `open+copyleft` < `everything` <
/// none; `none` is the profile of a licence or pack in none of the three.
pub const Profile = enum(u8) {
    open,
    open_copyleft,
    everything,
    none,

    pub fn name(p: Profile) []const u8 {
        return switch (p) {
            .open => "open",
            .open_copyleft => "open+copyleft",
            .everything => "everything",
            .none => "none",
        };
    }

    /// One of the three names a loader takes, exactly; null otherwise.
    pub fn parse(s: []const u8) ?Profile {
        if (std.mem.eql(u8, s, "open")) return .open;
        if (std.mem.eql(u8, s, "open+copyleft")) return .open_copyleft;
        if (std.mem.eql(u8, s, "everything")) return .everything;
        return null;
    }

    pub fn wider(a: Profile, b: Profile) Profile {
        return if (@intFromEnum(a) >= @intFromEnum(b)) a else b;
    }

    /// Does this profile (one of the three) hold `x`?
    pub fn holds(self: Profile, x: Profile) bool {
        return x != .none and @intFromEnum(x) <= @intFromEnum(self);
    }
};

/// The licence of a file that does not exist (1a, 1b).
pub const default_licence = "Apache-2.0";

const Commercial = enum { yes, no, unknown };

/// One row of `licences.toml` (1c).
pub const Row = struct {
    commercial: Commercial,
    share_alike: bool,
    fou_empty: bool,
    controlled: bool,
};

pub const Table = std.StringHashMap(Row);

pub const Error = error{ @"bad-licence", OutOfMemory };

/// Ruling 2a: the profile of a licence.
pub fn licenceProfile(table: *const Table, id: []const u8) Profile {
    const row = table.get(id) orelse return .everything;
    if (row.controlled) return .none;
    if (row.commercial == .yes and row.fou_empty) return if (row.share_alike) .open_copyleft else .open;
    return .everything;
}

// --- ruling 1, Lines ------------------------------------------------------

/// The lines of a file: cut at each line feed, one carriage return before it
/// (or at the end of the file) removed, trimmed of spaces and tabs.
const Lines = struct {
    it: std.mem.SplitIterator(u8, .scalar),

    fn init(text: []const u8) Lines {
        return .{ .it = std.mem.splitScalar(u8, text, '\n') };
    }

    fn next(self: *Lines) ?[]const u8 {
        var l = self.it.next() orelse return null;
        if (l.len > 0 and l[l.len - 1] == '\r') l = l[0 .. l.len - 1];
        return std.mem.trim(u8, l, " \t");
    }
};

fn isSpace(c: u8) bool {
    return c == ' ' or c == '\t';
}

/// A licence id: one or more of `A`-`Z`, `a`-`z`, `0`-`9`, `.`, `-`, `+`.
fn isId(s: []const u8) bool {
    if (s.len == 0) return false;
    for (s) |c| {
        if (!(std.ascii.isAlphanumeric(c) or c == '.' or c == '-' or c == '+')) return false;
    }
    return true;
}

/// A module or `uses` name (2b): one or more of `A`-`Z`, `a`-`z`, `0`-`9`,
/// `_`, `-`.
fn isName(s: []const u8) bool {
    if (s.len == 0) return false;
    for (s) |c| {
        if (!(std.ascii.isAlphanumeric(c) or c == '_' or c == '-')) return false;
    }
    return true;
}

/// Read a file of ruling 1. null: it does not exist (no entry of that name,
/// or a part of the path before the last is not a directory or does not
/// exist). Any other failure, and text that is not UTF-8, is `bad-licence`.
fn readLicenceFile(alloc: std.mem.Allocator, path: []const u8, msg: *[]const u8) Error!?[]const u8 {
    const text = std.fs.cwd().readFileAlloc(alloc, path, max_file) catch |err| switch (err) {
        error.FileNotFound, error.NotDir => return null,
        error.OutOfMemory => return error.OutOfMemory,
        else => {
            msg.* = try std.fmt.allocPrint(alloc, "cannot read {s}: {s}", .{ path, @errorName(err) });
            return error.@"bad-licence";
        },
    };
    if (!std.unicode.utf8ValidateSlice(text)) {
        msg.* = try std.fmt.allocPrint(alloc, "{s} is not valid UTF-8", .{path});
        return error.@"bad-licence";
    }
    return text;
}

fn badAt(alloc: std.mem.Allocator, msg: *[]const u8, path: []const u8, lineno: usize, comptime fmt: []const u8, args: anytype) Error {
    const detail = try std.fmt.allocPrint(alloc, fmt, args);
    msg.* = try std.fmt.allocPrint(alloc, "{s}: line {d}: {s}", .{ path, lineno, detail });
    return error.@"bad-licence";
}

fn badFile(alloc: std.mem.Allocator, msg: *[]const u8, path: []const u8, comptime fmt: []const u8, args: anytype) Error {
    const detail = try std.fmt.allocPrint(alloc, fmt, args);
    msg.* = try std.fmt.allocPrint(alloc, "{s}: {s}", .{ path, detail });
    return error.@"bad-licence";
}

// --- 1a, 1b: the licence of a pack and of a module ------------------------

// REUSE-IgnoreStart: the quoted licence lines below are data
const reuse_key = "SPDX-License-Identifier";
const tag_key = "SPDX-License-Identifier:";

/// 1a: `SPDX-License-Identifier = "<id>"` in `<packs>/<d>/REUSE.toml`.
pub fn packLicence(alloc: std.mem.Allocator, path: []const u8, msg: *[]const u8) Error![]const u8 {
    const text = (try readLicenceFile(alloc, path, msg)) orelse return default_licence;
    var found: ?[]const u8 = null;
    var lines = Lines.init(text);
    var lineno: usize = 0;
    while (lines.next()) |l| {
        lineno += 1;
        if (!std.mem.startsWith(u8, l, reuse_key)) continue;
        const rest = l[reuse_key.len..];
        // a line beginning `SPDX-License-Identifier:` (or any other
        // character after the key) is passed over
        if (rest.len == 0 or !(isSpace(rest[0]) or rest[0] == '=')) continue;
        var r = std.mem.trimLeft(u8, rest, " \t");
        const id: ?[]const u8 = blk: {
            if (r.len == 0 or r[0] != '=') break :blk null;
            r = std.mem.trimLeft(u8, r[1..], " \t");
            if (r.len < 2 or r[0] != '"' or r[r.len - 1] != '"') break :blk null;
            const v = r[1 .. r.len - 1];
            break :blk if (isId(v)) v else null;
        };
        const v = id orelse return badAt(alloc, msg, path, lineno, "not a licence line: {s}", .{l});
        if (found != null) return badAt(alloc, msg, path, lineno, "a second licence line", .{});
        found = v;
    }
    return found orelse badFile(alloc, msg, path, "no licence line", .{});
}

/// 1b: `SPDX-License-Identifier: <id>` in `<models>/<m>.def.license`.
pub fn moduleLicence(alloc: std.mem.Allocator, path: []const u8, msg: *[]const u8) Error![]const u8 {
    const text = (try readLicenceFile(alloc, path, msg)) orelse return default_licence;
    var found: ?[]const u8 = null;
    var lines = Lines.init(text);
    var lineno: usize = 0;
    while (lines.next()) |l| {
        lineno += 1;
        // a line beginning `SPDX-License-Identifier =` is passed over here
        // REUSE-IgnoreEnd
        if (!std.mem.startsWith(u8, l, tag_key)) continue;
        const rest = l[tag_key.len..];
        const id: ?[]const u8 = blk: {
            if (rest.len == 0 or !isSpace(rest[0])) break :blk null;
            const v = std.mem.trimLeft(u8, rest, " \t");
            break :blk if (isId(v)) v else null;
        };
        const v = id orelse return badAt(alloc, msg, path, lineno, "not a licence line: {s}", .{l});
        if (found != null) return badAt(alloc, msg, path, lineno, "a second licence line", .{});
        found = v;
    }
    return found orelse badFile(alloc, msg, path, "no licence line", .{});
}

// --- 1c: the table ----------------------------------------------------------

/// `<key>`, any spaces or tabs, `=`, any spaces or tabs: the rest of the
/// line. null when the line is not of that form.
fn keyValue(l: []const u8, key: []const u8) ?[]const u8 {
    if (!std.mem.startsWith(u8, l, key)) return null;
    const r = std.mem.trimLeft(u8, l[key.len..], " \t");
    if (r.len == 0 or r[0] != '=') return null;
    return std.mem.trimLeft(u8, r[1..], " \t");
}

/// A skipped key: the line begins with `key` followed by a space, a tab or `=`.
fn beginsKey(l: []const u8, key: []const u8) bool {
    return std.mem.startsWith(u8, l, key) and l.len > key.len and (isSpace(l[key.len]) or l[key.len] == '=');
}

const RowSeen = struct {
    commercial: bool = false,
    share_alike: bool = false,
    field_of_use: bool = false,
    distribution: bool = false,
    name: bool = false,
    url: bool = false,
    attribution: bool = false,
};

/// The table of `<packs>/../licences.toml`. When the file does not exist it
/// has one row, `Apache-2.0`, in `open`.
pub fn readTable(alloc: std.mem.Allocator, path: []const u8, msg: *[]const u8) Error!Table {
    var table = Table.init(alloc);
    const text = (try readLicenceFile(alloc, path, msg)) orelse {
        try table.put(default_licence, .{ .commercial = .yes, .share_alike = false, .fou_empty = true, .controlled = false });
        return table;
    };
    var lines = Lines.init(text);
    var lineno: usize = 0;
    var cur: ?[]const u8 = null;
    var row: Row = undefined;
    var seen = RowSeen{};
    while (lines.next()) |l| {
        lineno += 1;
        if (l.len == 0 or l[0] == '#') continue;
        const header_open = "[licences.\"";
        const header_close = "\"]";
        if (l[0] == '[') {
            if (!(l.len > header_open.len + header_close.len and std.mem.startsWith(u8, l, header_open) and
                std.mem.endsWith(u8, l, header_close) and isId(l[header_open.len .. l.len - header_close.len])))
                return badAt(alloc, msg, path, lineno, "not a row header: {s}", .{l});
            if (cur) |id| try finishRow(alloc, msg, path, &table, id, row, seen);
            const id = l[header_open.len .. l.len - header_close.len];
            if (table.contains(id)) return badAt(alloc, msg, path, lineno, "a second row of {s}", .{id});
            cur = id;
            row = .{ .commercial = .yes, .share_alike = false, .fou_empty = true, .controlled = false };
            seen = .{};
            continue;
        }
        if (cur == null) return badAt(alloc, msg, path, lineno, "a line before the first row: {s}", .{l});
        if (keyValue(l, "commercial")) |v| {
            if (seen.commercial) return badAt(alloc, msg, path, lineno, "commercial given twice", .{});
            seen.commercial = true;
            row.commercial = if (std.mem.eql(u8, v, "\"yes\""))
                .yes
            else if (std.mem.eql(u8, v, "\"no\""))
                .no
            else if (std.mem.eql(u8, v, "\"unknown\""))
                .unknown
            else
                return badAt(alloc, msg, path, lineno, "commercial is \"yes\", \"no\" or \"unknown\", not {s}", .{v});
        } else if (keyValue(l, "share_alike")) |v| {
            if (seen.share_alike) return badAt(alloc, msg, path, lineno, "share_alike given twice", .{});
            seen.share_alike = true;
            row.share_alike = if (std.mem.eql(u8, v, "true"))
                true
            else if (std.mem.eql(u8, v, "false"))
                false
            else
                return badAt(alloc, msg, path, lineno, "share_alike is true or false, not {s}", .{v});
        } else if (keyValue(l, "field_of_use")) |v| {
            if (seen.field_of_use) return badAt(alloc, msg, path, lineno, "field_of_use given twice", .{});
            seen.field_of_use = true;
            row.fou_empty = if (std.mem.eql(u8, v, "[]"))
                true
            else if (v.len >= 4 and std.mem.startsWith(u8, v, "[\"") and std.mem.endsWith(u8, v, "\"]"))
                false
            else
                return badAt(alloc, msg, path, lineno, "field_of_use is [] or [\"...\"], not {s}", .{v});
        } else if (keyValue(l, "distribution")) |v| {
            if (seen.distribution) return badAt(alloc, msg, path, lineno, "distribution given twice", .{});
            seen.distribution = true;
            row.controlled = if (std.mem.eql(u8, v, "\"public\""))
                false
            else if (std.mem.eql(u8, v, "\"controlled\""))
                true
            else
                return badAt(alloc, msg, path, lineno, "distribution is \"public\" or \"controlled\", not {s}", .{v});
        } else if (beginsKey(l, "name")) {
            if (seen.name) return badAt(alloc, msg, path, lineno, "name given twice", .{});
            seen.name = true;
        } else if (beginsKey(l, "url")) {
            if (seen.url) return badAt(alloc, msg, path, lineno, "url given twice", .{});
            seen.url = true;
        } else if (beginsKey(l, "attribution")) {
            if (seen.attribution) return badAt(alloc, msg, path, lineno, "attribution given twice", .{});
            seen.attribution = true;
        } else return badAt(alloc, msg, path, lineno, "not a line of a row: {s}", .{l});
    }
    if (cur) |id| try finishRow(alloc, msg, path, &table, id, row, seen);
    return table;
}

fn finishRow(alloc: std.mem.Allocator, msg: *[]const u8, path: []const u8, table: *Table, id: []const u8, row: Row, seen: RowSeen) Error!void {
    inline for (.{ "commercial", "share_alike", "field_of_use", "distribution" }) |k| {
        if (!@field(seen, k)) return badFile(alloc, msg, path, "the row of {s} has no {s} line", .{ id, k });
    }
    try table.put(id, row);
}

// --- 2b: the `module` and `uses` lines -------------------------------------

/// The `module` and `uses` lines of a module file or `pack.def`.
pub const DefLines = struct {
    /// the name of the first `module` line; null: none
    module: ?[]const u8 = null,
    uses: []const []const u8 = &.{},
    /// the file is shown public (Version 0.93, ruling 1); a file that
    /// cannot be read or is not UTF-8 is not
    public: bool = false,
};

// --- Version 0.93, ruling 1: shown public ----------------------------------

/// Is `l` (a line cut and trimmed as ruling 1 of 0.29 says) exactly
/// `distribution`, one or more spaces or tabs, and `public`?
fn exactPublicLine(l: []const u8) bool {
    const word = "distribution";
    if (!std.mem.startsWith(u8, l, word)) return false;
    const rest = l[word.len..];
    if (rest.len == 0 or !isSpace(rest[0])) return false;
    return std.mem.eql(u8, std.mem.trimLeft(u8, rest, " \t"), "public");
}

/// A doubtful line: with every double quote removed and then spaces, tabs
/// and carriage returns removed at its ends, it begins with `distribution`,
/// and it is not the exact line of `exactPublicLine` (with its quotes).
fn doubtfulLine(l: []const u8) bool {
    if (exactPublicLine(l)) return false;
    var buf: [12]u8 = undefined; // the length of `distribution`
    var n: usize = 0;
    var started = false;
    for (l) |c| {
        if (c == '"') continue;
        if (!started and (c == ' ' or c == '\t' or c == '\r')) continue;
        started = true;
        if (n == buf.len) break;
        buf[n] = c;
        n += 1;
    }
    return n == buf.len and std.mem.eql(u8, &buf, "distribution");
}

/// Version 0.93, ruling 1: the text of a module file or `pack.def` is shown
/// public when it is UTF-8, holds no NUL, no U+FEFF and no carriage return
/// other than one directly before a line feed or at the end, has at least
/// one exact `distribution public` line, and no doubtful line.
pub fn shownPublic(text: []const u8) bool {
    if (!std.unicode.utf8ValidateSlice(text)) return false;
    if (std.mem.indexOf(u8, text, "\xef\xbb\xbf") != null) return false; // U+FEFF
    for (text, 0..) |c, i| {
        if (c == 0) return false;
        if (c == '\r' and i + 1 != text.len and text[i + 1] != '\n') return false;
    }
    var found = false;
    var lines = Lines.init(text);
    while (lines.next()) |l| {
        if (doubtfulLine(l)) return false;
        if (exactPublicLine(l)) found = true;
    }
    return found;
}

/// `word`, one or more spaces or tabs, and a name: the name.
fn wordName(l: []const u8, word: []const u8) ?[]const u8 {
    if (!std.mem.startsWith(u8, l, word)) return null;
    const rest = l[word.len..];
    if (rest.len == 0 or !isSpace(rest[0])) return null;
    const n = std.mem.trimLeft(u8, rest, " \t");
    return if (isName(n)) n else null;
}

/// The lines of `text`; text that is not UTF-8 adds no line.
pub fn defLines(alloc: std.mem.Allocator, text: []const u8) !DefLines {
    if (!std.unicode.utf8ValidateSlice(text)) return .{};
    var out = DefLines{ .public = shownPublic(text) };
    var uses = std.ArrayList([]const u8).init(alloc);
    var lines = Lines.init(text);
    while (lines.next()) |l| {
        if (wordName(l, "module")) |n| {
            if (out.module == null) out.module = n;
        } else if (wordName(l, "uses")) |n| try uses.append(n);
    }
    out.uses = uses.items;
    return out;
}

/// The lines of the file at `path`; a file that cannot be read adds no line.
pub fn defFileLines(alloc: std.mem.Allocator, path: []const u8) !DefLines {
    const text = std.fs.cwd().readFileAlloc(alloc, path, max_file) catch |err| switch (err) {
        error.OutOfMemory => return error.OutOfMemory,
        else => return .{},
    };
    return defLines(alloc, text);
}

/// 2b: the profile of every module file. `lic[i]` is the profile of file
/// i's licence; a module's profile is the widest of it and those of the
/// modules it uses, directly or through others (all files of a used name).
pub fn moduleProfiles(alloc: std.mem.Allocator, lines: []const DefLines, lic: []const Profile) ![]Profile {
    const prof = try alloc.dupe(Profile, lic);
    var changed = true;
    while (changed) {
        changed = false;
        for (lines, 0..) |dl, i| {
            const p = usesProfile(lines, prof, prof[i], dl.uses);
            if (p != prof[i]) {
                prof[i] = p;
                changed = true;
            }
        }
    }
    return prof;
}

/// `start`, widened by the profile of every module file named in `names`.
pub fn usesProfile(lines: []const DefLines, prof: []const Profile, start: Profile, names: []const []const u8) Profile {
    var p = start;
    for (names) |u| {
        for (lines, 0..) |other, j| {
            const n = other.module orelse continue;
            if (std.mem.eql(u8, n, u)) p = p.wider(prof[j]);
        }
    }
    return p;
}

// --- tests -------------------------------------------------------------------

test "table lines" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var msg: []const u8 = "";
    try std.testing.expect(isId("CC-BY-SA-4.0"));
    try std.testing.expect(!isId("a b"));
    try std.testing.expectEqualStrings("x", keyValue("share_alike\t= x", "share_alike").?);
    try std.testing.expect(keyValue("share_alikes = x", "share_alike") == null);
    try std.testing.expect(beginsKey("name= 1", "name"));
    try std.testing.expect(!beginsKey("names = 1", "name"));
    try std.testing.expectEqualStrings("core", (try defLines(a, "  module\tcore \r\nmodule other\nuses x # c\nuses  y\r")).module.?);
    const dl = try defLines(a, "uses x # c\nuses  y\r");
    try std.testing.expectEqual(@as(usize, 1), dl.uses.len);
    try std.testing.expectEqualStrings("y", dl.uses[0]);
    _ = &msg;
}

test "shown public (Version 0.93, ruling 1)" {
    const yes = [_][]const u8{
        "format x\ndistribution public\n",
        "distribution\tpublic\r\n",
        "distribution public\r",
        "  distribution  public  \ndistribution public\n",
        "# distribution controlled\ndistribution public\nsource \"distribution controlled\"\n",
    };
    for (yes) |t| try std.testing.expect(shownPublic(t));
    const no = [_][]const u8{
        "",
        "format x\n",
        "distribution controlled\n",
        "distribution public\ndistribution controlled\n",
        "distribution public\n\"distribution\" controlled\n",
        "distribution public\ndistri\"bution\" x\n",
        "distribution public\ndistribution\"controlled\"\n",
        "distribution public\ndistribution # x\n",
        "distribution public\n\"distribution public\"\n",
        "distribution public\ndistributions x\n",
        "distribution public # note\n",
        "distribution \"public\"\n",
        "distribution\rpublic\n",
        "x\n\rdistribution public\n",
        "\xef\xbb\xbfformat x\ndistribution public\n",
        "distribution public\n# \x00\n",
        "distribution public\n# \xff\n",
    };
    for (no) |t| try std.testing.expect(!shownPublic(t));
}
