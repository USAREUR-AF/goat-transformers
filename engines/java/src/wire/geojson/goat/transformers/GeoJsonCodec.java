package goat.transformers;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * The {@code geojson} wire: a Feature with a Point geometry. Locators: {@code geometry.lon|lat|alt},
 * {@code properties.<name>}, {@code <name>} (top-level member). Residue is text, as in version 0.1: a string
 * member's value, a number's text as written, {@code true} or {@code false}, and the JSON text of anything else.
 * It is written back as a JSON string; an unmapped coordinate slot is written back as the number it was.
 */
final class GeoJsonCodec extends Codec<GeoJsonCodec.Doc> {

    /** Group items are read and written as the {@code json} wire does, with this wire's value types. */
    private final Items items;

    /**
     * The items of a group: the lines of its body read and written as on the {@code json} wire (through
     * {@link JsonTree}), each value as this wire reads and writes it (ruling 7 of 0.7).
     */
    private static final class Items extends JsonTree<Object> {
        Items(Pack pack) { super(pack); }

        @Override
        Object readValue(Transform t, Object v) { return decodeGeo(t, v); }

        @Override
        Object encodeOne(Pack.Field f, Entity e, Pack.Scope scope) {
            String s = encodeField(f, e, scope);
            return s == null ? null : jsonValue(f.transform, s);
        }

        // An Items codec reads and writes group items only; the message is GeoJsonCodec's.
        @Override
        Object parse(String text) { throw new IllegalStateException(); }

        @Override
        boolean holds(Object wire, Pack.When when) { throw new IllegalStateException(); }

        @Override
        Entity decodeKind(Object wire, Pack.Kind kind) { throw new IllegalStateException(); }

        @Override
        String encodeKind(Entity e, Pack.Kind kind) { throw new IllegalStateException(); }
    }

    GeoJsonCodec(Pack pack) {
        super(pack);
        items = new Items(pack);
        for (Pack.Kind k : pack.kinds) {
            for (Pack.Group g : k.scope.groups) JsonTree.prepare(g.body);
        }
    }

    /** A JSON value as the text this wire's transforms read. Throws IllegalArgumentException when it has none. */
    static String rawText(Object v, Transform t) {
        if (v instanceof String) return (String) v;
        if (v instanceof Json.Num) return ((Json.Num) v).text;
        if (v instanceof Boolean) return v.toString();
        if (t == Transform.STRING) return Json.write(v);
        throw new IllegalArgumentException("value is not a scalar");
    }

    /**
     * A member's model value: a JSON number through {@code int} or {@code float} is read as the {@code json} wire
     * reads it (ruling 2d of 0.11); any other value through its text (a JSON string by rulings 2a and 2b).
     */
    static Object decodeGeo(Transform t, Object v) {
        if (v instanceof Json.Num && (t == Transform.INT || t == Transform.FLOAT)) return JsonTree.decodeValue(t, v);
        return t.decode(rawText(v, t));
    }

    /** A parsed Feature: its top-level members, its Point coordinates (or null) and its properties (or null). */
    static final class Doc {
        Map<String, Object> feat;
        List<Object> coords;
        Map<String, Object> props;
    }

    @Override
    @SuppressWarnings("unchecked")
    Doc parse(String text) {
        Object doc;
        try {
            doc = Json.parse(text, true);   // ruling 22 of 0.5 is for the json wire; geojson keeps its 0.1 behaviour
        } catch (Json.ParseException ex) {
            throw malformed(ex.getMessage());
        }
        if (!(doc instanceof Map)) throw malformed("top level is not a JSON object");
        Doc d = new Doc();
        d.feat = (Map<String, Object>) doc;
        if (!"Feature".equals(d.feat.get("type"))) throw malformed("\"type\" is not \"Feature\"");
        Object g = d.feat.get("geometry");
        if (g instanceof Map) {
            Map<String, Object> geom = (Map<String, Object>) g;
            if (!"Point".equals(geom.get("type"))) throw malformed("geometry type is not \"Point\"");
            Object c = geom.get("coordinates");
            if (!(c instanceof List)) throw malformed("Point coordinates is not an array");
            d.coords = (List<Object>) c;
            if (d.coords.size() < 2) throw malformed("Point coordinates needs at least [lon, lat]");
            for (Object o : d.coords) if (!(o instanceof Json.Num)) throw malformed("Point coordinate is not a number");
        } else if (g != null && g != Json.NULL) {
            throw malformed("geometry is not an object or null");
        }
        Object p = d.feat.get("properties");
        if (p instanceof Map) d.props = (Map<String, Object>) p;
        else if (p != null && p != Json.NULL) throw malformed("properties is not an object or null");
        return d;
    }

    /** The JSON value at a locator, or null when the member is absent or {@code null}. */
    private static Object member(Doc d, String locator) {
        Object v;
        int ci = Locators.geojsonCoord(locator);
        if (ci >= 0) {
            v = (d.coords != null && ci < d.coords.size()) ? d.coords.get(ci) : null;
        } else if (locator.startsWith("properties.")) {
            v = d.props == null ? null : d.props.get(locator.substring("properties.".length()));
        } else {
            v = d.feat.get(locator);
        }
        return v == Json.NULL ? null : v;
    }

