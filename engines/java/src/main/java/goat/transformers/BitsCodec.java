package goat.transformers;

import java.util.ArrayList;
import java.util.List;

/**
 * The {@code bits} wire: a message is a sequence of fixed-size binary words whose fields are bit ranges, carried in
 * and out as hex text. A locator {@code <word>:<pos>:<len>} addresses {@code len} bits starting at bit
 * {@code word * word_bytes * 8 + pos} of the message, and may run past its word. With {@code bit_order lsb} bit
 * {@code i} of the message is bit {@code i mod 8} of byte {@code i div 8} and a value's first bit is its least
 * significant; with {@code msb} it is bit {@code 7 - (i mod 8)} and a value's first bit is its most significant.
 * {@code encode} writes only mapped fields and {@code when} values and leaves every other bit zero.
 */
final class BitsCodec extends Codec<byte[]> {
    private final int wordBytes;
    private final boolean msb;

    /** A parsed locator: first bit, counted from the start of its scope (the message, or one item), and bit length. */
    private static final class Loc {
        final long start;
        final int len;
        Loc(long start, int len) { this.start = start; this.len = len; }
        long end() { return start + len; }
    }

    /**
     * The fixed extent of a scope in bits from its start: {@code need} is what decode requires (every line but
     * {@code optional} fields), {@code end} what encode writes. The items of a group counted by a locator extend
     * both as the message is read or written.
     */
    private static final class Info {
        final long need;
        final long end;
        Info(long need, long end) { this.need = need; this.end = end; }
    }

    BitsCodec(Pack pack) {
        super(pack);
        this.wordBytes = pack.wordBytes;
        this.msb = pack.msbFirst;
        // Pack.parse has prepared every scope: the bits checks are load checks.
    }

    private static Loc loc(String locator, int wordBytes) {
        int[] wpl = parseLoc(locator);
        return new Loc((long) wpl[0] * wordBytes * 8 + wpl[1], wpl[2]);
    }

    private static GtException layout(String format, Pack.Line l, String source, String why) {
        return new GtException(GtException.Code.BAD_DIRECTIVE, format, l.locator, source + ":" + l.line + ": " + why);
    }

    /**
     * Parse the locators of one scope (the common lines plus one kind, or one group body; nested bodies were
     * prepared when they were resolved), record its fixed extent and check its layout (engine-spec 0.7):
     * nothing lies at or beyond the start of a group counted by a locator, and, in a body of {@code itemBits} bits
     * ({@code 0} for the message), nothing but such a group reaches beyond the item.
     */
    static void prepare(Pack.Scope scope, int wordBytes, int itemBits, String format, String source) {
        long need = 0, end = 0;
        Pack.Group counted = null;
        for (Pack.Line l : scope.lines) {
            if (l instanceof Pack.Group) {
                Pack.Group g = (Pack.Group) l;
                if (l.loc == null) {
                    String[] p = l.locator.split(":", -1);
                    l.loc = new Loc((long) Integer.parseInt(p[0]) * wordBytes * 8 + Integer.parseInt(p[1]), 0);
                    if (g.countLocator != null) g.countLoc = loc(g.countLocator, wordBytes);
                }
                long ext;
                if (g.countLocator != null) {
                    if (counted != null) {
                        // whichever of the two starts later starts at or beyond the other
                        throw layout(format, g, source, "a second group in the scope of a group counted by a locator, which is the last thing in its scope");
                    }
                    counted = g;
                    ext = ((Loc) g.countLoc).end();
                } else {
                    try {
                        ext = Math.addExact(((Loc) l.loc).start, Math.multiplyExact(g.countFixed, (long) g.itemBits));
                    } catch (ArithmeticException ex) {
                        throw new GtException(GtException.Code.BAD_PACK, format, l.locator, source + ":" + l.line + ": the group is too long");
                    }
                }
                need = Math.max(need, ext);
                end = Math.max(end, ext);
                if (itemBits > 0 && ext > itemBits) {
                    throw layout(format, g, source, (g.countLocator != null ? "the count locator" : "a nested group with a fixed count")
                            + " reaches beyond item " + itemBits);
                }
                continue;
            }
            if (l.loc == null) l.loc = loc(l.locator, wordBytes);
            long e = ((Loc) l.loc).end();
            end = Math.max(end, e);
            // Decode needs every mapped bit but those of `optional` fields.
            if (!(l instanceof Pack.Field && ((Pack.Field) l).optional)) need = Math.max(need, e);
            if (itemBits > 0 && e > itemBits) throw layout(format, l, source, "the line reaches beyond item " + itemBits);
        }
        if (counted != null) {
            long start = ((Loc) counted.loc).start;
            for (Pack.Line l : scope.lines) {
                if (l == counted) {
                    if (((Loc) counted.countLoc).end() > start) {
                        throw layout(format, l, source, "the count locator reaches the start of its group");
                    }
                } else if (l instanceof Pack.Group) {
                    Pack.Group g = (Pack.Group) l;
                    if (((Loc) l.loc).start >= start) {
                        throw layout(format, l, source, "a group at or beyond the start of a group counted by a locator");
                    }
                    // a fixed-count group that starts before it and whose items reach its start (ruling 16 of 0.7)
                    if (g.countLocator == null && ((Loc) l.loc).start + g.countFixed * g.itemBits > start) {
                        throw layout(format, l, source, "the items of a fixed-count group reach the start of a group counted by a locator");
                    }
                } else if (((Loc) l.loc).end() > start) {
                    throw layout(format, l, source, "bits at or beyond the start of a group counted by a locator");
                }
            }
        }
        scope.info = new Info(need, end);
    }

