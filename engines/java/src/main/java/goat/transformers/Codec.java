package goat.transformers;

import java.util.ArrayList;
import java.util.List;

/**
 * Shared logic of every wire: kind selection on decode and encode, typemap, and failure collection.
 * {@code W} is the wire's parsed message.
 */
abstract class Codec<W> {
    final Pack pack;
    /** The engine the codec's pack is loaded in: it finds the pack an {@code inner} line names (engine-spec 0.34). */
    Engine engine;
    Codec(Pack pack) { this.pack = pack; }

    /** Parse the wire text. Throws {@code malformed-wire}. */
    abstract W parse(String text);

    /** True when the parsed message holds the {@code when} line's value at its locator. */
    abstract boolean holds(W wire, Pack.When when);

    /** Decode the lines of the selected kind (common lines first) into a new entity, with residue. */
    abstract Entity decodeKind(W wire, Pack.Kind kind);

    /** Encode the entity through the lines of the selected kind. */
    abstract String encodeKind(Entity e, Pack.Kind kind);

    /** The limit on list items of one decode when the caller sets none (ruling 7b of 0.11). */
    static final long DEFAULT_MAX_ITEMS = 100_000;

    /** The items one decode may still hold (ruling 7 of 0.11). */
    private static final class Budget {
        final long max;
        long left;
        /** The lists the outer entity holds while an inner message is decoded (engine-spec 0.34); null otherwise. */
        java.util.Set<String> outerHeld;
        Budget(long max) { this.max = max; this.left = max; }
    }

    /** The budget of the decode running on this thread; a codec is shared, a decode is not. */
    private static final ThreadLocal<Budget> BUDGET = new ThreadLocal<>();

    Entity decode(String text) { return decode(text, DEFAULT_MAX_ITEMS); }

    /** Decode a message of a carrier pack for a run operation (engine-spec 0.92). */
    Run.State decodeRun(String text, long maxItems, boolean toCarrier) { throw new IllegalStateException(); }

    /**
     * Encode a run into this carrier pack (engine-spec 0.92, ruling 6): the outer lines from {@code outer}, the
     * messages from the joined entities, each completed by {@code complete} when the inner format differs.
     */
    String encodeRun(Entity outer, List<Entity> joined, String sourceInner, boolean context, boolean samePack,
                     java.util.function.Consumer<Entity> complete) { throw new IllegalStateException(); }

    /** Run {@code body} under a budget of {@code maxItems} list items. */
    static void underBudget(long maxItems, Runnable body) {
        Budget outer = BUDGET.get();
        BUDGET.set(new Budget(maxItems));
        try {
            body.run();
        } finally {
            if (outer == null) BUDGET.remove();
            else BUDGET.set(outer);
        }
    }

    /** Decode with at most {@code maxItems} list items, counted over every list at every level (ruling 7 of 0.11). */
    Entity decode(String text, long maxItems) {
        Budget outer = BUDGET.get();
        BUDGET.set(new Budget(maxItems));
        try {
            return decodeMessage(text);
        } finally {
            if (outer == null) BUDGET.remove();
            else BUDGET.set(outer);
        }
    }

    /** One decode, under the budget set by {@link #decode(String, long)}. */
    Entity decodeMessage(String text) {
        W wire = parse(text);
        Pack.Kind kind = selectForDecode(wire);
        Entity e = decodeKind(wire, kind);
        if (pack.hasKinds) e.setKind(pack.format, kind.name);
        return e;
    }

    /**
     * Take {@code n} items (an unsigned count) from the decode's limit before they are read; one more than the limit
     * allows is {@code malformed-wire} (ruling 7a, 7d and 7f of 0.11).
     */
    void takeItems(long n) {
        Budget b = BUDGET.get();
        if (b == null) return;
        if (Long.compareUnsigned(n, b.left) > 0) {
            throw malformed("the message holds more than " + b.max + " list items (the limit on list items)");
        }
        b.left -= n;
    }

