package goat.transformers;

import java.io.ByteArrayOutputStream;
import java.math.BigInteger;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;

import static goat.transformers.CborLayout.*;

/**
 * The {@code cbor} wire (engine-spec 0.28): the message is one CBOR data item (RFC 8949), a map or an array, carried
 * in and out as hex text. A path is integer keys, text keys and array positions {@code [i]} separated by {@code .}.
 * Tags are passed over on decode and not written on encode, except the pack's {@code tag <n>}, which encloses the
 * message. Output has the core deterministic encoding of RFC 8949 4.2.1. Residue is every unmapped member or element,
 * carried whole as the hex of its encoded item as it stood in the input.
 */
final class CborCodec extends Codec<CborCodec.Msg> {

    // ---- items ----

    /** One data item as read: its major type, its content, and the bytes it stood in. */
    static final class Item {
        int mt;
        /** Major types 0 and 1: the argument; 6: the tag number; 7: the simple value (when not a float). */
        long arg;
        /** Major types 2 and 3: the content, chunks joined. */
        byte[] bytes;
        /** Major type 4: the elements; 5: the keys and values, in input order. */
        Item[] elems, keys, vals;
        /** Major type 6: the item the tag encloses. */
        Item inner;
        /** Major type 7: a float of this width in bytes (2, 4 or 8) and these bits; 0 for a simple value. */
        int fw;
        long fbits;
        /** Its bytes in the input, its tags included: {@code [start, end)}. */
        int start, end;
    }

    static boolean nullish(Item it) { return it.mt == 7 && it.fw == 0 && (it.arg == 22 || it.arg == 23); }

    static Item strip(Item it) {
        while (it.mt == 6) it = it.inner;
        return it;
    }

    /** The deepest nesting of arrays, maps and tags: the top item level 1 (step 5 of "Reading a message"). */
    static final int MAX_DEPTH = 64;

    /** Reads one well-formed data item (RFC 8949 Appendix C); every failure is {@code malformed-wire}. */
    final class Reader {
        final byte[] b;
        int pos;

        Reader(byte[] b) { this.b = b; }

        private long need(int n) {
            if (b.length - pos < n) throw malformed("an item runs past the end of the input");
            long v = 0;
            for (int i = 0; i < n; i++) v = (v << 8) | (b[pos++] & 0xff);
            return v;
        }

        /** The argument of a head whose additional information is {@code ai} (below 28). */
        private long argument(int ai) {
            if (ai < 24) return ai;
            return need(1 << (ai - 24));
        }

