//! goat-transformers, the Zig engine, as a module for another program.
//!
//!     const gt = @import("goat_transformers");
//!     var engine = gt.Engine.init(allocator);
//!     _ = try engine.loadPacksOnly("vendor/goat/packs", "vendor/goat/model", &.{ "cot-xml", "geojson" });
//!     const out = try engine.convert("cot-xml", "geojson", input, null);
//!
//! `loadPacksOnly` loads the named packs and the model modules they need.
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
