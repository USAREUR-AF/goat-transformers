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
    private static final String[] COORD = {"lon", "lat", "alt"};
    private static final Set<String> RESERVED = Set.of("type", "geometry", "properties");

    /** Group items are read and written as the {@code json} wire does, with this wire's value types. */
    private final JsonCodec items;

    GeoJsonCodec(Pack pack) {
        super(pack);
        items = new JsonCodec(pack, true);
        for (Pack.Kind k : pack.kinds) {
            for (Pack.Group g : k.scope.groups) JsonCodec.prepare(g.body);
        }
    }

    /** Null when {@code locator} names a member a group may map: {@code properties.<name>} or a top-level member. */
    static String checkGroupLocator(String locator) {
        if (locator.startsWith("geometry.") || locator.equals("geometry")) {
            return "a geojson group is a properties.<name> member or a top-level member: " + locator;
        }
        return checkFieldLocator(locator);
    }

    /** A JSON value as the text this wire's transforms read. Throws IllegalArgumentException when it has none. */
    static String rawText(Object v, Transform t) {
        if (v instanceof String) return (String) v;
        if (v instanceof Json.Num) return ((Json.Num) v).text;
        if (v instanceof Boolean) return v.toString();
        if (t == Transform.STRING) return Json.write(v);
        throw new IllegalArgumentException("value is not a scalar");
    }

    static int coordIndex(String locator) {
        for (int i = 0; i < COORD.length; i++) if (locator.equals("geometry." + COORD[i])) return i;
        return -1;
    }

    static String checkFieldLocator(String locator) {
        if (coordIndex(locator) >= 0) return null;
        if (locator.startsWith("properties.")) {
            return locator.length() > "properties.".length() ? null : "empty properties member name";
        }
        if (locator.startsWith("geometry.")) return "geometry locator must be geometry.lon, geometry.lat or geometry.alt: " + locator;
        if (locator.isEmpty() || locator.contains(".")) return "bad geojson locator: " + locator;
        if (RESERVED.contains(locator)) return "top-level member \"" + locator + "\" is reserved by GeoJSON";
        return null;
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
        int ci = coordIndex(locator);
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
                e.putList(g.list, items.decodeItems(g, v, fails, true));
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
            String raw;
            try {
                raw = rawText(v, f.transform);
            } catch (IllegalArgumentException ex) {
                fails.add(f, ex.getMessage(), e);
                continue;
            }
            decodeField(f, raw, e, fails);
        }
        // residue: unmapped coordinate slots, properties members and top-level members
        List<Object> coords = d.coords;
        if (coords != null) {
            for (int i = 0; i < Math.min(3, coords.size()); i++) {
                String loc = "geometry." + COORD[i];
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
            if (RESERVED.contains(m.getKey()) || mapped.contains(m.getKey())) continue;
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
            int ci = coordIndex(l.locator);
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
                continue;
            }
            if (l instanceof Pack.When) continue;        // nothing is written for `present`
            if (l instanceof Pack.Group) {
                Pack.Group g = (Pack.Group) l;
                List<Entity> list = e.list(g.list);
                if (list == null) continue;              // an absent list writes nothing
                List<Object> arr = items.encodeItems(g, list, true);
                if (l.locator.startsWith("properties.")) props.putIfAbsent(l.locator.substring("properties.".length()), arr);
                else top.putIfAbsent(l.locator, arr);
                continue;
            }
            Pack.Field f = (Pack.Field) l;
            String s = encodeField(f, e, kind.scope);
            if (s == null) continue;
            Object jv = jsonValue(f.transform, s);
            // putIfAbsent: an earlier line on the same locator has precedence
            if (ci >= 0) {
                if (coord[ci] != null) continue;
                if (f.transform == Transform.FLOAT || f.transform == Transform.INT) coord[ci] = jv;
                else {
                    try {
                        coord[ci] = new Json.Num(Transform.formatDouble(Transform.asDouble(s)));
                    } catch (IllegalArgumentException ex) {
                        throw encodeFailure(f, ex);
                    }
                }
            } else if (l.locator.startsWith("properties.")) {
                props.putIfAbsent(l.locator.substring("properties.".length()), jv);
            } else {
                top.putIfAbsent(l.locator, jv);
            }
        }
        for (Map.Entry<String, String> r : e.residue(pack.format).entrySet()) {
            String loc = r.getKey();
            int ci = coordIndex(loc);
            if (ci >= 0) {
                if (coord[ci] == null) coord[ci] = new Json.Raw(r.getValue());
            } else {
                Object v = e.isRawResidue(pack.format, loc) ? new Json.Raw(r.getValue()) : r.getValue();
                if (loc.startsWith("properties.")) props.putIfAbsent(loc.substring("properties.".length()), v);
                else top.putIfAbsent(loc, v);
            }
        }
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