        Item item(int level) {
            int start = pos;
            if (pos >= b.length) throw malformed("the input ends where an item stands");
            int ib = b[pos++] & 0xff;
            int mt = ib >>> 5, ai = ib & 31;
            if (ib == 0xff) throw malformed("a break stands where an item stands");
            if (ai >= 28 && ai <= 30) throw malformed(String.format("reserved additional information %d at offset %d", ai, start));
            boolean indefinite = ai == 31;
            if (indefinite && (mt == 0 || mt == 1 || mt == 6 || mt == 7)) {
                throw malformed(String.format("additional information 31 on major type %d at offset %d", mt, start));
            }
            Item it = new Item();
            it.mt = mt;
            it.start = start;
            switch (mt) {
                case 0:
                case 1:
                    it.arg = argument(ai);
                    break;
                case 2:
                case 3:
                    if (!indefinite) {
                        it.bytes = chunk(mt, argument(ai));
                    } else {
                        ByteArrayOutputStream all = new ByteArrayOutputStream();
                        while (true) {
                            if (pos >= b.length) throw malformed("an indefinite string has no break");
                            int cb = b[pos] & 0xff;
                            if (cb == 0xff) {
                                pos++;
                                break;
                            }
                            pos++;
                            if (cb >>> 5 != mt || (cb & 31) >= 28) {
                                throw malformed("a chunk of an indefinite string is not a definite string of its major type");
                            }
                            byte[] c = chunk(mt, argument(cb & 31));
                            all.write(c, 0, c.length);
                        }
                        it.bytes = all.toByteArray();
                    }
                    break;
                case 4: {
                    if (level > MAX_DEPTH) throw malformed("the items nest deeper than " + MAX_DEPTH + " levels");
                    List<Item> el = new ArrayList<>();
                    if (!indefinite) {
                        long n = argument(ai);
                        // every element takes at least one byte: compared before any memory is taken for them
                        if (Long.compareUnsigned(n, b.length - pos) > 0) {
                            throw malformed("an array declares " + Long.toUnsignedString(n) + " elements and " + (b.length - pos) + " bytes are left");
                        }
                        for (long i = 0; i < n; i++) el.add(item(level + 1));
                    } else {
                        while (!atBreak()) el.add(item(level + 1));
                    }
                    it.elems = el.toArray(new Item[0]);
                    break;
                }
                case 5: {
                    if (level > MAX_DEPTH) throw malformed("the items nest deeper than " + MAX_DEPTH + " levels");
                    List<Item> ks = new ArrayList<>(), vs = new ArrayList<>();
                    if (!indefinite) {
                        long n = argument(ai);
                        if (Long.compareUnsigned(n, (b.length - pos) / 2) > 0) {
                            throw malformed("a map declares " + Long.toUnsignedString(n) + " members and " + (b.length - pos) + " bytes are left");
                        }
                        for (long i = 0; i < n; i++) {
                            ks.add(item(level + 1));
                            vs.add(item(level + 1));
                        }
                    } else {
                        while (!atBreak()) {
                            ks.add(item(level + 1));
                            if (pos < b.length && (b[pos] & 0xff) == 0xff) throw malformed("a map ends after a key with no value");
                            vs.add(item(level + 1));
                        }
                    }
                    it.keys = ks.toArray(new Item[0]);
                    it.vals = vs.toArray(new Item[0]);
                    Set<ByteBuffer> seen = new HashSet<>();
                    for (Item k : it.keys) {
                        if (!seen.add(ByteBuffer.wrap(canon(k)))) throw malformed("a map holds two equal keys");
                    }
                    break;
                }
                case 6:
                    if (level > MAX_DEPTH) throw malformed("the items nest deeper than " + MAX_DEPTH + " levels");
                    it.arg = argument(ai);
                    it.inner = item(level + 1);
                    break;
                default:
                    if (ai < 24) {
                        it.arg = ai;
                    } else if (ai == 24) {
                        it.arg = need(1);
                        if (it.arg < 32) throw malformed("a simple value below 32 in two bytes");
                    } else {
                        it.fw = 1 << (ai - 24);
                        it.fbits = need(it.fw);
                    }
            }
            it.end = pos;
            return it;
        }

        /** True, past the break, when a break stands next; the end of the input first is {@code malformed-wire}. */
        private boolean atBreak() {
            if (pos >= b.length) throw malformed("an indefinite item has no break");
            if ((b[pos] & 0xff) == 0xff) {
                pos++;
                return true;
            }
            return false;
        }

        /** The content of a definite string of {@code n} bytes; text must be valid UTF-8. */
        private byte[] chunk(int mt, long n) {
            if (Long.compareUnsigned(n, b.length - pos) > 0) {
                throw malformed("a string declares " + Long.toUnsignedString(n) + " bytes and " + (b.length - pos) + " are left");
            }
            int len = (int) n;
            byte[] c = java.util.Arrays.copyOfRange(b, pos, pos + len);
            pos += len;
            if (mt == 3 && !utf8(c)) throw malformed("a text string is not valid UTF-8");
            return c;
        }
    }

    /** Strict UTF-8: no overlong form, no surrogate, nothing above U+10FFFF. */
    static boolean utf8(byte[] b) {
        int i = 0, to = b.length;
        while (i < to) {
            int c = b[i] & 0xff;
            if (c < 0x80) {
                i++;
                continue;
            }
            int n;
            if (c >= 0xc2 && c <= 0xdf) n = 1;
            else if (c >= 0xe0 && c <= 0xef) n = 2;
            else if (c >= 0xf0 && c <= 0xf4) n = 3;
            else return false;
            if (to - i <= n) return false;
            int c1 = b[i + 1] & 0xff;
            if (c == 0xe0 && c1 < 0xa0) return false;
            if (c == 0xed && c1 > 0x9f) return false;
            if (c == 0xf0 && c1 < 0x90) return false;
            if (c == 0xf4 && c1 > 0x8f) return false;
            for (int k = 1; k <= n; k++) if ((b[i + k] & 0xc0) != 0x80) return false;
            i += n + 1;
        }
        return true;
    }

    // ---- the core deterministic encoding (RFC 8949 4.2.1) ----

    static byte[] canon(Item it) {
        ByteArrayOutputStream o = new ByteArrayOutputStream();
        canon(it, o);
        return o.toByteArray();
    }

