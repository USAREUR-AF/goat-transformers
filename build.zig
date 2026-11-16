//! The Zig package of this repository: the Zig engine (engines/zig) as the
//! module `goat_transformers`. It is here, at the repository root, because
//! `zig fetch` takes a package from the root of what it fetches.
//!
//!   zig fetch --save git+https://github.com/USAREUR-AF/goat-transformers#v0.8.0
//!
//! and in the build.zig of the program that uses it:
//!
//!   const gt = b.dependency("goat_transformers", .{ .target = target, .optimize = optimize });
//!   exe.root_module.addImport("goat_transformers", gt.module("goat_transformers"));
//!
//! The engine's own build and tests are in engines/zig.
const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    _ = b.addModule("goat_transformers", .{
        .root_source_file = b.path("engines/zig/src/root.zig"),
        .target = target,
        .optimize = optimize,
    });
}