    /** Null when {@code locator} is a well-formed bits group locator {@code <word>:<pos>}, else the reason. */
    static String checkGroupLocator(String locator) {
        String[] p = locator.split(":", -1);
        if (p.length != 2) return "a bits group locator is word:pos: " + locator;
        try {
            if (Integer.parseInt(p[0]) < 0 || Integer.parseInt(p[1]) < 0) return "bits word and pos must be >= 0: " + locator;
        } catch (NumberFormatException ex) {
            return "bits group locator word:pos must be integers: " + locator;
        }
        return null;
    }

    /** The bytes of as many whole words as reach bit {@code end}. */
    private int wholeWords(long end) {
        long wordBits = (long) wordBytes * 8;
        long bytes = (end + wordBits - 1) / wordBits * wordBytes;
        if (bytes > Integer.MAX_VALUE - 16) {
            throw new GtException(GtException.Code.BAD_PACK, pack.format, null, "bits message is too long: " + bytes + " bytes");
        }
        return (int) bytes;
    }

    /** The low {@code len} bits of {@code v} with their bytes in reverse order ({@code len} is a multiple of 8). */
    static long swapBytes(long v, int len) {
        return len == 64 ? Long.reverseBytes(v) : Long.reverseBytes(v) >>> (64 - len);
    }

    private static void reverse(byte[] b) {
        for (int i = 0, j = b.length - 1; i < j; i++, j--) {
            byte t = b[i];
            b[i] = b[j];
            b[j] = t;
        }
    }

    /** {@code word:pos:len} to {@code int[]{word, pos, len}}. Assumes {@link #checkLocator} has passed. */
    static int[] parseLoc(String locator) {
        String[] p = locator.split(":", -1);
        return new int[]{ Integer.parseInt(p[0]), Integer.parseInt(p[1]), Integer.parseInt(p[2]) };
    }

    /** Null when {@code locator} is a well-formed bits locator, else the reason. The transform checks the length. */
    static String checkLocator(String locator) {
        String[] p = locator.split(":", -1);
        if (p.length != 3) return "bits locator must be word:pos:len: " + locator;
        int word;
        int pos;
        int len;
        try {
            word = Integer.parseInt(p[0]);
            pos = Integer.parseInt(p[1]);
            len = Integer.parseInt(p[2]);
        } catch (NumberFormatException ex) {
            return "bits locator word:pos:len must be integers: " + locator;
        }
        if (word < 0) return "bits word index must be >= 0: " + locator;
        if (pos < 0) return "bits pos must be >= 0: " + locator;
        if (len < 1) return "bits len must be >= 1: " + locator;
        return null;
    }

    @Override
    byte[] parse(String text) { return fromHex(text); }

    @Override
    boolean holds(byte[] msg, Pack.When when) {
        Loc loc = (Loc) when.loc;
        if (loc.start + loc.len > (long) msg.length * 8) return false; // beyond the input: does not hold
        return readBits(msg, loc.start, loc.len) == when.number;
    }

