//! Tests of spec Version 0.93 (a controlled pack is in no licence profile)
//! in the library: rulings 5 and 6, and a controlled inner pack (Version
//! 0.34) under a profile. Each test writes its own tree to a temporary
//! directory.

const std = @import("std");
const gt = @import("main.zig");
const Engine = gt.Engine;

const src = "source \"goat-transformers spec/engine-spec.md, Version 0.93 (synthetic test tree)\"\n";

const core_def = "module core\nversion 0.93.0\ndistribution public\n" ++ src ++
    "key a int - \"outer key\"\nkey b int - \"inner key\"\n";
const ctl_def = "module ctl\nversion 0.93.0\ndistribution controlled\n" ++ src ++ "key c int - \"controlled key\"\n";
const pub_pack = "format t-pub\nversion 0.93.0\ndistribution public\n" ++ src ++ "wire json\nfield a pos.a int\n";
const ctl_pack = "format t-ctl\nversion 0.93.0\ndistribution controlled\n" ++ src ++ "wire json\nfield a pos.a int\n";
const ctl_module_text = "module m2\nversion 0.93.0\ndistribution controlled\n" ++ src;

const outer_pack = "format t-outer\nversion 0.93.0\ndistribution public\n" ++ src ++
    "wire bits\nlayout sequential\nbit_order msb\nfield a 8 uint\ninner t-inner\n";
// (a) an inner pack that is not shown public
const inner_controlled = "format t-inner\nversion 0.93.0\ndistribution controlled\n" ++ src ++
    "wire bits\nlayout sequential\nbit_order msb\nfield b 8 uint\n";
const inner_public = "format t-inner\nversion 0.93.0\ndistribution public\n" ++ src ++
    "wire bits\nlayout sequential\nbit_order msb\nfield b 8 uint\n";
// (b) an inner pack shown public that uses a controlled module
const inner_uses_ctl = "format t-inner\nversion 0.93.0\ndistribution public\n" ++ src ++
    "uses ctl\nwire bits\nlayout sequential\nbit_order msb\nfield ctl.c 8 uint\n";

const File = struct { path: []const u8, data: []const u8 };

// Write `files` under a new temporary directory; returns its `packs` path.
fn tree(a: std.mem.Allocator, tmp: *std.testing.TmpDir, files: []const File) ![]const u8 {
    for (files) |f| {
        if (std.fs.path.dirname(f.path)) |d| try tmp.dir.makePath(d);
        try tmp.dir.writeFile(.{ .sub_path = f.path, .data = f.data });
    }
    try tmp.dir.makePath("packs");
    const root = try tmp.dir.realpathAlloc(a, ".");
    return std.fmt.allocPrint(a, "{s}/packs", .{root});
}

const profiles = [_][]const u8{ "open", "open+copyleft", "everything" };

fn startsWith(s: []const u8, p: []const u8) bool {
    return std.mem.startsWith(u8, s, p);
}

test "0.93 ruling 6: a bad profile name, then the instance check; both leave the limit unchanged and no trace" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    const packs = try tree(a, &tmp, &.{
        .{ .path = "model/core.def", .data = core_def },
        .{ .path = "packs/pub/pack.def", .data = pub_pack },
    });

    // A profile name that is none of the three: bad-licence, the limit
    // unchanged (still `controlled`, so a controlled text loads after it).
    var e1 = Engine.init(a);
    try std.testing.expectError(error.@"bad-licence", e1.loadTree(.{ .packs_dir = packs, .profile = "Open" }));
    try std.testing.expect(startsWith(e1.last_error, "bad-licence: "));
    try std.testing.expectEqual(gt.Dist.controlled, e1.max_distribution);
    try std.testing.expectEqual(@as(u32, 0), e1.modules.count());
    _ = try e1.loadModel(core_def);
    _ = try e1.loadPack(ctl_pack);

    // The name is checked before the instance: an engine holding a
    // controlled pack and given a bad name is bad-licence.
    try std.testing.expectError(error.@"bad-licence", e1.loadTree(.{ .packs_dir = packs, .profile = "all" }));

    // The instance check: a controlled pack held, distribution-refused
    // before anything is read (a packs directory that does not exist is not
    // looked at), the limit unchanged and nothing loaded.
    try std.testing.expectError(error.@"distribution-refused", e1.loadTree(.{ .packs_dir = "no/such/dir/packs", .profile = "open" }));
    try std.testing.expect(startsWith(e1.last_error, "distribution-refused: "));
    try std.testing.expectError(error.@"distribution-refused", e1.loadTree(.{ .packs_dir = packs, .profile = "everything" }));
    try std.testing.expectEqual(gt.Dist.controlled, e1.max_distribution);
    try std.testing.expect(e1.findPack("t-pub") == null);
    try std.testing.expectEqual(@as(usize, 1), e1.packs.items.len);
    // no trace: a controlled text still loads, the limit still `controlled`
    e1.setMaxDistribution(.controlled);
    _ = try e1.loadModel(ctl_module_text);

    // A controlled module held (no controlled pack) is refused the same way.
    var e2 = Engine.init(a);
    _ = try e2.loadModel(core_def);
    _ = try e2.loadModel(ctl_module_text);
    try std.testing.expectError(error.@"distribution-refused", e2.loadTree(.{ .packs_dir = packs, .profile = "open" }));
    try std.testing.expectEqual(gt.Dist.controlled, e2.max_distribution);
    try std.testing.expectEqual(@as(usize, 0), e2.packs.items.len);
}

