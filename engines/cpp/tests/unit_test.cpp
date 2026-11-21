// Unit checks for the parts the vectors exercise only partly: number formatting,
// civil-date arithmetic, pack grammar errors, residue and parsing tolerance.
#include <chrono>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <utility>
#include <vector>

#include "codecs.hpp"
#include "goat_transformers/engine.hpp"
#include "util.hpp"

namespace gt = goat_transformers;
namespace detail = goat_transformers::detail;

namespace {

int failures = 0;
int checks = 0;

void check(bool ok, const std::string& what) {
    ++checks;
    if (!ok) {
        ++failures;
        std::cout << "FAIL " << what << "\n";
    }
}

void eq(const std::string& got, const std::string& want, const std::string& what) {
    check(got == want, what + ": got \"" + got + "\", want \"" + want + "\"");
}

template <typename F>
void expect_error(gt::ErrorKind kind, F&& f, const std::string& what) {
    try {
        f();
        check(false, what + ": no error raised");
    } catch (const gt::Error& e) {
        check(e.kind() == kind, what + ": got " + e.what());
    }
}

// Every pack states its distribution and a source (engine-spec.md v0.4).
#define HDR "version 0.1.0\ndistribution public\nsource \"unit test\"\n"

// The keys the packs below map, declared so the packs pass the v0.4 load checks.
const char* kCoreModel =
    "module core\nversion 0.1.0\ndistribution public\nsource \"unit test\"\n"
    "key uid string -\nkey time_ms int ms\nkey lat float deg\nkey lon float deg\n"
    "key callsign string -\nkey remarks string -\nkey a int -\nkey b int -\nkey v float deg \"scaled\"\n";

const char* kXmlPack =
    HDR "format t-xml\nwire xml\nroot event\n"
    "field uid @uid string\nfield time_ms @time iso8601_ms\nfield lat point/@lat float\n"
    "field callsign detail/contact/@callsign string\nfield remarks detail/remarks/#text string\n";

const char* kGeoPack =
    HDR "format t-geo\nwire geojson\n"
    "field uid id string\nfield time_ms properties.time_ms int\nfield lat geometry.lat float\n"
    "field lon geometry.lon float\n";

}  // namespace