    @Override
    boolean holds(Doc d, Pack.When when) {
        return Json.holds(member(d, when.locator), when);
    }

    @Override
    Entity decodeKind(Doc d, Pack.Kind kind) {
        Entity e = new Entity();
        Failures fails = new Failures();
        Set<String> mapped = new HashSet<>();
        for (Pack.Line l : kind.lines) {
            if (l instanceof Pack.Group) {
                mapped.add(l.locator);
                Pack.Group g = (Pack.Group) l;
                Object v = member(d, g.locator);
                if (v == null) continue;                    // absent or null: the list is absent
                e.putList(g.list, items.decodeItems(g, v, fails));
                continue;
            }
            if (!(l instanceof Pack.Field)) {
                // `when <locator> present` does not map the member (ruling 27 of 0.5); a value or a const does.
                if (!((Pack.When) l).present) mapped.add(l.locator);
                continue;
            }
            mapped.add(l.locator);
            Pack.Field f = (Pack.Field) l;
            if (e.get(f.key) != null) continue;         // an earlier line already gave the key its value
            Object v = member(d, f.locator);
            if (v == null) continue;
            // a string's text, or a number's (also a coordinate's) or boolean's canonical text (rulings 9 and 10 of 0.9)
            if (f.absent != null && f.absent.matches(Sentinels.jsonRaw(v))) continue;
            Object dv;
            try {
                if (f.scale != null) {
                    // scale and iscale refuse a string member (ruling 23 of 0.15); iscale reads the text as written
                    if (!(v instanceof Json.Num)) throw new IllegalArgumentException(f.scale.wireName() + " needs a JSON number");
                    dv = f.scale.decode(((Json.Num) v).text);
                } else {
                    dv = decodeGeo(f.transform, v);
                }
            } catch (IllegalArgumentException ex) {
                fails.add(f, ex.getMessage(), e);
                continue;
            }
            putDecoded(f, dv, e, fails);
        }
        // residue: unmapped coordinate slots, properties members and top-level members
        List<Object> coords = d.coords;
        if (coords != null) {
            for (int i = 0; i < Math.min(3, coords.size()); i++) {
                String loc = "geometry." + Locators.GEOJSON_COORD[i];
                if (!mapped.contains(loc)) e.putResidue(pack.format, loc, Json.write(coords.get(i)));
            }
        }
        if (d.props != null) {
            for (Map.Entry<String, Object> m : d.props.entrySet()) {
                String loc = "properties." + m.getKey();
                if (!mapped.contains(loc)) residue(e, loc, m.getValue());
            }
        }
        for (Map.Entry<String, Object> m : d.feat.entrySet()) {
            if (Locators.GEOJSON_RESERVED.contains(m.getKey()) || mapped.contains(m.getKey())) continue;
            residue(e, m.getKey(), m.getValue());
        }
        finishDecode(e, fails);
        return e;
    }

    /**
     * Record one unmapped member (ruling 13 of 0.6): a string as it is and a number as its text as written, both
     * coming back as strings; an array or object as its JSON text, coming back as it was; {@code null} dropped.
     */
    private void residue(Entity e, String loc, Object v) {
        if (v == null || v == Json.NULL) return;
        if (v instanceof String) {
            e.putResidue(pack.format, loc, (String) v);
        } else if (v instanceof Json.Num) {
            e.putResidue(pack.format, loc, ((Json.Num) v).text);
        } else {
            e.putResidue(pack.format, loc, Json.write(v));
            if (v instanceof Map || v instanceof List) e.markRawResidue(pack.format, loc);
        }
    }

    /** Write {@code v} unless the member holds a value; a sentinel there is replaced in its place. */
    private static void putOver(Map<String, Object> m, String name, Object v) {
        Object have = m.get(name);
        if (have == null || have == JsonTree.RESERVED || have == JsonTree.NULLED || have instanceof JsonTree.Placed) m.put(name, v);
    }

    /** Write {@code v} unless the member holds a value or a sentinel; a reserved place is filled. */
    private static void putFirst(Map<String, Object> m, String name, Object v) {
        Object have = m.get(name);
        if (have == null || have == JsonTree.RESERVED || have == JsonTree.NULLED) m.put(name, v);
    }

    static Object jsonValue(Transform t, String s) {
        switch (t) {
            case FLOAT:
            case INT:
                return new Json.Num(s);
            default:
                return s;
        }
    }

