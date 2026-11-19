package goat.transformers;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * The {@code json} wire: the message is one JSON object. A locator is one or more member names separated by
 * {@code .}; each name but the last addresses a nested object. Residue is every unmapped scalar member at any
 * depth of nested objects, keyed by its path, holding its canonical JSON text.
 */
final class JsonCodec extends Codec<Map<String, Object>> {
    JsonCodec(Pack pack) {
        super(pack);
        for (Pack.Kind k : pack.kinds) prepare(k.scope);
    }

    /** For the {@code geojson} codec: the item logic of this wire over that pack's group bodies. */
    JsonCodec(Pack pack, boolean itemsOnly) { super(pack); }

    private static final String[] ITSELF = new String[0];

    /** Split every locator of the scope into its member names; {@code .} (the item itself) is the empty path. */
    static void prepare(Pack.Scope scope) {
        for (Pack.Line l : scope.lines) {
            if (l.loc != null) continue;                 // a common line, already done for another kind
            l.loc = l.locator.equals(".") ? ITSELF : l.locator.split("\\.", -1);
            if (l instanceof Pack.Group) prepare(((Pack.Group) l).body);
        }
    }

    /** Null when {@code locator} is a valid json path, else the reason. */
    static String checkLocator(String locator) {
        if (locator.isEmpty()) return "empty json path";
        for (String seg : locator.split("\\.", -1)) {
            if (seg.isEmpty()) return "json path has an empty member name: " + locator;
        }
        return null;
    }

    @Override
    @SuppressWarnings("unchecked")
    Map<String, Object> parse(String text) {
        Object doc;
        try {
            doc = Json.parse(text);
        } catch (Json.ParseException ex) {
            throw malformed(ex.getMessage());
        }
        if (!(doc instanceof Map)) throw malformed("top level is not a JSON object");
        return (Map<String, Object>) doc;
    }

    /** The value at a path, or null when a member on the way is absent, {@code null} or not an object. */
    @SuppressWarnings("unchecked")
    static Object member(Map<String, Object> top, String[] path) {
        Map<String, Object> cur = top;
        for (int i = 0; i < path.length; i++) {
            Object v = cur.get(path[i]);
            if (v == null || v == Json.NULL) return null;
            if (i == path.length - 1) return v;
            if (!(v instanceof Map)) return null;
            cur = (Map<String, Object>) v;
        }
        return null;
    }

    @Override
    boolean holds(Map<String, Object> top, Pack.When when) {
        return Json.holds(member(top, (String[]) when.loc), when);
    }

    private static String typeName(Object v) {
        if (v instanceof String) return "a string";
        if (v instanceof Json.Num) return "a number";
        if (v instanceof Boolean) return "a boolean";
        if (v instanceof Map) return "an object";
        return "an array";
    }

    /** One JSON value to its model value. Throws IllegalArgumentException on the wrong JSON type or a bad value. */
    static Object decodeValue(Transform t, Object v) {
        switch (t) {
            case STRING:
                if (v instanceof String) return v;
                throw new IllegalArgumentException("string needs a JSON string, found " + typeName(v));
            case FLOAT:
                if (v instanceof Json.Num) {
                    double d = Double.parseDouble(((Json.Num) v).text);
                    if (!Double.isFinite(d)) throw new IllegalArgumentException("number out of range: " + v);
                    return d;
                }
                throw new IllegalArgumentException("float needs a JSON number, found " + typeName(v));
            case INT:
                if (v instanceof Json.Num) {
                    try {
                        return new BigDecimal(((Json.Num) v).text).longValueExact();
                    } catch (ArithmeticException | NumberFormatException ex) {
                        throw new IllegalArgumentException("not an integer in 64-bit range: " + v);
                    }
                }
                throw new IllegalArgumentException("int needs a JSON number, found " + typeName(v));
            case ISO8601_MS:
            case ISO8601_S:
                if (v instanceof String) return Transform.parseIso((String) v);
                throw new IllegalArgumentException(t.wireName() + " needs a JSON string, found " + typeName(v));
            case BOOL:
                if (v instanceof Boolean) return ((Boolean) v) ? 1L : 0L;
                throw new IllegalArgumentException("bool needs true or false, found " + typeName(v));
            default:
                throw new IllegalStateException(t.name());
        }
    }

    @Override
    Entity decodeKind(Map<String, Object> top, Pack.Kind kind) {
        Entity e = new Entity();
        Failures fails = new Failures();
        Set<String> mapped = new HashSet<>();
        decodeScope(top, kind.scope, e, fails, mapped, false);
        residue(top, "", mapped, e);
        finishDecode(e, fails);
        return e;
    }