test "0.93 ruling 6: after a load with a profile the limit is public, also when the load fails later" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    const packs = try tree(a, &tmp, &.{
        .{ .path = "model/core.def", .data = core_def },
        .{ .path = "packs/pub/pack.def", .data = pub_pack },
    });
    var tmp2 = std.testing.tmpDir(.{});
    defer tmp2.cleanup();
    // no model directory: the modules are those e1 already holds
    const ctl_packs = try tree(a, &tmp2, &.{
        .{ .path = "packs/ctl/pack.def", .data = ctl_pack },
    });
    var tmp3 = std.testing.tmpDir(.{});
    defer tmp3.cleanup();
    const bad_packs = try tree(a, &tmp3, &.{
        .{ .path = "model/core.def", .data = core_def },
        .{ .path = "licences.toml", .data = "not a table\n" },
    });

    // The limit becomes `public` with the load; a controlled text loaded
    // directly later is refused; setting `controlled` afterwards is no error
    // and has no effect.
    var e1 = Engine.init(a);
    e1.setMaxDistribution(.controlled); // set before: the lower is public
    const l1 = try e1.loadTree(.{ .packs_dir = packs, .profile = "open" });
    try std.testing.expectEqual(@as(usize, 1), l1.packs.len);
    try std.testing.expectEqual(gt.Dist.public, e1.max_distribution);
    try std.testing.expectError(error.@"distribution-refused", e1.loadPack(ctl_pack));
    try std.testing.expectError(error.@"distribution-refused", e1.loadModel(ctl_module_text));
    e1.setMaxDistribution(.controlled);
    try std.testing.expectEqual(gt.Dist.public, e1.max_distribution);
    try std.testing.expectError(error.@"distribution-refused", e1.loadPack(ctl_pack));
    // a later load with no profile is bounded by the limit, not the profile
    try std.testing.expectError(error.@"distribution-refused", e1.loadTree(.{ .packs_dir = ctl_packs, .packs_only = &.{"ctl"} }));

    // The limit stays `public` when the load with a profile fails later.
    var e2 = Engine.init(a);
    try std.testing.expectError(error.@"bad-licence", e2.loadTree(.{ .packs_dir = bad_packs, .profile = "everything" }));
    try std.testing.expectEqual(gt.Dist.public, e2.max_distribution);
    e2.setMaxDistribution(.controlled);
    try std.testing.expectError(error.@"distribution-refused", e2.loadModel(ctl_module_text));
}

// The hook of ruling 5: the file changed after it was read for its profile.
fn toControlled(alloc: std.mem.Allocator, _: []const u8, text: []const u8) []const u8 {
    return std.mem.replaceOwned(u8, alloc, text, "distribution public", "distribution controlled") catch text;
}