    /**
     * Check {@code n} items (an unsigned count) against the decode's limit without taking them: the count of a list
     * that decode discards (ruling 7 of engine-spec 0.34).
     */
    void checkItems(long n) {
        Budget b = BUDGET.get();
        if (b != null && Long.compareUnsigned(n, b.left) > 0) {
            throw malformed("the message holds more than " + b.max + " list items (the limit on list items)");
        }
    }

    /** The items the decode may still hold, or -1 outside a decode. */
    static long itemsLeft() {
        Budget b = BUDGET.get();
        return b == null ? -1 : b.left;
    }

    /** Set the items the decode may still hold (engine-spec 0.34: after an inner message is merged). */
    static void setItemsLeft(long left) {
        Budget b = BUDGET.get();
        if (b != null && left >= 0) b.left = left;
    }

    /** True when an inner message is being decoded and the outer entity already holds {@code list}. */
    static boolean heldByOuter(String list) {
        Budget b = BUDGET.get();
        return b != null && b.outerHeld != null && b.outerHeld.contains(list);
    }

    /** Set the lists the outer entity holds for an inner decode; returns the previous set. */
    static java.util.Set<String> setOuterHeld(java.util.Set<String> held) {
        Budget b = BUDGET.get();
        if (b == null) return null;
        java.util.Set<String> was = b.outerHeld;
        b.outerHeld = held;
        return was;
    }

    /** Give back the items of a list that a later group of the same list replaces (ruling 7g of 0.11). */
    void giveBackItems(List<Entity> items) {
        Budget b = BUDGET.get();
        if (b == null || items == null) return;
        b.left += deepCount(items);
    }

    /** The items of every list of an entity, at every level. */
    static long listItems(Entity e) {
        long n = 0;
        if (e != null) for (List<Entity> l : e.lists().values()) n += deepCount(l);
        return n;
    }

    /** The items of a list and of every list inside its items. */
    static long deepCount(List<Entity> items) {
        long n = items.size();
        for (Entity it : items) for (List<Entity> inner : it.lists().values()) n += deepCount(inner);
        return n;
    }

    String encode(Entity e) { return encode(e, false); }

    /**
     * Encode; {@code layer} is true when the message is written as the inner message of another pack's
     * {@code inner} line (engine-spec 0.34), which changes the order in which the kind records are consulted.
     */
    String encode(Entity e, boolean layer) {
        return encodeKind(e, selectForEncode(e, layer));
    }

    /**
     * The kind name the entity records for this format, or null when no record names it (engine-spec 0.34): at the
     * top level {@code Entity.kind} then {@code Entity.inner_kind}; as a layer {@code Entity.inner_kind} then
     * {@code Entity.kind}. A record that names the format with no kind name gives the empty text.
     */
    final String recordedKind(Entity e, boolean layer) {
        boolean byKind = pack.format.equals(e.kindFormat()), byInner = pack.format.equals(e.innerKindFormat());
        String kind = !byKind ? null : e.kindName() == null ? "" : e.kindName();
        String inner = !byInner ? null : e.innerKindName() == null ? "" : e.innerKindName();
        return layer ? (inner != null ? inner : kind) : (kind != null ? kind : inner);
    }

    final Pack.Kind selectForDecode(W wire) {
        if (!pack.hasKinds) return pack.kinds.get(0);
        for (Pack.When w : pack.commonWhens) {
            if (!holds(wire, w)) {
                throw new GtException(GtException.Code.NO_KIND, pack.format, w.locator,
                        "the common when line " + w.locator + " " + w.value + " does not hold");
            }
        }
        for (Pack.Kind k : candidates(wire)) {
            boolean all = true;
            for (Pack.When w : k.whens) {
                if (!holds(wire, w)) { all = false; break; }
            }
            if (all) return k;
        }
        throw new GtException(GtException.Code.NO_KIND, pack.format, null, "the message matches no kind");
    }

    /** The kinds decode considers for this message, in pack order. The xml wire narrows them by root element. */
    List<Pack.Kind> candidates(W wire) { return pack.kinds; }

