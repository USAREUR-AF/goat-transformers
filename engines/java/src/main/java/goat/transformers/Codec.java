package goat.transformers;

import java.util.ArrayList;
import java.util.List;

/**
 * Shared logic of every wire: kind selection on decode and encode, typemap, and failure collection.
 * {@code W} is the wire's parsed message.
 */
abstract class Codec<W> {
    final Pack pack;
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
        Budget(long max) { this.max = max; this.left = max; }
    }

    /** The budget of the decode running on this thread; a codec is shared, a decode is not. */
    private static final ThreadLocal<Budget> BUDGET = new ThreadLocal<>();

    Entity decode(String text) { return decode(text, DEFAULT_MAX_ITEMS); }

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

    /** Give back the items of a list that a later group of the same list replaces (ruling 7g of 0.11). */
    void giveBackItems(List<Entity> items) {
        Budget b = BUDGET.get();
        if (b == null || items == null) return;
        b.left += deepCount(items);
    }

    /** The items of a list and of every list inside its items. */
    static long deepCount(List<Entity> items) {
        long n = items.size();
        for (Entity it : items) for (List<Entity> inner : it.lists().values()) n += deepCount(inner);
        return n;
    }

    String encode(Entity e) {
        return encodeKind(e, selectForEncode(e));
    }

    private Pack.Kind selectForDecode(W wire) {
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

    private Pack.Kind selectForEncode(Entity e) {
        if (!pack.hasKinds) return pack.kinds.get(0);
        if (pack.format.equals(e.kindFormat())) {
            Pack.Kind k = e.kindName() == null ? null : pack.kind(e.kindName());
            if (k == null) {
                throw new GtException(GtException.Code.NO_KIND, pack.format, null,
                        "the entity names kind " + e.kindName() + ", which this format does not have");
            }
            return k;
        }
        for (Pack.Kind k : pack.kinds) {
            boolean all = true;
            for (String key : k.requires) {
                if (e.get(key) != null) continue;
                // `requires <list>` holds when the list is present and has at least one item.
                List<Entity> items = e.list(key);
                if (items == null || items.isEmpty()) { all = false; break; }
            }
            if (all) return k;
        }
        throw new GtException(GtException.Code.NO_KIND, pack.format, null,
                "the entity has the required keys of no kind");
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
        void add(Pack.Field f, String why, Entity e) { add(f, why, e, false); }
        void add(Pack.Field f, String why, Entity e, boolean isHard) {
            fields.add(f);
            whys.add(why);
            into.add(e);
            hard.add(isHard);
        }
    }

    /**
     * Store a decoded value: through the field's value table, then the typemap for model key {@code type} (an
     * unmapped code passes through). The earliest line that yields a value for a key wins; later lines leave it.
     */
    void putDecoded(Pack.Field f, Object v, Entity e, Failures fails) {
        if (e.get(f.key) != null) return;
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
        Object v = e.get(f.key);
        if (v == null) v = scope.defaultValues.get(f.key);
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
            v = f.transform.decode(raw);
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
        String firstLocator = null;
        for (int i = 0; i < fails.fields.size(); i++) {
            Pack.Field f = fails.fields.get(i);
            if (!fails.hard.get(i) && fails.into.get(i).get(f.key) != null) continue;
            if (firstLocator == null) firstLocator = f.locator;
            items.add(f.key + " @ " + f.locator + ": " + fails.whys.get(i));
        }
        if (!items.isEmpty()) {
            throw new GtException(GtException.Code.TRANSFORM_DECODE, pack.format, firstLocator,
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
            return f.transform.encode(v);
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
