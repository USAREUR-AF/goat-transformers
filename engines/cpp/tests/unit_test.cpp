// Unit checks for the parts the vectors exercise only partly: number formatting,
// civil-date arithmetic, pack grammar errors, residue and parsing tolerance.
#include <iostream>
#include <string>
#include <vector>

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
#define HDR "distribution public\nsource \"unit test\"\n"

// The keys the packs below map, declared so the packs pass the v0.4 load checks.
const char* kCoreModel =
    "module core\nversion 0.1.0\ndistribution public\nsource \"unit test\"\n"
    "key uid string -\nkey time_ms int ms\nkey lat float deg\nkey lon float deg\n"
    "key callsign string -\nkey remarks string -\nkey a int -\nkey b int -\nkey v float deg \"scaled\"\n";

const char* kXmlPack =
    HDR "format t-xml\nversion 0.1.0\nwire xml\nroot event\n"
    "field uid @uid string\nfield time_ms @time iso8601_ms\nfield lat point/@lat float\n"
    "field callsign detail/contact/@callsign string\nfield remarks detail/remarks/#text string\n";

const char* kGeoPack =
    HDR "format t-geo\nversion 0.1.0\nwire geojson\n"
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

    // pack grammar
    expect_error(gt::ErrorKind::UnknownDirective, [] { gt::parse_pack(HDR "format a\nwire xml\nroot r\nbogus x\n"); },
                 "unknown directive");
    expect_error(gt::ErrorKind::UnknownTransform,
                 [] { gt::parse_pack(HDR "format a\nwire xml\nroot r\nfield k @k hex\n"); }, "unknown transform");
    expect_error(gt::ErrorKind::UnknownWire, [] { gt::parse_pack(HDR "format a\nwire yaml\n"); }, "unknown wire");
    expect_error(gt::ErrorKind::InvalidPack, [] { gt::parse_pack(HDR "format a\nwire xml\n"); }, "xml without root");
    expect_error(gt::ErrorKind::InvalidLocator,
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
    expect_error(gt::ErrorKind::InvalidPack,
                 [] { gt::parse_pack(HDR "format a\nwire bits\nword_bytes 2\nfield k 0:0:8 string\n"); },
                 "text transform on bits wire");
    expect_error(gt::ErrorKind::InvalidPack, [] { gt::parse_pack(HDR "format a\nwire xml\nroot r\nfield k @k uint\n"); },
                 "bits transform on text wire");
    expect_error(gt::ErrorKind::InvalidPack, [] { gt::parse_pack(HDR "format a\nwire bits\nfield k 0:0:8 uint\n"); },
                 "bits without word_bytes");
    expect_error(gt::ErrorKind::InvalidPack,
                 [] { gt::parse_pack(HDR "format a\nwire xml\nroot r\nword_bytes 2\nfield k @k string\n"); },
                 "word_bytes on non-bits wire");
    {
        // 0.5: a field may run past the end of its word.
        gt::Pack rp = gt::parse_pack(HDR "format a\nwire bits\nword_bytes 1\nfield k 0:4:8 uint\n");
        check(rp.fields.size() == 1, "bits field may run past its word");
    }
    expect_error(gt::ErrorKind::BadDirective,
                 [] { gt::parse_pack(HDR "format a\nwire bits\nword_bytes 2\nfield k 0:0:0 uint\n"); },
                 "bits len zero");
    expect_error(gt::ErrorKind::BadDirective,
                 [] { gt::parse_pack(HDR "format a\nwire bits\nword_bytes 2\nfield k 0:0:65 uint\n"); },
                 "bits len 65 on uint");
    expect_error(gt::ErrorKind::UnknownTransform,
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
    expect_error(gt::ErrorKind::InvalidModel,
                 [] { gt::parse_model("module m\ndistribution public\nsource s\nkey a.b int -\n"); },
                 "dot in key name");
    expect_error(gt::ErrorKind::MissingDistribution, [] { gt::parse_model("module m\nsource s\n"); },
                 "module without distribution");
    expect_error(gt::ErrorKind::MissingSource, [] { gt::parse_model("module m\ndistribution public\n"); },
                 "module without source");
    expect_error(gt::ErrorKind::DuplicateKey,
                 [] { gt::parse_model("module m\ndistribution public\nsource s\nkey a int -\nkey a int -\n"); },
                 "duplicate key");
    expect_error(gt::ErrorKind::MissingDistribution, [] { gt::parse_pack("format a\nwire geojson\n"); },
                 "missing-distribution precedes missing-source");
    expect_error(gt::ErrorKind::DuplicateModule, [&] { eng.load_model(kCoreModel); }, "duplicate module");
    expect_error(gt::ErrorKind::UndeclaredKey,
                 [&] { eng.add_pack(gt::parse_pack(HDR "format u\nwire geojson\nfield nope id string\n")); },
                 "undeclared key");
    expect_error(gt::ErrorKind::KeyTypeMismatch,
                 [&] { eng.add_pack(gt::parse_pack(HDR "format u\nwire geojson\nfield lat id string\n")); },
                 "key type mismatch");
    expect_error(gt::ErrorKind::ModuleNotUsed,
                 [&] { eng.add_pack(gt::parse_pack(HDR "format u\nwire geojson\nfield x.y id string\n")); },
                 "module not used");
    expect_error(gt::ErrorKind::UnknownModule,
                 [&] { eng.add_pack(gt::parse_pack(HDR "format u\nwire geojson\nuses x\nfield x.y id string\n")); },
                 "unknown module");
    try {
        gt::parse_pack("format a\nwire geojson\n");
    } catch (const gt::Error& e) {
        check(std::string(e.what()).rfind("missing-distribution:", 0) == 0, "message begins with kind and colon");
    }
    {
        gt::Engine pub;
        pub.set_max_distribution(gt::Distribution::Public);
        expect_error(gt::ErrorKind::DistributionRefused,
                     [&] { pub.load_model("module core\ndistribution controlled\nsource s\n"); },
                     "public engine refuses controlled module");
        pub.load_model(kCoreModel);
        expect_error(gt::ErrorKind::DistributionRefused,
                     [&] {
                         pub.add_pack(gt::parse_pack(
                             "distribution controlled\nsource s\nformat c\nwire geojson\nfield uid id string\n"));
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
        expect_error(gt::ErrorKind::InvalidPack,
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
            const std::string mh = "module x\ndistribution public\nsource s\nkey a float -\nkey i int -\nkey t string -\n";
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
            check(begins(error_text([&] { gt::parse_model("module x\nsource s\nkey a float -\nderive x.a cube x.a\n"); }),
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
            check(begins(error_text([] { gt::parse_pack("format a\nwire json\nfield uid id string via t\n"); }),
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
                         "invalid_pack"),
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
            eq(r.encode("gj", made), "{\"items\":[{\"n\":1,\"k\":\"item\"},{\"name\":\"b\",\"n\":1,\"k\":\"item\"}],\"a\":{\"nums\":[{}]}}",
               "an entity built by hand; a scalar item with no value is {}");
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
                      e2.load_model("module x\nversion 0.1.0\nsource s\nkey a string -\nderive x.a copy uid\n");
                  }),
                         "bad-directive"),
                  "a derive naming a core key with core not loaded, before missing-distribution");
        } catch (const std::exception& ex) {
            check(false, std::string("0.7 behaviour threw: ") + ex.what());
        }
    }

    std::cout << "unit: " << checks << " checks, " << failures << " failed\n";
    return failures == 0 ? 0 : 1;
}