    /**
     * Decode the lines of one scope from a JSON value into {@code e}: the message object, or one array element of
     * a group ({@code mapped} is then null: items carry no residue). {@code geo}: the element is an item of a
     * {@code geojson} pack, whose values are read as that wire reads them (ruling 7 of 0.7).
     */
    @SuppressWarnings("unchecked")
    void decodeScope(Object el, Pack.Scope scope, Entity e, Failures fails, Set<String> mapped, boolean geo) {
        Map<String, Object> obj = el instanceof Map ? (Map<String, Object>) el : null;
        for (Pack.Line l : scope.lines) {
            String[] path = (String[]) l.loc;
            if (l instanceof Pack.Group) {
                if (mapped != null) mapped.add(l.locator);
                Pack.Group g = (Pack.Group) l;
                Object v = obj == null ? null : member(obj, path);
                if (v == null) continue;                    // absent or null: the list is absent
                e.putList(g.list, decodeItems(g, v, fails, geo));
                continue;
            }
            if (!(l instanceof Pack.Field)) {
                // `when <locator> present` does not map the member (ruling 27 of 0.5); a value or a const does.
                if (mapped != null && !((Pack.When) l).present) mapped.add(l.locator);
                continue;
            }
            if (mapped != null) mapped.add(l.locator);
            Pack.Field f = (Pack.Field) l;
            if (e.get(f.key) != null) continue;         // an earlier line already gave the key its value
            Object v;
            if (path.length == 0) {
                v = el == Json.NULL ? null : el;
                if (v instanceof Map || v instanceof List) {
                    fails.add(f, "the item is " + typeName(v) + ", not a scalar", e);
                    continue;
                }
            } else {
                v = obj == null ? null : member(obj, path);
            }
            if (v == null) continue;                    // absent or null: the key is absent
            // a string's text, or a number's or boolean's canonical text: a sentinel yields no value (Version 0.9)
            if (f.absent != null && f.absent.matches(Sentinels.jsonRaw(v))) continue;
            Object d;
            try {
                d = geo ? GeoJsonCodec.decodeGeo(f.transform, v) : decodeValue(f.transform, v);
            } catch (IllegalArgumentException ex) {
                fails.add(f, ex.getMessage(), e);
                continue;
            }
            putDecoded(f, d, e, fails);
        }
    }

    /** The items of a group from the value at its locator: one item per array element, in order. */
    @SuppressWarnings("unchecked")
    List<Entity> decodeItems(Pack.Group g, Object v, Failures fails, boolean geo) {
        if (!(v instanceof List)) throw malformed("the member at " + g.locator + " is " + typeName(v) + ", not an array");
        List<Object> arr = (List<Object>) v;
        List<Entity> items = new ArrayList<>(arr.size());
        takeItems(arr.size());   // the array is parsed already; its items are counted before any is read
        for (Object el : arr) {
            Entity item = new Entity();
            decodeScope(el, g.body, item, fails, null, geo);
            items.add(item);
        }
        return items;
    }

    @SuppressWarnings("unchecked")
    private void residue(Map<String, Object> obj, String prefix, Set<String> mapped, Entity e) {
        for (Map.Entry<String, Object> m : obj.entrySet()) {
            String name = m.getKey();
            if (name.indexOf('.') >= 0) continue;        // not addressable: dropped
            String path = prefix.isEmpty() ? name : prefix + "." + name;
            Object v = m.getValue();
            if (v instanceof Map) {
                residue((Map<String, Object>) v, path, mapped, e);
            } else if (v instanceof String || v instanceof Boolean) {
                if (!mapped.contains(path)) e.putResidue(pack.format, path, Json.write(v));
            } else if (v instanceof Json.Num) {
                if (!mapped.contains(path)) {
                    String text;
                    try {
                        text = Json.canonNumber(((Json.Num) v).text);
                    } catch (IllegalArgumentException ex) {
                        throw malformed(ex.getMessage());
                    }
                    e.putResidue(pack.format, path, text);
                }
            }
            // arrays and null members are not carried
        }
    }

    /** A model value to its JSON value. */
    private static Object encodeValue(Transform t, Object v) {
        switch (t) {
            case STRING:
            case ISO8601_MS:
            case ISO8601_S:
                return t.encode(v);
            case FLOAT:
            case INT:
                return new Json.Num(t.encode(v));
            case BOOL:
                return t.encode(v).equals("true") ? Boolean.TRUE : Boolean.FALSE;
            default:
                throw new IllegalStateException(t.name());
        }
    }

    /**
     * The object that holds the last name of {@code path}, creating the nested objects on the way so each takes
     * the position of the first line that addresses into it. Null when a member on the way already holds a scalar.
     */
    @SuppressWarnings("unchecked")
    private static Map<String, Object> parent(Map<String, Object> top, String[] path) {
        Map<String, Object> cur = top;
        for (int i = 0; i < path.length - 1; i++) {
            Object v = cur.get(path[i]);
            if (v == null) {
                v = new LinkedHashMap<String, Object>();
                cur.put(path[i], v);
            } else if (!(v instanceof Map)) {
                return null;
            }
            cur = (Map<String, Object>) v;
        }
        return cur;
    }

    private static boolean isEmptyObject(Object v) { return v instanceof Map && ((Map<?, ?>) v).isEmpty(); }

