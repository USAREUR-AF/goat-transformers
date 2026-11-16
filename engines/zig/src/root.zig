//! goat-transformers, the Zig engine, as a module for another program.
//!
//!     const gt = @import("goat_transformers");
//!     var engine = gt.Engine.init(allocator);
//!     try gt.loadTree(&engine, "vendor/goat", &.{ "cot-xml", "geojson" });
//!     const out = try engine.convert("cot-xml", "geojson", input, null);
//!
//! The engine keeps what it loads for its whole life and frees nothing on its
//! own: give it an arena. A failure is a Zig error named as the specification
//! names it, and `engine.last_error` holds `<kind>: <detail>`.

const std = @import("std");
const engine_zig = @import("main.zig");

pub const Engine = engine_zig.Engine;
pub const Entity = engine_zig.Entity;
pub const Value = engine_zig.MV;
/// One caller-supplied key of a conversion: the `context` of `Engine.convert`.
pub const KV = engine_zig.KV;
pub const Distribution = engine_zig.Dist;

const max_file = 256 * 1024 * 1024;

const Head = struct { name: []const u8, text: []const u8, uses: []const []const u8 };

/// The `module` name and the `uses` names of a module or pack text.
fn scanHead(alloc: std.mem.Allocator, text: []const u8) !Head {
    var name: []const u8 = "";
    var uses = std.ArrayList([]const u8).init(alloc);
    var lines = std.mem.splitScalar(u8, text, '\n');
    while (lines.next()) |line| {
        var toks = std.mem.tokenizeAny(u8, line, " \t\r");
        const kw = toks.next() orelse continue;
        const is_module = std.mem.eql(u8, kw, "module");
        if (!is_module and !std.mem.eql(u8, kw, "uses")) continue;
        const arg = toks.next() orelse continue;
        if (arg[0] == '#') continue;
        if (toks.next()) |more| if (more[0] != '#') continue;
        if (is_module) {
            if (name.len == 0) name = arg;
        } else try uses.append(arg);
    }
    return .{ .name = name, .text = text, .uses = uses.items };
}

fn place(engine: *Engine, name: []const u8, heads: []const Head, placing: *std.ArrayList([]const u8)) anyerror!void {
    if (engine.modules.contains(name)) return;
    // a module no file declares is left to the pack's load: unknown-module
    const head = for (heads) |h| {
        if (std.mem.eql(u8, h.name, name)) break h;
    } else return;
    for (placing.items) |p| if (std.mem.eql(u8, p, name)) {
        engine.last_error = try std.fmt.allocPrint(engine.alloc, "bad-directive: model module {s}: its `uses` lines form a cycle", .{name});
        return error.@"bad-directive";
    };
    try placing.append(name);
    for (head.uses) |u| if (!std.mem.eql(u8, u, name)) try place(engine, u, heads, placing);
    _ = placing.pop();
    _ = try engine.loadModel(head.text);
}

