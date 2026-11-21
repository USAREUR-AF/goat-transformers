//! goat-xf: the command-line tool of the Zig engine (spec Version 0.23, the
//! command-line contract).
//!
//!     goat-xf convert --from <format> --to <format> [--set <key>=<value>]... <options>
//!     goat-xf list-formats <options>
//!     goat-xf capability --from <format> --to <format> <options>
//!     goat-xf matrix <options>
//!     goat-xf licences [--json] <options>
//!     goat-xf help
//!
//! `--profile <open | open+copyleft | everything>` and the `licences`
//! subcommand are Version 0.29 (licence profiles in the loaders).
//!
//! Loading, `convert` and the capability report are the engine's own
//! (`main.zig`); this file reads the arguments, loads in the contract's order
//! and writes the contract's output.

const std = @import("std");
const gt = @import("main.zig");

const Engine = gt.Engine;
const KV = gt.KV;

const usage_text =
    \\usage:
    \\  goat-xf convert --from <format> --to <format> [--set <key>=<value>]... <options>
    \\  goat-xf list-formats <options>
    \\  goat-xf capability --from <format> --to <format> <options>
    \\  goat-xf matrix <options>
    \\  goat-xf licences [--json] <options>
    \\  goat-xf help
    \\
    \\<options>, in any order, each at most once:
    \\  --packs <dir>                 the directory whose subdirectories are packs (default: packs)
    \\  --models <dir>                the model modules (default: <packs>/../model)
    \\  --packs-only <name>[,<name>]  load only these subdirectories of --packs, in the order given
    \\  --max-items <n>               the limit on list items one decode holds (default: 100000)
    \\  --max-distribution <public|controlled>   (default: controlled)
    \\  --profile <open|open+copyleft|everything>  load only the packs and modules
    \\                                the profile holds (default: no profile)
    \\
    \\licences writes one line per loaded pack: directory, format, licence and
    \\profile, tab-separated; --json (no value) writes them as JSON instead.
    \\
    \\Exit status: 0 success, 1 a load or call failure (standard error begins
    \\with the kind and a colon), 2 a usage error.
    \\
;

const Sub = enum { convert, list_formats, capability, matrix, licences };

const Opts = struct {
    sub: Sub,
    from: ?[]const u8 = null,
    to: ?[]const u8 = null,
    sets: std.ArrayList(KV),
    packs: ?[]const u8 = null,
    models: ?[]const u8 = null,
    packs_only: ?[]const u8 = null,
    max_items: ?u64 = null,
    max_distribution: ?gt.Dist = null,
    profile: ?[]const u8 = null,
    json: bool = false,
};

fn usageExit(comptime fmt: []const u8, args: anytype) noreturn {
    const w = std.io.getStdErr().writer();
    w.print("usage error: " ++ fmt ++ "\n", args) catch {};
    w.writeAll(usage_text) catch {};
    std.process.exit(2);
}

// Exit 1: the first line of standard error is the failure's message.
fn failExit(msg: []const u8) noreturn {
    const w = std.io.getStdErr().writer();
    w.print("{s}\n", .{msg}) catch {};
    std.process.exit(1);
}

// One or more digits alone, at most 2^63 - 1; leading zeros allowed.
fn parseMaxItems(s: []const u8) ?u64 {
    if (s.len == 0) return null;
    const limit: u64 = std.math.maxInt(i64);
    var v: u64 = 0;
    for (s) |c| {
        if (c < '0' or c > '9') return null;
        const d: u64 = c - '0';
        if (v > (limit - d) / 10) return null;
        v = v * 10 + d;
    }
    return v;
}