    /** The item with its core deterministic encoding: shortest heads and floats, definite lengths, sorted keys. */
    static void canon(Item it, ByteArrayOutputStream o) {
        switch (it.mt) {
            case 0:
            case 1:
                head(o, it.mt, it.arg);
                return;
            case 2:
            case 3:
                head(o, it.mt, it.bytes.length);
                o.write(it.bytes, 0, it.bytes.length);
                return;
            case 4:
                head(o, 4, it.elems.length);
                for (Item e : it.elems) canon(e, o);
                return;
            case 5: {
                TreeMap<String, byte[]> members = new TreeMap<>();
                for (int i = 0; i < it.keys.length; i++) members.put(toHex(canon(it.keys[i])), canon(it.vals[i]));
                head(o, 5, members.size());
                for (Map.Entry<String, byte[]> m : members.entrySet()) {
                    byte[] k = fromHexText(m.getKey());
                    o.write(k, 0, k.length);
                    o.write(m.getValue(), 0, m.getValue().length);
                }
                return;
            }
            case 6:
                head(o, 6, it.arg);
                canon(it.inner, o);
                return;
            default:
                if (it.fw == 0) {
                    if (it.arg < 24) o.write(0xe0 | (int) it.arg);
                    else {
                        o.write(0xf8);
                        o.write((int) it.arg);
                    }
                } else {
                    canonFloat(it, o);
                }
        }
    }

    /** The double of a float item. */
    static double floatValue(Item it) {
        if (it.fw == 2) return half((int) it.fbits);
        if (it.fw == 4) return Float.intBitsToFloat((int) it.fbits);
        return Double.longBitsToDouble(it.fbits);
    }

    static double half(int h) {
        int e = (h >>> 10) & 31, m = h & 0x3ff;
        double v;
        if (e == 0) v = m * 0x1p-24;
        else if (e == 31) v = m == 0 ? Double.POSITIVE_INFINITY : Double.NaN;
        else v = (m + 1024) * Math.scalb(1.0, e - 25);
        return (h & 0x8000) != 0 ? -v : v;
    }

    /** A float item at the shortest width that holds it; a NaN keeps its payload (RFC 8949 4.1). */
    private static void canonFloat(Item it, ByteArrayOutputStream o) {
        boolean nan = it.fw == 2 ? ((it.fbits & 0x7c00) == 0x7c00 && (it.fbits & 0x3ff) != 0)
                : it.fw == 4 ? Float.isNaN(Float.intBitsToFloat((int) it.fbits)) : Double.isNaN(Double.longBitsToDouble(it.fbits));
        if (!nan) {
            writeFloat(o, floatValue(it));
            return;
        }
        long sign, mant;   // the sign and the significand widened to 52 bits by zero padding on the right
        if (it.fw == 2) {
            sign = (it.fbits >>> 15) & 1;
            mant = (it.fbits & 0x3ffL) << 42;
        } else if (it.fw == 4) {
            sign = (it.fbits >>> 31) & 1;
            mant = (it.fbits & 0x7fffffL) << 29;
        } else {
            sign = it.fbits >>> 63;
            mant = it.fbits & 0xfffffffffffffL;
        }
        if ((mant & ((1L << 42) - 1)) == 0) {
            int h = (int) ((sign << 15) | 0x7c00 | (mant >>> 42));
            o.write(0xf9);
            o.write(h >>> 8);
            o.write(h & 0xff);
        } else if ((mant & ((1L << 29) - 1)) == 0) {
            long f = (sign << 31) | 0x7f800000L | (mant >>> 29);
            o.write(0xfa);
            for (int s = 24; s >= 0; s -= 8) o.write((int) (f >>> s) & 0xff);
        } else {
            long d = (sign << 63) | 0x7ff0000000000000L | mant;
            o.write(0xfb);
            for (int s = 56; s >= 0; s -= 8) o.write((int) (d >>> s) & 0xff);
        }
    }

    /** The half-precision bits that hold {@code d} exactly, or -1; subnormal halves included. {@code d} is not NaN. */
    static int halfExact(double d) {
        int sign = (int) (Double.doubleToRawLongBits(d) >>> 63) << 15;
        double a = Math.abs(d);
        if (a == 0) return sign;
        if (Double.isInfinite(a)) return sign | 0x7c00;
        if (a < 0x1p-24) return -1;
        if (a < 0x1p-14) {
            double m = a * 0x1p24;   // exact: a power-of-two scaling within range
            if (m != Math.floor(m)) return -1;
            return sign | (int) m;
        }
        int e = Math.getExponent(a);
        if (e > 15) return -1;
        double m = Math.scalb(a, 10 - e);
        if (m != Math.floor(m)) return -1;
        return sign | ((e + 15) << 10) | ((int) m - 1024);
    }

