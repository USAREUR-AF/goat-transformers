package goat.transformers;

import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * The {@code json} wire: the message is one JSON object. A locator is one or more member names separated by
 * {@code .}; each name but the last addresses a nested object. Residue is every unmapped scalar member at any
 * depth of nested objects, keyed by its path, holding its canonical JSON text.
 */
final class JsonCodec extends JsonTree<Map<String, Object>> {
    JsonCodec(Pack pack) {
        super(pack);
        for (Pack.Kind k : pack.kinds) prepare(k.scope);
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

    @Override
    boolean holds(Map<String, Object> top, Pack.When when) {
        return Json.holds(member(top, (String[]) when.loc), when);
    }

    @Override
    Entity decodeKind(Map<String, Object> top, Pack.Kind kind) {
        Entity e = new Entity();
        Failures fails = new Failures();
        Set<String> mapped = new HashSet<>();
        decodeScope(top, kind.scope, e, fails, mapped);
        unreadOverflow(top, fails.read);
        residue(top, "", mapped, e);
        finishDecode(e, fails);
        return e;
    }

    /**
     * A number outside the double range that no field reads, anywhere in the document (arrays, members of group
     * items and when members included), is malformed-wire (ruling 27 of 0.15).
     */
    @SuppressWarnings("unchecked")
    private void unreadOverflow(Object v, java.util.Map<Object, Boolean> read) {
        if (v instanceof Map) {
            for (Object c : ((Map<String, Object>) v).values()) unreadOverflow(c, read);
        } else if (v instanceof List) {
            for (Object c : (List<Object>) v) unreadOverflow(c, read);
        } else if (v instanceof Json.Num && !read.containsKey(v)) {
            String t = ((Json.Num) v).text;
            if (Double.isInfinite(Double.parseDouble(t))) throw malformed("number out of range: " + t);
        }
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

    @Override
    String encodeKind(Entity e, Pack.Kind kind) {
        LinkedHashMap<String, Object> top = new LinkedHashMap<>();
        encodeScope(top, kind.scope, e);
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
}