    private Pack.Kind selectForEncode(Entity e, boolean layer) {
        if (!pack.hasKinds) return pack.kinds.get(0);
        String named = recordedKind(e, layer);
        if (named != null) {
            Pack.Kind k = pack.kind(named);
            if (k == null) {
                throw new GtException(GtException.Code.NO_KIND, pack.format, null,
                        "the entity names kind " + named + ", which this format does not have");
            }
            return k;
        }
        for (Pack.Kind k : pack.kinds) {
            // `requires <list>` holds when the list is present and has at least one item; `<key>=<values>` when
            // the key's canonical text is listed (engine-spec 0.20). Every term must hold.
            if (Pack.allHold(k.requires, e)) return k;
        }
        throw new GtException(GtException.Code.NO_KIND, pack.format, null,
                "the entity has the required keys of no kind");
    }

    /**
     * The check of engine-spec 0.94 in {@code convert} with {@code from} different from {@code to}, after the context
     * and the derivations and before any line is written: a pack with message kinds refuses the kind encode chooses
     * when the entity holds no key of it ({@code no-kind}). A kind the entity records for this format is kept and not
     * checked (ruling 4). Choosing itself may be the {@code no-kind} of 0.5, which comes first (ruling 5).
     */
    void checkHeld(Entity e) {
        if (!pack.hasKinds) return;
        Pack.Kind k = selectForEncode(e, false);
        if (recordedKind(e, false) != null) return;
        java.util.Set<String> keys = new java.util.LinkedHashSet<>();
        for (Pack.Line l : k.lines) kindKeys(l, keys);
        for (Pack.Require r : k.requires) keys.add(r.key);
        refuseUnheld(keys, e, k.name);
    }

    /** The keys of a kind one line adds (0.94): a field's key, a list by its entry, the lines of a gate. */
    private static void kindKeys(Pack.Line l, java.util.Set<String> out) {
        if (l instanceof Pack.Field) out.add(((Pack.Field) l).key);
        else if (l instanceof Pack.Group) out.add(((Pack.Group) l).list + "[]");
        else if (l instanceof Pack.Gate) for (Pack.Line b : ((Pack.Gate) l).body.lines) kindKeys(b, out);
    }

    /**
     * {@code no-kind} unless the entity holds one of {@code keys} (engine-spec 0.94): a key holds when the entity has
     * a value for it; a list ({@code rows[]}, or a {@code requires} key that names a list) when it has an item. An
     * entry of an item key ({@code rows[].x}) does not count.
     */
    final void refuseUnheld(java.util.Collection<String> keys, Entity e, String kind) {
        for (String k : keys) {
            if (k.endsWith("[]")) {
                if (k.indexOf("[].") < 0 && hasItems(e, k.substring(0, k.length() - 2))) return;
            } else if (k.indexOf("[].") < 0 && (e.get(k) != null || hasItems(e, k))) {
                return;
            }
        }
        throw new GtException(GtException.Code.NO_KIND, pack.format, null,
                "the entity holds no key of kind " + kind + " (a conversion into a kind holds one of its keys)");
    }

    private static boolean hasItems(Entity e, String list) {
        List<Entity> items = e.list(list);
        return items != null && !items.isEmpty();
    }

    GtException malformed(String why) {
        return new GtException(GtException.Code.MALFORMED_WIRE, pack.format, null, why);
    }

    /** Collects transform failures so a decode reports every unsatisfied field at once. */
    static final class Failures {
        final List<Pack.Field> fields = new ArrayList<>();
        final List<String> whys = new ArrayList<>();
        /** The entity or item each failed line was decoding into. */
        final List<Entity> into = new ArrayList<>();
        /** True for a failure no other line of the key makes good (a table with no entry, ruling 10 of 0.7). */
        final List<Boolean> hard = new ArrayList<>();
        /** json: the numbers a field maps, by identity (ruling 27 of 0.15). */
        final java.util.Map<Object, Boolean> read = new java.util.IdentityHashMap<>();
        /** The format of the pack whose line failed. */
        final List<String> formats = new ArrayList<>();
        private final String format;
        Failures(String format) { this.format = format; }
        void add(Pack.Field f, String why, Entity e) { add(f, why, e, false); }
        void add(Pack.Field f, String why, Entity e, boolean isHard) {
            fields.add(f);
            whys.add(why);
            into.add(e);
            hard.add(isHard);
            formats.add(format);
        }