    @Override
    String encodeKind(Entity e, Pack.Kind kind) {
        Object[] coord = new Object[3];
        LinkedHashMap<String, Object> props = new LinkedHashMap<>();
        LinkedHashMap<String, Object> top = new LinkedHashMap<>();
        for (Pack.Line l : kind.lines) {
            int ci = Locators.geojsonCoord(l.locator);
            // A when or const value is written over any field, at the position of the first line naming the locator.
            Pack.When w = kind.fixed.get(l.locator);
            if (w != null) {
                Object jv = Json.whenValue(w);
                if (ci >= 0) {
                    if (!(jv instanceof Json.Num)) {
                        throw new GtException(GtException.Code.TRANSFORM_ENCODE, pack.format, l.locator,
                                "when value " + w.value + " is not a number, and a coordinate must be one");
                    }
                    coord[ci] = jv;
                } else if (l.locator.startsWith("properties.")) {
                    props.put(l.locator.substring("properties.".length()), jv);
                } else {
                    top.put(l.locator, jv);
                }
                checkHeldRange(l, e);   // ruling 9 of 0.56
                continue;
            }
            if (l instanceof Pack.When) continue;        // nothing is written for `present`
            if (l instanceof Pack.Group) {
                Pack.Group g = (Pack.Group) l;
                List<Entity> list = e.list(g.list);
                if (list == null) continue;              // an absent list writes nothing
                List<Object> arr = items.encodeItems(g, list);
                if (l.locator.startsWith("properties.")) putFirst(props, l.locator.substring("properties.".length()), arr);
                else putFirst(top, l.locator, arr);
                continue;
            }
            Pack.Field f = (Pack.Field) l;
            String s = encodeField(f, e, kind.scope);
            if (s == null) {
                // the first sentinel of an absent key, in place until a line whose key is present writes (ruling 16 of 0.9)
                if (!f.writesSentinel() || f.suppressed(e)) {
                    // null (engine-spec 0.56): the member is written null unless a line on it writes a value
                    if (ci < 0 && f.out.nul && !f.suppressed(e)) {
                        if (l.locator.startsWith("properties.")) putFirst(props, l.locator.substring("properties.".length()), JsonTree.NULLED);
                        else putFirst(top, l.locator, JsonTree.NULLED);
                        continue;
                    }
                    // the member's place, should a later line on the locator write it (ruling 23 of 0.9, ruling 1 of 0.18)
                    if (ci < 0 && l.locator.startsWith("properties.")) props.putIfAbsent(l.locator.substring("properties.".length()), JsonTree.RESERVED);
                    else if (ci < 0) top.putIfAbsent(l.locator, JsonTree.RESERVED);
                    continue;
                }
                Object jv = f.absent.firstJson();
                if (ci >= 0) {
                    if (coord[ci] != null) continue;
                    if (!(jv instanceof Json.Num)) {
                        throw new GtException(GtException.Code.TRANSFORM_ENCODE, pack.format, l.locator,
                                "sentinel " + f.absent.firstText() + " is not a number, and a coordinate must be one");
                    }
                    coord[ci] = new JsonTree.Placed(jv);   // counts as a value for ruling 5 of 0.1.1 (ruling 10 of 0.9)
                } else if (l.locator.startsWith("properties.")) {
                    putFirst(props, l.locator.substring("properties.".length()), new JsonTree.Placed(jv));
                } else {
                    putFirst(top, l.locator, new JsonTree.Placed(jv));
                }
                continue;
            }
            Object jv = jsonValue(f.transform, s);
            // putIfAbsent: an earlier line on the same locator has precedence, a sentinel does not
            if (ci >= 0) {
                if (coord[ci] != null && !(coord[ci] instanceof JsonTree.Placed)) continue;
                if (f.transform == Transform.FLOAT || f.transform == Transform.INT) coord[ci] = jv;
                else {
                    try {
                        coord[ci] = new Json.Num(Transform.formatDouble(Transform.asDouble(s)));
                    } catch (IllegalArgumentException ex) {
                        throw encodeFailure(f, ex);
                    }
                }
            } else if (l.locator.startsWith("properties.")) {
                putOver(props, l.locator.substring("properties.".length()), jv);
            } else {
                putOver(top, l.locator, jv);
            }
        }
        for (Map.Entry<String, String> r : e.residue(pack.format).entrySet()) {
            String loc = r.getKey();
            int ci = Locators.geojsonCoord(loc);
            if (ci >= 0) {
                if (coord[ci] == null) coord[ci] = new Json.Raw(r.getValue());
            } else {
                Object v = e.isRawResidue(pack.format, loc) ? new Json.Raw(r.getValue()) : r.getValue();
                if (loc.startsWith("properties.")) props.putIfAbsent(loc.substring("properties.".length()), v);
                else top.putIfAbsent(loc, v);
            }
        }
        JsonTree.unplace(props);
        JsonTree.unplace(top);
        for (int i = 0; i < 3; i++) if (coord[i] instanceof JsonTree.Placed) coord[i] = ((JsonTree.Placed) coord[i]).v;
        LinkedHashMap<String, Object> out = new LinkedHashMap<>();
        out.put("type", "Feature");
        if (coord[0] != null && coord[1] != null) {
            List<Object> c = new ArrayList<>();
            c.add(coord[0]);
            c.add(coord[1]);
            if (coord[2] != null) c.add(coord[2]);
            LinkedHashMap<String, Object> geom = new LinkedHashMap<>();
            geom.put("type", "Point");
            geom.put("coordinates", c);
            out.put("geometry", geom);
        } else {
            out.put("geometry", Json.NULL);
        }
        out.put("properties", props);
        out.putAll(top);
        return Json.write(out);
    }
}