    /** {@code d} (not NaN) as the shortest of half, single and double that holds it exactly (RFC 8949 4.2.2). */
    static void writeFloat(ByteArrayOutputStream o, double d) {
        int h = halfExact(d);
        if (h >= 0) {
            o.write(0xf9);
            o.write(h >>> 8);
            o.write(h & 0xff);
            return;
        }
        float f = (float) d;
        if ((double) f == d) {
            int bits = Float.floatToRawIntBits(f);
            o.write(0xfa);
            for (int s = 24; s >= 0; s -= 8) o.write((bits >>> s) & 0xff);
            return;
        }
        long bits = Double.doubleToRawLongBits(d);
        o.write(0xfb);
        for (int s = 56; s >= 0; s -= 8) o.write((int) (bits >>> s) & 0xff);
    }

    static byte[] fromHexText(String h) {
        byte[] out = new byte[h.length() / 2];
        for (int i = 0; i < out.length; i++) {
            out[i] = (byte) ((Character.digit(h.charAt(2 * i), 16) << 4) | Character.digit(h.charAt(2 * i + 1), 16));
        }
        return out;
    }

    // ---- the codec ----

    /** A parsed message: the top item, its tags passed over. */
    static final class Msg {
        final Item top;
        final byte[] b;

        Msg(Item top, byte[] b) {
            this.top = top;
            this.b = b;
        }
    }

    /** True when the paths decide an array for the top item (Types). */
    private final boolean topArray;

    CborCodec(Pack pack) {
        super(pack);
        boolean arr = false;
        for (Pack.Kind k : pack.kinds) {
            PNode root = (PNode) k.scope.info;
            for (Pack.Line l : k.scope.lines) {
                Step[] p = (Step[]) l.loc;
                if ((p.length > 0 && p[0].kind == POS) || (p.length == 0 && l instanceof Pack.Group)) arr = true;
            }
            if (root == null) throw new IllegalStateException("cbor scope not checked");
        }
        topArray = arr;
    }

    @Override
    Msg parse(String text) {
        byte[] b = fromHex(text);
        Reader r = new Reader(b);
        Item top = r.item(1);
        if (r.pos != b.length) throw malformed((b.length - r.pos) + " bytes stand after the data item");
        if (pack.cborTagged) {
            if (top.mt != 6 || top.arg != pack.cborTag) {
                throw malformed("the outermost tag of the input is not " + Long.toUnsignedString(pack.cborTag));
            }
            top = top.inner;
        }
        top = strip(top);
        if (topArray ? top.mt != 4 : top.mt != 5) {
            throw malformed("the top item is not " + (topArray ? "an array" : "a map") + ", as the pack's paths decide");
        }
        return new Msg(top, b);
    }

    /** The member or element of {@code c} (tags passed over) that the step names, or null when there is none. */
    private static Item child(Item c, Step s) {
        if (s.kind == POS) return s.pos < c.elems.length ? c.elems[s.pos] : null;
        for (int i = 0; i < c.keys.length; i++) {
            Item k = c.keys[i];
            if (s.kind == KEY_INT ? (k.mt == s.mt && k.arg == s.arg) : (k.mt == 3 && java.util.Arrays.equals(k.bytes, s.text))) {
                return c.vals[i];
            }
        }
        return null;
    }

    private static boolean isType(Item c, int as) { return as == MAP ? c.mt == 5 : c.mt == 4; }

    @Override
    boolean holds(Msg msg, Pack.When when) {
        Step[] p = (Step[]) when.loc;
        Item cur = msg.top;
        for (Step s : p) {
            cur = strip(cur);
            if (!isType(cur, s.needs())) return false;   // the wrong type for the next step: does not hold (step 7)
            cur = child(cur, s);
            if (cur == null) return false;
        }
        cur = strip(cur);
        if (when.present) return !nullish(cur);
        byte[] want = when.cbor;
        switch (cur.mt) {
            case 0:
            case 1:
            case 3:
                return java.util.Arrays.equals(canon(cur), want);
            case 7:
                return cur.fw == 0 && (cur.arg == 20 || cur.arg == 21) && java.util.Arrays.equals(canon(cur), want);
            default:
                return false;
        }
    }