/// Load the named packs from `<root>/packs/<name>/pack.def`, and before them
/// the model modules they need from `<root>/model/*.def`: `core`, every module
/// a named pack `uses`, and every module one of those `uses`, each after the
/// modules it uses. Nothing else in the tree is loaded. A module the engine
/// already holds is not loaded again, so the call can be repeated with more
/// packs. The engine's distribution limit applies.
///
/// A tree is a directory holding `model/` and `packs/`: a checkout of the
/// library, or a bundle written by `tools/goat-pkg bundle`.
pub fn loadTree(engine: *Engine, root: []const u8, packs: []const []const u8) !void {
    const alloc = engine.alloc;
    var texts = std.ArrayList([]const u8).init(alloc);
    for (packs, 0..) |name, i| {
        const again = for (packs[0..i]) |p| {
            if (std.mem.eql(u8, p, name)) break true;
        } else false;
        if (again) continue;
        const path = try std.fmt.allocPrint(alloc, "{s}/packs/{s}/pack.def", .{ root, name });
        const text = std.fs.cwd().readFileAlloc(alloc, path, max_file) catch |err| switch (err) {
            error.FileNotFound, error.NotDir => {
                engine.last_error = try std.fmt.allocPrint(alloc, "unknown-format: no pack {s} under {s}/packs", .{ name, root });
                return error.@"unknown-format";
            },
            else => return err,
        };
        try texts.append(text);
    }

    var heads = std.ArrayList(Head).init(alloc);
    const model_dir = try std.fmt.allocPrint(alloc, "{s}/model", .{root});
    if (std.fs.cwd().openDir(model_dir, .{ .iterate = true })) |opened| {
        var dir = opened;
        defer dir.close();
        var names = std.ArrayList([]const u8).init(alloc);
        var it = dir.iterate();
        while (try it.next()) |entry| {
            if (entry.kind != .file or !std.mem.endsWith(u8, entry.name, ".def")) continue;
            try names.append(try alloc.dupe(u8, entry.name));
        }
        std.mem.sort([]const u8, names.items, {}, nameLess);
        for (names.items) |n| {
            const head = try scanHead(alloc, try dir.readFileAlloc(alloc, n, max_file));
            const dup = for (heads.items) |h| {
                if (std.mem.eql(u8, h.name, head.name)) break true;
            } else false;
            if (head.name.len != 0 and !dup) try heads.append(head);
        }
    } else |err| switch (err) {
        error.FileNotFound => {},
        else => return err,
    }

    var placing = std.ArrayList([]const u8).init(alloc);
    try place(engine, "core", heads.items, &placing);
    for (texts.items) |text| {
        const head = try scanHead(alloc, text);
        for (head.uses) |u| try place(engine, u, heads.items, &placing);
    }
    for (texts.items) |text| _ = try engine.loadPack(text);
}

fn nameLess(_: void, a: []const u8, b: []const u8) bool {
    return std.mem.lessThan(u8, a, b);
}

const cot_event =
    \\<event version="2.0" uid="J-01334" type="a-f-G-U-C" time="2021-02-27T20:00:00.000Z" how="m-g"><point lat="30.0090027" lon="-85.9578182" hae="-42.6" ce="45.3" le="99.5"/><detail><contact callsign="GATOR"/></detail></event>
;
const geojson_feature =
    \\{"type":"Feature","geometry":{"type":"Point","coordinates":[-85.9578182,30.0090027,-42.6]},"properties":{"type":"a-f-G-U-C","time_ms":1614456000000,"how":"m-g","ce":45.3,"le":99.5,"callsign":"GATOR"},"id":"J-01334"}
;

// `zig build tree-test` runs these from engines/zig, so the tree is ../..
test "loadTree loads the named packs and the modules they use" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    var engine = Engine.init(arena.allocator());
    try loadTree(&engine, "../..", &.{ "cot-xml", "geojson" });
    try std.testing.expectEqual(@as(usize, 1), engine.modules.count());
    try std.testing.expectEqual(@as(usize, 2), engine.packs.items.len);
    try std.testing.expectEqualStrings(geojson_feature, try engine.convert("cot-xml", "geojson", cot_event, null));
}

test "loadTree follows uses through modules and can be repeated" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    var engine = Engine.init(arena.allocator());
    // asterix-cat062 uses cat062, and cat062 uses track
    try loadTree(&engine, "../..", &.{"asterix-cat062"});
    try std.testing.expectEqual(@as(usize, 3), engine.modules.count());
    try loadTree(&engine, "../..", &.{"canonical-track-v2"});
    try std.testing.expectEqual(@as(usize, 2), engine.packs.items.len);
    try std.testing.expectEqual(@as(usize, 3), engine.modules.count());
    try std.testing.expectError(error.@"unknown-format", loadTree(&engine, "../..", &.{"no-such-format"}));
}
