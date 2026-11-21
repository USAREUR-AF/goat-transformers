//! goat-transformers, the Zig engine, as a module for another program.
//!
//!     const gt = @import("goat_transformers");
//!     var engine = gt.Engine.init(allocator);
//!     _ = try engine.loadPacksOnly("vendor/goat/packs", "vendor/goat/model", &.{ "cot-xml", "geojson" });
//!     const out = try engine.convert("cot-xml", "geojson", input, null);
//!
//! `loadPacksOnly` loads the named packs and the model modules they need.
//!
//! `loadTree` loads a tree as the command-line tool does (spec Version 0.23,
//! Loading), and takes an optional licence profile (Version 0.29): with
//! `.profile = "open"` (or `"open+copyleft"`, `"everything"`) it reads
//! `licences.toml` beside the packs directory, each pack's `REUSE.toml` and
//! each module's `.def.license`, and loads only what the profile holds; a
//! file it cannot read, or another profile name, is `error.@"bad-licence"`.
//! With no profile it reads no licence file.
//!
//!     const loaded = try engine.loadTree(.{ .packs_dir = "vendor/goat/packs", .profile = "open" });
//! The engine keeps what it loads for its whole life and frees nothing on its
//! own: give it an arena. A failure is a Zig error named as the specification
//! names it, and `engine.last_error` holds `<kind>: <detail>`.
//!
//! One loaded engine may convert on several threads at once through
//! `convertIn`, each call with its own `Engine.Call` (its allocator, and its
//! own failure message); `convert` itself is for one thread at a time.
//!
//!     var call = gt.Engine.Call{ .alloc = per_thread_allocator };
//!     const out = engine.convertIn(&call, "cot-xml", "geojson", input, null) catch |err| ...; // call.last_error

const std = @import("std");
const engine_zig = @import("main.zig");

pub const Engine = engine_zig.Engine;
pub const Entity = engine_zig.Entity;
pub const Value = engine_zig.MV;
/// One caller-supplied key of a conversion: the `context` of `Engine.convert`.
pub const KV = engine_zig.KV;
pub const Distribution = engine_zig.Dist;

const cot_event =
    \\<event version="2.0" uid="J-01334" type="a-f-G-U-C" time="2021-02-27T20:00:00.000Z" how="m-g"><point lat="30.0090027" lon="-85.9578182" hae="-42.6" ce="45.3" le="99.5"/><detail><contact callsign="GATOR"/></detail></event>
;
const geojson_feature =
    \\{"type":"Feature","geometry":{"type":"Point","coordinates":[-85.9578182,30.0090027,-42.6]},"properties":{"type":"a-f-G-U-C","time_ms":1614456000000,"how":"m-g","ce":45.3,"le":99.5,"callsign":"GATOR"},"id":"J-01334"}
;

// `zig build module-test` runs this from engines/zig, so the packs are ../../packs
test "the module loads two packs and converts" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    var engine = Engine.init(arena.allocator());
    const loaded = try engine.loadPacksOnly("../../packs", "../../model", &.{ "cot-xml", "geojson" });
    try std.testing.expectEqual(@as(usize, 2), loaded.packs.len);
    try std.testing.expectEqualStrings(geojson_feature, try engine.convert("cot-xml", "geojson", cot_event, null));
}

test {
    _ = @import("licence.zig");
}

// Version 0.29, ruling 3: the library loader with a profile.
const lic_fixtures = "../../packs/conformance/tool-fixtures/";

fn treeFormats(alloc: std.mem.Allocator, loaded: Engine.TreeLoaded) ![]const u8 {
    var out = std.ArrayList(u8).init(alloc);
    for (loaded.packs) |p| try out.writer().print("{s}:{s}:{s}:{s} ", .{ p.dir, p.format, p.licence orelse "-", p.profile.name() });
    return out.items;
}