    /**
     * The item at the path from {@code el}, or null when a step's item is absent or is {@code null} or
     * {@code undefined} partway (ruling 12). An item on the way that is not the container its next step needs is
     * {@code malformed-wire} (step 8).
     */
    private Item walk(Item el, Step[] p, Pack.Line l) {
        Item cur = el;
        for (Step s : p) {
            cur = strip(cur);
            if (nullish(cur)) return null;
            if (!isType(cur, s.needs())) {
                throw malformed("line " + l.line + " (" + l.locator + ") needs " + (s.needs() == MAP ? "a map" : "an array")
                        + " before step " + s.repr + " and the item there is not one");
            }
            cur = child(cur, s);
            if (cur == null) return null;
        }
        return cur;
    }

    @Override
    Entity decodeKind(Msg msg, Pack.Kind kind) {
        Entity e = new Entity();
        Failures fails = new Failures(pack.format);
        decodeScope(msg.top, kind.scope, e, fails);
        PNode root = (PNode) kind.scope.info;
        if (!root.mapped) residue(msg, msg.top, root, "", e);
        finishDecode(e, fails);
        return e;
    }

    private void decodeScope(Item el, Pack.Scope scope, Entity e, Failures fails) {
        for (Pack.Line l : scope.lines) {
            Step[] p = (Step[]) l.loc;
            Item v = walk(el, p, l);
            if (l instanceof Pack.Group) {
                Pack.Group g = (Pack.Group) l;
                if (v == null) continue;
                v = strip(v);
                if (nullish(v)) continue;              // an absent list
                if (v.mt != 4) throw malformed("the group path " + l.locator + " holds an item that is not an array");
                takeItems(v.elems.length);
                PNode body = (PNode) g.body.info;
                List<Entity> items = new ArrayList<>(v.elems.length);
                for (Item x : v.elems) {
                    Entity item = new Entity();
                    Item s = strip(x);
                    // an element of the wrong type for the body is an item with no keys (ruling 12 of 0.7)
                    boolean read = body.mapped || (!nullish(s) && (body.as == 0 || isType(s, body.as)));
                    if (read) decodeScope(s, g.body, item, fails);
                    items.add(item);
                }
                e.putList(g.list, items);
                continue;
            }
            if (!(l instanceof Pack.Field)) continue;
            Pack.Field f = (Pack.Field) l;
            if (v == null) continue;
            v = strip(v);
            if (nullish(v)) continue;                   // null and undefined are absent
            if (settled(f, e)) continue;         // an earlier line gave the key its value
            Object d;
            try {
                d = decodeValue(f.cbor, v);
            } catch (IllegalArgumentException ex) {
                fails.add(f, ex.getMessage(), e);
                continue;
            }
            putDecoded(f, d, e, fails);
        }
    }

    private static final BigInteger TWO_64 = BigInteger.ONE.shiftLeft(64);

    /** The integer an item of major type 0 or 1 holds. */
    static BigInteger intValue(Item v) {
        BigInteger a = new BigInteger(Long.toUnsignedString(v.arg));
        return v.mt == 0 ? a : a.negate().subtract(BigInteger.ONE);
    }

    private static String typeName(Item v) {
        switch (v.mt) {
            case 0: return "an unsigned integer";
            case 1: return "a negative integer";
            case 2: return "a byte string";
            case 3: return "a text string";
            case 4: return "an array";
            case 5: return "a map";
            case 6: return "a tag";
            default: return v.fw != 0 ? "a float" : "simple value " + v.arg;
        }
    }

    static Object decodeValue(CT t, Item v) {
        switch (t) {
            case UINT:
                if (v.mt != 0) throw new IllegalArgumentException("uint takes major type 0, found " + typeName(v));
                if (v.arg < 0) throw new IllegalArgumentException("uint " + Long.toUnsignedString(v.arg) + " is above 2^63-1");
                return v.arg;
            case INT:
            case EPOCH_S: {
                if (v.mt != 0 && v.mt != 1) throw new IllegalArgumentException(t.wireName + " takes major type 0 or 1, found " + typeName(v));
                if (v.arg < 0) throw new IllegalArgumentException("integer " + intValue(v) + " is outside -2^63 to 2^63-1");
                long n = v.mt == 0 ? v.arg : -1 - v.arg;
                if (t == CT.INT) return n;
                try {
                    return Math.multiplyExact(n, 1000L);
                } catch (ArithmeticException ex) {
                    throw new IllegalArgumentException(n + " s in time_ms lies outside -2^63 to 2^63-1");
                }
            }
            case FLOAT: {
                double d;
                if (v.mt == 0 || v.mt == 1) d = intValue(v).doubleValue();   // nearest, ties to even
                else if (v.mt == 7 && v.fw != 0) d = floatValue(v);
                else throw new IllegalArgumentException("float takes a float or an integer, found " + typeName(v));
                if (!Double.isFinite(d)) throw new IllegalArgumentException("float " + d + " is not finite");
                return d;
            }
            case TEXT:
                if (v.mt != 3) throw new IllegalArgumentException("text takes major type 3, found " + typeName(v));
                return new String(v.bytes, StandardCharsets.UTF_8);
            case BYTES:
                if (v.mt != 2) throw new IllegalArgumentException("bytes takes major type 2, found " + typeName(v));
                return toHex(v.bytes);
            default:
                if (v.mt != 7 || v.fw != 0 || (v.arg != 20 && v.arg != 21)) {
                    throw new IllegalArgumentException("bool takes false or true, found " + typeName(v));
                }
                return v.arg == 21 ? 1L : 0L;
        }
    }