test "0.93 ruling 5: a file that reads as controlled when it is loaded is distribution-refused" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    const packs = try tree(a, &tmp, &.{
        .{ .path = "model/core.def", .data = core_def },
        .{ .path = "packs/pub/pack.def", .data = pub_pack },
    });
    for (profiles) |pr| {
        // without the hook it loads
        var e0 = Engine.init(a);
        _ = try e0.loadTree(.{ .packs_dir = packs, .profile = pr });
        try std.testing.expect(e0.findPack("t-pub") != null);
        // with it, `core` is the first file loaded, and fails the load
        var e1 = Engine.init(a);
        e1.test_load_hook = toControlled;
        try std.testing.expectError(error.@"distribution-refused", e1.loadTree(.{ .packs_dir = packs, .profile = pr }));
        try std.testing.expect(startsWith(e1.last_error, "distribution-refused: module core"));
        try std.testing.expectEqual(@as(u32, 0), e1.modules.count());
    }
    // a pack.def changed after its check (no model directory change)
    var tmp2 = std.testing.tmpDir(.{});
    defer tmp2.cleanup();
    const packs2 = try tree(a, &tmp2, &.{
        .{ .path = "model/core.def", .data = core_def },
        .{ .path = "packs/pub/pack.def", .data = pub_pack },
    });
    var e2 = Engine.init(a);
    e2.test_load_hook = struct {
        fn f(alloc: std.mem.Allocator, name: []const u8, text: []const u8) []const u8 {
            return if (std.mem.eql(u8, name, "pub")) toControlled(alloc, name, text) else text;
        }
    }.f;
    try std.testing.expectError(error.@"distribution-refused", e2.loadTree(.{ .packs_dir = packs2, .profile = "open" }));
    try std.testing.expect(startsWith(e2.last_error, "distribution-refused: pack t-pub"));
    try std.testing.expect(e2.findPack("t-pub") == null);
    // the hook is not used without a profile: nothing is checked there
    var e3 = Engine.init(a);
    e3.test_load_hook = toControlled;
    _ = try e3.loadTree(.{ .packs_dir = packs2 });
    try std.testing.expectEqual(gt.Dist.public, e3.findPack("t-pub").?.distribution.?);
}

// Only the outer pack loads; decode and encode through the inner line give
// unknown-format; model_keys of the outer does not fail and lists only its
// own key.
fn expectOuterOnly(a: std.mem.Allocator, packs: []const u8, pr: []const u8) !void {
    var e = Engine.init(a);
    const l = try e.loadTree(.{ .packs_dir = packs, .profile = pr });
    try std.testing.expectEqual(@as(usize, 1), l.packs.len);
    try std.testing.expectEqualStrings("t-outer", l.packs[0].format);
    try std.testing.expect(e.findPack("t-inner") == null);
    try std.testing.expectError(error.@"unknown-format", e.decode("t-outer", "0102"));
    var ent = gt.Entity.init(a);
    try ent.put("a", .{ .int = 1 });
    try ent.put("b", .{ .int = 2 });
    try std.testing.expectError(error.@"unknown-format", e.encode("t-outer", &ent));
    const keys = try e.modelKeysOf("t-outer");
    try std.testing.expectEqual(@as(usize, 1), keys.len);
    try std.testing.expectEqualStrings("a", keys[0]);
}

test "0.93 and 0.34: a controlled inner pack never loads under a profile" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();

    // (a) the inner pack is not shown public
    var ta = std.testing.tmpDir(.{});
    defer ta.cleanup();
    const pa = try tree(a, &ta, &.{
        .{ .path = "model/core.def", .data = core_def },
        .{ .path = "packs/outer/pack.def", .data = outer_pack },
        .{ .path = "packs/inner/pack.def", .data = inner_controlled },
    });
    // (b) the inner pack is shown public and uses a controlled module
    var tb = std.testing.tmpDir(.{});
    defer tb.cleanup();
    const pb = try tree(a, &tb, &.{
        .{ .path = "model/core.def", .data = core_def },
        .{ .path = "model/ctl.def", .data = ctl_def },
        .{ .path = "packs/outer/pack.def", .data = outer_pack },
        .{ .path = "packs/inner/pack.def", .data = inner_uses_ctl },
    });
    for (profiles) |pr| {
        try expectOuterOnly(a, pa, pr);
        try expectOuterOnly(a, pb, pr);
    }

    // the same outer pack with an inner pack that is shown public and uses
    // no controlled module: both load under every profile, and the layered
    // decode works (the fixture is a working pair)
    var tc = std.testing.tmpDir(.{});
    defer tc.cleanup();
    const pc = try tree(a, &tc, &.{
        .{ .path = "model/core.def", .data = core_def },
        .{ .path = "packs/outer/pack.def", .data = outer_pack },
        .{ .path = "packs/inner/pack.def", .data = inner_public },
    });
    for (profiles) |pr| {
        var e0 = Engine.init(a);
        const l0 = try e0.loadTree(.{ .packs_dir = pc, .profile = pr });
        try std.testing.expectEqual(@as(usize, 2), l0.packs.len);
        const ent = try e0.decode("t-outer", "0102");
        try std.testing.expectEqual(@as(i64, 2), ent.fields.get("b").?.int);
    }

    // (c) no profile, the limit public, the inner pack in the load
    var e1 = Engine.init(a);
    e1.setMaxDistribution(.public);
    try std.testing.expectError(error.@"distribution-refused", e1.loadTree(.{ .packs_dir = pa }));
    try std.testing.expect(startsWith(e1.last_error, "distribution-refused: pack t-inner"));
}
