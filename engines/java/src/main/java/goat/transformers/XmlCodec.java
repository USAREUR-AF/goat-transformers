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
        if (l.text) return (!el.children.isEmpty() && Xml.isBlank(el.text)) ? "" : el.text.toString();
        return el.attrs.get(l.attr);
    }

    @Override
    boolean holds(Xml.Element root, Pack.When when) {
        String raw = raw(root, (Loc) when.loc);
        if (raw == null) return false;
        return when.present || raw.equals(when.text);
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
        return Xml.write(root);
    }

    /** Write the lines of one scope under {@code root}: the document root, or one item element. */
    private void encodeScope(Xml.Element root, Pack.Scope scope, Entity e, Set<String> written) {
        for (Pack.Line l : scope.lines) {
            Loc loc = (Loc) l.loc;
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
            if (written.contains(l.locator)) continue;   // an earlier line on this locator already wrote it
            String s = encodeField((Pack.Field) l, e, scope);
            if (s == null) continue;
            put(root, loc, s);
            written.add(l.locator);
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
