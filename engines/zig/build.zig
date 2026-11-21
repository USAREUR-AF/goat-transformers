const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    // Spec Version 0.24: the wires of the build. `-Dwires=xml,json,geojson`
    // builds the codecs of those wires only; the codec of every other wire is
    // left out of the build. No `-Dwires`: all seven.
    const wire_names = [_][]const u8{ "xml", "geojson", "json", "bits", "protobuf", "text", "tlv" };
    var have = [_]bool{false} ** wire_names.len;
    if (b.option([]const u8, "wires", "The wires to build, comma-separated: xml,geojson,json,bits,protobuf,text,tlv (default all seven)")) |list| {
        var parts = std.mem.splitScalar(u8, list, ',');
        while (parts.next()) |part| {
            const name = std.mem.trim(u8, part, " ");
            if (name.len == 0) continue;
            for (wire_names, 0..) |w, i| {
                if (std.mem.eql(u8, w, name)) {
                    have[i] = true;
                    break;
                }
            } else {
                std.log.err("-Dwires: {s} is not a wire (xml, geojson, json, bits, protobuf, text, tlv)", .{name});
                std.process.exit(1);
            }
        }
    } else have = [_]bool{true} ** wire_names.len;
    const wire_opts = b.addOptions();
    for (wire_names, have) |w, on| wire_opts.addOption(bool, b.fmt("wire_{s}", .{w}), on);

    // The engine as a module for another program:
    //   const gt = b.dependency("goat_transformers", .{ .target = target, .optimize = optimize });
    //   exe.root_module.addImport("goat_transformers", gt.module("goat_transformers"));
    const module = b.addModule("goat_transformers", .{
        .root_source_file = b.path("src/root.zig"),
        .target = target,
        .optimize = optimize,
    });
    module.addOptions("build_options", wire_opts);

    const exe = b.addExecutable(.{
        .name = "gt-engine-zig",
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    exe.root_module.addOptions("build_options", wire_opts);
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
    safe_exe.root_module.addOptions("build_options", wire_opts);
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

    // `zig build cli`: the command-line tool of spec Version 0.23,
    // zig-out/bin/goat-xf. Not part of the default install step, so the
    // harness builds as before.
    const cli_exe = b.addExecutable(.{
        .name = "goat-xf",
        .root_source_file = b.path("src/cli.zig"),
        .target = target,
        .optimize = optimize,
    });
    cli_exe.root_module.addOptions("build_options", wire_opts);
    const cli_step = b.step("cli", "Build the command-line tool zig-out/bin/goat-xf (spec Version 0.23)");
    cli_step.dependOn(&b.addInstallArtifact(cli_exe, .{}).step);

    // `zig build module-test`:the module another program imports loads packs and converts.
    const module_tests = b.addTest(.{
        .root_source_file = b.path("src/root.zig"),
        .target = target,
        .optimize = optimize,
    });
    module_tests.root_module.addOptions("build_options", wire_opts);
    const module_step = b.step("module-test", "Run the check of the module another program imports");
    module_step.dependOn(&b.addRunArtifact(module_tests).step);
}