        int size() { return fields.size(); }

        /**
         * The keys of {@link #joined} whose only value so far is the inner pack's (engine-spec 0.34): the next line
         * read here is this pack's first of the key, so its table is checked though its value is not kept (ruling 23).
         */
        final java.util.Set<String> innerKeys = new java.util.HashSet<>();
        Entity joined;

        /**
         * Drop the failures from {@code from} on that another line makes good: those in the items of a list a layered
         * decode discards (ruling 21 of engine-spec 0.34). A table with no entry stays an error.
         */
        void dropSoft(int from) {
            for (int i = size() - 1; i >= from; i--) {
                if (hard.get(i)) continue;
                fields.remove(i);
                whys.remove(i);
                into.remove(i);
                hard.remove(i);
                formats.remove(i);
            }
        }

        /**
         * Take the failures of an inner decode (engine-spec 0.34) as those of lines read here. Its entity {@code from}
         * joins {@code to}, so its lines and those read here are the lines of one key (ruling 23).
         */
        void addInner(Failures inner, Entity from, Entity to) {
            for (int i = 0; i < inner.size(); i++) {
                boolean root = inner.into.get(i) == from;
                fields.add(inner.fields.get(i));
                whys.add(inner.whys.get(i));
                into.add(root ? to : inner.into.get(i));
                hard.add(inner.hard.get(i));
                formats.add(inner.formats.get(i));
            }
        }
    }

    /**
     * Store a decoded value: through the field's value table, then the typemap for model key {@code type} (an
     * unmapped code passes through). The earliest line that yields a value for a key wins; later lines leave it.
     */
    void putDecoded(Pack.Field f, Object v, Entity e, Failures fails) {
        boolean given = e.get(f.key) != null;
        if (given && !(e == fails.joined && fails.innerKeys.contains(f.key))) return;
        if (f.viaDecode != null) {
            Object m = f.viaDecode.get(Pack.canonText(v));
            if (m == null) {
                if (!f.yields().equals(f.keyType)) {
                    // The transform succeeded and the table has no entry: later lines of the key do not make it good.
                    fails.add(f, "table " + f.via + " has no entry for " + Pack.canonText(v), e, true);
                    return;
                }
            } else if (m == Pack.UNREADABLE) {
                fails.add(f, "table " + f.via + " maps " + Pack.canonText(v) + " to a value that is not " + f.keyType, e, true);
                return;
            } else {
                v = m;
            }
        }
        if (given) {
            fails.innerKeys.remove(f.key);   // this pack gave the key a value too: its later lines are not tried
            return;
        }
        if (f.key.equals("type") && !pack.nativeToCot.isEmpty() && v instanceof String) {
            String cot = pack.nativeToCot.get(v);
            if (cot != null) v = cot;
        }
        e.put(f.key, v);
    }

    /**
     * The value a field writes: the entity's value, else the kind's {@code default}; then the reverse typemap and
     * the field's value table. Null when there is neither a value nor a default.
     */
    Object valueToEncode(Pack.Field f, Entity e, Pack.Scope scope) {
        return valueToEncode(f, e, scope.defaultValues);
    }

    /** As {@link #valueToEncode(Pack.Field, Entity, Pack.Scope)}, with the defaults in force for the line. */
    Object valueToEncode(Pack.Field f, Entity e, java.util.Map<String, Object> defaults) {
        if (f.suppressed(e)) return null;   // `with` (engine-spec 0.18): neither the value nor a default
        Object v = e.get(f.key);
        if (v == null) v = defaults.get(f.key);
        if (v == null) return null;
        if (f.key.equals("type") && v instanceof String && !pack.cotToNative.isEmpty()) {
            String nat = pack.cotToNative.get(v);
            if (nat != null) v = nat;
        }
        if (f.viaEncode != null) {
            Object n = f.viaEncode.get(Pack.canonText(v));
            if (n == null) {
                if (!f.yields().equals(f.keyType)) {
                    throw encodeFailure(f, new IllegalArgumentException("table " + f.via + " has no entry for " + Pack.canonText(v)));
                }
            } else if (n == Pack.UNREADABLE) {
                throw encodeFailure(f, new IllegalArgumentException(
                        "table " + f.via + " maps " + Pack.canonText(v) + " to a value that is not " + f.yields()));
            } else {
                v = n;
            }
        }
        return v;
    }

