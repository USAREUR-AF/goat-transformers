const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

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

    // The malformed-input run: every vector input cut short and with single
    // bytes replaced. Always built with safety checks on, whatever
    // `-Doptimize` says, so that a read outside the input is a panic and
    // fails the step.
    const safe_exe = b.addExecutable(.{
        .name = "gt-engine-zig-safe",
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = .ReleaseSafe,
    });
    const fuzz_cmd = b.addRunArtifact(safe_exe);
    fuzz_cmd.addArg("--fuzz");
    if (b.args) |args| fuzz_cmd.addArgs(args);
    const fuzz_step = b.step("fuzz", "Run every vector input, cut short and mutated, through a safe build");
    fuzz_step.dependOn(&fuzz_cmd.step);

    // `zig build test` runs the conformance harness (it IS the test), then
    // the malformed-input run.
    const test_step = b.step("test", "Run the conformance harness over all packs, then the malformed-input run");
    test_step.dependOn(&run_cmd.step);
    fuzz_cmd.step.dependOn(&run_cmd.step);
    test_step.dependOn(&fuzz_cmd.step);
}