// Every argument is checked here, before anything is loaded.
fn parseArgs(alloc: std.mem.Allocator, args: []const []const u8) !Opts {
    const eq = std.mem.eql;
    if (args.len == 0) usageExit("no subcommand", .{});
    const first = args[0];
    if (eq(u8, first, "help") or eq(u8, first, "-h") or eq(u8, first, "--help")) {
        std.io.getStdOut().writer().writeAll(usage_text) catch {};
        std.process.exit(0);
    }
    const sub: Sub = if (eq(u8, first, "convert"))
        .convert
    else if (eq(u8, first, "list-formats"))
        .list_formats
    else if (eq(u8, first, "capability"))
        .capability
    else if (eq(u8, first, "matrix"))
        .matrix
    else if (eq(u8, first, "licences"))
        .licences
    else
        usageExit("unknown subcommand {s}", .{first});

    var o = Opts{ .sub = sub, .sets = std.ArrayList(KV).init(alloc) };
    const takes_pair = sub == .convert or sub == .capability;
    var i: usize = 1;
    while (i < args.len) : (i += 2) {
        const name = args[i];
        // `--json` takes no value: the next argument is again an option name
        if (sub == .licences and eq(u8, name, "--json")) {
            if (o.json) usageExit("--json given twice", .{});
            o.json = true;
            i -= 1;
            continue;
        }
        const known = eq(u8, name, "--packs") or eq(u8, name, "--models") or eq(u8, name, "--packs-only") or
            eq(u8, name, "--max-items") or eq(u8, name, "--max-distribution") or eq(u8, name, "--profile") or
            (takes_pair and (eq(u8, name, "--from") or eq(u8, name, "--to"))) or
            (sub == .convert and eq(u8, name, "--set"));
        if (!known) usageExit("{s} is not an option of {s}", .{ name, first });
        if (i + 1 >= args.len) usageExit("{s} needs a value", .{name});
        const value = args[i + 1];
        if (eq(u8, name, "--set")) {
            const at = std.mem.indexOfScalar(u8, value, '=') orelse usageExit("--set takes <key>=<value>", .{});
            if (at == 0) usageExit("--set takes <key>=<value> with a key before the =", .{});
            try o.sets.append(.{ .key = value[0..at], .value = value[at + 1 ..] });
            continue;
        }
        if (eq(u8, name, "--max-items")) {
            if (o.max_items != null) usageExit("{s} given twice", .{name});
            o.max_items = parseMaxItems(value) orelse usageExit("--max-items takes digits, at most 9223372036854775807", .{});
            continue;
        }
        if (eq(u8, name, "--max-distribution")) {
            if (o.max_distribution != null) usageExit("{s} given twice", .{name});
            o.max_distribution = if (eq(u8, value, "public"))
                .public
            else if (eq(u8, value, "controlled"))
                .controlled
            else
                usageExit("--max-distribution takes public or controlled", .{});
            continue;
        }
        if (eq(u8, name, "--profile")) {
            if (o.profile != null) usageExit("{s} given twice", .{name});
            if (gt.Profile.parse(value) == null) usageExit("--profile takes open, open+copyleft or everything", .{});
            o.profile = value;
            continue;
        }
        const slot: *?[]const u8 = if (eq(u8, name, "--from"))
            &o.from
        else if (eq(u8, name, "--to"))
            &o.to
        else if (eq(u8, name, "--packs"))
            &o.packs
        else if (eq(u8, name, "--models"))
            &o.models
        else
            &o.packs_only;
        if (slot.* != null) usageExit("{s} given twice", .{name});
        slot.* = value;
    }
    if (takes_pair) {
        if (o.from == null) usageExit("{s} needs --from", .{first});
        if (o.to == null) usageExit("{s} needs --to", .{first});
    }
    if (o.packs_only) |only| {
        if (only.len == 0) usageExit("--packs-only is empty", .{});
        var parts = std.mem.splitScalar(u8, only, ',');
        while (parts.next()) |part| {
            if (part.len == 0) usageExit("--packs-only holds an empty name", .{});
        }
    }
    return o;
}

fn strLess(_: void, a: []const u8, b: []const u8) bool {
    return std.mem.lessThan(u8, a, b);
}

// Loading (Version 0.23): every module of --models, then the packs; with
// --profile, only what the profile holds (Version 0.29).
fn load(eng: *Engine, alloc: std.mem.Allocator, o: *const Opts) ![]const Engine.TreePack {
    var only: ?[]const []const u8 = null;
    if (o.packs_only) |text| {
        var names = std.ArrayList([]const u8).init(alloc);
        var parts = std.mem.splitScalar(u8, text, ',');
        while (parts.next()) |part| try names.append(part);
        only = names.items;
    }
    const loaded = eng.loadTree(.{
        .packs_dir = o.packs orelse "packs",
        .models_dir = o.models,
        .packs_only = only,
        .profile = o.profile,
        .read_licences = o.sub == .licences,
    }) catch |err| {
        if (err == error.OutOfMemory) return err;
        failExit(if (eng.last_error.len > 0) eng.last_error else @errorName(err));
    };
    return loaded.packs;
}

fn packLess(_: void, a: Engine.TreePack, b: Engine.TreePack) bool {
    return std.mem.lessThan(u8, a.dir, b.dir);
}

// A JSON string value of `licences --json` (Version 0.29, ruling 4c).
fn jsonString(out: *std.ArrayList(u8), s: []const u8) !void {
    try out.append('"');
    for (s) |c| {
        switch (c) {
            '"' => try out.appendSlice("\\\""),
            '\\' => try out.appendSlice("\\\\"),
            0...0x1f => try out.writer().print("\\u{x:0>4}", .{c}),
            else => try out.append(c),
        }
    }
    try out.append('"');
}