    /** Decode one text-wire value into the entity. */
    void decodeField(Pack.Field f, String raw, Entity e, Failures fails) {
        Object v;
        try {
            v = f.scale != null ? f.scale.decode(raw) : f.codes != null ? f.codes.decodeText(raw) : f.transform.decode(raw);
        } catch (IllegalArgumentException ex) {
            fails.add(f, ex.getMessage(), e);
            return;
        }
        putDecoded(f, v, e, fails);
    }

    /**
     * A failed line is an error unless another line gave its key a value: decode takes a key from the earliest
     * line whose locator is present and whose transform succeeds.
     */
    void finishDecode(Entity e, Failures fails) {
        List<String> items = new ArrayList<>();
        String firstLocator = null, firstFormat = null;
        for (int i = 0; i < fails.fields.size(); i++) {
            Pack.Field f = fails.fields.get(i);
            if (!fails.hard.get(i) && fails.into.get(i).get(f.key) != null) continue;
            if (firstFormat == null) {
                firstFormat = fails.formats.get(i);
                firstLocator = f.locator;
            }
            items.add(f.key + " @ " + f.locator + ": " + fails.whys.get(i));
        }
        if (!items.isEmpty()) {
            throw new GtException(GtException.Code.TRANSFORM_DECODE, firstFormat, firstLocator,
                    "fields absent: " + String.join("; ", items), e);
        }
    }

    GtException encodeFailure(Pack.Field f, IllegalArgumentException ex) {
        return new GtException(GtException.Code.TRANSFORM_ENCODE, pack.format, f.locator, f.key + ": " + ex.getMessage());
    }

    /** Encode one model value to wire text. Null when the entity lacks the key and the kind has no default. */
    String encodeField(Pack.Field f, Entity e, Pack.Scope scope) {
        Object v = valueToEncode(f, e, scope);
        if (v == null) return null;
        try {
            return f.scale != null ? f.scale.encode(v) : f.codes != null ? f.codes.encodeText(v) : f.transform.encode(v);
        } catch (IllegalArgumentException ex) {
            throw encodeFailure(f, ex);
        }
    }

    // ---- hex I/O, shared by the binary wires ----

    byte[] fromHex(String text) {
        int n = text.length();
        byte[] out = new byte[n / 2];
        int len = 0, hi = -1;
        for (int i = 0; i < n; i++) {
            char c = text.charAt(i);
            int d;
            if (c >= '0' && c <= '9') d = c - '0';
            else if (c >= 'a' && c <= 'f') d = c - 'a' + 10;
            else if (c >= 'A' && c <= 'F') d = c - 'A' + 10;
            else if (c == ' ' || c == '\t' || c == '\n' || c == '\r') continue;   // ruling 40 of 0.8: these four only
            else throw malformed("hex has a non-hex digit");
            if (hi < 0) {
                hi = d;
            } else {
                out[len++] = (byte) ((hi << 4) | d);
                hi = -1;
            }
        }
        if (hi >= 0) throw malformed("hex has an odd number of digits: " + (2 * len + 1));
        return len == out.length ? out : java.util.Arrays.copyOf(out, len);
    }

    private static final char[] HEX = "0123456789abcdef".toCharArray();

    static String toHex(byte[] msg) {
        char[] out = new char[msg.length * 2];
        for (int i = 0; i < msg.length; i++) {
            int v = msg[i] & 0xff;
            out[2 * i] = HEX[v >>> 4];
            out[2 * i + 1] = HEX[v & 0xf];
        }
        return new String(out);
    }
}
