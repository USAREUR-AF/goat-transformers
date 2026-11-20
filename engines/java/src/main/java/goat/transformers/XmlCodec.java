package goat.transformers;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * The {@code xml} wire. Locators: {@code @attr}, {@code path/@attr}, {@code path/#text}. Residue is the unmapped
 * attributes of the root element; unmapped child elements are not carried.
 */
final class XmlCodec extends Codec<Xml.Element> {
    /** Root element name to the kinds that have it, in pack order. */
    private final Map<String, List<Pack.Kind>> byRoot = new HashMap<>();

    XmlCodec(Pack pack) {
        super(pack);
        for (Pack.Kind k : pack.kinds) {
            prepare(k.scope);
            k.scope.info = elementPlan(k.scope);
            byRoot.computeIfAbsent(k.root, r -> new ArrayList<>()).add(k);
        }
    }

    private static void prepare(Pack.Scope scope) {
        for (Pack.Line l : scope.lines) {
            if (l.loc != null) continue;                 // a common line, already done for another kind
            l.loc = split(l.locator);
            if (l instanceof Pack.Group) prepare(((Pack.Group) l).body);
        }
    }

    /**
     * The {@code element} lines of a scope (engine-spec 0.18) as the elements to create before each line: each
     * element named by an {@code element} line, and each element on the way to it, is placed at the first line of
     * any kind that addresses it or a path under it (ruling 13). Line index to the paths, shorter paths first; null
     * when the scope has no {@code element} line.
     */
    private static Map<Integer, List<List<String>>> elementPlan(Pack.Scope scope) {
        java.util.LinkedHashSet<List<String>> prefixes = new java.util.LinkedHashSet<>();
        for (Pack.Line l : scope.lines) {
            if (!(l instanceof Pack.Element)) continue;
            List<String> path = ((Loc) l.loc).path;
            for (int n = 1; n <= path.size(); n++) prefixes.add(path.subList(0, n));
        }
        if (prefixes.isEmpty()) return null;
        Map<Integer, List<List<String>>> plan = new HashMap<>();
        for (List<String> p : prefixes) {
            for (int i = 0; i < scope.lines.size(); i++) {
                Pack.Line l = scope.lines.get(i);
                if (l instanceof Pack.When && ((Pack.When) l).present) continue;   // names no position (ruling 19)
                List<String> path = ((Loc) l.loc).path;
                if (path.size() >= p.size() && path.subList(0, p.size()).equals(p)) {
                    plan.computeIfAbsent(i, k -> new ArrayList<>()).add(p);
                    break;
                }
            }
        }
        for (List<List<String>> ps : plan.values()) ps.sort((a, b) -> Integer.compare(a.size(), b.size()));
        return plan;
    }

    /** Null when {@code locator} is a path of element names, as a group needs, else the reason. */
    static String checkGroupLocator(String locator) {
        for (String seg : locator.split("/", -1)) {
            if (seg.isEmpty() || seg.startsWith("@") || seg.startsWith("#")) {
                return "an xml group locator is a path of element names: " + locator;
            }
        }
        return null;
    }

    @Override
    List<Pack.Kind> candidates(Xml.Element root) {
        List<Pack.Kind> c = byRoot.get(root.name);
        return c == null ? Collections.emptyList() : c;
    }

    /** A split locator: element path under the root plus the attribute name, or text when attr is null. */
    static final class Loc {
        final List<String> path;
        final String attr;
        final boolean text;
        Loc(List<String> path, String attr, boolean text) { this.path = path; this.attr = attr; this.text = text; }
    }

    static Loc split(String locator) {
        String[] parts = locator.split("/", -1);
        String last = parts[parts.length - 1];
        if (last.startsWith("@")) return new Loc(Arrays.asList(parts).subList(0, parts.length - 1), last.substring(1), false);
        if (last.equals("#text")) return new Loc(Arrays.asList(parts).subList(0, parts.length - 1), null, true);
        return new Loc(Arrays.asList(parts), null, false); // bare element path (residue only)
    }

    /** Null when {@code locator} is a valid xml field locator, else the reason. */
    static String checkFieldLocator(String locator) {
        String[] parts = locator.split("/", -1);
        String last = parts[parts.length - 1];
        if (!(last.startsWith("@") && last.length() > 1) && !last.equals("#text")) {
            return "xml locator must end in @name or #text: " + locator;
        }
        for (int i = 0; i < parts.length - 1; i++) {
            if (parts[i].isEmpty() || parts[i].startsWith("@") || parts[i].startsWith("#")) {
                return "bad element path segment \"" + parts[i] + "\" in " + locator;
            }
        }
        return null;
    }

    @Override
    Xml.Element parse(String text) {
        Xml.Element root;
        try {
            root = Xml.parse(text);
        } catch (Xml.ParseException ex) {
            throw malformed(ex.getMessage());
        }
        // In a pack with kinds a root that matches no kind is no-kind (ruling 11 of 0.6): the kinds are picked by root.
        if (!pack.hasKinds && !root.name.equals(pack.root)) {
            throw new GtException(GtException.Code.MISSING_ROOT, pack.format, null,
                    "expected root <" + pack.root + ">, found <" + root.name + ">");
        }
        return root;
    }

    /** The raw wire text at a locator, or null when the attribute or element is absent. */
    private static String raw(Xml.Element root, Loc l) {
        Xml.Element el = find(root, l.path);
        if (el == null) return null;
        // all character data directly inside, kept exactly; none at all is no text (ruling 1m of 0.11)
        if (l.text) return el.text.length() == 0 ? null : el.text.toString();
        return el.attrs.get(l.attr);
    }

    @Override
    boolean holds(Xml.Element root, Pack.When when) {
        Loc loc = (Loc) when.loc;
        // `when .../#text present` holds when the element exists, with or without text (ruling 1m of 0.11)
        if (when.present && loc.text) return find(root, loc.path) != null;
        String raw = raw(root, loc);
        if (raw == null) return false;
        return when.present || when.matchesText(raw);
    }

    @Override
    Entity decodeKind(Xml.Element root, Pack.Kind kind) {
        Entity e = new Entity();
        Failures fails = new Failures();
        Set<String> mapped = new HashSet<>();
        decodeScope(root, kind.scope, e, fails, mapped);
        // Residue: unmapped attributes on the root element. Unmapped child elements are not carried.
        for (Map.Entry<String, String> a : root.attrs.entrySet()) {
            String loc = "@" + a.getKey();
            if (!mapped.contains(loc)) e.putResidue(pack.format, loc, a.getValue());
        }
        finishDecode(e, fails);
        return e;
    }

    /** Decode the lines of one scope under {@code el}: the root, or one item element ({@code mapped} is then null). */
    private void decodeScope(Xml.Element el, Pack.Scope scope, Entity e, Failures fails, Set<String> mapped) {
        for (Pack.Line l : scope.lines) {
            if (l instanceof Pack.Element) continue;   // decode ignores an element line (engine-spec 0.18)
            if (l instanceof Pack.Group) {
                // The items: each child named by the last name, under the first element matched by the names before.
                Pack.Group g = (Pack.Group) l;
                List<String> path = ((Loc) l.loc).path;
                Xml.Element holder = find(el, path.subList(0, path.size() - 1));
                if (holder == null) continue;
                String name = path.get(path.size() - 1);
                List<Entity> items = null;
                for (Xml.Element c : holder.children) {
                    if (!c.name.equals(name)) continue;
                    if (items == null) items = new ArrayList<>();
                    takeItems(1);
                    Entity item = new Entity();
                    decodeScope(c, g.body, item, fails, null);
                    items.add(item);
                }
                if (items != null) e.putList(g.list, items);   // no item occurs: the list is absent
                continue;
            }
            if (!(l instanceof Pack.Field)) {
                // `when <locator> present` does not map the member (ruling 27 of 0.5); a value or a const does.
                if (mapped != null && !((Pack.When) l).present) mapped.add(l.locator);
                continue;
            }
            if (mapped != null) mapped.add(l.locator);
            if (e.get(((Pack.Field) l).key) != null) continue;   // an earlier line already gave the key its value
            String raw = raw(el, (Loc) l.loc);
            if (raw == null) continue;
            // the text with references resolved, not trimmed (ruling 14 of 0.9): a sentinel yields no value
            if (((Pack.Field) l).absent != null && ((Pack.Field) l).absent.matches(raw)) continue;
            decodeField((Pack.Field) l, raw, e, fails);
        }
    }

    private static Xml.Element find(Xml.Element root, List<String> path) {
        Xml.Element cur = root;
        for (String seg : path) {
            cur = cur.child(seg);
            if (cur == null) return null;
        }
        return cur;
    }

    private static Xml.Element ensure(Xml.Element root, List<String> path) {
        Xml.Element cur = root;
        for (String seg : path) cur = cur.ensureChild(seg);
        return cur;
    }

    @Override
    String encodeKind(Entity e, Pack.Kind kind) {
        Xml.Element root = new Xml.Element(kind.root);
        Set<String> written = new HashSet<>();
        encodeScope(root, kind.scope, e, written);
        for (Map.Entry<String, String> r : e.residue(pack.format).entrySet()) {
            if (written.contains(r.getKey())) continue;
            put(root, split(r.getKey()), r.getValue());
            written.add(r.getKey());
        }
        try {
            return Xml.write(root);
        } catch (Xml.Unwritable ex) {
            throw new GtException(GtException.Code.TRANSFORM_ENCODE, pack.format, null, ex.getMessage());
        }
    }

    /** Write the lines of one scope under {@code root}: the document root, or one item element. */
    private void encodeScope(Xml.Element root, Pack.Scope scope, Entity e, Set<String> written) {
        // Locators that hold only a sentinel so far: a later line whose key is present writes over it (ruling 16 of 0.9).
        Set<String> sentinel = new HashSet<>();
        @SuppressWarnings("unchecked")
        Map<Integer, List<List<String>>> plan = scope.info instanceof Map ? (Map<Integer, List<List<String>>>) scope.info : null;
        for (int i = 0; i < scope.lines.size(); i++) {
            Pack.Line l = scope.lines.get(i);
            Loc loc = (Loc) l.loc;
            if (plan != null && plan.containsKey(i)) {
                for (List<String> p : plan.get(i)) ensure(root, p);   // written even when nothing inside it is
            }
            if (l instanceof Pack.Element) continue;
            if (l instanceof Pack.Group) {
                // One element per item, at the position of the group line. An empty or absent list writes nothing.
                Pack.Group g = (Pack.Group) l;
                List<Entity> items = e.list(g.list);
                if (items == null || items.isEmpty()) continue;
                Xml.Element holder = ensure(root, loc.path.subList(0, loc.path.size() - 1));
                String name = loc.path.get(loc.path.size() - 1);
                for (Entity item : items) {
                    Xml.Element c = new Xml.Element(name);
                    holder.children.add(c);
                    encodeScope(c, g.body, item, new HashSet<>());
                }
                continue;
            }
            // A when or const value is written over any field, at the position of the first line naming the locator.
            Pack.When w = scope.fixed.get(l.locator);
            if (w != null) {
                if (!written.add(l.locator)) continue;
                Xml.Element el = ensure(root, loc.path);
                if (loc.attr != null) {
                    el.attrs.put(loc.attr, w.text);
                } else {
                    el.text.setLength(0);
                    el.text.append(w.text);
                }
                continue;
            }
            if (l instanceof Pack.When) continue;        // nothing is written for `present`
            boolean over = sentinel.contains(l.locator);
            if (written.contains(l.locator) && !over) continue;   // an earlier line on this locator already wrote it
            Pack.Field f = (Pack.Field) l;
            String s = encodeField(f, e, scope);
            if (s == null) {
                if (f.absent == null || f.suppressed(e) || written.contains(l.locator)) continue;
                put(root, loc, f.absent.firstText());
                written.add(l.locator);
                sentinel.add(l.locator);
                continue;
            }
            if (over) {
                // replace the sentinel in its place
                Xml.Element el = ensure(root, loc.path);
                if (loc.attr != null) el.attrs.put(loc.attr, s);
                else if (loc.text) {
                    el.text.setLength(0);
                    el.text.append(s);
                }
                sentinel.remove(l.locator);
                continue;
            }
            put(root, loc, s);
            written.add(l.locator);
        }
        placeAttributes(root, scope);
    }

    /**
     * Order each element's attributes by the first line naming them, whichever line's value was written there:
     * a line that wrote nothing, one suppressed by {@code with} included (ruling 23 of 0.9, ruling 1 of 0.18).
     * Attributes no line names (residue) keep their order after them. A {@code when ... present} names no position.
     */
    private static void placeAttributes(Xml.Element root, Pack.Scope scope) {
        Map<Xml.Element, List<String>> order = null;
        for (Pack.Line l : scope.lines) {
            if (!(l instanceof Pack.Field) && !(l instanceof Pack.When && !((Pack.When) l).present)) continue;
            Loc loc = (Loc) l.loc;
            if (loc.attr == null) continue;
            Xml.Element el = find(root, loc.path);
            if (el == null || el.attrs.size() < 2) continue;
            if (order == null) order = new java.util.IdentityHashMap<>();
            List<String> names = order.computeIfAbsent(el, k -> new ArrayList<>());
            if (!names.contains(loc.attr)) names.add(loc.attr);
        }
        if (order == null) return;
        for (Map.Entry<Xml.Element, List<String>> o : order.entrySet()) {
            Xml.Element el = o.getKey();
            java.util.LinkedHashMap<String, String> was = new java.util.LinkedHashMap<>(el.attrs);
            el.attrs.clear();
            for (String n : o.getValue()) if (was.containsKey(n)) el.attrs.put(n, was.remove(n));
            el.attrs.putAll(was);
        }
    }

    private static void put(Xml.Element root, Loc l, String value) {
        Xml.Element el = ensure(root, l.path);
        if (l.attr != null) {
            el.attrs.putIfAbsent(l.attr, value);
        } else if (l.text) {
            el.text.append(value);
        }
        // bare path: ensure() already created the element
    }
}