test "the loader with a profile loads what the profile holds" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const packs = lic_fixtures ++ "licences-a/packs";

    var e1 = Engine.init(a);
    const open = try e1.loadTree(.{ .packs_dir = packs, .profile = "open" });
    try std.testing.expectEqualStrings("plain:lic-plain:Apache-2.0:open zz-first-by-format:lic-aa:Apache-2.0:open ", try treeFormats(a, open));
    // `book` (CC-BY-NC-SA) and `derived`, which uses it, and `sa` are not loaded
    try std.testing.expectEqual(@as(usize, 1), open.modules);
    try std.testing.expect(e1.findPack("lic-nc") == null);

    var e2 = Engine.init(a);
    const cl = try e2.loadTree(.{ .packs_dir = packs, .profile = "open+copyleft", .packs_only = &.{ "nc", "uses-sa", "nc" } });
    try std.testing.expectEqualStrings("uses-sa:lic-uses-sa:Apache-2.0:open+copyleft ", try treeFormats(a, cl));

    // no profile: every pack, and no licence file read
    var e3 = Engine.init(a);
    const all = try e3.loadTree(.{ .packs_dir = packs });
    try std.testing.expectEqual(@as(usize, 11), all.packs.len);
    try std.testing.expect(all.packs[0].licence == null);

    // no profile but the licences read: a pack in none is loaded, profile none
    var e4 = Engine.init(a);
    const closed = try e4.loadTree(.{ .packs_dir = packs, .packs_only = &.{"closed"}, .read_licences = true });
    try std.testing.expectEqualStrings("closed:lic-closed:OGL-UK-3.0:none ", try treeFormats(a, closed));

    // a name not one of the three is refused before anything is read
    var e5 = Engine.init(a);
    try std.testing.expectError(error.@"bad-licence", e5.loadTree(.{ .packs_dir = "no/such/dir", .profile = "Open" }));
    try std.testing.expect(std.mem.startsWith(u8, e5.last_error, "bad-licence: "));

    // a table that cannot be read: bad-licence with a profile, nothing loaded
    var e6 = Engine.init(a);
    try std.testing.expectError(error.@"bad-licence", e6.loadTree(.{ .packs_dir = lic_fixtures ++ "licences-bad-table/packs", .profile = "everything" }));
    try std.testing.expectEqual(@as(u32, 0), e6.modules.count());
    var e7 = Engine.init(a);
    _ = try e7.loadTree(.{ .packs_dir = lic_fixtures ++ "licences-bad-table/packs" });
    try std.testing.expect(e7.findPack("lic-plain") != null);

    // a module licence file with two licence lines, read before any module loads
    var e8 = Engine.init(a);
    try std.testing.expectError(error.@"bad-licence", e8.loadTree(.{ .packs_dir = lic_fixtures ++ "licences-bad-module/packs", .profile = "open", .packs_only = &.{"plain"} }));
    try std.testing.expectEqual(@as(u32, 0), e8.modules.count());
}

// Version 0.25, ruling 1c: one instance used from several threads at once
// gives each conversion the result it gives alone. The packs of the
// benchmark set on every wire (the two catalog packs left out, for the time
// a Debug load of them takes); every conversion vector of those packs, failed
// conversions included, first once in order on the engine, then by eight
// threads at once, each in its own order and three times over. Each result,
// the output bytes or the failure's whole message, must equal the first one,
// which must agree with the vector.
const thread_packs = [_][]const u8{
    "adsb",           "asterix-cat062", "canonical-track-v2", "cot-protobuf", "cot-xml",
    "dhcpv6-options", "geojson",        "isa",                "mavlink2",     "nmea0183",
    "nmea2000",       "remote-id",      "sapient",
};

const TVec = struct {
    name: []const u8,
    from: []const u8,
    to: []const u8,
    input: []const u8,
    context: ?[]const KV,
    max_items: ?usize,
    // the result of the first, single-threaded run
    ok: bool = false,
    result: []const u8 = "",
};

fn runOne(engine: *const Engine, alloc: std.mem.Allocator, v: *const TVec) !struct { ok: bool, text: []const u8 } {
    var call = Engine.Call{ .alloc = alloc, .max_items = v.max_items };
    if (engine.convertIn(&call, v.from, v.to, v.input, v.context)) |out| {
        return .{ .ok = true, .text = out };
    } else |err| {
        if (err == error.OutOfMemory) return err;
        return .{ .ok = false, .text = call.last_error };
    }
}