    /** The step that addresses a map key, or null when the key is not addressable. */
    private static Step keyStep(Item k) {
        if (k.mt == 0) return new Step(KEY_INT, 0, k.arg, null, 0, Long.toUnsignedString(k.arg));
        if (k.mt == 1) {
            if (k.arg < 0) return null;   // below -2^63 (ruling 17)
            return new Step(KEY_INT, 1, k.arg, null, 0, Long.toString(-1 - k.arg));
        }
        if (k.mt == 3) {
            String s = new String(k.bytes, StandardCharsets.UTF_8);
            if (isTextKey(s)) return new Step(KEY_TEXT, 3, 0, k.bytes, 0, s);
        }
        return null;
    }

    private static String hex(byte[] b, int from, int to) { return toHex(java.util.Arrays.copyOfRange(b, from, to)); }

    /**
     * Every member or element of a container a line walks into that no line maps is residue, keyed by its path,
     * holding its item as it stood in the input; one a line walks into gives its own residue (Residue).
     */
    private void residue(Msg msg, Item c, PNode node, String prefix, Entity e) {
        int n = c.mt == 4 ? c.elems.length : c.keys.length;
        for (int i = 0; i < n; i++) {
            Item v;
            String step;
            if (c.mt == 4) {
                if (i > 65535) break;   // no key a path can write (ruling 18)
                v = c.elems[i];
                step = "[" + i + "]";
            } else {
                v = c.vals[i];
                Step s = keyStep(c.keys[i]);
                if (s == null) {
                    e.putResidue(pack.format, prefix + "#" + hex(msg.b, c.keys[i].start, c.keys[i].end), hex(msg.b, v.start, v.end));
                    continue;
                }
                step = s.repr;
            }
            PNode k = node.kids.get(step);
            String path = prefix + step;
            if (k != null && k.mapped) continue;
            if (k != null && k.walked) {
                Item x = strip(v);
                if (nullish(x)) continue;                // walked into: not residue (ruling 12)
                if (x.mt == 4 || x.mt == 5) {
                    residue(msg, x, k, path + ".", e);
                    continue;
                }
            }
            e.putResidue(pack.format, path, hex(msg.b, v.start, v.end));
        }
    }

    // ---- encode ----

    private static final byte[] NULL = {(byte) 0xf6}, EMPTY_MAP = {(byte) 0xa0}, EMPTY_ARRAY = {(byte) 0x80};

    /** A place of the output: a map, an array, or an encoded item. */
    private static final class ONode {
        final int type;   // MAP, ARRAY, or 0 for an encoded item
        byte[] leaf;
        /** The scope's tree at this place, for the gaps of an array (ruling 23); null when no line names it. */
        PNode shape;
        /** A map: key encoding (hex, so the order is bytewise) to member. An array: position to element. */
        final TreeMap<String, ONode> members = new TreeMap<>();
        final TreeMap<Integer, ONode> elems = new TreeMap<>();

        ONode(int type, PNode shape) {
            this.type = type;
            this.shape = shape;
        }

        ONode get(Step s) { return s.kind == POS ? elems.get(s.pos) : members.get(s.keyHex); }

        void put(Step s, ONode n) {
            if (s.kind == POS) elems.put(s.pos, n);
            else members.put(s.keyHex, n);
        }
    }

    private static ONode leaf(byte[] b) {
        ONode n = new ONode(0, null);
        n.leaf = b;
        return n;
    }