    @Override
    Entity decodeKind(byte[] msg, Pack.Kind kind) {
        Info info = (Info) kind.scope.info;
        int need = wholeWords(info.need);
        if (msg.length < need) throw tooShort(msg, need, kind);
        Entity e = new Entity();
        Failures fails = new Failures();
        long far = decodeScope(msg, (long) msg.length * 8, kind.scope, 0, e, fails);
        // The message is extended by the items, to whole words.
        need = wholeWords(Math.max(info.need, far));
        if (msg.length < need) throw tooShort(msg, need, kind);
        finishDecode(e, fails);
        return e;
    }

    private GtException tooShort(byte[] msg, int need, Pack.Kind kind) {
        return malformed("bits message is " + msg.length + " bytes, shorter than the " + need + " bytes"
                + (kind.name == null ? "" : " of kind " + kind.name) + " (words of " + wordBytes + ")");
    }

    /**
     * Decode the lines of one scope that starts at bit {@code base} of the message. Returns the bit after the last
     * item of its groups, or 0 when it has none.
     */
    private long decodeScope(byte[] msg, long bits, Pack.Scope scope, long base, Entity e, Failures fails) {
        long far = 0;
        for (Pack.Line l : scope.lines) {
            if (l instanceof Pack.Group) {
                Pack.Group g = (Pack.Group) l;
                long n = g.countFixed;
                if (g.countLocator != null) {
                    Loc c = (Loc) g.countLoc;
                    if (base + c.end() > bits) throw malformed("the input ends before the count of " + g.list + " at " + g.countLocator);
                    n = readBits(msg, base + c.start, c.len);
                }
                long pos = base + ((Loc) g.loc).start;
                List<Entity> items = new ArrayList<>((int) Math.min(n & 0xffff, 4096));
                for (long i = 0; i != n; i++) {
                    if (pos + g.itemBits > bits) {
                        throw malformed("the input ends before item " + i + " of the " + Long.toUnsignedString(n) + " of " + g.list);
                    }
                    Entity item = new Entity();
                    long nested = decodeScope(msg, bits, g.body, pos, item, fails);
                    // A nested group counted by a locator may run past the item: the next item starts where it ends.
                    pos = Math.max(pos + g.itemBits, nested);
                    items.add(item);
                }
                e.putList(g.list, items);
                far = Math.max(far, pos);
                continue;
            }
            if (!(l instanceof Pack.Field)) continue;
            Pack.Field f = (Pack.Field) l;
            Loc loc = (Loc) l.loc;
            if (e.get(f.key) != null) continue;          // an earlier line already gave the key its value
            long start = base + loc.start;
            if (start + loc.len > bits) {
                if (f.optional) continue;                // beyond the input: absent
                throw malformed("the input ends before " + f.key + " at " + f.locator);
            }
            Object v;
            try {
                if (f.bits.isAscii()) {
                    byte[] bytes = new byte[loc.len / 8];
                    for (int i = 0; i < bytes.length; i++) bytes[i] = (byte) readBits(msg, start + 8L * i, 8);
                    if (f.swap) reverse(bytes);
                    v = f.bits.decodeAscii(bytes, f.trim);
                } else {
                    long raw = readBits(msg, start, loc.len);
                    v = f.bits.decode(f.swap ? swapBytes(raw, loc.len) : raw, loc.len);
                }
            } catch (IllegalArgumentException ex) {
                fails.add(f, ex.getMessage(), e);
                continue;
            }
            putDecoded(f, v, e, fails);
        }
        return far;
    }

    /** The message being written: grows as items are added; bits not written are zero. */
    private static final class Buf {
        byte[] b;
        Buf(int bytes) { b = new byte[bytes]; }
        void ensure(long bits) {
            long bytes = (bits + 7) >>> 3;
            if (bytes <= b.length) return;
            if (bytes > Integer.MAX_VALUE - 16) throw new IllegalStateException("bits message is too long");
            b = java.util.Arrays.copyOf(b, (int) Math.max(bytes, b.length * 2L));
        }
    }

    @Override
    String encodeKind(Entity e, Pack.Kind kind) {
        Info info = (Info) kind.scope.info;
        Buf buf = new Buf(wholeWords(info.end));
        long far = encodeScope(buf, kind.scope, 0, e);
        return toHex(java.util.Arrays.copyOf(buf.b, wholeWords(Math.max(info.end, far))));
    }

    private GtException groupFailure(Pack.Group g, String why) {
        return new GtException(GtException.Code.TRANSFORM_ENCODE, pack.format, g.locator, g.list + ": " + why);
    }