const Worker = struct {
    engine: *const Engine,
    vecs: []const TVec,
    start: usize,
    differ: *std.atomic.Value(usize),
    done: *std.atomic.Value(usize),

    fn run(self: *const Worker) void {
        var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
        defer arena.deinit();
        const n = self.vecs.len;
        for (0..3) |round| {
            for (0..n) |i| {
                // each thread its own order: a start and a direction
                const j = if ((self.start + round) % 2 == 0) (self.start + i) % n else (self.start + n - i) % n;
                const v = &self.vecs[j];
                const got = runOne(self.engine, arena.allocator(), v) catch {
                    _ = self.differ.fetchAdd(1, .monotonic);
                    continue;
                };
                if (got.ok != v.ok or !std.mem.eql(u8, got.text, v.result)) {
                    std.debug.print("thread {d}: {s}: differs from the single-threaded run\n", .{ self.start, v.name });
                    _ = self.differ.fetchAdd(1, .monotonic);
                }
                _ = self.done.fetchAdd(1, .monotonic);
                _ = arena.reset(.retain_capacity);
            }
        }
    }
};

test "one engine converts on eight threads at once as it does alone" {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    const alloc = arena.allocator();
    var engine = Engine.init(alloc);
    _ = try engine.loadPacksOnly("../../packs", "../../model", &thread_packs);

    var vecs = std.ArrayList(TVec).init(alloc);
    for (thread_packs) |pk| {
        const vdir_path = try std.fmt.allocPrint(alloc, "../../packs/{s}/vectors", .{pk});
        var dir = std.fs.cwd().openDir(vdir_path, .{ .iterate = true }) catch continue;
        defer dir.close();
        var it = dir.iterate();
        while (try it.next()) |entry| {
            if (entry.kind != .file or !std.mem.endsWith(u8, entry.name, ".json")) continue;
            const text = try dir.readFileAlloc(alloc, entry.name, 64 << 20);
            const parsed = try std.json.parseFromSliceLeaky(std.json.Value, alloc, text, .{});
            const o = parsed.object;
            const from = (o.get("from") orelse continue).string;
            const to = (o.get("to") orelse continue).string;
            if (engine.findPack(from) == null or engine.findPack(to) == null) continue;
            var context: ?[]const KV = null;
            if (o.get("context")) |cv| {
                var kvs = std.ArrayList(KV).init(alloc);
                var cit = cv.object.iterator();
                while (cit.next()) |ce| try kvs.append(.{ .key = ce.key_ptr.*, .value = ce.value_ptr.*.string });
                context = kvs.items;
            }
            const max_items: ?usize = if (o.get("max_items")) |mi| @intCast(mi.integer) else null;
            var v = TVec{
                .name = try std.fmt.allocPrint(alloc, "{s}/{s}", .{ pk, entry.name }),
                .from = from,
                .to = to,
                .input = (o.get("input") orelse continue).string,
                .context = context,
                .max_items = max_items,
            };
            // the single-threaded run, checked against the vector
            const got = try runOne(&engine, alloc, &v);
            v.ok = got.ok;
            v.result = got.text;
            if (o.get("expect")) |want| {
                try std.testing.expect(got.ok);
                try std.testing.expectEqualStrings(want.string, got.text);
            } else if (o.get("expect_error")) |want| {
                try std.testing.expect(!got.ok);
                try std.testing.expect(std.mem.startsWith(u8, got.text, want.string));
                try std.testing.expectEqual(@as(u8, ':'), got.text[want.string.len]);
            }
            try vecs.append(v);
        }
    }
    var failed: usize = 0;
    for (vecs.items) |v| {
        if (!v.ok) failed += 1;
    }
    // both kinds of result are exercised
    try std.testing.expect(vecs.items.len > 100);
    try std.testing.expect(failed > 0);

    var differ = std.atomic.Value(usize).init(0);
    var done = std.atomic.Value(usize).init(0);
    const n_threads = 8;
    var workers: [n_threads]Worker = undefined;
    var threads: [n_threads]std.Thread = undefined;
    for (0..n_threads) |t| {
        workers[t] = .{ .engine = &engine, .vecs = vecs.items, .start = t * vecs.items.len / n_threads, .differ = &differ, .done = &done };
        threads[t] = try std.Thread.spawn(.{}, Worker.run, .{&workers[t]});
    }
    for (threads) |th| th.join();
    try std.testing.expectEqual(@as(usize, 0), differ.load(.monotonic));
    try std.testing.expectEqual(n_threads * 3 * vecs.items.len, done.load(.monotonic));
}