    /** The container at the path's last step, creating the containers on the way; null when a value stands there. */
    private static ONode parent(ONode top, Step[] p, PNode shape) {
        ONode cur = top;
        PNode sh = shape;
        for (int i = 0; i < p.length - 1; i++) {
            if (cur.type != p[i].needs()) return null;
            sh = sh == null ? null : sh.kids.get(p[i].repr);
            ONode next = cur.get(p[i]);
            if (next == null) {
                next = new ONode(p[i + 1].needs(), sh);
                cur.put(p[i], next);
            }
            if (next.shape == null) next.shape = sh;
            cur = next;
        }
        if (cur.type != p[p.length - 1].needs()) return null;
        return cur;
    }

    /** True when an item stands at the path, or a value stands on the way to it: nothing more is written there. */
    private static boolean taken(ONode top, Step[] p) {
        ONode cur = top;
        for (int i = 0; i < p.length; i++) {
            if (cur.type != p[i].needs()) return true;
            ONode next = cur.get(p[i]);
            if (next == null) return false;
            cur = next;
        }
        return true;
    }

    @Override
    String encodeKind(Entity e, Pack.Kind kind) {
        PNode root = (PNode) kind.scope.info;
        ONode top = new ONode(topArray ? ARRAY : MAP, root);
        encodeScope(top, kind.scope, e);
        for (Map.Entry<String, String> r : e.residue(pack.format).entrySet()) placeResidue(top, root, r.getKey(), r.getValue());
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        if (pack.cborTagged) head(out, 6, pack.cborTag);
        write(top, out);
        return toHex(out.toByteArray());
    }

    /** Write one scope's lines into {@code top}: when and const values over fields (ruling 16 of 0.5), then groups. */
    private void encodeScope(ONode top, Pack.Scope scope, Entity e) {
        PNode shape = (PNode) scope.info;
        for (Pack.Line l : scope.lines) {
            if (!(l instanceof Pack.When) || ((Pack.When) l).present) continue;
            Step[] p = (Step[]) l.loc;
            if (taken(top, p)) continue;                // the earliest value on the path
            parent(top, p, shape).put(p[p.length - 1], leaf(((Pack.When) l).cbor));
        }
        for (Pack.Line l : scope.lines) {
            Step[] p = (Step[]) l.loc;
            if (l instanceof Pack.Group) {
                Pack.Group g = (Pack.Group) l;
                List<Entity> items = e.list(g.list);
                if (items == null) continue;            // an absent list writes nothing
                ONode arr;
                if (p.length == 0) {
                    arr = top;                          // `group <list> .`: the top item is the list
                } else {
                    if (taken(top, p)) continue;
                    arr = new ONode(ARRAY, null);
                    parent(top, p, shape).put(p[p.length - 1], arr);
                }
                PNode body = (PNode) g.body.info;
                for (int i = 0; i < items.size(); i++) arr.elems.put(i, encodeItem(g, body, items.get(i)));
                continue;
            }
            if (!(l instanceof Pack.Field) || p.length == 0) continue;
            Pack.Field f = (Pack.Field) l;
            if (taken(top, p)) continue;                // a when, a const or an earlier line wrote it
            byte[] v = encodeOne(f, e, scope);
            if (v != null) parent(top, p, shape).put(p[p.length - 1], leaf(v));   // containers only for a value
        }
    }

    /** One element of a group's array (Writing step 4). */
    private ONode encodeItem(Pack.Group g, PNode body, Entity item) {
        if (body.mapped) {
            // a body of `.` lines: the element is the first present value, else null
            for (Pack.Line l : g.body.lines) {
                if (!(l instanceof Pack.Field)) continue;
                byte[] v = encodeOne((Pack.Field) l, item, g.body);
                if (v != null) return leaf(v);
            }
            return leaf(NULL);
        }
        ONode el = new ONode(body.as == ARRAY ? ARRAY : MAP, body);
        encodeScope(el, g.body, item);
        return el;
    }

    /** The encoded item a field writes, or null when the entity lacks the key and the scope has no default. */
    private byte[] encodeOne(Pack.Field f, Entity e, Pack.Scope scope) {
        Object v = valueToEncode(f, e, scope);
        if (v == null) return null;
        try {
            return encodeValue(f.cbor, v);
        } catch (IllegalArgumentException ex) {
            throw encodeFailure(f, ex);
        }
    }