// The loaded format names in byte order.
fn sortedFormats(alloc: std.mem.Allocator, eng: *const Engine) ![]const []const u8 {
    const names = try alloc.alloc([]const u8, eng.packs.items.len);
    for (eng.packs.items, 0..) |p, i| names[i] = p.format;
    std.mem.sort([]const u8, names, {}, strLess);
    return names;
}

fn joinList(out: *std.ArrayList(u8), items: []const []const u8) !void {
    for (items, 0..) |k, i| {
        if (i > 0) try out.append(' ');
        try out.appendSlice(k);
    }
}

// One line of the matrix form.
fn capabilityLine(eng: *Engine, out: *std.ArrayList(u8), from: []const u8, to: []const u8) !void {
    const c = eng.capability(from, to) catch |err| {
        if (err == error.OutOfMemory) return err;
        failExit(eng.last_error);
    };
    try out.writer().print("{s}\t{s}\t{s}\t", .{ from, to, c.grade });
    try joinList(out, c.carried);
    try out.append('\t');
    try joinList(out, c.dropped);
    try out.append('\n');
}

// The context: a key given twice takes its last value and keeps the place of
// its first.
fn context(alloc: std.mem.Allocator, sets: []const KV) ![]const KV {
    var ctx = std.ArrayList(KV).init(alloc);
    outer: for (sets) |kv| {
        for (ctx.items) |*have| {
            if (std.mem.eql(u8, have.key, kv.key)) {
                have.value = kv.value;
                continue :outer;
            }
        }
        try ctx.append(kv);
    }
    return ctx.items;
}

pub fn main() !void {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    const alloc = arena.allocator();

    const argv = try std.process.argsAlloc(alloc);
    const o = try parseArgs(alloc, if (argv.len > 0) argv[1..] else argv);

    var eng = Engine.init(alloc);
    if (o.max_distribution) |d| eng.setMaxDistribution(d);
    if (o.max_items) |n| eng.setMaxItems(@intCast(n));
    const loaded = try load(&eng, alloc, &o);

    var out = std.ArrayList(u8).init(alloc);
    switch (o.sub) {
        .list_formats => {
            const fmts = try sortedFormats(alloc, &eng);
            for (fmts) |f| {
                const p = eng.findPack(f).?;
                try out.writer().print("{s}\t{s}\t{s}\n", .{ p.format, p.version, @tagName(p.wire) });
            }
        },
        .licences => {
            const packs = try alloc.dupe(Engine.TreePack, loaded);
            std.mem.sort(Engine.TreePack, packs, {}, packLess);
            if (o.json) try out.appendSlice("{\"packs\":[");
            for (packs, 0..) |p, i| {
                const lic = p.licence.?;
                if (o.json) {
                    if (i > 0) try out.append(',');
                    try out.appendSlice("{\"pack\":");
                    try jsonString(&out, p.dir);
                    try out.appendSlice(",\"format\":");
                    try jsonString(&out, p.format);
                    try out.appendSlice(",\"licence\":");
                    try jsonString(&out, lic);
                    try out.appendSlice(",\"profile\":");
                    try jsonString(&out, p.profile.name());
                    try out.append('}');
                } else {
                    try out.writer().print("{s}\t{s}\t{s}\t{s}\n", .{ p.dir, p.format, lic, p.profile.name() });
                }
            }
            if (o.json) try out.appendSlice("]}\n");
        },
        .capability => try capabilityLine(&eng, &out, o.from.?, o.to.?),
        .matrix => {
            try out.appendSlice("from\tto\tgrade\tcarried\tdropped\n");
            const fmts = try sortedFormats(alloc, &eng);
            for (fmts) |f| {
                for (fmts) |t| try capabilityLine(&eng, &out, f, t);
            }
        },
        .convert => {
            const from = o.from.?;
            const to = o.to.?;
            // `--from`, then `--to`, before standard input is read
            for ([_][]const u8{ from, to }) |f| {
                if (eng.findPack(f) == null) {
                    failExit(try std.fmt.allocPrint(alloc, "unknown-format: no loaded pack has format {s}", .{f}));
                }
            }
            const input = try std.io.getStdIn().readToEndAlloc(alloc, std.math.maxInt(usize));
            if (!std.unicode.utf8ValidateSlice(input)) {
                failExit("malformed-wire: the input is not valid UTF-8");
            }
            const ctx: ?[]const KV = if (o.sets.items.len > 0) try context(alloc, o.sets.items) else null;
            const result = eng.convert(from, to, input, ctx) catch |err| {
                if (err == error.OutOfMemory) return err;
                failExit(eng.last_error);
            };
            try out.appendSlice(result);
        },
    }
    std.io.getStdOut().writer().writeAll(out.items) catch std.process.exit(1);
}