    @Override
    String encodeKind(Entity e, Pack.Kind kind) {
        LinkedHashMap<String, Object> top = new LinkedHashMap<>();
        encodeScope(top, kind.scope, e, false);
        for (Map.Entry<String, String> r : e.residue(pack.format).entrySet()) {
            String[] path = r.getKey().split("\\.", -1);
            Map<String, Object> obj = parent(top, path);
            if (obj == null) continue;
            String last = path[path.length - 1];
            Object have = obj.get(last);
            if (have == null) obj.put(last, new Json.Raw(r.getValue()));
        }
        unplace(top);
        prune(top);
        return Json.write(top);
    }

    /** A sentinel written for an absent key: a later line whose key is present writes over it (ruling 16 of 0.9). */
    static final class Placed {
        final Object v;
        Placed(Object v) { this.v = v; }
    }

    /** Replace every {@link Placed} in the object, and in the objects nested in it, by the value it holds. */
    @SuppressWarnings("unchecked")
    static void unplace(Map<String, Object> obj) {
        for (Map.Entry<String, Object> m : obj.entrySet()) {
            Object v = m.getValue();
            if (v instanceof Placed) m.setValue(((Placed) v).v);
            else if (v instanceof Map) unplace((Map<String, Object>) v);
        }
    }

    /**
     * Write the lines of one scope into {@code top} from {@code e}. Returns the scalar a {@code .} field wrote, or
     * null when none did: the caller then writes {@code top}.
     */
    Object encodeScope(Map<String, Object> top, Pack.Scope scope, Entity e, boolean geo) {
        Object itself = null;
        for (Pack.Line l : scope.lines) {
            String[] path = (String[]) l.loc;
            if (path.length == 0) {                      // `.`: the item itself as a scalar
                Pack.Field f = (Pack.Field) l;
                if (itself != null && !(itself instanceof Placed)) continue;
                Object jv = encodeOne(f, e, scope, geo);
                if (jv != null) itself = jv;
                else if (itself == null && f.absent != null) itself = new Placed(f.absent.firstJson());
                continue;
            }
            Map<String, Object> obj = parent(top, path);
            String last = path[path.length - 1];
            if (l instanceof Pack.Group) {
                Pack.Group g = (Pack.Group) l;
                List<Entity> items = e.list(g.list);
                if (items == null || obj == null) continue;   // an absent list writes nothing
                Object have = obj.get(last);
                if (have != null && !isEmptyObject(have)) continue;
                obj.put(last, encodeItems(g, items, geo));
                continue;
            }
            // A when or const value is written over any field, at the position of the first line naming the locator.
            Pack.When w = scope.fixed.get(l.locator);
            if (w != null) {
                if (obj != null) obj.put(last, Json.whenValue(w));
                continue;
            }
            if (l instanceof Pack.When) continue;        // nothing is written for `present`
            Pack.Field f = (Pack.Field) l;
            if (obj == null) continue;
            Object have = obj.get(last);
            boolean over = have instanceof Placed;
            if (have != null && !isEmptyObject(have) && !over) continue; // an earlier line on this locator already wrote it
            Object jv = encodeOne(f, e, scope, geo);
            if (jv != null) obj.put(last, jv);
            else if (f.absent != null && !over) obj.put(last, new Placed(f.absent.firstJson()));
        }
        return itself instanceof Placed ? ((Placed) itself).v : itself;
    }

    /** The JSON value one field writes, or null when the entity lacks the key and the scope has no default. */
    private Object encodeOne(Pack.Field f, Entity e, Pack.Scope scope, boolean geo) {
        if (geo) {
            String s = encodeField(f, e, scope);
            return s == null ? null : GeoJsonCodec.jsonValue(f.transform, s);
        }
        Object v = valueToEncode(f, e, scope);
        if (v == null) return null;
        try {
            return encodeValue(f.transform, v);
        } catch (IllegalArgumentException ex) {
            throw encodeFailure(f, ex);
        }
    }

    /** The array a group writes: one element per item; an item with no members written is {@code {}}. */
    List<Object> encodeItems(Pack.Group g, List<Entity> items, boolean geo) {
        List<Object> arr = new ArrayList<>(items.size());
        for (Entity item : items) {
            LinkedHashMap<String, Object> obj = new LinkedHashMap<>();
            Object itself = encodeScope(obj, g.body, item, geo);
            unplace(obj);
            if (itself != null) {
                arr.add(itself);
            } else {
                prune(obj);
                // a scalar (`.`) item with no value is written null (ruling 11 of 0.7)
                arr.add(obj.isEmpty() && hasItself(g.body) ? Json.NULL : obj);
            }
        }
        return arr;
    }

    private static boolean hasItself(Pack.Scope body) {
        for (Pack.Line l : body.lines) if (((String[]) l.loc).length == 0) return true;
        return false;
    }

    /** Remove every nested object that has no members. */
    @SuppressWarnings("unchecked")
    private static void prune(Map<String, Object> obj) {
        Iterator<Map.Entry<String, Object>> it = obj.entrySet().iterator();
        while (it.hasNext()) {
            Object v = it.next().getValue();
            if (v instanceof Map) {
                prune((Map<String, Object>) v);
                if (((Map<String, Object>) v).isEmpty()) it.remove();
            }
            // an array is a list: it stays, also when empty, and each of its items was pruned as it was built
        }
    }
}