    static byte[] encodeValue(CT t, Object v) {
        ByteArrayOutputStream o = new ByteArrayOutputStream();
        switch (t) {
            case UINT: {
                long n = Transform.asLong(v);
                if (n < 0) throw new IllegalArgumentException("uint carries no negative value, got " + n);
                head(o, 0, n);
                break;
            }
            case INT: {
                long n = Transform.asLong(v);
                if (n >= 0) head(o, 0, n);
                else head(o, 1, -1 - n);
                break;
            }
            case EPOCH_S: {
                long ms = Transform.asLong(v);
                long s = ms / 1000, r = ms % 1000;
                if (Math.abs(r) >= 500) s += ms < 0 ? -1 : 1;   // half away from zero
                if (s >= 0) head(o, 0, s);
                else head(o, 1, -1 - s);
                break;
            }
            case FLOAT: {
                double d = Transform.asDouble(v);
                if (!Double.isFinite(d)) throw new IllegalArgumentException("float " + d + " is not finite");
                writeFloat(o, d);
                break;
            }
            case TEXT: {
                byte[] b = Transform.STRING.encode(v).getBytes(StandardCharsets.UTF_8);
                head(o, 3, b.length);
                o.write(b, 0, b.length);
                break;
            }
            case BYTES: {
                String s = Transform.STRING.encode(v);
                if (s.length() % 2 != 0) throw new IllegalArgumentException("bytes takes an even number of hex digits, got " + s.length());
                for (int i = 0; i < s.length(); i++) {
                    char c = s.charAt(i);
                    if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) {
                        throw new IllegalArgumentException("bytes takes lowercase hex digits, got \"" + s + "\"");
                    }
                }
                byte[] b = fromHexText(s);
                head(o, 2, b.length);
                o.write(b, 0, b.length);
                break;
            }
            default: {
                long b = Transform.asLong(v);
                if (b != 0 && b != 1) throw new IllegalArgumentException("bool carries only 1 and 0, got " + b);
                o.write(b == 1 ? 0xf5 : 0xf4);
            }
        }
        return o.toByteArray();
    }

    /**
     * Put one residue entry back into its map or array, re-encoded under 4.2.1. An entry whose key is not a path of
     * this wire, whose value is not one well-formed item, or whose place a line writes, is not written (ruling 21).
     */
    private void placeResidue(ONode top, PNode shape, String key, String hex) {
        String[] parts = key.split("\\.", -1);
        Step[] p = new Step[parts.length];
        byte[] rawKey = null;
        for (int i = 0; i < parts.length; i++) {
            if (i == parts.length - 1 && parts[i].startsWith("#")) {
                String h = parts[i].substring(1);
                Item k = readOne(h);
                if (k == null) return;
                rawKey = canon(k);
                p[i] = new Step(KEY_TEXT, 3, 0, new byte[0], 0, parts[i]);   // a map member; its key is rawKey
                continue;
            }
            p[i] = parseStep(parts[i]);
            if (p[i] == null) return;
        }
        Item v = readOne(hex);
        if (v == null || (rawKey == null && taken(top, p))) return;   // the line wins (ruling 21)
        ONode c = parent(top, p, shape);
        if (c == null) return;
        Step last = p[p.length - 1];
        if (rawKey != null) {
            String kh = toHex(rawKey);
            if (c.type != MAP || c.members.containsKey(kh)) return;
            c.members.put(kh, leaf(canon(v)));
            return;
        }
        if (c.get(last) != null) return;   // the line wins
        c.put(last, leaf(canon(v)));
    }

    /** Exactly one well-formed item from hex text, or null. */
    private Item readOne(String hex) {
        try {
            byte[] b = fromHex(hex);
            Reader r = new Reader(b);
            Item it = r.item(1);
            return r.pos == b.length ? it : null;
        } catch (GtException ex) {
            return null;
        }
    }

    private void write(ONode n, ByteArrayOutputStream o) {
        if (n.type == 0) {
            o.write(n.leaf, 0, n.leaf.length);
        } else if (n.type == MAP) {
            head(o, 5, n.members.size());
            for (Map.Entry<String, ONode> m : n.members.entrySet()) {
                byte[] k = fromHexText(m.getKey());
                o.write(k, 0, k.length);
                write(m.getValue(), o);
            }
        } else {
            int len = n.elems.isEmpty() ? 0 : n.elems.lastKey() + 1;
            head(o, 4, len);
            for (int i = 0; i < len; i++) {
                ONode el = n.elems.get(i);
                if (el != null) {
                    write(el, o);
                    continue;
                }
                // a gap below the highest present position (Writing step 3, ruling 23)
                PNode k = n.shape == null ? null : n.shape.kids.get("[" + i + "]");
                byte[] gap = k != null && k.walked && !k.group ? (k.as == MAP ? EMPTY_MAP : k.as == ARRAY ? EMPTY_ARRAY : NULL) : NULL;
                o.write(gap, 0, gap.length);
            }
        }
    }
}