int main() {
    // numbers
    eq(detail::format_double(30.0), "30", "30.0");
    eq(detail::format_double(-42.6), "-42.6", "-42.6");
    eq(detail::format_double(1e21), "1000000000000000000000", "1e21");
    eq(detail::format_double(1e-7), "0.0000001", "1e-7");
    eq(detail::format_double(1.5e-10), "0.00000000015", "1.5e-10");
    eq(detail::format_double(0.1), "0.1", "0.1");
    eq(detail::format_double(123456789012345680000.0), "123456789012345680000", "1.2345678901234568e20");

    // time
    std::int64_t ms = -1;
    check(detail::parse_iso8601_ms("1970-01-01T00:00:00Z", ms) && ms == 0, "epoch zero");
    check(detail::parse_iso8601_ms("2021-02-27T20:00:00.000Z", ms) && ms == 1614456000000, "vector time");
    check(detail::parse_iso8601_ms("2000-02-29T12:34:56.789Z", ms) && ms == 951827696789, "leap day");
    check(detail::parse_iso8601_ms("2021-02-27T20:00:00.5Z", ms) && ms == 1614456000500, "one fraction digit");
    check(!detail::parse_iso8601_ms("2021-02-29T00:00:00Z", ms), "non-leap Feb 29 rejected");
    check(!detail::parse_iso8601_ms("2021-02-27T20:00:00", ms), "missing zone rejected");
    // 0.6: an offset is accepted and converted to UTC; `T` and `Z` may be lowercase.
    check(detail::parse_iso8601_ms("2021-02-27T20:00:00+00:00", ms) && ms == 1614456000000, "offset +00:00");
    check(detail::parse_iso8601_ms("2021-02-27T21:30:00.250+01:30", ms) && ms == 1614456000250, "offset east of UTC");
    check(detail::parse_iso8601_ms("2021-02-27T14:30:00-05:30", ms) && ms == 1614456000000, "offset west of UTC");
    check(detail::parse_iso8601_ms("2021-02-27t20:00:00z", ms) && ms == 1614456000000, "lowercase t and z");
    check(!detail::parse_iso8601_ms("2021-02-27T20:00:00+0000", ms), "offset without a colon rejected");
    check(!detail::parse_iso8601_ms("2021-02-27T20:00:00+24:00", ms), "offset hour out of range rejected");
    eq(detail::format_iso8601_ms(0), "1970-01-01T00:00:00.000Z", "format zero");
    eq(detail::format_iso8601_ms(-1), "1969-12-31T23:59:59.999Z", "format -1");
    eq(detail::format_iso8601_ms(951827696789), "2000-02-29T12:34:56.789Z", "format leap day");
    eq(detail::format_iso8601_ms(253402300799999), "9999-12-31T23:59:59.999Z", "format max");
    for (std::int64_t z = -800000; z <= 800000; z += 997) {
        std::int64_t y;
        unsigned m, d;
        detail::civil_from_days(z, y, m, d);
        check(detail::days_from_civil(y, m, d) == z, "civil round trip day " + std::to_string(z));
    }

    // 0.11 rulings 2 and 3: the number and time grammars.
    {
        std::int64_t i = 0;
        double d = 0;
        std::uint64_t u = 0;
        check(detail::parse_int_text("-007", i) && i == -7, "2a: leading zeros");
        check(detail::parse_int_text("-9223372036854775808", i) && i == INT64_MIN, "2a: the smallest integer");
        check(!detail::parse_int_text("9223372036854775808", i), "2a: above the largest integer");
        check(!detail::parse_int_text("+1", i) && !detail::parse_int_text(" 1", i) && !detail::parse_int_text("1.0", i),
              "2a: sign, space, fraction");
        check(detail::parse_number_text("-1e-400", d) && d == 0.0 && std::signbit(d), "2b: negative zero");
        check(detail::parse_number_text("1e-400", d) && d == 0.0 && !std::signbit(d), "2b: below the smallest subnormal");
        check(!detail::parse_number_text("1.7976931348623159e308", d), "2b: nearest double infinite");
        check(!detail::parse_number_text(".5", d) && !detail::parse_number_text("5.", d) &&
                  !detail::parse_number_text("Infinity", d) && !detail::parse_number_text("0x10", d),
              "2b: forms refused");
        check(detail::parse_unsigned_text("007", u) && u == 7 && !detail::parse_unsigned_text("+7", u), "2c: unsigned");
        check(detail::json_exact_int("9.223372036854775807e18", i) && i == INT64_MAX, "2d: exact with an exponent");
        check(detail::json_exact_int("9007199254740993.0", i) && i == 9007199254740993, "2d: above 2^53 with a zero fraction");
        check(!detail::json_exact_int("1.5", i) && !detail::json_exact_int("1e19", i), "2d: fraction and overflow");
        check(detail::parse_iso8601_ms("1969-12-31T23:59:59.9999Z", i) && i == -1, "3c: digits dropped, not rounded");
        check(!detail::parse_iso8601_ms("0000-01-01T00:00:00Z", i), "3b: year 0000");
        check(!detail::parse_iso8601_ms("0001-01-01T00:00:00+00:01", i), "3d: an offset before year 0001");
        check(!detail::parse_iso8601_ms(" 2020-01-01T00:00:00Z", i), "3a: a leading space");
        eq(detail::format_iso8601_ms(detail::kMinIsoMs), "0001-01-01T00:00:00.000Z", "3f: the first instant");
    }

    // 0.26: iso8601_s writes the second that holds the instant, no fraction.
    {
        eq(detail::format_iso8601_s(0), "1970-01-01T00:00:00Z", "0.26: zero");
        eq(detail::format_iso8601_s(999), "1970-01-01T00:00:00Z", "0.26: 999 dropped, not rounded");
        eq(detail::format_iso8601_s(-1), "1969-12-31T23:59:59Z", "0.26: -1");
        eq(detail::format_iso8601_s(1709210096789), "2024-02-29T12:34:56Z", "0.26: a fraction dropped");
        eq(detail::format_iso8601_s(detail::kMinIsoMs), "0001-01-01T00:00:00Z", "0.26: the first instant");
        eq(detail::format_iso8601_s(detail::kMaxIsoMs), "9999-12-31T23:59:59Z", "0.26: the last instant");
        bool threw = false;
        try { (void)detail::format_iso8601_s(detail::kMinIsoMs - 1); } catch (const std::domain_error&) { threw = true; }
        check(threw, "0.26: below the range refused");
        threw = false;
        try { (void)detail::format_iso8601_s(detail::kMaxIsoMs + 1); } catch (const std::domain_error&) { threw = true; }
        check(threw, "0.26: above the range refused");
        // ruling 1: the wires of iso8601_ms, no parameter.
        for (const char* w : {"wire xml\nroot r\nfield k @k iso8601_s\n", "wire json\nfield k k iso8601_s\n",
                              "wire geojson\nfield k k iso8601_s\n", "wire text\nfield k 0 iso8601_s\n"})
            check(gt::parse_pack(std::string(HDR "format a\n") + w).fields.size() == 1,
                  std::string("0.26: iso8601_s loads on ") + w);
        expect_error(gt::ErrorKind::BadDirective,
                     [] { gt::parse_pack(HDR "format a\nwire bits\nword_bytes 1\nfield k 0:0:8 iso8601_s\n"); },
                     "0.26: iso8601_s on bits");
        expect_error(gt::ErrorKind::BadDirective,
                     [] { gt::parse_pack(HDR "format a\nwire protobuf\nfield k 1 iso8601_s\n"); },
                     "0.26: iso8601_s on protobuf");
        expect_error(gt::ErrorKind::BadDirective,
                     [] { gt::parse_pack(HDR "format a\nwire tlv\nfield k 4:1 iso8601_s\n"); },
                     "0.26: iso8601_s on tlv");
        expect_error(gt::ErrorKind::BadDirective,
                     [] { gt::parse_pack(HDR "format a\nwire xml\nroot r\nfield k @k iso8601_s:3\n"); },
                     "0.26: iso8601_s with a parameter");
    }

    // pack grammar
    expect_error(gt::ErrorKind::UnknownDirective, [] { gt::parse_pack(HDR "format a\nwire xml\nroot r\nbogus x\n"); },
                 "unknown directive");
    expect_error(gt::ErrorKind::UnknownTransform,
                 [] { gt::parse_pack(HDR "format a\nwire xml\nroot r\nfield k @k nosuch\n"); }, "unknown transform");
    // v0.27: the CRC-32 of ISO/IEC 13818-1, with the two check values of "The CRC".
    check(detail::crc32_mpeg2("123456789", 9) == 0x0376E6E7u, "crc32 of 123456789 is 0x0376E6E7");
    check(detail::crc32_mpeg2("", 0) == 0xFFFFFFFFu, "crc32 of no bytes is 0xFFFFFFFF");
    check(detail::crc32_mpeg2("123456789xyz", 9) == 0x0376E6E7u, "crc32 covers only the first end bytes");

    // v0.13: `hex` and `utf8` are transforms of the tlv wire, bad-directive on another.
    expect_error(gt::ErrorKind::BadDirective,
                 [] { gt::parse_pack(HDR "format a\nwire xml\nroot r\nfield k @k hex\n"); }, "hex on xml");
    expect_error(gt::ErrorKind::BadDirective,
                 [] { gt::parse_pack(HDR "format a\nwire tlv\nfield k 4:1 nosuch\n"); }, "unknown transform on tlv");
    // 0.11 ruling 5b: a `field` before the `wire` line is missing-wire, before its transform is read.
    expect_error(gt::ErrorKind::MissingWire,
                 [] { gt::parse_pack(HDR "field k 4:1 nosuch\nformat a\nwire tlv\n"); }, "unknown transform before wire tlv");
    expect_error(gt::ErrorKind::MissingWire,
                 [] { gt::parse_pack(HDR "field k @k nosuch\nformat a\nwire xml\nroot r\n"); },
                 "unknown transform before wire xml");
    expect_error(gt::ErrorKind::UnknownWire, [] { gt::parse_pack(HDR "format a\nwire yaml\n"); }, "unknown wire");
    expect_error(gt::ErrorKind::MissingRoot, [] { gt::parse_pack(HDR "format a\nwire xml\n"); }, "xml without root");
    expect_error(gt::ErrorKind::BadLocator,
                 [] { gt::parse_pack(HDR "format a\nwire geojson\nfield k geometry.x float\n"); }, "bad geo locator");
    {
        gt::Pack p = gt::parse_pack(HDR "format a # c\nwire xml\nroot r\nfield k \"x y/@z\" string\n");
        check(p.fields.size() == 1 && p.fields[0].locator == "x y/@z", "quoted locator");
    }

    // engine behaviour
    gt::Engine eng;
    eng.load_model(kCoreModel, "core");
    eng.add_pack(gt::parse_pack(kXmlPack, "t-xml"));
    eng.add_pack(gt::parse_pack(kGeoPack, "t-geo"));

    const std::string canon =
        "<event uid=\"U1\" time=\"2021-02-27T20:00:00.000Z\" version=\"2.0\"><point lat=\"1.5\"/>"
        "<detail><contact callsign=\"A&amp;B\"/><remarks>hi &lt;there&gt;</remarks></detail></event>";
    const std::string messy =
        "<?xml version='1.0' encoding='UTF-8'?>\n<!-- c -->\n<event  uid='U1' time=\"2021-02-27T20:00:00Z\""
        " version=\"2.0\">\n  <point lat=\"1.50\" hae=\"0\" />\n  <detail><contact callsign=\"A&amp;B\"></contact>"
        "<remarks><![CDATA[hi <there>]]></remarks><track></track></detail>\n</event>\n";
    try {
        eq(eng.convert("t-xml", "t-xml", canon), canon, "xml round trip with root-attribute residue");
        eq(eng.convert("t-xml", "t-xml", messy), canon, "xml tolerance to canonical; unmapped child content is dropped (0.1.1 ruling 6)");
        eq(eng.convert("t-xml", "t-geo", canon),
           "{\"type\":\"Feature\",\"geometry\":null,\"properties\":{\"time_ms\":1614456000000},\"id\":\"U1\"}",
           "xml to geojson drops xml residue, null geometry without lon");
        const std::string g =
            "{ \"type\": \"Feature\", \"id\": \"G\", \"bbox\": [1,2], \"geometry\": {\"type\":\"Point\","
            "\"coordinates\": [10.0, 20.25]}, \"properties\": {\"x\": \"\\u00e9\", \"time_ms\": 5, \"n\": 1e2} }";
        eq(eng.convert("t-geo", "t-geo", g),
           "{\"type\":\"Feature\",\"geometry\":{\"type\":\"Point\",\"coordinates\":[10,20.25]},"
           "\"properties\":{\"time_ms\":5,\"x\":\"\xC3\xA9\",\"n\":\"1e2\"},\"id\":\"G\",\"bbox\":[1,2]}",
           "geojson round trip with residue: a scalar's text written as a string, an array as it was (0.6 ruling 13)");
        eq(eng.convert("t-geo", "t-geo", "{\"properties\":{\"d\":1,\"o\":{\"a\":1.50,\"b\":null},\"d\":\"z\",\"q\":null},\"id\":\"G\"}"),
           "{\"type\":\"Feature\",\"geometry\":null,\"properties\":{\"d\":\"z\",\"o\":{\"a\":1.50,\"b\":null}},\"id\":\"G\"}",
           "geojson residue: of two members with one name the last value at the first position; an object as it was");
    } catch (const std::exception& e) {
        check(false, std::string("engine behaviour threw: ") + e.what());
    }
    expect_error(gt::ErrorKind::MissingRoot, [&] { eng.decode("t-xml", "<other/>"); }, "wrong root");
    eq(gt::error_kind_name(gt::ErrorKind::MissingRoot), "missing-root", "the name of missing-root");
    expect_error(gt::ErrorKind::MalformedWire, [&] { eng.decode("t-xml", "<event><a></event>"); }, "bad xml");
    expect_error(gt::ErrorKind::MalformedWire, [&] { eng.decode("t-geo", "{\"type\":"); }, "bad json");
    expect_error(gt::ErrorKind::TransformDecode, [&] { eng.decode("t-xml", "<event time=\"yesterday\"/>"); },
                 "bad time");
    expect_error(gt::ErrorKind::UnknownFormat, [&] { eng.decode("nope", ""); }, "unknown format");

    // ---- bits wire (engine-spec.md v0.2) ----
    eng.add_pack(gt::parse_pack(HDR "format t-bits\nwire bits\nword_bytes 2\n"
                                "field a 0:0:8 uint\nfield b 0:8:4 twos\n", "t-bits"));
    eng.add_pack(gt::parse_pack(HDR "format t-lin\nwire bits\nword_bytes 4\n"
                                "field v 0:0:16 linscale:32767:180\n", "t-lin"));
    try {
        gt::Entity be;
        be.fields["a"] = gt::Value::of_int(200);
        be.fields["b"] = gt::Value::of_int(-3);
        eq(eng.encode("t-bits", be), "c80d", "bits encode uint+twos");

        gt::Entity bd = eng.decode("t-bits", "c80d");
        check(bd.fields["a"].kind == gt::Value::Kind::Int && bd.fields["a"].i == 200, "bits decode uint");
        check(bd.fields["b"].kind == gt::Value::Kind::Int && bd.fields["b"].i == -3, "bits decode twos negative");

        gt::Entity bw = eng.decode("t-bits", " c8 0d\n");  // whitespace ignored
        check(bw.fields["a"].i == 200 && bw.fields["b"].i == -3, "bits decode ignores whitespace");

        eq(eng.convert("t-bits", "t-bits", "c80d"), "c80d", "bits round-trip identity");
        eq(eng.convert("t-bits", "t-bits", "0000"), "0000", "bits all-zero round-trip");

        gt::Entity le = eng.decode("t-lin", "00400000");
        check(le.fields["v"].kind == gt::Value::Kind::Float && le.fields["v"].f > 89.0 &&
                  le.fields["v"].f < 91.0, "linscale decode in band");
        eq(eng.convert("t-lin", "t-lin", "00400000"), "00400000", "linscale round-trip at grid point");
    } catch (const std::exception& e) {
        check(false, std::string("bits behaviour threw: ") + e.what());
    }
    expect_error(gt::ErrorKind::MalformedWire, [&] { eng.decode("t-bits", "c80"); }, "bits odd hex");
    expect_error(gt::ErrorKind::MalformedWire, [&] { eng.decode("t-bits", "zz0d"); }, "bits bad hex digit");
    expect_error(gt::ErrorKind::MalformedWire, [&] { eng.decode("t-bits", "c8"); }, "bits short message");

    // bits/text transform-kind and locator validation at pack load
    expect_error(gt::ErrorKind::BadDirective,
                 [] { gt::parse_pack(HDR "format a\nwire bits\nword_bytes 2\nfield k 0:0:8 string\n"); },
                 "text transform on bits wire");
    expect_error(gt::ErrorKind::BadDirective, [] { gt::parse_pack(HDR "format a\nwire xml\nroot r\nfield k @k uint\n"); },
                 "bits transform on text wire");
    expect_error(gt::ErrorKind::BadDirective, [] { gt::parse_pack(HDR "format a\nwire bits\nfield k 0:0:8 uint\n"); },
                 "bits without word_bytes");
    expect_error(gt::ErrorKind::BadDirective,
                 [] { gt::parse_pack(HDR "format a\nwire xml\nroot r\nword_bytes 2\nfield k @k string\n"); },
                 "word_bytes on non-bits wire");
    {
        // 0.5: a field may run past the end of its word.
        gt::Pack rp = gt::parse_pack(HDR "format a\nwire bits\nword_bytes 1\nfield k 0:4:8 uint\n");
        check(rp.fields.size() == 1, "bits field may run past its word");
    }
    // 0.11 ruling 5a: a bit length of 0 is bad-locator.
    expect_error(gt::ErrorKind::BadLocator,
                 [] { gt::parse_pack(HDR "format a\nwire bits\nword_bytes 2\nfield k 0:0:0 uint\n"); },
                 "bits len zero");
    expect_error(gt::ErrorKind::BadDirective,
                 [] { gt::parse_pack(HDR "format a\nwire bits\nword_bytes 2\nfield k 0:0:65 uint\n"); },
                 "bits len 65 on uint");
    // 0.11 ruling 4d: a transform's parameters that are not valid are bad-directive.
    expect_error(gt::ErrorKind::BadDirective,
                 [] { gt::parse_pack(HDR "format a\nwire bits\nword_bytes 2\nfield k 0:0:8 linscale\n"); },
                 "linscale without arguments");
    {
        gt::Pack lp = gt::parse_pack(HDR "format a\nwire bits\nword_bytes 4\nfield v 0:0:16 linscale:32767:180\n");
        check(lp.fields.size() == 1 && lp.fields[0].transform == gt::Transform::Linscale &&
                  lp.fields[0].scale_maxpos == 32767.0 && lp.fields[0].scale_range == 180.0,
              "linscale arguments parsed");
    }

    // ---- model modules and distribution (engine-spec.md v0.4) ----
    {
        gt::Module m = gt::parse_model(kCoreModel);
        check(m.name == "core" && m.distribution == gt::Distribution::Public && m.keys.size() == 9 &&
                  m.find("v") && m.find("v")->type == gt::KeyType::Float && m.find("v")->meaning == "scaled",
              "module parsed");
    }
    expect_error(gt::ErrorKind::UnknownDirective,
                 [] { gt::parse_model("module m\ndistribution public\nsource s\nbogus x\n"); }, "module directive");
    expect_error(gt::ErrorKind::BadDirective,
                 [] { gt::parse_model("module m\nversion 1\ndistribution public\nsource s\nkey a.b int -\n"); },
                 "dot in key name");
    expect_error(gt::ErrorKind::MissingDistribution, [] { gt::parse_model("module m\nversion 1\nsource s\n"); },
                 "module without distribution");
    expect_error(gt::ErrorKind::MissingSource, [] { gt::parse_model("module m\nversion 1\ndistribution public\n"); },
                 "module without source");
    expect_error(gt::ErrorKind::DuplicateKey,
                 [] { gt::parse_model("module m\nversion 1\ndistribution public\nsource s\nkey a int -\nkey a int -\n"); },
                 "duplicate key");
    expect_error(gt::ErrorKind::MissingDistribution, [] { gt::parse_pack("format a\nversion 1\nwire geojson\n"); },
                 "missing-distribution precedes missing-source");
    expect_error(gt::ErrorKind::DuplicateModule, [&] { eng.load_model(kCoreModel); }, "duplicate module");
    expect_error(gt::ErrorKind::UndeclaredKey,
                 [&] { eng.add_pack(gt::parse_pack(HDR "format u\nwire geojson\nfield nope id string\n")); },
                 "undeclared key");
    expect_error(gt::ErrorKind::KeyTypeMismatch,
                 [&] { eng.add_pack(gt::parse_pack(HDR "format u\nwire geojson\nfield lat id string\n")); },
                 "key type mismatch");
    // v0.26 ruling 1: iso8601_s yields int; on a key of another type it is key-type-mismatch.
    expect_error(gt::ErrorKind::KeyTypeMismatch,
                 [&] { eng.add_pack(gt::parse_pack(HDR "format u\nwire geojson\nfield lat t iso8601_s\n")); },
                 "iso8601_s on a float key");
    expect_error(gt::ErrorKind::KeyTypeMismatch,
                 [&] { eng.add_pack(gt::parse_pack(HDR "format u\nwire geojson\nfield uid t iso8601_s\n")); },
                 "iso8601_s on a string key");
    expect_error(gt::ErrorKind::ModuleNotUsed,
                 [&] { eng.add_pack(gt::parse_pack(HDR "format u\nwire geojson\nfield x.y id string\n")); },
                 "module not used");
    expect_error(gt::ErrorKind::UnknownModule,
                 [&] { eng.add_pack(gt::parse_pack(HDR "format u\nwire geojson\nuses x\nfield x.y id string\n")); },
                 "unknown module");
    try {
        gt::parse_pack("format a\nversion 1\nwire geojson\n");
    } catch (const gt::Error& e) {
        check(std::string(e.what()).rfind("missing-distribution:", 0) == 0, "message begins with kind and colon");
    }
    {
        gt::Engine pub;
        pub.set_max_distribution(gt::Distribution::Public);
        expect_error(gt::ErrorKind::DistributionRefused,
                     [&] { pub.load_model("module core\nversion 1\ndistribution controlled\nsource s\n"); },
                     "public engine refuses controlled module");
        pub.load_model(kCoreModel);
        expect_error(gt::ErrorKind::DistributionRefused,
                     [&] {
                         pub.add_pack(gt::parse_pack(
                             "distribution controlled\nsource s\nformat c\nversion 1\nwire geojson\nfield uid id string\n"));
                     },
                     "public engine refuses controlled pack");
    }

    // ---- message kinds, the json wire and the 0.5 bits additions ----
    auto begins = [](const std::string& msg, const std::string& kind) { return msg.rfind(kind + ":", 0) == 0; };
    auto error_text = [](auto&& f) -> std::string {
        try {
            f();
        } catch (const gt::Error& e) {
            return e.what();
        }
        return "";
    };
    {
        // pack grammar
        gt::Pack kp = gt::parse_pack(HDR "format k\nwire xml\nroot r\nfield uid @id string\nwhen @v \"a # b\"\n"
                                         "kind one\nwhen @k =present\nrequires lat lon\nfield lat @lat float\n"
                                         "kind two\nwhen @k present\n");
        check(kp.fields.size() == 1 && kp.whens.size() == 1 && kp.whens[0].text == "a # b" && kp.kinds.size() == 2 &&
                  kp.kinds[0].name == "one" && kp.kinds[0].requires_keys.size() == 2 &&
                  kp.kinds[0].whens[0].forced_string && kp.kinds[0].whens[0].text == "present" &&
                  !kp.kinds[0].whens[0].present && kp.kinds[1].whens[0].present,
              "kinds parsed; '#' in quotes is literal; '=present' is the literal text");
        expect_error(gt::ErrorKind::DuplicateKind,
                     [] { gt::parse_pack(HDR "format a\nwire xml\nroot r\nkind a\nkind a\n"); }, "duplicate kind");
        // 0.6: `duplicate-field` is withdrawn; a key may be mapped by several lines.
        check(gt::parse_pack(HDR "format a\nwire xml\nroot r\nfield k @a string\nfield k @b string\nkind a\n"
                                 "field k @c string\n")
                      .fields.size() == 2,
              "a key mapped by several lines loads, in common lines and in a kind");
        expect_error(gt::ErrorKind::BadDirective,
                     [] { gt::parse_pack(HDR "format a\nwire xml\nroot r\nrequires uid\nkind a\n"); },
                     "requires before first kind");
        expect_error(gt::ErrorKind::BadDirective,
                     [] { gt::parse_pack(HDR "format a\nwire xml\nroot r\nwhen @k a\n"); }, "when without kind");
        expect_error(gt::ErrorKind::BadDirective,
                     [] { gt::parse_pack(HDR "format a\nwire json\nbit_order msb\n"); }, "bit_order on json");
        expect_error(gt::ErrorKind::BadDirective,
                     [] { gt::parse_pack(HDR "format a\nwire bits\nword_bytes 1\nkind a\nwhen 0:0:3 8\n"); },
                     "bits when value does not fit");
        expect_error(gt::ErrorKind::BadDirective,
                     [] { gt::parse_pack(HDR "format a\nwire bits\nword_bytes 1\nfield k 0:0:2048 ascii\n"); },
                     "ascii longer than 2040 bits");
        expect_error(gt::ErrorKind::BadDirective,
                     [] { gt::parse_pack(HDR "format a\nwire xml\nroot r\nfield k @k bool\n"); }, "bool off the json wire");
        check(begins(error_text([] { gt::parse_pack(HDR "format a\nwire xml\nroot r\nkind a\nkind a\n"); }),
                     "duplicate-kind"),
              "duplicate-kind message begins with the kind");
        gt::Pack two = gt::parse_pack(HDR "format a\nwire xml\nroot r\nfield k @a string\nfield k @a string\n");
        check(two.fields.size() == 2, "repeated key and locator load in a pack with no kinds");
        gt::Pack q = gt::parse_pack(HDR "format a\nwire xml\nroot r\nfield k \"a\\b/@c\" string\n");
        check(q.fields[0].locator == "a\\b/@c", "no escape inside quotes");
    }
    {
        gt::Engine k;
        k.load_model("module core\nversion 0.1.0\ndistribution public\nsource s\nkey uid string -\nkey lat float deg\n"
                     "key lon float deg\nkey hae float m\nkey callsign string -\nkey time_ms int ms\nkey flag int -\n"
                     "key ce float m\n");
        k.add_pack(gt::parse_pack(
            HDR "format kj\nwire json\nwhen schema s1\nfield uid id string\nfield lat pos.lat float\n"
                "kind full\nrequires hae\nwhen meta.v 2\nfield hae pos.alt float\nfield flag meta.on bool\n"
                "kind base\n"));
        k.add_pack(gt::parse_pack(
            HDR "format kb\nwire bits\nword_bytes 2\nbit_order msb\nfield time_ms 0:0:8 uint\n"
                "kind pos\nwhen 0:8:4 1\nrequires lat\nfield lat 0:12:20 sscale:1/1000\nfield hae 1:16:16 uscale:0.5:-100\n"
                "kind name\nwhen 0:8:4 2\nrequires callsign\nfield callsign 1:0:24 ascii\n"
                "kind none\nwhen 0:8:4 0\n"));
        k.add_pack(gt::parse_pack(
            HDR "format kp\nwire protobuf\nfield uid 1 pstring\n"
                "kind pos\nwhen 5 present\nrequires lat\nfield lat 5.1 pdouble\n"
                "kind code\nwhen 3 7\nfield time_ms 4 pvarint\n"));
        try {
            check(k.model_keys("kj") == std::vector<std::string>({"uid", "lat", "hae", "flag"}), "model_keys union");

            // json: kind by `when`, member order, nested residue, bool, null
            gt::Entity e = k.decode("kj", "{\"x\":{\"y\":1.50,\"z\":[1]},\"meta\":{\"on\":true,\"v\":2.0},\"id\":\"a\","
                                          "\"pos\":{\"alt\":3,\"lat\":null},\"schema\":\"s1\"}");
            check(e.kind.first == "kj" && e.kind.second == "full", "json decode selects kind");
            check(e.fields.count("flag") && e.fields["flag"].i == 1 && !e.fields.count("lat"), "json bool and null");
            eq(k.encode("kj", e), "{\"schema\":\"s1\",\"id\":\"a\",\"pos\":{\"alt\":3},\"meta\":{\"v\":2,\"on\":true},\"x\":{\"y\":1.5}}",
               "json canonical output");
            e.kind = {};
            e.fields.erase("hae");
            eq(k.encode("kj", e), "{\"schema\":\"s1\",\"id\":\"a\",\"x\":{\"y\":1.5}}", "json encode picks kind by requires");
            e.fields["flag"] = gt::Value::of_int(2);
            e.kind = {"kj", "full"};
            check(begins(error_text([&] { k.encode("kj", e); }), "transform-encode"), "bool encodes only 1 and 0");
            check(begins(error_text([&] { k.decode("kj", "{\"schema\":\"s2\"}"); }), "no-kind"), "common when fails");
            check(begins(error_text([&] { k.decode("kj", "{\"schema\":\"s1\",\"id\":5}"); }), "transform-decode"),
                  "json value of the wrong type");
            check(begins(error_text([&] { k.decode("kj", "[1]"); }), "malformed-wire"), "json message is an object");

            // bits: msb order, a field past its word, scale transforms, ascii
            gt::Entity b;
            b.fields["time_ms"] = gt::Value::of_int(0xAB);
            b.fields["lat"] = gt::Value::of_float(-1.5);
            b.fields["hae"] = gt::Value::of_float(28.0);
            eq(k.encode("kb", b), "ab1ffa240100", "bits msb encode, field runs past its word");
            gt::Entity bd = k.decode("kb", "ab1ffa240100ffff");
            check(bd.kind.second == "pos" && bd.fields["lat"].f == -1.5 && bd.fields["hae"].f == 28.0,
                  "bits decode, longer input accepted");
            check(begins(error_text([&] { k.decode("kb", "ab1ffa24"); }), "malformed-wire"), "bits input too short");
            check(begins(error_text([&] { k.decode("kb", "ab30"); }), "no-kind"), "bits unknown kind code");
            b.fields["hae"] = gt::Value::of_float(-101.0);
            check(begins(error_text([&] { k.encode("kb", b); }), "transform-encode"), "uscale below the field range");
            gt::Entity n;
            n.fields["callsign"] = gt::Value::of_string("AB");
            eq(k.encode("kb", n), "002041420000", "ascii NUL-padded");
            check(k.decode("kb", "002000000000").fields.at("callsign").s.empty(), "all-NUL ascii is the empty string");
            check(begins(error_text([&] { k.decode("kb", "002041004200"); }), "transform-decode"), "NUL inside ascii");
            n.fields["callsign"] = gt::Value::of_string("ABCD");
            check(begins(error_text([&] { k.encode("kb", n); }), "transform-encode"), "ascii text too long");
            eq(k.encode("kb", gt::Entity{}), "0000", "bits default kind");

            // protobuf: `present` writes an empty field; an integer `when` is written as a varint
            gt::Entity pe;
            pe.fields["uid"] = gt::Value::of_string("a");
            eq(k.encode("kp", pe), "0a01611807", "protobuf encode picks kind by requires, writes the when varint");
            pe.kind = {"kp", "pos"};
            eq(k.encode("kp", pe), "0a01612a00", "protobuf present writes an empty field");
            check(k.decode("kp", "0a01612a00").kind.second == "pos", "protobuf decode selects kind by presence");
            check(begins(error_text([&] { k.decode("kp", "0a0161"); }), "no-kind"), "protobuf no kind");
            pe.kind = {"kp", "nope"};
            check(begins(error_text([&] { k.encode("kp", pe); }), "no-kind"), "entity names an unknown kind");

            // convert clears the kind unless from == to
            eq(k.convert("kp", "kj", "0a01612a00"), "{\"schema\":\"s1\",\"id\":\"a\"}", "cross-format convert re-selects the kind");
        } catch (const std::exception& ex) {
            check(false, std::string("0.5 behaviour threw: ") + ex.what());
        }
    }

    // ---- 0.6: mapping rules ----
    {
        const char* core6 =
            "module core\nversion 0.1.0\ndistribution public\nsource \"unit test\"\n"
            "key uid string -\nkey type string -\nkey time_ms int ms\nkey lat float deg\nkey lon float deg\n"
            "key callsign string -\nkey course float deg\nkey speed_ms float m/s\nkey ce float m\n";
        const char* mod6 =
            "module m\nversion 0.1.0\ndistribution public\nsource \"unit test\"\n"
            "key east float -\nkey north float -\nkey n int -\nkey n2 int -\nkey s string -\nkey big float -\n"
            "key huge float -\nkey cls string -\n"
            "derive course bearing m.east m.north\nderive speed_ms hypot m.east m.north\n"
            "derive m.n2 offset:-2 m.n\nderive m.s \"join: - \" uid callsign\n"
            "derive m.huge scale:1e200 m.big\n";
        try {
            gt::Engine r;
            r.load_model(core6);
            r.load_model(mod6);

            // derived keys, on their own (`complete`)
            gt::Entity d;
            d.fields["m.east"] = gt::Value::of_float(-4.0);
            d.fields["m.north"] = gt::Value::of_float(0.0);
            d.fields["m.n"] = gt::Value::of_int(5);
            d.fields["uid"] = gt::Value::of_string("u");
            d.fields["callsign"] = gt::Value::of_string("c");
            d.fields["m.big"] = gt::Value::of_float(1e200);
            r.complete(d);
            check(d.fields.count("course") && d.fields["course"].f == 270.0, "bearing is reduced to [0, 360)");
            check(d.fields.count("speed_ms") && d.fields["speed_ms"].f == 4.0, "hypot");
            check(d.fields.count("m.n2") && d.fields["m.n2"].kind == gt::Value::Kind::Int && d.fields["m.n2"].i == 3,
                  "offset on int keys is integer addition");
            check(d.fields.count("m.s") && d.fields["m.s"].s == "u - c", "join with a quoted separator");
            check(!d.fields.count("m.huge"), "a result that is not finite leaves the target absent");
            gt::Entity z;
            z.fields["m.east"] = gt::Value::of_float(0.0);
            z.fields["m.north"] = gt::Value::of_float(0.0);
            r.complete(z);
            check(!z.fields.count("course") && z.fields.count("speed_ms") && z.fields["speed_ms"].f == 0.0,
                  "bearing is absent when both arguments are 0");
            gt::Entity kept;
            kept.fields["m.east"] = gt::Value::of_float(3.0);
            kept.fields["m.north"] = gt::Value::of_float(4.0);
            kept.fields["speed_ms"] = gt::Value::of_float(9.0);
            r.complete(kept);
            check(kept.fields["speed_ms"].f == 9.0, "a present target is kept");

            // derive load checks
            const std::string mh = "module x\nversion 1\ndistribution public\nsource s\nkey a float -\nkey i int -\nkey t string -\n";
            auto derive_error = [&](const std::string& line) {
                gt::Engine e2;
                e2.load_model(core6);
                return error_text([&] { e2.load_model(mh + line + "\n"); });
            };
            check(begins(derive_error("derive x.a cube x.a"), "bad-directive"), "derive: unknown function");
            check(begins(derive_error("derive x.a scale x.a"), "bad-directive"), "derive: scale without a factor");
            check(begins(derive_error("derive x.a neg:2 x.a"), "bad-directive"), "derive: parameter on neg");
            check(begins(derive_error("derive x.a hypot x.a x.a x.a"), "bad-directive"), "derive: too many arguments");
            check(derive_error("derive x.t join:- x.t").empty(), "derive: join takes one or more arguments (0.6 ruling 7)");
            check(begins(derive_error("derive x.t join:-"), "bad-directive"), "derive: join of no argument");
            check(begins(derive_error("derive x.i offset:0.5 x.i"), "bad-directive"), "derive: fractional offset on int keys");
            check(begins(derive_error("derive x.a offset:1 x.i"), "bad-directive"), "derive: offset on mixed types");
            check(begins(derive_error("derive x.a copy nope"), "bad-directive"), "derive: undeclared core key");
            check(derive_error("derive lat neg x.a\nkey late float -\nderive x.late neg lat").empty(),
                  "derive: core target, and a key declared after the line that names it");
            check(begins(error_text([&] { gt::parse_model("module x\nversion 1\nsource s\nkey a float -\nderive x.a cube x.a\n"); }),
                         "bad-directive"),
                  "derive line errors precede missing-distribution");

            // caller-supplied keys
            r.add_pack(gt::parse_pack(HDR "format cj\nwire json\nuses m\nfield uid id string\nfield lat lat float\n"
                                          "field time_ms t int\nfield callsign name string\nfield m.cls cls int via c\n"
                                          "field speed_ms v float\ndefault callsign NONE\nconst ver 1\n"
                                          "map c 01 one\nmap c 2 two\n"));
            eq(r.convert("cj", "cj", "{\"id\":\"a\",\"ver\":7}"), "{\"id\":\"a\",\"name\":\"NONE\",\"ver\":1}",
               "default written, const over the input, no context: nothing derived");
            eq(r.convert("cj", "cj", "{\"id\":\"a\",\"lat\":1}",
                         r.context_from_text({{"lat", "9"}, {"time_ms", "5"}, {"callsign", "X"}})),
               "{\"id\":\"a\",\"lat\":1,\"t\":5,\"name\":\"X\",\"ver\":1}",
               "context fills only the keys the entity lacks, and comes before the default");
            check(begins(error_text([&] { r.context_from_text({{"nope", "1"}}); }), "undeclared-key"),
                  "context key no module declares");
            check(begins(error_text([&] { r.context_from_text({{"q.x", "1"}}); }), "undeclared-key"),
                  "context key of a module that is not loaded");
            check(begins(error_text([&] { r.context_from_text({{"time_ms", "soon"}}); }), "key-type-mismatch"),
                  "context value that cannot be read as the key's type");
            gt::Engine::Context typed;
            typed["lat"] = gt::Value::of_string("north");
            check(begins(error_text([&] { r.convert("cj", "cj", "{\"id\":\"a\"}", typed); }), "key-type-mismatch"),
                  "typed context value of the wrong type");
            eq(r.convert("cj", "cj", "{\"id\":\"a\"}", gt::Engine::Context{}), "{\"id\":\"a\",\"name\":\"NONE\",\"ver\":1}",
               "an empty context is a context");

            // value tables: entries compare as canonical text
            check(r.decode("cj", "{\"cls\":1}").fields.at("m.cls").s == "one", "table entry 01 matches the wire integer 1");
            gt::Entity te;
            te.fields["m.cls"] = gt::Value::of_string("one");
            eq(r.encode("cj", te), "{\"name\":\"NONE\",\"cls\":1,\"ver\":1}", "table entry 01 is written as the integer 1");
            te.fields["m.cls"] = gt::Value::of_string("three");
            check(begins(error_text([&] { r.encode("cj", te); }), "transform-encode"),
                  "model value with no entry, types differ");
            check(begins(error_text([&] {
                      r.add_pack(gt::parse_pack(HDR "format bad\nwire json\nfield lat a float\ndefault lat north\n"));
                  }),
                         "key-type-mismatch"),
                  "default that cannot be read as the key's type");
            check(begins(error_text([&] {
                      r.add_pack(gt::parse_pack(HDR "format bad\nwire json\nfield lat a float\ndefault x.y 1\n"));
                  }),
                         "module-not-used"),
                  "default for a key of a module the pack does not use");
            check(begins(error_text([] { gt::parse_pack(HDR "format a\nwire json\nfield uid id string loud\n"); }),
                         "bad-directive"),
                  "unknown field option");
            check(begins(error_text([] { gt::parse_pack(HDR "format a\nwire json\nfield uid id string via\nmap t a b\n"); }),
                         "bad-directive"),
                  "via without a table name");
            check(begins(error_text([] { gt::parse_pack("format a\nversion 1\nwire json\nfield uid id string via t\n"); }),
                         "bad-directive"),
                  "via with no map line precedes missing-distribution");

            // a default does not satisfy `requires`; a kind's default is in scope for common fields
            r.add_pack(gt::parse_pack(HDR "format kx\nwire xml\nfield callsign @name string\ndefault callsign COMMON\n"
                                          "kind a\nroot alpha\nrequires lat\nfield lat @lat float\n"
                                          "kind b\nroot beta\ndefault callsign KIND\nconst @k =present\n"));
            eq(r.encode("kx", gt::Entity{}), "<beta name=\"KIND\" k=\"present\"/>",
               "requires does not see a default; the kind's default is used before the common one; const =present writes the text");
            check(begins(error_text([] { gt::parse_pack(HDR "format a\nwire xml\nroot r\nconst @k present\n"); }),
                         "bad-directive"),
                  "const present (0.6 ruling 3)");
            gt::Entity ka;
            ka.fields["lat"] = gt::Value::of_float(1.0);
            eq(r.encode("kx", ka), "<alpha name=\"COMMON\" lat=\"1\"/>", "the kind's root is written");
            check(r.decode("kx", "<beta name=\"q\" k=\"1\" z=\"2\"/>").residue.size() == 1,
                  "a const maps its locator: only the unmapped attribute is residue");
            check(begins(error_text([&] { r.decode("kx", "<gamma/>"); }), "no-kind"), "root of no kind");
            check(begins(error_text([] { gt::parse_pack(HDR "format a\nwire xml\nkind a\nroot x\nkind b\n"); }),
                         "missing-root"),
                  "xml without a pack root needs a root in every kind");

            // one key at several locators, text order on xml
            r.add_pack(gt::parse_pack(HDR "format two\nwire xml\nroot r\nfield lat @a float\nfield uid @id string\n"
                                          "field lat @b float\n"));
            check(r.decode("two", "<r a=\"x\" b=\"2\"/>").fields.at("lat").f == 2.0,
                  "earliest line fails, a later line gives the value");
            check(begins(error_text([&] { r.decode("two", "<r a=\"x\" b=\"y\"/>"); }), "transform-decode"),
                  "every line of the key fails");
            eq(r.convert("two", "two", "<r b=\"2\" id=\"u\"/>"), "<r a=\"2\" id=\"u\" b=\"2\"/>",
               "encode writes the value at every locator of the key");

            // bits options with words of several bytes
            r.add_pack(gt::parse_pack(HDR "format ob\nwire bits\nword_bytes 2\nbit_order msb\n"
                                          "field time_ms 0:0:16 uint swap\nfield callsign 1:0:24 ascii trim optional\n"
                                          "field lat 3:0:32 f32 optional\nfield lon 5:0:64 f64 optional\n"));
            gt::Entity ob = r.decode("ob", "3412");
            check(ob.fields.size() == 1 && ob.fields.at("time_ms").i == 0x1234, "optional fields beyond the input are absent");
            check(r.decode("ob", "3412412020").fields.at("callsign").s == "A", "optional field wholly inside the input; trim");
            check(begins(error_text([&] { r.decode("ob", "34"); }), "malformed-wire"),
                  "input shorter than the non-optional fields");
            eq(r.encode("ob", ob), "341200000000000000000000000000000000", "encode writes the whole message");
            check(begins(error_text([&] { r.decode("ob", "341200000000" "7f800000"); }), "transform-decode"),
                  "f32 infinity on the wire");
            check(begins(error_text([&] { r.decode("ob", "341200000000" "00000000" "7ff8000000000000"); }),
                         "transform-decode"),
                  "f64 not-a-number on the wire");
            gt::Entity wide;
            wide.fields["lat"] = gt::Value::of_float(1e39);
            check(begins(error_text([&] { r.encode("ob", wide); }), "transform-encode"), "f32 outside single range");
            wide.fields.clear();
            wide.fields["callsign"] = gt::Value::of_string("\xC3\xA9");
            check(begins(error_text([&] { r.encode("ob", wide); }), "transform-encode"), "ascii text with a byte above 0x7E");

            // json: the same member name twice is malformed (0.5 ruling 22)
            check(begins(error_text([&] { r.decode("cj", "{\"id\":\"a\",\"x\":{\"y\":1,\"y\":2}}"); }), "malformed-wire"),
                  "json duplicate member name, nested");
        } catch (const std::exception& ex) {
            check(false, std::string("0.6 behaviour threw: ") + ex.what());
        }
    }

    // ---- 0.7: groups, and the 0.6 rulings the vectors now pin
    {
        const char* core7 =
            "module core\nversion 0.1.0\ndistribution public\nsource s\nkey uid string -\nkey lat float deg\n"
            "key type string -\n";
        const char* mod7 =
            "module g\nversion 0.1.0\ndistribution public\nsource s\nkey name string -\nkey n int -\nkey r float -\n"
            "list items \"things\"\nlist subs\nlist nums\n";
        try {
            gt::Engine r;
            r.load_model(core7);
            r.load_model(mod7);
            check(r.is_list("g.items") && !r.is_list("g.name") && !r.is_list("g.nope") && !r.find_key("g.items"),
                  "a list is declared, and is not a key");
            check(begins(error_text([&] { gt::parse_model(std::string(mod7) + "key items string -\n"); }), "duplicate-key"),
                  "a key named as a list");
            check(begins(error_text([&] { gt::parse_model(std::string(mod7) + "list n\n"); }), "duplicate-key"),
                  "a list named as a key");

            r.add_pack(gt::parse_pack(HDR "format gj\nwire json\nuses g\nfield uid id string\n"
                                          "group g.items items\n  field g.name name string\n  field g.n n int\n"
                                          "  default g.n 1\n  const k item\n"
                                          "  group g.subs subs\n    field g.r . float\n  end\nend\n"
                                          "group g.nums a.nums\n  field g.n . int\nend\nfield lat lat float\n"));
            check(r.model_keys("gj") == std::vector<std::string>({"uid", "g.items[]", "g.items[].g.name", "g.items[].g.n",
                                                                  "g.items[].g.subs[]", "g.items[].g.subs[].g.r",
                                                                  "g.nums[]", "g.nums[].g.n", "lat"}),
                  "model_keys lists a list as <list>[] and an item key as <list>[].<key>");
            gt::Entity d = r.decode("gj", "{\"id\":\"u\",\"items\":[{\"name\":\"a\",\"subs\":[1.5,2]},{\"n\":4,\"x\":1}],\"a\":{\"nums\":[]}}");
            check(d.lists.size() == 2 && d.lists.at("g.items").size() == 2 && d.lists.at("g.nums").empty(),
                  "decode fills Entity.lists; a present and empty list is kept");
            check(d.lists.at("g.items")[0].fields.at("g.name").s == "a" && !d.lists.at("g.items")[0].fields.count("g.n") &&
                      d.lists.at("g.items")[0].lists.at("g.subs")[1].fields.at("g.r").f == 2.0 &&
                      !d.lists.at("g.items")[1].lists.count("g.subs") && d.residue.empty(),
                  "items hold keys and nested lists; a default does not change the item; items carry no residue");
            eq(r.encode("gj", d),
               "{\"id\":\"u\",\"items\":[{\"name\":\"a\",\"n\":1,\"k\":\"item\",\"subs\":[1.5,2]},{\"n\":4,\"k\":\"item\"}],"
               "\"a\":{\"nums\":[]}}",
               "encode writes the items in order, defaults and constants per item");
            gt::Entity made;
            made.lists["g.items"].emplace_back();
            made.lists["g.items"].emplace_back();
            made.lists["g.items"][1].fields["g.name"] = gt::Value::of_string("b");
            made.lists["g.nums"].emplace_back();
            eq(r.encode("gj", made), "{\"items\":[{\"n\":1,\"k\":\"item\"},{\"name\":\"b\",\"n\":1,\"k\":\"item\"}],\"a\":{\"nums\":[null]}}",
               "an entity built by hand; a scalar item with no value is null (0.7 ruling 11)");
            check(begins(error_text([&] { r.decode("gj", "{\"items\":5}"); }), "malformed-wire"), "a list member that is not an array");
            check(begins(error_text([&] { r.decode("gj", "{\"items\":[{\"subs\":[[1]]}]}"); }), "transform-decode"),
                  "'.' on an item that is an array");

            // bits: a count locator, a fixed count, a nested group that runs past its item
            r.add_pack(gt::parse_pack(HDR "format gb\nwire bits\nword_bytes 1\nuses g\n"
                                          "group g.nums 0:8 item 4 count 2\n  field g.n 0:0:4 uint\nend\n"
                                          "group g.items 0:16 item 16 count 0:0:8\n  field g.n 0:0:8 uint\n"
                                          "  group g.subs 0:16 item 8 count 0:8:8\n    field g.r 0:0:8 uscale:1/2\n  end\nend\n"));
            gt::Entity b = r.decode("gb", "02 21 07 02 03 04 09 00 ff");
            check(b.lists.at("g.nums").size() == 2 && b.lists.at("g.nums")[1].fields.at("g.n").i == 2 &&
                      b.lists.at("g.items").size() == 2 && b.lists.at("g.items")[0].lists.at("g.subs").size() == 2 &&
                      b.lists.at("g.items")[0].lists.at("g.subs")[1].fields.at("g.r").f == 2.0 &&
                      b.lists.at("g.items")[1].fields.at("g.n").i == 9 && b.lists.at("g.items")[1].lists.at("g.subs").empty(),
                  "bits groups: the next item starts where a nested counted group ends; longer input is accepted");
            eq(r.encode("gb", b), "0221070203040900", "bits groups re-encode, the count written from the number of items");
            check(begins(error_text([&] { r.decode("gb", "0221070203"); }), "malformed-wire"), "input ends inside the nested items");
            gt::Entity nb;
            check(begins(error_text([&] { r.encode("gb", nb); }), "transform-encode"), "an absent list under a fixed count");
            nb.lists["g.nums"].resize(3);
            check(begins(error_text([&] { r.encode("gb", nb); }), "transform-encode"), "a fixed count with another number of items");
            nb.lists["g.nums"].resize(2);
            eq(r.encode("gb", nb), "0000", "an absent list under a count locator writes the count 0");
            eq(r.convert("gj", "gb", "{\"items\":[{\"n\":7,\"subs\":[0.5]}],\"a\":{\"nums\":[1,2]}}"), "0121070101",
               "a list is carried between two formats that map it, item by item");

            // xml and protobuf
            r.add_pack(gt::parse_pack(HDR "format gx\nwire xml\nroot m\nuses g\nfield uid @id string\n"
                                          "group g.items b/i\n  field g.name \"#text\" string\n  field g.n @n int\nend\n"));
            eq(r.convert("gx", "gx", "<m id=\"u\"><b><x/><i n=\"1\">a</i><i/></b><b><i>z</i></b></m>"),
               "<m id=\"u\"><b><i n=\"1\">a</i><i/></b></m>", "xml items: the children of the first element matched");
            check(!r.decode("gx", "<m><b/></m>").lists.count("g.items"), "xml: no item occurs, the list is absent");
            r.add_pack(gt::parse_pack(HDR "format gp\nwire protobuf\nuses g\nfield uid 1 pstring\n"
                                          "group g.nums 2\n  field g.n . pvarint\nend\n"
                                          "group g.items 3\n  field g.name 1 pstring\nend\n"));
            eq(r.convert("gp", "gp", "1001 12020203 1a00 1a030a0161"), "12030102031a001a030a0161",
               "protobuf: unpacked and packed scalars read, the packed form written; items in wire order");
            check(begins(error_text([&] { r.decode("gp", "1801"); }), "malformed-wire"), "an item that is not a submessage");
            check(begins(error_text([&] { r.decode("gp", "120180"); }), "malformed-wire"), "a packed varint cut short");
            check(!r.decode("gp", "1200").lists.count("g.nums"), "a packed occurrence with no values leaves the list absent");

            // `requires <list>`
            r.add_pack(gt::parse_pack(HDR "format gk\nwire json\nuses g\nkind full\nwhen s f\nrequires g.items\n"
                                          "group g.items items\n  field g.name name string\nend\nkind bare\nwhen s b\n"));
            eq(r.convert("gj", "gk", "{\"items\":[{\"name\":\"a\"}]}"), "{\"s\":\"f\",\"items\":[{\"name\":\"a\"}]}",
               "requires <list> holds with at least one item");
            eq(r.convert("gj", "gk", "{\"items\":[]}"), "{\"s\":\"b\"}", "requires <list> does not hold for an empty list");

            // load errors
            auto load_error = [&](const std::string& body) {
                return error_text([&] {
                    gt::Engine e2;
                    e2.load_model(core7);
                    e2.load_model(mod7);
                    e2.add_pack(gt::parse_pack(HDR "format z\nuses g\n" + body));
                });
            };
            check(begins(load_error("wire json\ngroup g.items items\n"), "bad-directive"), "a group with no end");
            check(begins(load_error("wire json\nend\n"), "bad-directive"), "an end with no open group");
            check(begins(load_error("wire json\ngroup g.items items\nmap t 1 a\nend\n"), "bad-directive"), "map inside a group");
            check(begins(load_error("wire json\ngroup g.items a\nend\ngroup g.items b\nend\n"), "bad-directive"),
                  "a list mapped by two groups of one scope");
            check(begins(load_error("wire json\ngroup g.items items count 2\nend\n"), "bad-directive"), "count on json");
            check(begins(load_error("wire json\nfield g.name . string\n"), "bad-directive"), "'.' outside a group");
            check(begins(load_error("wire json\ngroup g.name items\nend\n"), "key-type-mismatch"), "a group naming a key");
            check(begins(load_error("wire json\nfield g.items items string\n"), "key-type-mismatch"), "a field naming a list");
            check(begins(load_error("wire json\ngroup g.nope items\nend\n"), "undeclared-key"), "a group naming no list");
            check(begins(load_error("wire bits\nword_bytes 1\ngroup g.items 0:8 item 8\nend\n"), "bad-directive"),
                  "a bits group with no count");
            check(begins(load_error("wire bits\nword_bytes 1\ngroup g.items 0:8 item 8 count 0:0:8\nend\nfield g.n 0:8:8 uint\n"),
                         "bad-directive"),
                  "a field at the start of a group counted by a locator");
            check(begins(load_error("wire bits\nword_bytes 1\ngroup g.items 0:8 item 8 count 0:4:8\nend\n"), "bad-directive"),
                  "a count locator that reaches the group's start");
            check(begins(load_error("wire bits\nword_bytes 1\ngroup g.items 0:8 item 8 count 0:0:8\n  field g.n 0:4:8 uint\nend\n"),
                         "bad-directive"),
                  "an item field beyond item bits");
            check(load_error("wire bits\nword_bytes 1\nfield g.n 0:0:8 uint\ngroup g.items 0:8 item 8 count 0:0:8\n"
                             "  field g.n 0:0:8 uint\nend\n")
                      .empty(),
                  "a count locator on the bits of a field loads");

            // 0.6 rulings: a table miss of another type is not forgiven; the context is checked after the decode
            r.add_pack(gt::parse_pack(HDR "format gt\nwire json\nfield lat a string via w\nfield lat b float\n"
                                          "map w high 0.9\n"));
            check(begins(error_text([&] { r.decode("gt", "{\"a\":\"mid\",\"b\":0.5}"); }), "transform-decode"),
                  "a table miss fails the decode; later lines of the key are not tried");
            check(r.decode("gt", "{\"a\":5,\"b\":0.5}").fields.at("lat").f == 0.5, "a failed transform is forgiven by a later line");
            check(begins(error_text([&] { r.convert_text("gt", "gt", "{\"a\":\"mid\"}", {{"nope", "1"}}); }), "transform-decode"),
                  "the decode's error comes before the context check");
            check(begins(error_text([&] { r.convert_text("gt", "gt", "{\"a\":\"high\"}", {{"nope", "1"}}); }), "undeclared-key"),
                  "an undeclared context key after a good decode");
            check(begins(error_text([&] {
                      gt::Engine e2;
                      e2.load_model("module x\nversion 0.1.0\ndistribution public\nsource s\nkey a string -\nderive x.a copy uid\n");
                  }),
                         "bad-directive"),
                  "a derive naming a core key with core not loaded");
            check(begins(error_text([&] {
                      gt::Engine e2;
                      e2.load_model("module x\nversion 0.1.0\nsource s\nkey a string -\nderive x.a copy uid\n");
                  }),
                         "missing-distribution"),
                  "a derive key check runs after missing-distribution (0.8 rulings 29 and 32)");
            check(begins(error_text([&] {
                      gt::Engine e2;
                      e2.load_model("module x\nversion 0.1.0\nsource s\nkey a string -\nderive x.a nosuchfn x.a\n");
                  }),
                         "bad-directive"),
                  "a derive line refused on its own text is raised as the file is read (0.8 ruling 32)");
        } catch (const std::exception& ex) {
            check(false, std::string("0.7 behaviour threw: ") + ex.what());
        }
    }

    {
        // Version 0.8: sequential layouts, `uses` in a module, the derive functions added.
        try {
            const char* core8 = "module core\nversion 0.1.0\ndistribution public\nsource s\nkey uid string -\nkey time_ms int ms\n";
            const char* mod8 =
                "module q\nversion 0.1.0\ndistribution public\nsource s\n"
                "key n int -\nkey x int -\nkey y int -\nkey z int -\nkey t string -\nkey f float -\n"
                "list items\nlist subs\n";
            gt::Engine r;
            r.load_model(core8);
            r.load_model(mod8);
            const std::string seq = HDR "uses q\nwire bits\nlayout sequential\nbit_order msb\n";
            r.add_pack(gt::parse_pack(seq + "format s1\nfield q.n 8 uint\npresence p 3\npad 5\n"
                                            "if p.1\n  field q.x 8 uint\nend\n"
                                            "if p.2 !p.3\n  field q.y 8 uint\nend\n"
                                            "opt\n  field q.z 7 uint\nend\n"
                                            "default q.n 9\n"));
            gt::Pack sp = r.pack("s1");
            check(sp.sequential && sp.fields.empty() && sp.seq.lines.size() == 6 && sp.seq_presences.size() == 1 &&
                      sp.seq_presences[0].max_named == 3,
                  "a sequential pack is a tree of lines");
            gt::Entity e = r.decode("s1", "01 80 11 85");
            check(e.fields.at("q.n").i == 1 && e.fields.at("q.x").i == 17 && e.fields.count("q.y") == 0 &&
                      e.fields.at("q.z").i == 5,
                  "presence, if and opt at a cursor");
            eq(r.encode("s1", e), "01801185", "sequential round trip");
            gt::Entity made;
            made.fields["q.y"] = gt::Value::of_int(2);
            eq(r.encode("s1", made), "09400200", "a default, a presence bit computed from the entity, an opt not written");
            check(r.decode("s1", "01 20 00").fields.size() == 1, "a bit named only with '!' is named: p.3 alone decodes");
            r.add_pack(gt::parse_pack(seq + "format s4\npresence p 2\nif p.1\n  field q.x 6 uint\nend\n"));
            check(r.decode("s4", "85").fields.at("q.x").i == 5, "a presence of two bits, one named");
            check(begins(error_text([&] { r.decode("s4", "40"); }), "malformed-wire"),
                  "a presence bit that is 1 and that no 'if' names");
            eq(r.encode("s1", r.decode("s1", "01 20 00 00")), "010000", "a bit named only with '!' is written 0");
            check(begins(error_text([&] { r.decode("s1", "01 80"); }), "malformed-wire"), "the input ends before a field");
            eq(r.convert("s1", "s1", "01 00 00 ff ff"), "010000", "input beyond the last line is ignored");
            check(r.model_keys("s1") == std::vector<std::string>({"q.n", "q.x", "q.y", "q.z"}), "model_keys of a sequential pack");

            // groups, items by kind, a length block, a chain and `also`
            r.add_pack(gt::parse_pack(seq + "format s2\nmap t 1 100\n"
                                            "group q.items count 8\n"
                                            "  field q.x 4 uint\n"
                                            "  kind a\n  when 4 1\n  requires q.y\n  field q.y 8 uint\n"
                                            "  kind b\n  when 4 2\n"
                                            "end\n"
                                            "length 8 plus 1\n"
                                            "  chain\n    field q.n 7 uint\n    fx\n    field q.z 7 uint\n    fx\n  end\n"
                                            "end\n"
                                            "field q.x 8 uint\nalso q.y via t\n"));
            gt::Entity e2 = r.decode("s2", "02 51 22 62 03 03 06 01");
            const auto& items = e2.lists.at("q.items");
            check(items.size() == 2 && items[0].kind.first == "s2" && items[0].kind.second == "a" &&
                      items[0].fields.at("q.y").i == 34 && items[1].kind.second == "b" && items[1].fields.at("q.x").i == 6,
                  "each item selects a kind and records it");
            check(e2.fields.at("q.n").i == 1 && e2.fields.at("q.z").i == 3 && e2.fields.at("q.x").i == 1 &&
                      e2.fields.at("q.y").i == 100,
                  "a length block, a chain, and 'also' filling a second key through its table");
            eq(r.encode("s2", e2), "0251226203030601", "a round trip with item kinds, a length block and a chain");
            gt::Entity made2;
            made2.lists["q.items"].emplace_back();
            made2.lists["q.items"][0].fields["q.x"] = gt::Value::of_int(7);
            made2.fields["q.y"] = gt::Value::of_int(100);
            eq(r.encode("s2", made2), "0172020001", "an item kind by 'requires'; the 'also' key written when the field key is absent");
            made2.lists["q.items"][0].kind = {"s2", "nope"};
            eq(r.encode("s2", made2), "0172020001", "an item naming a kind its group does not have selects by 'requires' (ruling 26)");
            made2.lists["q.items"][0].kind = {"s2", "a"};
            eq(r.encode("s2", made2), "017100020001", "an item naming a kind its group has is written as that kind");
            made2.lists["q.items"][0].kind = {};
            check(begins(error_text([&] { r.decode("s2", "01 53"); }), "no-kind"), "an item that matches no kind");
            check(begins(error_text([&] { r.decode("s2", "00 00 00"); }), "malformed-wire"), "a stated length below 'plus'");
            check(begins(error_text([&] { r.decode("s2", "00 03 03 07 00"); }), "malformed-wire"),
                  "a chain that ends with an fx line whose bit is 1");
            check(r.model_keys("s2") ==
                      std::vector<std::string>({"q.items[]", "q.items[].q.x", "q.items[].q.y", "q.n", "q.z", "q.x", "q.y"}),
                  "model_keys of a sequential pack with a group");

            // `length ... whole`, `while`, `more` and `fx` groups
            r.add_pack(gt::parse_pack(seq + "format s3\nlength 8 whole\ngroup q.items while\n  field q.x 7 uint\nend\n"
                                            "align 8\ngroup q.subs fx\n  field q.y 7 uint\nend\n"));
            gt::Entity e3 = r.decode("s3", "04 85 00 0a ff");
            check(e3.lists.at("q.items").size() == 1 && e3.lists.at("q.items")[0].fields.at("q.x").i == 5 &&
                      e3.lists.at("q.subs").size() == 1,
                  "'length ... whole' ends the message; input beyond it is ignored");
            eq(r.encode("s3", e3), "0485000a", "the length of the whole message is written last");
            check(begins(error_text([&] { r.decode("s3", "05 85 00 0a"); }), "malformed-wire"), "input shorter than the stated length");
            e3.lists.erase("q.subs");
            check(begins(error_text([&] { r.encode("s3", e3); }), "transform-encode"), "an absent list under 'fx' outside a block");

            // load errors
            auto load_error = [&](const std::string& body) {
                return error_text([&] {
                    gt::Engine e4;
                    e4.load_model(core8);
                    e4.load_model(mod8);
                    e4.add_pack(gt::parse_pack(HDR "format z\nuses q\nwire bits\n" + body));
                });
            };
            check(load_error("layout sequential\nfield q.n 8 uint\n").empty(), "a sequential pack loads");
            check(load_error("word_bytes 1\nlayout fixed\nfield q.n 0:0:8 uint\n").empty(), "'layout fixed' loads");
            check(begins(load_error("layout sequential\nword_bytes 1\n"), "bad-directive"), "word_bytes in a sequential pack");
            check(begins(load_error("layout sequential\nfield q.n 0:0:8 uint\n"), "bad-directive"), "a positional locator in a sequential pack");
            check(begins(load_error("layout sequential\nfield q.n 8 uint optional\n"), "bad-directive"), "'optional' in a sequential pack");
            check(begins(load_error("layout sequential\nopt\n  field q.n 8 uint\n"), "bad-directive"), "an 'opt' with no end");
            check(begins(load_error("layout sequential\npresence p 2\nif p.3\nend\n"), "bad-directive"), "an 'if' naming a bit beyond its presence");
            check(begins(load_error("layout sequential\nopt\n  presence p 2\nend\nif p.1\nend\n"), "bad-directive"),
                  "an 'if' after the block that holds its presence");
            check(begins(load_error("layout sequential\npresence p 2\npresence p 2\n"), "bad-directive"), "a presence declared twice in one block");
            check(begins(load_error("layout sequential\nwhen 8 1\n"), "bad-directive"), "a 'when' in a body with no kind");
            check(begins(load_error("layout sequential\nkind a\nfield q.n 8 uint\nwhen 8 1\n"), "bad-directive"),
                  "a 'when' after another line of its kind");
            check(begins(load_error("layout sequential\nconst 4 16\n"), "bad-directive"), "a const that does not fit its bits");
            check(begins(load_error("layout sequential\nlength 8 bits whole\n"), "bad-directive"), "'length ... bits whole'");
            check(begins(load_error("layout sequential\nconst 8 1\nalso q.x\n"), "bad-directive"), "'also' after a const");
            check(begins(load_error("layout sequential\nfield q.n 8 uint\nalso q.t\n"), "key-type-mismatch"), "'also' naming a key of another type");
            check(begins(load_error("layout sequential\ngroup q.items count 8\n  kind a\n  kind a\nend\n"), "duplicate-kind"),
                  "a kind name twice in one group body");
            check(begins(load_error("layout sequential\ngroup q.n fx\nend\n"), "key-type-mismatch"), "a sequential group naming a scalar key");
            check(begins(load_error("word_bytes 1\nfield q.n 0:0:8 uint\npad 8\n"), "bad-directive"), "'pad' in a fixed-layout pack");
            check(begins(load_error("word_bytes 1\nfield q.n 8 uint\n"), "bad-directive"), "a bit length for a locator in a fixed-layout pack");
            check(begins(error_text([&] {
                      gt::Engine e4;
                      e4.load_model(core8);
                      e4.add_pack(gt::parse_pack(HDR "format z\nwire json\nlayout sequential\n"));
                  }),
                         "bad-directive"),
                  "'layout sequential' on a wire other than bits");

            // 0.8 rulings 16 to 30
            // 16: the earliest key the entity holds; with none, the default of the earliest key that has one
            r.add_pack(gt::parse_pack(seq + "format s5\nfield q.n 8 uint\nalso q.x\nalso q.y\ndefault q.x 4\ndefault q.y 9\n"));
            gt::Entity m5;
            eq(r.encode("s5", m5), "04", "no key held: the default of the earliest key that has one");
            m5.fields["q.y"] = gt::Value::of_int(7);
            eq(r.encode("s5", m5), "07", "a held key is written, not the default of an earlier key");
            m5.fields["q.n"] = gt::Value::of_int(2);
            eq(r.encode("s5", m5), "02", "the earliest held key is written");
            // 20: align stops at the end of the input or extent; pad and const do not
            r.add_pack(gt::parse_pack(seq + "format s6\nfield q.n 4 uint\nalign 16\n"));
            check(r.decode("s6", "50").fields.at("q.n").i == 5, "align stops at the end of the input");
            eq(r.convert("s6", "s6", "50"), "5000", "align is written in full");
            r.add_pack(gt::parse_pack(seq + "format s7\nlength 8\n  field q.x 4 uint\n  align 64\nend\nfield q.y 8 uint\n"));
            gt::Entity e7 = r.decode("s7", "01 50 07");
            check(e7.fields.at("q.x").i == 5 && e7.fields.at("q.y").i == 7, "align stops at the end of its extent");
            eq(r.encode("s7", e7), "075000000000000007", "align in an extent is written in full, from the message start");
            r.add_pack(gt::parse_pack(seq + "format s8\nfield q.n 8 uint\npad 8\n"));
            r.add_pack(gt::parse_pack(seq + "format s9\nfield q.n 8 uint\nconst 8 1\n"));
            check(begins(error_text([&] { r.decode("s8", "05"); }), "malformed-wire"), "a pad past the end of the input");
            check(begins(error_text([&] { r.decode("s9", "05"); }), "malformed-wire"), "a const past the end of the input");
            // 21: an indicator bit at the end of an extent reads as 0
            r.add_pack(gt::parse_pack(seq + "format s10\nlength 8 bits\n  group q.items more\n    field q.x 7 uint\n  end\nend\n"));
            gt::Entity e10 = r.decode("s10", "08 89");
            check(e10.lists.at("q.items").size() == 2 && e10.lists.at("q.items")[0].fields.at("q.x").i == 9 &&
                      e10.lists.at("q.items")[1].fields.empty(),
                  "a 'more' bit at the end of the extent reads 0: one last item, of lines that read as absent");
            check(r.decode("s10", "00").lists.count("q.items") == 0, "a group that starts at the end of its extent is an absent list");
            // 34: a `while` or `fx` group at the end of its extent is an absent list, as a `more` group is
            r.add_pack(gt::parse_pack(seq + "format s12\nlength 8 bits\n  group q.items while\n    field q.x 7 uint\n  end\nend\n"
                                            "length 8 bits\n  group q.subs fx\n    field q.y 7 uint\n  end\nend\n"));
            gt::Entity e12 = r.decode("s12", "00 00");
            check(e12.lists.empty(), "a 'while' and an 'fx' group whose first indicator lies at the end of the extent");
            // 33: when both groups of a list are on the wire, decode keeps the later group's items
            r.add_pack(gt::parse_pack(seq + "format s13\nopt\n  group q.items count 8\n    field q.x 8 uint\n  end\nend\n"
                                            "opt\n  group q.items count 8\n    field q.x 8 uint\n  end\nend\n"));
            gt::Entity e13 = r.decode("s13", "80 80 c0 80 40 80");
            check(e13.lists.at("q.items").size() == 2 && e13.lists.at("q.items")[1].fields.at("q.x").i == 2,
                  "two groups of one list on the wire: the later group's items are kept");
            // 23: a list in two groups of one scope
            const std::string g = "group q.items count 8\n  field q.x 8 uint\nend\n";
            check(load_error("layout sequential\nopt\n" + g + "end\nopt\n" + g + "end\n").empty(),
                  "a list in two groups in different 'opt' blocks loads");
            check(load_error("layout sequential\npresence p 2\nif p.1 !p.2\n" + g + "end\nif p.2\n" + g + "end\n").empty(),
                  "a list in two groups in different 'if' blocks loads");
            check(begins(load_error("layout sequential\n" + g + g), "bad-directive"), "a list in two groups outside any block");
            check(begins(load_error("layout sequential\npresence p 2\nif p.1\n" + g + "if p.2\n" + g + "end\nend\n"), "bad-directive"),
                  "a list in two groups, the block of one enclosing the block of the other (ruling 33)");
            check(load_error("layout sequential\nopt\nopt\n" + g + "end\nopt\n" + g + "end\nend\n").empty(),
                  "a list in two groups in sibling blocks of one outer block loads");
            check(begins(load_error("layout sequential\nopt\n" + g + g + "end\n"), "bad-directive"), "a list in two groups of one block");
            check(begins(load_error("layout sequential\n" + g + "opt\n" + g + "end\n"), "bad-directive"),
                  "a list in two groups, one of them outside any block");
            check(begins(load_error("layout sequential\nlength 8\n" + g + "end\nlength 8\n" + g + "end\n"), "bad-directive"),
                  "a list in two groups in two 'length' blocks");
            check(begins(load_error("layout sequential\n" + g + "kind a\nwhen 8 1\n" + g), "bad-directive"),
                  "a list in the common lines and in a kind");
            check(load_error("layout sequential\nkind a\nwhen 8 1\n" + g + "kind b\nwhen 8 2\n" + g).empty(),
                  "a list in two kinds loads");
            // 24: header and table directives inside any block
            for (const char* line : {"format z2", "version 2", "distribution public", "source s", "uses q", "wire bits",
                                     "layout sequential", "bit_order msb", "map t 1 2", "typemap a b"}) {
                for (const char* block : {"opt", "chain", "length 8", "group q.items count 8"})
                    check(begins(load_error("layout sequential\n" + std::string(block) + "\n  " + line + "\nend\n"), "bad-directive"),
                          std::string("'") + line + "' inside '" + block + "'");
                check(begins(load_error("layout sequential\npresence p 1\nif p.1\n  " + std::string(line) + "\nend\n"), "bad-directive"),
                      std::string("'") + line + "' inside an 'if'");
            }
            // 26: an item carried to a group that lacks its kind selects by `requires`
            r.add_pack(gt::parse_pack(seq + "format s11\npresence p 2\npad 6\n"
                                            "if p.1 !p.2\n  group q.items count 8\n    kind small\n    when 8 1\n"
                                            "    requires q.x\n    field q.x 8 uint\n    kind tiny\n    when 8 0\n  end\nend\n"
                                            "if p.2\n  group q.items count 8\n    kind wide\n    when 8 2\n"
                                            "    requires q.x\n    field q.x 16 uint\n    kind none\n    when 8 0\n  end\nend\n"));
            gt::Entity e11 = r.decode("s11", "80 01 01 05");
            check(e11.lists.at("q.items")[0].kind == std::make_pair(std::string("s11"), std::string("small")),
                  "Item.kind holds the format with the kind name");
            eq(r.encode("s11", e11), "c001020005", "an item whose kind the written group lacks selects by 'requires'");

            // 0.7 rulings 11 to 21, pinned
            auto load_error7 = [&](const std::string& body) {
                return error_text([&] {
                    gt::Engine e4;
                    e4.load_model(core8);
                    e4.load_model(mod8);
                    e4.add_pack(gt::parse_pack(HDR "format z\nuses q\n" + body));
                });
            };
            check(begins(load_error7("wire protobuf\ngroup q.items 2\n  field q.t . pstring\n  field q.t 1 pstring\nend\n"), "bad-directive"),
                  "a protobuf group body mixing '.' with a path");
            check(begins(load_error7("wire json\ngroup q.items items\n  field q.t name string\nend\nfield q.t items.first string\n"),
                         "bad-directive"),
                  "a field whose locator passes through a group's path");
            check(load_error7("wire json\ngroup q.items data.items\n  field q.t name string\nend\nfield q.t data.count string\n").empty(),
                  "a field beside a group's path loads");
            check(begins(load_error7("wire json\ngroup q.items items\n  field q.t name string\n  uses q\nend\n"), "bad-directive"),
                  "'uses' inside a group");
            check(begins(load_error7("wire bits\nword_bytes 1\ngroup q.subs 0:8 item 8 count 2\nend\n"
                                     "group q.items 0:16 item 8 count 0:0:8\nend\n"),
                         "bad-directive"),
                  "a fixed-count group whose items reach a group counted by a locator");
            check(begins(error_text([&] { r.convert_text("s1", "s1", "01 00 00", {{"q.items", "x"}}); }), "key-type-mismatch"),
                  "a context key that is a list");

            // `uses` in a module, and the derive functions of 0.8
            auto model_error = [&](const std::string& other, bool with_q, bool q_controlled) {
                return error_text([&] {
                    gt::Engine e5;
                    e5.load_model(core8);
                    if (with_q) {
                        std::string q = mod8;
                        if (q_controlled) q.replace(q.find("public"), 6, "controlled");
                        e5.load_model(q);
                    }
                    e5.load_model("module o\nversion 0.1.0\ndistribution public\nsource s\nkey i int -\nkey s string -\nkey f float -\n" + other);
                });
            };
            check(model_error("uses q\nderive o.i copy q.n\n", true, false).empty(), "a derive argument of a used module loads");
            check(begins(model_error("derive o.i copy q.n\n", true, false), "bad-directive"), "a derive argument of a module not used");
            check(begins(model_error("uses q\nderive q.n copy o.i\n", true, false), "bad-directive"), "a derive target of a used module");
            check(begins(model_error("uses q\n", false, false), "unknown-module"), "a module that uses a module not loaded");
            check(begins(model_error("uses q\n", true, true), "distribution-violation"), "a public module that uses a controlled one");
            check(begins(model_error("derive o.i day_seconds time_ms\n", true, false), "bad-directive"), "day_seconds on an int target");
            check(begins(model_error("derive o.i not o.i o.i\n", true, false), "bad-directive"), "'not' of two arguments");
            check(begins(model_error("derive o.i text_of o.i\n", true, false), "bad-directive"), "text_of on an int target");

            // 0.8 ruling 29: the order of a module's checks
            auto module_error = [&](const std::string& text, bool limit_public, bool twice) {
                return error_text([&] {
                    gt::Engine e6;
                    e6.load_model(core8);
                    std::string q = mod8;
                    q.replace(q.find("public"), 6, "controlled");
                    if (!limit_public) e6.load_model(q);
                    if (twice) e6.load_model("module o\nversion 0.1.0\ndistribution public\nsource s\nkey i int -\n");
                    if (limit_public) e6.set_max_distribution(gt::Distribution::Public);
                    e6.load_model("module o\nversion 0.1.0\n" + text + "key i int -\nderive o.i copy o.nokey\n");
                });
            };
            check(begins(module_error("uses nosuch\n", true, false), "missing-distribution"), "a module's missing-distribution comes first");
            check(begins(module_error("distribution controlled\nuses nosuch\n", true, false), "missing-source"),
                  "missing-source before distribution-refused");
            check(begins(module_error("distribution controlled\nsource s\nuses nosuch\n", true, false), "distribution-refused"),
                  "distribution-refused before unknown-module");
            check(begins(module_error("distribution public\nsource s\nuses nosuch\n", false, false), "unknown-module"),
                  "unknown-module before the derive checks");
            check(begins(module_error("distribution public\nsource s\nuses q\n", false, false), "distribution-violation"),
                  "distribution-violation before the derive checks");
            check(begins(module_error("distribution public\nsource s\n", false, true), "bad-directive"),
                  "the derive checks before duplicate-module");
            check(begins(error_text([&] { gt::parse_model("module o\nversion 0.1.0\nkey i int -\nderive o.i nosuchfn o.i\n"); }),
                         "bad-directive"),
                  "parse_model: an unknown derive function before missing-distribution (0.6 ruling 9)");
            check(begins(error_text([&] { gt::parse_model("module o\nversion 0.1.0\nkey i int -\nderive o.i copy o.nokey\n"); }),
                         "missing-distribution"),
                  "parse_model: missing-distribution before an undeclared derive key");
            check(begins(error_text([&] {
                      gt::parse_model("module o\nversion 0.1.0\ndistribution public\nsource s\nkey i int -\nderive o.i copy o.nokey\n");
                  }),
                         "bad-directive"),
                  "parse_model: an undeclared derive key of the module itself");

            gt::Engine d;
            d.load_model(core8);
            d.load_model(mod8);
            d.load_model("module o\nversion 0.1.0\ndistribution public\nsource s\nuses q\n"
                         "key i int -\nkey s string -\nkey f float -\nkey a int -\nkey no int -\n"
                         "derive o.f day_seconds time_ms\nderive o.a any q.x q.y\nderive o.no not q.x\n"
                         "derive o.i parse_int uid\nderive o.s text_of q.n\n");
            gt::Entity de;
            de.fields["time_ms"] = gt::Value::of_int(-1);
            de.fields["q.y"] = gt::Value::of_int(0);
            de.fields["uid"] = gt::Value::of_string("-12");
            de.fields["q.n"] = gt::Value::of_int(-7);
            d.complete(de);
            check(de.fields.at("o.f").f == 86399.999 && de.fields.at("o.a").i == 0 && de.fields.count("o.no") == 0 &&
                      de.fields.at("o.i").i == -12 && de.fields.at("o.s").s == "-7",
                  "day_seconds before 1970, any of the present arguments, parse_int and text_of");
            gt::Entity de2;
            de2.fields["uid"] = gt::Value::of_string("track-12");
            de2.fields["q.x"] = gt::Value::of_int(3);
            d.complete(de2);
            check(de2.fields.count("o.i") == 0 && de2.fields.at("o.a").i == 1 && de2.fields.at("o.no").i == 0 &&
                      de2.fields.count("o.f") == 0,
                  "parse_int of text that is not an integer leaves the target absent; any with one argument present");
            // 0.8 ruling 28: parse_int accepts an optional '-' and then digits,
            // leading zeros included, within 64 bits
            const std::int64_t kMax = 9223372036854775807;
            const std::pair<const char*, std::int64_t> ints[] = {
                {"0", 0}, {"007", 7}, {"-007", -7}, {"-0", 0}, {"9223372036854775807", kMax},
                {"-9223372036854775808", -kMax - 1}, {"0009223372036854775807", kMax}};
            for (const auto& c : ints) {
                gt::Entity pe;
                pe.fields["uid"] = gt::Value::of_string(c.first);
                d.complete(pe);
                check(pe.fields.count("o.i") == 1 && pe.fields.at("o.i").i == c.second, std::string("parse_int of \"") + c.first + "\"");
            }
            for (const char* text : {"", "-", "+5", " 5", "5 ", "1e3", "--5", "5-", "1.0", "0x10", "9223372036854775808",
                                     "-9223372036854775809", "99999999999999999999999"}) {
                gt::Entity pe;
                pe.fields["uid"] = gt::Value::of_string(text);
                d.complete(pe);
                check(pe.fields.count("o.i") == 0, std::string("parse_int of \"") + text + "\" leaves the target absent");
            }
        } catch (const std::exception& ex) {
            check(false, std::string("0.8 behaviour threw: ") + ex.what());
        }
    }

    // Engine::load_packs: only the packs named, with the modules they need.
    {
        namespace fs = std::filesystem;
        const fs::path dir = fs::temp_directory_path() /
                             ("goat-transformers-unit-" +
                              std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
        try {
            auto put = [&](const fs::path& rel, const std::string& text) {
                fs::create_directories((dir / rel).parent_path());
                std::ofstream out(dir / rel, std::ios::binary);
                out << text;
            };
            const std::string mh = "version 0.1.0\ndistribution public\nsource s\n";
            put("model/core.def", "module core\n" + mh + "key uid string -\n");
            put("model/base.def", "module base\n" + mh + "key n int -\n");
            // The file name is not the module name: a module is found by its `module` line.
            put("model/zz-file.def", "module top\n" + mh + "uses base\nkey m int -\nderive top.m copy base.n\n");
            put("model/side.def", "module side\nversion 0.1.0\ndistribution controlled\nsource s\nkey k int -\n");
            put("packs/a/pack.def", HDR "format fmt-a\nwire json\nfield uid id string\n");
            put("packs/b/pack.def", HDR "format fmt-b\nuses top\nwire json\nfield uid id string\nfield top.m m int\n");
            put("packs/c/pack.def", "distribution controlled\nsource s\nformat fmt-c\nversion 1\nuses side\nwire json\nfield side.k k int\n");
            const std::string packs = (dir / "packs").string();

            gt::Engine all = gt::Engine::load(packs);
            check(all.formats() == std::vector<std::string>({"fmt-a", "fmt-b", "fmt-c"}) && all.modules().size() == 4,
                  "load: every pack and every module");
            gt::Engine one = gt::Engine::load_packs(packs, {"b"});
            check(one.formats() == std::vector<std::string>({"fmt-b"}), "load_packs: only the pack named");
            check(one.modules() == std::vector<std::string>({"base", "core", "top"}),
                  "load_packs: core, the modules the pack uses and the modules those use");
            eq(one.convert("fmt-b", "fmt-b", "{\"id\":\"u\",\"m\":3}"), "{\"id\":\"u\",\"m\":3}", "load_packs: the pack converts");
            gt::Engine two = gt::Engine::load_packs(packs, {"b", "a", "b"});
            check(two.formats() == std::vector<std::string>({"fmt-a", "fmt-b"}), "load_packs: several packs, a name given twice loaded once");
            check(gt::Engine::load_packs(packs, {"a"}).modules() == std::vector<std::string>({"core"}),
                  "load_packs: a pack that uses no module needs core only");
            check(gt::Engine::load_packs(packs, {}).formats().empty(), "load_packs: no name, no pack");
            // A controlled module no named pack needs is not loaded, so a public limit does not refuse it.
            expect_error(gt::ErrorKind::DistributionRefused,
                         [&] { gt::Engine::load(packs, "", gt::Distribution::Public); }, "load: a controlled module under a public limit");
            check(gt::Engine::load_packs(packs, {"a", "b"}, "", gt::Distribution::Public).formats().size() == 2,
                  "load_packs: a module no named pack needs is not loaded");
            expect_error(gt::ErrorKind::DistributionRefused,
                         [&] { gt::Engine::load_packs(packs, {"c"}, "", gt::Distribution::Public); },
                         "load_packs: the checks of a named pack still apply");
            expect_error(gt::ErrorKind::Io, [&] { gt::Engine::load_packs(packs, {"nosuch"}); }, "load_packs: a name that is not a pack");
            expect_error(gt::ErrorKind::Io, [&] { gt::Engine::load_packs(packs, {"../packs/a"}); }, "load_packs: a name is not a path");
            expect_error(gt::ErrorKind::Io, [&] { gt::Engine::load_packs(packs, {""}); }, "load_packs: an empty name");
            expect_error(gt::ErrorKind::Io, [&] { gt::Engine::load_packs(packs, {"a"}, (dir / "nomodels").string()); },
                         "load_packs: a named models directory that does not exist");
            fs::remove(dir / "model" / "base.def");
            expect_error(gt::ErrorKind::UnknownModule, [&] { gt::Engine::load_packs(packs, {"b"}); },
                         "load_packs: a needed module that no file defines");
        } catch (const std::exception& ex) {
            check(false, std::string("load_packs threw: ") + ex.what());
        }
        std::error_code ec;
        fs::remove_all(dir, ec);
    }

    // ---- 0.8 malformed input: ruling 40, and the sign of a 63- and 64-bit `twos` field
    try {
        gt::Engine m;
        m.load_model(kCoreModel, "core");
        m.load_model("module m40\nversion 0.1.0\ndistribution public\nsource \"unit test\"\n"
                     "key n int -\nkey t int -\nlist nums\n",
                     "m40");
        m.add_pack(gt::parse_pack(kXmlPack, "t-xml"));
        m.add_pack(gt::parse_pack(HDR "format r40-json\nwire json\nfield uid id string\n", "r40-json"));
        m.add_pack(gt::parse_pack(HDR "format r40-pb\nuses m40\nwire protobuf\nfield uid 1 pstring\n"
                                      "group m40.nums 3\n  field m40.n . pvarint\nend\n",
                                  "r40-pb"));
        m.add_pack(gt::parse_pack(HDR "format r40-bits\nuses m40\nwire bits\nword_bytes 8\n"
                                      "field m40.n 0:0:63 twos\nfield m40.t 1:0:64 twos\n",
                                  "r40-bits"));
        const auto malformed = [&](const char* format, const std::string& input, const std::string& what) {
            expect_error(gt::ErrorKind::MalformedWire, [&] { m.convert(format, format, input); }, what);
        };
        const auto converts = [&](const char* format, const std::string& input, const std::string& want,
                                  const std::string& what) {
            try {
                eq(m.convert(format, format, input), want, what);
            } catch (const std::exception& ex) {
                check(false, what + ": " + ex.what());
            }
        };
        const std::string nines(18, 'f');  // nine bytes 0xff

        // Hex text: space, tab, line feed and carriage return only.
        converts("r40-pb", " 0a\t01\n75\r", "0a0175", "hex: space, tab, LF and CR are skipped");
        malformed("r40-pb", "0a\v0175", "hex: a vertical tab");
        malformed("r40-pb", "0a\f0175", "hex: a form feed");
        malformed("r40-pb", std::string("0a\xC2\xA0") + "0175", "hex: a no-break space");
        malformed("r40-bits", "ffffffffffffff7f\vffffffffffffffff", "hex on bits: a vertical tab");

        // Protobuf: field number 0, wire types 3, 4, 6 and 7, a field number above 2^29-1.
        malformed("r40-pb", "0001", "protobuf: field number 0");
        malformed("r40-pb", "0b", "protobuf: wire type 3");
        malformed("r40-pb", "0c", "protobuf: wire type 4");
        malformed("r40-pb", "0e00", "protobuf: wire type 6");
        malformed("r40-pb", "0f00", "protobuf: wire type 7");
        malformed("r40-pb", "808080801000", "protobuf: field number 2^29");
        converts("r40-pb", "f8ffffff0f00", "", "protobuf: field number 2^29-1 in a field no line maps");
        // A ten-byte varint whose last byte is above 1.
        converts("r40-pb", "10" + nines + "01", "", "protobuf: a ten-byte varint with last byte 1");
        malformed("r40-pb", "10" + nines + "02", "protobuf: a ten-byte varint with last byte 2");
        malformed("r40-pb", "10" + nines + "7f", "protobuf: a ten-byte varint with last byte 0x7f");
        malformed("r40-pb", "10" + nines + "8100", "protobuf: a varint of eleven bytes");
        malformed("r40-pb", nines + "0200", "protobuf: a ten-byte tag with last byte 2");
        // A length that would wrap the cursor.
        malformed("r40-pb", "0a" + nines + "01", "protobuf: a length of 2^64-1");
        // A truncated varint inside a packed field.
        converts("r40-pb", "1a03018101", "1a03018101", "protobuf: a packed field of two varints");
        malformed("r40-pb", "1a0180", "protobuf: a packed field that ends inside a varint");
        malformed("r40-pb", "1a03010281", "protobuf: a packed field whose last varint is cut");
        malformed("r40-pb", "1a0b01" + nines + "02", "protobuf: a packed ten-byte varint with last byte 2");

        // JSON: half of a surrogate pair without its other half.
        converts("r40-json", "{\"id\":\"\\ud83d\\ude00\"}", "{\"id\":\"\xF0\x9F\x98\x80\"}", "json: a surrogate pair");
        malformed("r40-json", "{\"id\":\"\\ud83d\"}", "json: a high surrogate alone");
        malformed("r40-json", "{\"id\":\"\\ude00\"}", "json: a low surrogate alone");
        malformed("r40-json", "{\"id\":\"\\ud83dx\"}", "json: a high surrogate before a character");
        malformed("r40-json", "{\"id\":\"\\ud83d\\u0041\"}", "json: a high surrogate before another escape");
        malformed("r40-json", "{\"id\":\"\\ud83d\\ud83d\"}", "json: two high surrogates");
        malformed("r40-json", "{\"\\ud83d\":1,\"id\":\"u\"}", "json: a high surrogate alone in a member name");

        // XML: a document type declaration anywhere.
        converts("t-xml", "<?xml version=\"1.0\"?><!-- c --><event uid=\"u\"/>", "<event uid=\"u\"/>",
                 "xml: a declaration and a comment before the root");
        malformed("t-xml", "<!DOCTYPE event><event uid=\"u\"/>", "xml: a DOCTYPE before the root");
        malformed("t-xml", "<?xml version=\"1.0\"?>\n<!DOCTYPE event SYSTEM \"e.dtd\">\n<event uid=\"u\"/>",
                  "xml: a DOCTYPE with a system identifier");
        malformed("t-xml", "<!DOCTYPE event [<!ENTITY a \"b\">]><event uid=\"&a;\"/>", "xml: a DOCTYPE that declares an entity");
        malformed("t-xml", "<event uid=\"u\"/><!DOCTYPE event>", "xml: a DOCTYPE after the root");
        malformed("t-xml", "<event uid=\"u\"><!DOCTYPE event></event>", "xml: a DOCTYPE inside the root");
        malformed("t-xml", "<event uid=\"u\"><!ENTITY a \"b\"></event>", "xml: an entity declaration inside the root");
        malformed("t-xml", "<event uid=\"&a;\"/>", "xml: an entity that is not predefined");
        // Numeric character references: digits only, and a character XML 1.0 allows.
        converts("t-xml", "<event uid=\"&#65;&#x42;&#x9;&#x10FFFF;&lt;\"/>", "<event uid=\"AB&#9;\xF4\x8F\xBF\xBF&lt;\"/>",
                 "xml: decimal and hexadecimal character references");
        for (const char* ref : {"&#+65;", "&#-65;", "&#x+41;", "&#x-41;", "&# 65;", "&#;", "&#x;", "&#X41;", "&#xg;", "&#6x5;",
                                "&#0;", "&#1;", "&#8;", "&#11;", "&#x1F;", "&#xD800;", "&#xDFFF;", "&#xFFFE;", "&#xFFFF;",
                                "&#x110000;", "&#99999999999999999999;", "&#65"})
            malformed("t-xml", std::string("<event uid=\"") + ref + "\"/>", std::string("xml: the character reference ") + ref);
        malformed("t-xml", "<event uid=\"u\"><detail><remarks>&#x0;</remarks></detail></event>",
                  "xml: a character reference to U+0000 in text");

        // `twos` in 63 and in 64 bits: the sign is extended without signed overflow.
        const auto twos = [&](const std::string& input, std::int64_t n, std::int64_t t, const std::string& what) {
            try {
                const gt::Entity e = m.decode("r40-bits", input);
                const auto ni = e.fields.find("m40.n"), ti = e.fields.find("m40.t");
                check(ni != e.fields.end() && ti != e.fields.end() && ni->second.kind == gt::Value::Kind::Int &&
                          ti->second.kind == gt::Value::Kind::Int && ni->second.i == n && ti->second.i == t,
                      what);
                eq(m.convert("r40-bits", "r40-bits", input), input, what + ", written back");
            } catch (const std::exception& ex) {
                check(false, what + ": " + ex.what());
            }
        };
        twos("ffffffffffffff7fffffffffffffffff", -1, -1, "twos: -1 in 63 and in 64 bits");
        twos("00000000000000400000000000000080", -4611686018427387904LL, INT64_MIN, "twos: the least 63-bit and 64-bit values");
        twos("01000000000000400100000000000080", -4611686018427387903LL, INT64_MIN + 1, "twos: one above the least values");
        twos("ffffffffffffff3fffffffffffffff7f", 4611686018427387903LL, INT64_MAX, "twos: the greatest 63-bit and 64-bit values");
        twos("00000000000000000000000000000000", 0, 0, "twos: zero");
    } catch (const std::exception& ex) {
        check(false, std::string("ruling 40 checks threw: ") + ex.what());
    }

    // v0.14, six-bit armor: the rulings no vector pins.
    try {
        gt::Engine ae;
        ae.load_model(kCoreModel, "core");
        // Ruling 7: an `optional` field whose key has a `default` counts toward L.
        ae.add_pack(gt::parse_pack(HDR "format t-armor\nwire bits\nword_bytes 1\nbit_order msb\n"
                                       "armor sixbit\nfield a 0:0:6 uint\nfield b 0:6:6 uint optional\ndefault b 5\n",
                                   "t-armor"));
        eq(ae.convert("t-armor", "t-armor", "1"), "15", "armor: an optional field with a default is written");
        eq(ae.convert("t-armor", "t-armor", "17"), "17", "armor: an optional field present");
        // Ruling 9: a scope that writes no bit gives the empty text.
        ae.add_pack(gt::parse_pack(HDR "format t-armor0\nwire bits\nword_bytes 4\nbit_order msb\n"
                                       "armor sixbit\nfield a 0:0:6 uint optional\n",
                                   "t-armor0"));
        eq(ae.convert("t-armor0", "t-armor0", ""), "", "armor: nothing to write is the empty text");
        eq(ae.convert("t-armor0", "t-armor0", "w"), "w", "armor: one character, no whole word");
        // Ruling 8: a `length ... bytes` block is still padded to a whole byte.
        ae.add_pack(gt::parse_pack(HDR "format t-armor-seq\nwire bits\nlayout sequential\n"
                                       "bit_order msb\narmor sixbit\nfield a 6 uint\nlength 4\n  field b 6 uint\nend\n",
                                   "t-armor-seq"));
        eq(ae.convert("t-armor-seq", "t-armor-seq", "148"), "148", "armor: a length block padded to a byte");
        expect_error(gt::ErrorKind::MalformedWire, [&] { ae.convert("t-armor-seq", "t-armor-seq", "14"); },
                     "armor: a length block past the input");
    } catch (const std::exception& ex) {
        check(false, std::string("armor checks threw: ") + ex.what());
    }
    expect_error(gt::ErrorKind::BadDirective,
                 [] {
                     gt::parse_pack(HDR "format a\nwire bits\nlayout sequential\nbit_order msb\nfield a 6 uint\n"
                                        "opt\n  armor sixbit\nend\n");
                 },
                 "armor inside an opt block");
    expect_error(gt::ErrorKind::BadDirective,
                 [] {
                     gt::parse_pack(HDR "format a\nwire bits\nlayout sequential\nbit_order msb\nkind k\n"
                                        "when 6 1\narmor sixbit\n");
                 },
                 "armor after a kind, sequential");
    expect_error(gt::ErrorKind::BadDirective,
                 [] {
                     gt::parse_pack(HDR "format a\nwire bits\nword_bytes 1\nbit_order msb\n"
                                        "group items 0:0 item 6 count 1\n  armor sixbit\nend\n");
                 },
                 "armor inside a group");
    expect_error(gt::ErrorKind::BadDirective,
                 [] { gt::parse_pack(HDR "format a\nwire bits\nword_bytes 1\nfield a 0:0:12 sixbit trim swap\n"); },
                 "sixbit swap");
    expect_error(gt::ErrorKind::BadDirective,
                 [] { gt::parse_pack(HDR "format a\nwire bits\nword_bytes 1\nfield a 0:0:8 uint trim\n"); },
                 "trim on uint");
    expect_error(gt::ErrorKind::BadDirective,
                 [] { gt::parse_pack(HDR "format a\nwire bits\nlayout sequential\nfield a 1536 sixbit\n"); },
                 "sixbit 1536 bits, sequential");

    // Engine::load_tool with a licence profile (engine-spec.md 0.29).
    {
        namespace fs = std::filesystem;
        const fs::path dir = fs::temp_directory_path() /
                             ("goat-transformers-unit-licences-" +
                              std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
        try {
            auto put = [&](const fs::path& rel, const std::string& text) {
                fs::create_directories((dir / rel).parent_path());
                std::ofstream out(dir / rel, std::ios::binary);
                out << text;
            };
            auto row = [](const std::string& id, const std::string& commercial, const std::string& sa,
                          const std::string& fou, const std::string& dist) {
                return "[licences.\"" + id + "\"]\r\nname = \"" + id + "\"\r\ncommercial = \"" + commercial +
                       "\"\r\nshare_alike\t=  " + sa + "\r\nfield_of_use = " + fou + "\r\ndistribution = \"" +
                       dist + "\"\r\nattribution = true\r\n\r\n";
            };
            const std::string table = "# flags\r\n\r\n" + row("Apache-2.0", "yes", "false", "[]", "public") +
                                      row("SA", "yes", "true", "[]", "public") +
                                      row("FOU", "yes", "false", "[\"\"]", "public") +
                                      row("NC", "no", "false", "[]", "public") +
                                      row("CLOSED", "yes", "false", "[]", "controlled");
            put("licences.toml", table);
            const std::string mh = "version 0.1.0\ndistribution public\nsource s\n";
            put("model/core.def", "module core\n" + mh + "key uid string -\n");
            // REUSE-IgnoreStart: the quoted licence lines below are data
            // A `SPDX-License-Identifier =` line is passed over in a module's licence file.
            put("model/sa.def", "module sa\n" + mh + "key n int -\n");
            put("model/sa.def.license", "SPDX-License-Identifier = \"NC\"\n  SPDX-License-Identifier:\tSA\r\n");
            // Through another module: p uses q, which is NC, so p is everything.
            put("model/p.def", "module p\n" + mh + "uses q\nkey a int -\n");
            put("model/q.def", "module q\n" + mh + "key b int -\n");
            put("model/q.def.license", "SPDX-License-Identifier: NC\n");
            put("packs/plain/pack.def", HDR "format f-plain\nwire json\nfield uid id string\n");
            put("packs/sa/pack.def", HDR "format f-sa\nuses sa\nwire json\nfield uid id string\nfield sa.n n int\n");
            put("packs/fou/pack.def", HDR "format f-fou\nwire json\nfield uid id string\n");
            // A `SPDX-License-Identifier:` line is passed over in a pack's REUSE.toml.
            put("packs/fou/REUSE.toml", "SPDX-License-Identifier: NC\nSPDX-License-Identifier = \"FOU\"\n");
            put("packs/closed/pack.def", HDR "format f-closed\nwire json\nfield uid id string\n");
            put("packs/closed/REUSE.toml", "SPDX-License-Identifier=\"CLOSED\"\n");
            put("packs/uses-p/pack.def", HDR "format f-uses-p\nuses p\nwire json\nfield uid id string\n");
            // Broken, and outside `open`: skipped unread with that profile.
            put("packs/zbroken/pack.def", "this is not a pack\n");
            put("packs/zbroken/REUSE.toml", "SPDX-License-Identifier = \"NC\"\n");
            const std::string packs = (dir / "packs").string(), models = (dir / "model").string();
            auto listing = [](const gt::Engine& e) {
                std::string out;
                for (const auto& p : e.pack_licences())
                    out += p.dir + "\t" + p.format + "\t" + p.licence + "\t" + p.profile + "\n";
                return out;
            };

            gt::Engine open = gt::Engine::load_tool(packs, models, nullptr, gt::Distribution::Controlled, "open");
            check(open.formats() == std::vector<std::string>({"f-plain"}), "profile open: only the open pack");
            check(open.modules() == std::vector<std::string>({"core"}), "profile open: only the open modules");
            eq(listing(open), "plain\tf-plain\tApache-2.0\topen\n", "profile open: pack_licences");
            gt::Engine cl = gt::Engine::load_tool(packs, models, nullptr, gt::Distribution::Controlled, "open+copyleft");
            check(cl.formats() == std::vector<std::string>({"f-plain", "f-sa"}), "profile open+copyleft: the packs");
            check(cl.modules() == std::vector<std::string>({"core", "sa"}), "profile open+copyleft: the modules");
            eq(cl.convert("f-sa", "f-sa", "{\"id\":\"u\",\"n\":3}"), "{\"id\":\"u\",\"n\":3}", "profile: a held pack converts");
            expect_error(gt::ErrorKind::UnknownFormat, [&] { cl.convert("f-fou", "f-fou", "{}"); },
                         "profile: a skipped pack is unknown-format");
            // A named pack outside the profile is skipped, twice; the name checks come first.
            std::vector<std::string> twice{"zbroken", "plain", "zbroken"};
            check(gt::Engine::load_tool(packs, models, &twice, gt::Distribution::Controlled, "open").formats() ==
                      std::vector<std::string>({"f-plain"}),
                  "profile: --packs-only skips a pack outside it, twice");
            std::vector<std::string> missing{"nope"};
            expect_error(gt::ErrorKind::UnknownFormat,
                         [&] { gt::Engine::load_tool(packs, models, &missing, gt::Distribution::Controlled, "open"); },
                         "profile: the name checks come first");
            expect_error(gt::ErrorKind::UnknownDirective,
                         [&] { gt::Engine::load_tool(packs, models, nullptr, gt::Distribution::Controlled, "everything"); },
                         "profile everything: the broken pack is held and fails");
            expect_error(gt::ErrorKind::BadLicence,
                         [&] { gt::Engine::load_tool(packs + "/none", models + "/none", nullptr, gt::Distribution::Controlled, "Open"); },
                         "a profile that is no profile is bad-licence before anything is read");
            check(gt::Engine::is_profile("open+copyleft") && !gt::Engine::is_profile("") && !gt::Engine::is_profile("none"),
                  "is_profile");

            // No profile: no licence file read, nothing in pack_licences; with
            // read_licences every pack is held and listed.
            fs::remove(dir / "packs/zbroken/pack.def");
            fs::remove(dir / "packs/zbroken/REUSE.toml");
            fs::remove(dir / "packs/zbroken");
            gt::Engine none = gt::Engine::load_tool(packs, models, nullptr);
            check(none.formats().size() == 5 && none.pack_licences().empty(), "no profile: every pack, no licence read");
            gt::Engine all = gt::Engine::load_tool(packs, models, nullptr, gt::Distribution::Controlled, std::nullopt, true);
            eq(listing(all),
               "closed\tf-closed\tCLOSED\tnone\nfou\tf-fou\tFOU\teverything\nplain\tf-plain\tApache-2.0\topen\n"
               "sa\tf-sa\tApache-2.0\topen+copyleft\nuses-p\tf-uses-p\tApache-2.0\teverything\n",
               "read_licences: every pack with its licence and profile");

            // Files that cannot be read as ruling 1 says.
            auto bad_licence = [&](const std::string& what) {
                expect_error(gt::ErrorKind::BadLicence,
                             [&] { gt::Engine::load_tool(packs, models, nullptr, gt::Distribution::Controlled, "everything"); },
                             what);
            };
            put("packs/plain/REUSE.toml", "\xEF\xBB\xBFSPDX-License-Identifier = \"Apache-2.0\"\n");
            bad_licence("a licence line after a byte-order mark is no licence line");
            put("packs/plain/REUSE.toml", "SPDX-License-Identifier = \"A\"\nSPDX-License-Identifier = \"B\"\n");
            bad_licence("two licence lines");
            put("packs/plain/REUSE.toml", "SPDX-License-Identifier = Apache-2.0\n");
            bad_licence("a licence line without quotes");
            put("packs/plain/REUSE.toml", "SPDX-License-Identifier = \"Apache-2.0\"\n");
            put("model/sa.def.license", "SPDX-License-Identifier:SA\n");
            bad_licence("a module licence line with no space after the colon");
            put("model/sa.def.license", "SPDX-License-Identifier: \xFF\n");
            bad_licence("a module licence file that is not UTF-8");
            put("model/sa.def.license", "SPDX-License-Identifier: SA\n");
            // REUSE-IgnoreEnd
            put("licences.toml", table + "[licences.\"X\"]\ncommercial = \"yes\"\nshare_alike = false\n"
                                         "field_of_use = [ ]\ndistribution = \"public\"\n");
            bad_licence("field_of_use = [ ]");
            put("licences.toml", table + row("SA", "yes", "true", "[]", "public"));
            bad_licence("a second row of one licence");
            put("licences.toml", table + "[licences.\"X\"]\ncommercial = \"yes\"\nshare_alike = false\nfield_of_use = []\n");
            bad_licence("a row without distribution");
            put("licences.toml", table + "[licences.\"X\"]\ncommercial = \"yes\" # c\n");
            bad_licence("a value followed by a comment");
            fs::remove(dir / "licences.toml");
            fs::create_directories(dir / "licences.toml");
            bad_licence("licences.toml is a directory");
            fs::remove(dir / "licences.toml");
            // No table: Apache-2.0 alone is known, so `sa` (licence SA) is everything.
            eq(listing(gt::Engine::load_tool(packs, models, nullptr, gt::Distribution::Controlled, "everything")),
               "closed\tf-closed\tCLOSED\teverything\nfou\tf-fou\tFOU\teverything\nplain\tf-plain\tApache-2.0\topen\n"
               "sa\tf-sa\tApache-2.0\teverything\nuses-p\tf-uses-p\tApache-2.0\teverything\n",
               "no licences.toml: the table of Apache-2.0 alone");
        } catch (const std::exception& ex) {
            check(false, std::string("0.29 licence profiles threw: ") + ex.what());
        }
        std::error_code ec;
        fs::remove_all(dir, ec);
    }

    // v0.34: checks made where an `inner` line is reached that no vector pins,
    // and the two orders of kind selection.
    try {
        const std::string model =
            "module core\nversion 0.1.0\ndistribution public\nsource \"unit test\"\nkey a int -\nkey b int -\n";
        const std::string seq = "wire bits\nlayout sequential\nbit_order msb\n";
        auto pack = [](const std::string& format, const std::string& dist, const std::string& body) {
            return "format " + format + "\nversion 0.1.0\ndistribution " + dist + "\nsource \"unit test\"\n" + body;
        };
        gt::Engine eng;
        eng.load_model(model);
        eng.add_pack(gt::parse_pack(pack("in-k", "public", seq + "kind p\nwhen 8 1\nrequires b\nfield b 8 uint\n"
                                                                 "kind q\nwhen 8 2\nrequires b\nfield b 16 uint\n")));
        eng.add_pack(gt::parse_pack(pack("in-c", "controlled", seq + "field b 8 uint\n")));
        eng.add_pack(gt::parse_pack(pack("out-pub", "public", seq + "field a 8 uint\ninner in-c\n")));
        eng.add_pack(gt::parse_pack(pack("out-ctl", "controlled", seq + "field a 8 uint\ninner in-c\n")));
        eng.add_pack(gt::parse_pack(pack("out-k", "public", seq + "field a 8 uint\ninner in-k\n")));
        expect_error(gt::ErrorKind::DistributionViolation, [&] { (void)eng.decode("out-pub", "0102"); },
                     "0.34: a public outer pack whose inner pack is controlled, on decode");
        expect_error(gt::ErrorKind::DistributionViolation, [&] { (void)eng.convert("out-ctl", "out-pub", "0102"); },
                     "0.34: a public outer pack whose inner pack is controlled, on encode");
        eq(eng.convert("out-ctl", "out-ctl", "0102"), "0102", "0.34: a controlled outer pack, a controlled inner pack");
        check(eng.model_keys("out-pub") == std::vector<std::string>{"a"},
              "0.34: an inner line that fails its checks adds no keys");
        gt::Entity e = eng.decode("out-k", "09020005");
        check(e.inner_kind == std::make_pair(std::string("in-k"), std::string("q")) && e.kind.second.empty(),
              "0.34: Entity.inner_kind after decode");
        eq(eng.encode("in-k", e), "020005", "0.34: a top-level encode selects by Entity.inner_kind naming the format");
        e.kind = {"in-k", "p"};
        eq(eng.encode("in-k", e), "0105", "0.34: a top-level encode selects by Entity.kind first");
        eq(eng.encode("out-k", e), "09020005", "0.34: an inner line selects by Entity.inner_kind first");
        e.inner_kind = {};
        eq(eng.encode("out-k", e), "090105", "0.34: an inner line selects by Entity.kind next");
        e.kind = {"in-k", "r"};
        expect_error(gt::ErrorKind::NoKind, [&] { (void)eng.encode("out-k", e); },
                     "0.34: a named kind the inner pack does not have");
    } catch (const std::exception& ex) {
        check(false, std::string("0.34 inner lines threw: ") + ex.what());
    }

    std::cout << "unit: " << checks << " checks, " << failures << " failed\n";
    return failures == 0 ? 0 : 1;
}