    /**
     * Write the lines of one scope that starts at bit {@code base}. Returns the bit after the last item of its
     * groups, or 0 when it has none.
     */
    private long encodeScope(Buf buf, Pack.Scope scope, long base, Entity e) {
        buf.ensure(base + ((Info) scope.info).end);
        // Fields last line first, so that where two present fields cover the same bits the earlier line's value stays.
        List<Pack.Line> lines = scope.lines;
        for (int i = lines.size() - 1; i >= 0; i--) {
            if (!(lines.get(i) instanceof Pack.Field)) continue;
            Pack.Field f = (Pack.Field) lines.get(i);
            Object v = valueToEncode(f, e, scope);
            if (v == null) continue; // absent key and no default: its bits stay zero
            Loc loc = (Loc) f.loc;
            long start = base + loc.start;
            try {
                if (f.bits.isAscii()) {
                    byte[] bytes = f.bits.encodeAscii(v, loc.len / 8);
                    if (f.swap) reverse(bytes);
                    for (int b = 0; b < bytes.length; b++) writeBits(buf.b, start + 8L * b, 8, bytes[b] & 0xffL);
                } else {
                    long raw = f.bits.encode(v, loc.len);
                    writeBits(buf.b, start, loc.len, f.swap ? swapBytes(raw, loc.len) : raw);
                }
            } catch (IllegalArgumentException ex) {
                throw encodeFailure(f, ex);
            }
        }
        // const values are written over any field, then when values (ruling 15 of 0.7)
        for (int pass = 0; pass < 2; pass++) {
            for (Pack.Line l : lines) {
                if (!(l instanceof Pack.When) || ((Pack.When) l).isConst != (pass == 0)) continue;
                Loc loc = (Loc) l.loc;
                writeBits(buf.b, base + loc.start, loc.len, ((Pack.When) l).number);
            }
        }
        // groups: the items back to back; a count locator holds their number, written over any field there
        long far = 0;
        for (Pack.Group g : scope.groups) {
            List<Entity> items = e.list(g.list);
            int n = items == null ? 0 : items.size();
            if (g.countLocator == null) {
                if (items == null) throw groupFailure(g, "the list is absent and the group has the fixed count " + g.countFixed);
                if (n != g.countFixed) throw groupFailure(g, n + " items, and the group has the fixed count " + g.countFixed);
            } else {
                Loc c = (Loc) g.countLoc;
                if (c.len < 63 && n > BitsTransform.mask(c.len)) {
                    throw groupFailure(g, n + " items do not fit the " + c.len + "-bit count at " + g.countLocator);
                }
                writeBits(buf.b, base + c.start, c.len, n);
            }
            long pos = base + ((Loc) g.loc).start;
            for (int i = 0; i < n; i++) {
                buf.ensure(pos + g.itemBits);
                long nested = encodeScope(buf, g.body, pos, items.get(i));
                pos = Math.max(pos + g.itemBits, nested);
            }
            buf.ensure(pos);
            far = Math.max(far, pos);
        }
        return far;
    }

    private long readBits(byte[] msg, long start, int len) { return readBits(msg, start, len, msb); }

    private void writeBits(byte[] msg, long start, int len, long value) { writeBits(msg, start, len, value, msb); }

    /** The {@code len} bits from bit {@code start} of the message, in the bit order {@code msb} names. */
    static long readBits(byte[] msg, long start, int len, boolean msb) {
        long v = 0;
        for (int k = 0; k < len; k++) {
            long j = start + k;
            int by = msg[(int) (j >>> 3)] & 0xff;
            if (msb) {
                v = (v << 1) | ((by >>> (7 - (int) (j & 7))) & 1);
            } else {
                v |= (long) ((by >>> (int) (j & 7)) & 1) << k;
            }
        }
        return v;
    }

    static void writeBits(byte[] msg, long start, int len, long value, boolean msb) {
        for (int k = 0; k < len; k++) {
            long j = start + k;
            int idx = (int) (j >>> 3);
            int bitMask;
            boolean set;
            if (msb) {
                bitMask = 1 << (7 - (int) (j & 7));
                set = ((value >>> (len - 1 - k)) & 1L) != 0;
            } else {
                bitMask = 1 << (int) (j & 7);
                set = ((value >>> k) & 1L) != 0;
            }
            int by = msg[idx] & 0xff;
            msg[idx] = (byte) (set ? (by | bitMask) : (by & ~bitMask));
        }
    }

    static void reverseBytes(byte[] b) { reverse(b); }
}
