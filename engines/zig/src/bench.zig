//! gt-bench-zig: the benchmark of spec Version 0.25, ruling 2.
//!
//!     gt-bench-zig [<set.json>] [--packs <dir>] [--models <dir>]
//!
//! Defaults: `bench/set.json`, `--packs packs`, `--models <packs>/../model`,
//! all relative to the current directory (the repository root). Vector paths
//! in the set are relative to the current directory as well.
//!
//! It loads the packs the set's vectors name (their `from` and `to`) and the
//! model modules those packs use into one engine instance, timing the load.
//! Then, for each vector in order: one conversion whose output must equal the
//! vector's `expect` (else the run fails, exit 1, the reason on standard
//! error), then `iterations` conversions, timed. Standard output holds one
//! line per vector, then the load line, and nothing else:
//!
//!     {"vector": "<path>", "iterations": <n>, "ns_per_op": <integer>}
//!     {"load": <number of packs>, "ns": <integer>}

const std = @import("std");
const gt = @import("main.zig");

const Engine = gt.Engine;
const KV = gt.KV;

const max_file: usize = 64 << 20;

const Vec = struct {
    path: []const u8,
    from: []const u8,
    to: []const u8,
    input: []const u8,
    expect: []const u8,
    context: ?[]const KV,
    max_items: ?usize,
};

fn die(comptime fmt: []const u8, args: anytype) noreturn {
    std.io.getStdErr().writer().print("bench: " ++ fmt ++ "\n", args) catch {};
    std.process.exit(1);
}

fn str(obj: std.json.ObjectMap, key: []const u8) ?[]const u8 {
    const v = obj.get(key) orelse return null;
    return if (v == .string) v.string else null;
}

pub fn main() !void {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    const alloc = arena.allocator();

    const args = try std.process.argsAlloc(alloc);
    var set_path: []const u8 = "bench/set.json";
    var packs_dir: []const u8 = "packs";
    var models_opt: ?[]const u8 = null;
    var ai: usize = 1;
    while (ai < args.len) : (ai += 1) {
        const a = args[ai];
        if (std.mem.eql(u8, a, "--packs") or std.mem.eql(u8, a, "--models")) {
            ai += 1;
            if (ai >= args.len) die("{s} needs a value", .{a});
            if (std.mem.eql(u8, a, "--packs")) packs_dir = args[ai] else models_opt = args[ai];
        } else if (std.mem.startsWith(u8, a, "--")) {
            die("unknown option {s}", .{a});
        } else set_path = a;
    }
    const models_dir = models_opt orelse try std.fmt.allocPrint(alloc, "{s}/../model", .{packs_dir});

    // the set, and every vector of it, read before anything is timed
    const set_text = std.fs.cwd().readFileAlloc(alloc, set_path, max_file) catch |err|
        die("cannot read {s}: {s}", .{ set_path, @errorName(err) });
    const set = std.json.parseFromSliceLeaky(std.json.Value, alloc, set_text, .{}) catch
        die("{s} is not JSON", .{set_path});
    if (set != .object) die("{s} is not a JSON object", .{set_path});
    const it_v = set.object.get("iterations") orelse die("{s}: no `iterations`", .{set_path});
    if (it_v != .integer or it_v.integer < 1) die("{s}: `iterations` is not an integer of 1 or more", .{set_path});
    const iterations: u64 = @intCast(it_v.integer);
    const vl = set.object.get("vectors") orelse die("{s}: no `vectors`", .{set_path});
    if (vl != .array) die("{s}: `vectors` is not an array", .{set_path});

    var vecs = std.ArrayList(Vec).init(alloc);
    var names = std.ArrayList([]const u8).init(alloc);
    for (vl.array.items) |pv| {
        if (pv != .string) die("{s}: a vector path is not a string", .{set_path});
        const path = pv.string;
        const text = std.fs.cwd().readFileAlloc(alloc, path, max_file) catch |err|
            die("cannot read {s}: {s}", .{ path, @errorName(err) });
        const v = std.json.parseFromSliceLeaky(std.json.Value, alloc, text, .{}) catch
            die("{s} is not JSON", .{path});
        if (v != .object) die("{s} is not a JSON object", .{path});
        const o = v.object;
        var context: ?[]const KV = null;
        if (o.get("context")) |cv| {
            if (cv != .object) die("{s}: `context` is not an object", .{path});
            var kvs = std.ArrayList(KV).init(alloc);
            var cit = cv.object.iterator();
            while (cit.next()) |ce| {
                if (ce.value_ptr.* != .string) die("{s}: context key {s} is not a string", .{ path, ce.key_ptr.* });
                try kvs.append(.{ .key = ce.key_ptr.*, .value = ce.value_ptr.*.string });
            }
            context = kvs.items;
        }
        var max_items: ?usize = null;
        if (o.get("max_items")) |mi| {
            if (mi != .integer or mi.integer < 0) die("{s}: `max_items` is not an integer of 0 or more", .{path});
            max_items = @intCast(mi.integer);
        }
        const vec = Vec{
            .path = path,
            .from = str(o, "from") orelse die("{s}: no `from`", .{path}),
            .to = str(o, "to") orelse die("{s}: no `to`", .{path}),
            .input = str(o, "input") orelse die("{s}: no `input`", .{path}),
            .expect = str(o, "expect") orelse die("{s}: no `expect`", .{path}),
            .context = context,
            .max_items = max_items,
        };
        try vecs.append(vec);
        try names.append(vec.from);
        try names.append(vec.to);
    }

    // the load: the named packs and the modules they use, timed
    var eng = Engine.init(alloc);
    var timer = try std.time.Timer.start();
    const loaded = eng.loadPacksOnly(packs_dir, models_dir, names.items) catch |err|
        die("load failed: {s} ({s})", .{ eng.last_error, @errorName(err) });
    const load_ns = timer.read();

    var out = std.ArrayList(u8).init(alloc);
    const w = out.writer();
    var varena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer varena.deinit();
    for (vecs.items) |v| {
        eng.setMaxItems(v.max_items orelse gt.default_max_items);
        eng.scratch = varena.allocator();
        const got = eng.convert(v.from, v.to, v.input, v.context) catch |err|
            die("{s}: convert failed: {s} ({s})", .{ v.path, eng.last_error, @errorName(err) });
        if (!std.mem.eql(u8, got, v.expect)) die("{s}: the output differs from `expect`\n   expected: {s}\n   got:      {s}", .{ v.path, v.expect, got });
        _ = varena.reset(.retain_capacity);
        timer.reset();
        var i: u64 = 0;
        while (i < iterations) : (i += 1) {
            const r = eng.convert(v.from, v.to, v.input, v.context) catch |err|
                die("{s}: convert failed on iteration {d}: {s} ({s})", .{ v.path, i, eng.last_error, @errorName(err) });
            std.mem.doNotOptimizeAway(r.ptr);
            _ = varena.reset(.retain_capacity);
        }
        const total = timer.read();
        try w.writeAll("{\"vector\": ");
        try std.json.stringify(v.path, .{}, w);
        try w.print(", \"iterations\": {d}, \"ns_per_op\": {d}}}\n", .{ iterations, total / iterations });
    }
    eng.scratch = alloc;
    try w.print("{{\"load\": {d}, \"ns\": {d}}}\n", .{ loaded.packs.len, load_ns });
    std.io.getStdOut().writer().writeAll(out.items) catch std.process.exit(1);
}
