const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    // The engine as a module for another program:
    //   const gt = b.dependency("goat_transformers", .{ .target = target, .optimize = optimize });
    //   exe.root_module.addImport("goat_transformers", gt.module("goat_transformers"));
    _ = b.addModule("goat_transformers", .{
        .root_source_file = b.path("src/root.zig"),
        .target = target,
        .optimize = optimize,
    });

    const exe = b.addExecutable(.{
        .name = "gt-engine-zig",
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    b.installArtifact(exe);

    const run_cmd = b.addRunArtifact(exe);
    run_cmd.step.dependOn(b.getInstallStep());
    if (b.args) |args| run_cmd.addArgs(args);

    const run_step = b.step("run", "Run the conformance harness");
    run_step.dependOn(&run_cmd.step);

    // `zig build test` also runs the conformance harness (it IS the test).
    const test_step = b.step("test", "Run the conformance harness over all packs");
    test_step.dependOn(&run_cmd.step);

    // `zig build tree-test`: the checks of the module's tree loader.
    const tree_tests = b.addTest(.{
        .root_source_file = b.path("src/root.zig"),
        .target = target,
        .optimize = optimize,
    });
    const tree_step = b.step("tree-test", "Run the checks of the module's tree loader");
    tree_step.dependOn(&b.addRunArtifact(tree_tests).step);
}
