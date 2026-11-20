package goat.transformers;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * The {@code bits} wire: a message is a sequence of fixed-size binary words whose fields are bit ranges, carried in
 * and out as hex text. A locator {@code <word>:<pos>:<len>} addresses {@code len} bits starting at bit
 * {@code word * word_bytes * 8 + pos} of the message, and may run past its word. With {@code bit_order lsb} bit
 * {@code i} of the message is bit {@code i mod 8} of byte {@code i div 8} and a value's first bit is its least
 * significant; with {@code msb} it is bit {@code 7 - (i mod 8)} and a value's first bit is its most significant.
 * {@code encode} writes only mapped fields and {@code when} values and leaves every other bit zero. With
 * {@code armor sixbit} (engine-spec 0.14) the message is armored text of any number of bits: decode needs the bits
 * the lines reach, not whole words, and encode writes the first {@code L} bits.
 */
final class BitsCodec extends Codec<Codec.BitMsg> {
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
        /** The furthest bit of any line, the lines and locators of gate blocks included (the buffer encode needs). */
        final long all;
        /** True when the scope has a gate block (engine-spec 0.17). */
        final boolean gated;
        Info(long need, long end, long all, boolean gated) {
            this.need = need;
            this.end = end;
            this.all = all;
            this.gated = gated;
        }
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
        long need = 0, end = 0, all = 0;
        boolean gated = false;
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
                        throw new GtException(GtException.Code.BAD_DIRECTIVE, format, l.locator, source + ":" + l.line + ": the group is too long");
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
            if (l instanceof Pack.Gate) {
                // A gate and its lines count toward no fixed extent: decode and encode measure the blocks that hold.
                gated = true;
                for (Pack.Line b : gateLines((Pack.Gate) l, new ArrayList<>())) {
                    if (b.loc == null) b.loc = loc(b.locator, wordBytes);
                    long e = ((Loc) b.loc).end();
                    all = Math.max(all, e);
                    if (itemBits > 0 && e > itemBits) {
                        throw layout(format, b, source, (b instanceof Pack.Gate ? "the gate" : "a line of an if block")
                                + " reaches beyond item " + itemBits);
                    }
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
        if (gated) {
            // A gate any of whose bits lies within the items of a fixed-count group of its scope (ruling 9 of 0.17).
            for (Pack.Group g : scope.groups) {
                if (g.countLocator != null) continue;
                long gs = ((Loc) g.loc).start, ge = gs + g.countFixed * g.itemBits;
                for (Pack.Line l : scope.lines) {
                    if (!(l instanceof Pack.Gate)) continue;
                    for (Pack.Line b : gateLines((Pack.Gate) l, new ArrayList<>())) {
                        if (!(b instanceof Pack.Gate)) continue;
                        Loc c = (Loc) b.loc;
                        if (c.start < ge && c.end() > gs) {
                            throw layout(format, b, source, "the gate lies within the items of group " + g.list);
                        }
                    }
                }
            }
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
                } else if (l instanceof Pack.Gate) {
                    for (Pack.Line b : gateLines((Pack.Gate) l, new ArrayList<>())) {
                        if (((Loc) b.loc).end() > start) {
                            throw layout(format, b, source, (b instanceof Pack.Gate ? "a gate" : "a line of an if block")
                                    + " at or beyond the start of a group counted by a locator");
                        }
                    }
                } else if (((Loc) l.loc).end() > start) {
                    throw layout(format, l, source, "bits at or beyond the start of a group counted by a locator");
                }
            }
        }
        scope.info = new Info(need, end, Math.max(all, end), gated);
    }

    /** The gate itself and every line of its block, nested blocks included, in line order, added to {@code out}. */
    private static List<Pack.Line> gateLines(Pack.Gate g, List<Pack.Line> out) {
        out.add(g);
        for (Pack.Line b : g.body.lines) {
            if (b instanceof Pack.Gate) gateLines((Pack.Gate) b, out);
            else out.add(b);
        }
        return out;
    }

    /** Null when {@code locator} is a well-formed bits group locator {@code <word>:<pos>}, else the reason. */
    static String checkGroupLocator(String locator) {
        String[] p = locator.split(":", -1);
        if (p.length != 2) return "a bits group locator is word:pos: " + locator;
        for (String part : p) {
            if (!Transform.UNSIGNED.matcher(part).matches()) return "a bits group locator word:pos takes two digit-only parts: " + locator;
        }
        try {
            if (Integer.parseInt(p[0]) < 0 || Integer.parseInt(p[1]) < 0) return "bits word and pos must be >= 0: " + locator;
        } catch (NumberFormatException ex) {
            return "bits group locator word:pos must be integers: " + locator;
        }
        return null;
    }

    /** The bytes of as many whole words as reach bit {@code end}. */
    private int wholeWords(long end) { return wholeWords(end, GtException.Code.MALFORMED_WIRE); }

    /** As {@link #wholeWords(long)}; a message too long to hold fails with {@code code}. */
    private int wholeWords(long end, GtException.Code code) {
        long wordBits = (long) wordBytes * 8;
        long bytes = (end + wordBits - 1) / wordBits * wordBytes;
        if (bytes > Integer.MAX_VALUE - 16) {
            throw new GtException(code, pack.format, null, "bits message is too long: " + bytes + " bytes");
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
        for (String part : p) {
            if (!Transform.UNSIGNED.matcher(part).matches()) return "bits locator word:pos:len takes three digit-only parts: " + locator;
        }
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
    BitMsg parse(String text) { return parseBits(text); }

    @Override
    boolean holds(BitMsg msg, Pack.When when) {
        Loc loc = (Loc) when.loc;
        if (loc.start + loc.len > msg.bits) return false; // beyond the input: does not hold
        return when.matches(readBits(msg.b, loc.start, loc.len));   // a value, a list or a range (0.20)
    }

    @Override
    Entity decodeKind(BitMsg in, Pack.Kind kind) {
        Info info = (Info) kind.scope.info;
        byte[] msg = in.b;
        if (pack.armorSixbit) {
            // Armored text: the bits the lines reach, whatever word_bytes is (0.14, "Fixed layout").
            if (in.bits < info.need) throw armorShort(in.bits, info.need, kind);
        } else {
            int need = wholeWords(info.need);
            if (msg.length < need) throw tooShort(msg, need, kind);
        }
        Entity e = new Entity();
        Failures fails = new Failures();
        long far = decodeScope(msg, in.bits, kind.scope, 0, e, fails);
        if (pack.armorSixbit) {
            if (in.bits < far) throw armorShort(in.bits, far, kind);
        } else {
            // The message is extended by the items, to whole words.
            int need = wholeWords(Math.max(info.need, far));
            if (msg.length < need) throw tooShort(msg, need, kind);
        }
        finishDecode(e, fails);
        return e;
    }

    private GtException armorShort(long bits, long need, Pack.Kind kind) {
        return malformed("armored message is " + bits + " bits, shorter than the " + need + " bits"
                + (kind.name == null ? "" : " of kind " + kind.name) + " its lines reach");
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
        return decodeLines(msg, bits, scope.lines, base, false, e, fails);
    }

    /**
     * True when gate {@code g} of a scope at bit {@code base} holds on {@code msg}, of which {@code bits} bits are
     * input: a gate any of whose bits lies beyond them does not hold, nor does its {@code !} form.
     */
    private boolean gateHolds(byte[] msg, long bits, long base, Pack.Gate g) {
        Loc loc = (Loc) g.loc;
        if (base + loc.end() > bits) return false;
        return g.holds(readBits(msg, base + loc.start, loc.len));
    }

    /**
     * Decode {@code lines} of a scope at bit {@code base}; {@code held}: they are the lines of a gate block that
     * holds. Returns the furthest bit the decode requires beyond the scope's fixed extent: the end of the items of
     * its groups, and the lines of the blocks that hold (their {@code optional} fields excepted), or 0.
     */
    private long decodeLines(byte[] msg, long bits, List<Pack.Line> lines, long base, boolean held, Entity e, Failures fails) {
        long far = 0;
        for (Pack.Line l : lines) {
            if (l instanceof Pack.Gate) {
                Pack.Gate g = (Pack.Gate) l;
                // A block that does not hold sets no key; its lines count as lines whose locator is absent.
                if (gateHolds(msg, bits, base, g)) far = Math.max(far, decodeLines(msg, bits, g.body.lines, base, true, e, fails));
                continue;
            }
            if (held && !(l instanceof Pack.Field && ((Pack.Field) l).optional)) {
                far = Math.max(far, base + ((Loc) l.loc).end());   // a held block's fields and consts count
            }
            if (l instanceof Pack.Group) {
                Pack.Group g = (Pack.Group) l;
                long n = g.countFixed;
                if (g.countLocator != null) {
                    Loc c = (Loc) g.countLoc;
                    if (base + c.end() > bits) throw malformed("the input ends before the count of " + g.list + " at " + g.countLocator);
                    n = readBits(msg, base + c.start, c.len);
                }
                takeItems(n);   // compared with the limit before any item is read (ruling 7d of 0.11)
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
            if (f.absent != null) {
                // the raw value, as uint reads it, after swap: a sentinel is a line whose locator is absent
                long raw = readBits(msg, start, loc.len);
                if (f.absent.matches(f.swap ? swapBytes(raw, loc.len) : raw)) continue;
            }
            Object v;
            try {
                if (f.bits.isChars()) {
                    // character i is the w bits from bit i * w of the field, read as uint reads them
                    int w = f.bits.charWidth();
                    int[] codes = new int[loc.len / w];
                    for (int i = 0; i < codes.length; i++) codes[i] = (int) readBits(msg, start + (long) w * i, w);
                    v = f.bits.decodeChars(codes);
                } else if (f.bits.isAscii()) {
                    byte[] bytes = new byte[loc.len / 8];
                    for (int i = 0; i < bytes.length; i++) bytes[i] = (byte) readBits(msg, start + 8L * i, 8);
                    if (f.swap) reverse(bytes);
                    v = f.bits.decodeAscii(bytes, f.trim);
                } else if (f.bits.isSixbit()) {
                    v = BitsTransform.decodeSixbit(readSixbit(msg, start, loc.len, msb), f.trim);
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
            if (bytes > Integer.MAX_VALUE - 16) {
                throw new GtException(GtException.Code.TRANSFORM_ENCODE, null, null, "the message is too long: " + bytes + " bytes");
            }
            b = java.util.Arrays.copyOf(b, (int) Math.max(bytes, b.length * 2L));
        }
    }

    @Override
    String encodeKind(Entity e, Pack.Kind kind) {
        Info info = (Info) kind.scope.info;
        Buf buf = new Buf(wholeWords(info.all, GtException.Code.TRANSFORM_ENCODE));
        List<Choice> choices = new ArrayList<>();
        long far = encodeScope(buf, kind.scope, 0, e, choices);
        byte[] out;
        long outBits;
        long armorBits = 0;
        if (pack.armorSixbit) {
            // the first L bits (0.14); the decoder sees them padded to whole six-bit characters
            armorBits = armorLength(kind.scope, e, far);
            outBits = (armorBits + 5) / 6 * 6;
            out = java.util.Arrays.copyOf(buf.b, (int) ((outBits + 7) >>> 3));
            for (long i = armorBits; i < outBits; i++) writeBits(out, i, 1, 0);   // the zero fill bits
        } else {
            out = java.util.Arrays.copyOf(buf.b, wholeWords(Math.max(info.end, far), GtException.Code.TRANSFORM_ENCODE));
            outBits = (long) out.length * 8;
        }
        // Step 6 of 0.17, once on the final output for every scope and item: it decodes to the same choice.
        for (Choice c : choices) {
            Set<Pack.Gate> got = newGateSet();
            evaluate(out, outBits, c.base, c.lines, got);
            for (Pack.Gate g : c.all) {
                if (got.contains(g) != c.held.contains(g)) {
                    throw new GtException(GtException.Code.TRANSFORM_ENCODE, pack.format, g.locator, "the if block at "
                            + g.locator + (c.held.contains(g) ? " does not hold" : " holds") + " on the output, unlike the choice encode made");
                }
            }
        }
        return pack.armorSixbit ? toArmor(buf.b, armorBits) : toHex(out);
    }

    /**
     * {@code L} of 0.14 in the fixed layout: one more than the highest bit of any field, when or const line of the
     * scope, or of a group's items (a count locator counts, whatever the list), except an {@code optional} field
     * whose key is absent with no default and no {@code absent} sentinel. {@code far} is the bit after the last item
     * written, or after the last line or gate locator of a held gate block (0.17).
     */
    private static long armorLength(Pack.Scope scope, Entity e, long far) {
        long l = far;
        for (Pack.Line line : scope.lines) {
            if (line instanceof Pack.Group) {
                Pack.Group g = (Pack.Group) line;
                if (g.countLocator != null) l = Math.max(l, ((Loc) g.countLoc).end());
                else if (g.countFixed > 0) l = Math.max(l, ((Loc) g.loc).start + g.countFixed * (long) g.itemBits);
                continue;
            }
            // a gate block counts through {@code far}: its locator and lines when it is held (0.17, Encode)
            if (line instanceof Pack.Gate) continue;
            if (line instanceof Pack.Field) {
                Pack.Field f = (Pack.Field) line;
                // A field with absent writes its first sentinel, so it counts, optional or not (ruling 12 of 0.14).
                // A line suppressed by `with` writes neither its value, its default nor its sentinel (ruling 1 of 0.18).
                if (f.optional && (f.suppressed(e)
                        || (f.absent == null && e.get(f.key) == null && scope.defaultValues.get(f.key) == null))) continue;
            }
            l = Math.max(l, ((Loc) line.loc).end());
        }
        return l;
    }

    /** The gate blocks of one scope (or item) at bit {@code base}, and those encode chose to hold. */
    private static final class Choice {
        final long base;
        final List<Pack.Line> lines;
        final List<Pack.Gate> all;
        final Set<Pack.Gate> held;
        Choice(long base, List<Pack.Line> lines, List<Pack.Gate> all, Set<Pack.Gate> held) {
            this.base = base;
            this.lines = lines;
            this.all = all;
            this.held = held;
        }
    }

    private static Set<Pack.Gate> newGateSet() { return java.util.Collections.newSetFromMap(new java.util.IdentityHashMap<>()); }

    /** Add to {@code held} the blocks of {@code lines} that hold on {@code msg}; a nested block only when its block holds. */
    private void evaluate(byte[] msg, long bits, long base, List<Pack.Line> lines, Set<Pack.Gate> held) {
        for (Pack.Line l : lines) {
            if (!(l instanceof Pack.Gate)) continue;
            Pack.Gate g = (Pack.Gate) l;
            if (gateHolds(msg, bits, base, g)) {
                held.add(g);
                evaluate(msg, bits, base, g.body.lines, held);
            }
        }
    }

    /** Every gate of {@code lines}, nested ones included, in line order, depth first. */
    private static void gates(List<Pack.Line> lines, List<Pack.Gate> out) {
        for (Pack.Line l : lines) {
            if (!(l instanceof Pack.Gate)) continue;
            out.add((Pack.Gate) l);
            gates(((Pack.Gate) l).body.lines, out);
        }
    }

    /**
     * A block is open when one of its field lines, or a line of a nested open block, maps a key the entity (or the
     * item) holds; a default or a sentinel does not open it. Adds the open blocks of {@code lines} to {@code open}.
     */
    private static boolean open(List<Pack.Line> lines, Entity e, Set<Pack.Gate> open) {
        boolean any = false;
        for (Pack.Line l : lines) {
            if (l instanceof Pack.Field) {
                // a line suppressed by `with` opens no block (ruling 1 of 0.18)
                if (held((Pack.Field) l, e)) any = true;
            } else if (l instanceof Pack.Gate) {
                Pack.Gate g = (Pack.Gate) l;
                if (open(g.body.lines, e, open)) {
                    open.add(g);
                    any = true;
                }
            }
        }
        return any;
    }

    /**
     * The lines written for a scope: those outside any block and those of the held blocks, in line order, each field
     * with the defaults in force for it (a block's own defaults over those of the blocks around it and the scope's).
     */
    private static void participating(List<Pack.Line> lines, Set<Pack.Gate> held, Map<String, Object> defaults,
                                      List<Pack.Line> out, List<Map<String, Object>> outDefaults, List<Pack.Gate> heldOut) {
        for (Pack.Line l : lines) {
            if (l instanceof Pack.Gate) {
                Pack.Gate g = (Pack.Gate) l;
                if (!held.contains(g)) continue;
                heldOut.add(g);
                Map<String, Object> d = defaults;
                if (!g.body.defaultValues.isEmpty()) {
                    d = new java.util.HashMap<>(defaults);
                    d.putAll(g.body.defaultValues);
                }
                participating(g.body.lines, held, d, out, outDefaults, heldOut);
            } else if (!(l instanceof Pack.Group)) {
                out.add(l);
                outDefaults.add(defaults);
            }
        }
    }

    private GtException groupFailure(Pack.Group g, String why) {
        return new GtException(GtException.Code.TRANSFORM_ENCODE, pack.format, g.locator, g.list + ": " + why);
    }

    /** Write one field's value at bit {@code start}, by its transform, {@code swap} included. */
    private void writeValue(byte[] b, long start, Pack.Field f, Object v) {
        Loc loc = (Loc) f.loc;
        try {
            if (f.bits.isChars()) {
                int w = f.bits.charWidth();
                int[] codes = f.bits.encodeChars(v, loc.len / w);
                for (int c = 0; c < codes.length; c++) writeBits(b, start + (long) w * c, w, codes[c]);
            } else if (f.bits.isAscii()) {
                byte[] bytes = f.bits.encodeAscii(v, loc.len / 8);
                if (f.swap) reverse(bytes);
                for (int i = 0; i < bytes.length; i++) writeBits(b, start + 8L * i, 8, bytes[i] & 0xffL);
            } else if (f.bits.isSixbit()) {
                writeSixbit(b, start, BitsTransform.encodeSixbit(v, loc.len / 6), msb);
            } else {
                long raw = f.bits.encode(v, loc.len);
                writeBits(b, start, loc.len, f.swap ? swapBytes(raw, loc.len) : raw);
            }
        } catch (IllegalArgumentException ex) {
            throw encodeFailure(f, ex);
        }
    }

    /**
     * The 0.5 encode of {@code lines} (fields, const and when lines, in line order) into a scope at bit {@code base}:
     * the sentinels of absent keys, then the fields last line first so that the earlier line's value stays, then the
     * {@code gateValues} ({@code {start, len, value}}, scope-relative) on every bit no line with a present key
     * covers ({@code present}), then const values, then when values (ruling 15 of 0.7, ruling 7 of 0.17).
     */
    private void writeLines(byte[] b, long base, List<Pack.Line> lines, Object[] values, List<long[]> gateValues,
                            java.util.BitSet present, Entity e) {
        // The sentinels of absent keys first: a line that writes a value wins over them whatever the order (ruling 16 of 0.9).
        for (int i = lines.size() - 1; i >= 0; i--) {
            if (!(lines.get(i) instanceof Pack.Field) || values[i] != null) continue;
            Pack.Field f = (Pack.Field) lines.get(i);
            if (f.absent == null || f.suppressed(e)) continue; // absent key and no default, or `with`: its bits stay zero
            Loc loc = (Loc) f.loc;
            long raw = f.absent.firstNum();
            writeBits(b, base + loc.start, loc.len, f.swap ? swapBytes(raw, loc.len) : raw);
        }
        for (int i = lines.size() - 1; i >= 0; i--) {
            if (!(lines.get(i) instanceof Pack.Field) || values[i] == null) continue;
            Pack.Field f = (Pack.Field) lines.get(i);
            writeValue(b, base + ((Loc) f.loc).start, f, values[i]);
        }
        if (gateValues != null) {
            for (long[] gv : gateValues) {
                int len = (int) gv[1];
                for (int k = 0; k < len; k++) {
                    long rel = gv[0] + k;
                    if (present.get((int) rel)) continue;
                    long bit = msb ? (gv[2] >>> (len - 1 - k)) & 1L : (gv[2] >>> k) & 1L;
                    writeBits(b, base + rel, 1, bit);
                }
            }
        }
        // const values are written over any field, then when values (ruling 15 of 0.7)
        for (int pass = 0; pass < 2; pass++) {
            for (Pack.Line l : lines) {
                if (!(l instanceof Pack.When) || ((Pack.When) l).isConst != (pass == 0)) continue;
                Loc loc = (Loc) l.loc;
                Pack.When w = (Pack.When) l;
                if (w.isList() && coveredByMatch(lines, values, w, loc, b, base, e)) continue;
                writeBits(b, base + loc.start, loc.len, w.number);
            }
        }
    }

    /**
     * Ruling 3 of 0.20: a field line whose key the entity holds (a default does not count) covers exactly the bits
     * of a {@code when} with a list or a range, and the value written there matches the {@code when}: it stays.
     */
    private boolean coveredByMatch(List<Pack.Line> lines, Object[] values, Pack.When w, Loc loc, byte[] b, long base, Entity e) {
        for (int i = 0; i < lines.size(); i++) {
            if (!(lines.get(i) instanceof Pack.Field) || values[i] == null) continue;
            Pack.Field f = (Pack.Field) lines.get(i);
            Loc fl = (Loc) f.loc;
            if (fl.start != loc.start || fl.len != loc.len || !held(f, e)) continue;
            if (w.matches(readBits(b, base + loc.start, loc.len))) return true;
        }
        return false;
    }

    /** True when the entity holds the line's key and the line is not suppressed by {@code with} (ruling 1 of 0.18). */
    private static boolean held(Pack.Field f, Entity e) { return e.get(f.key) != null && !f.suppressed(e); }

    /** Set in {@code mask} the bits of {@code loc}. */
    private static void mark(java.util.BitSet mask, Loc loc) { mask.set((int) loc.start, (int) loc.end()); }

    /**
     * Write the lines of one scope that starts at bit {@code base}. Returns the furthest bit written beyond the
     * scope's fixed extent: the end of the items of its groups and the lines and gates of its held blocks, or 0.
     */
    private long encodeScope(Buf buf, Pack.Scope scope, long base, Entity e, List<Choice> choices) {
        Info info = (Info) scope.info;
        buf.ensure(base + info.all);
        List<Pack.Line> lines = scope.lines;
        List<Pack.Line> outside = new ArrayList<>(lines.size());
        for (Pack.Line l : lines) if (!(l instanceof Pack.Gate) && !(l instanceof Pack.Group)) outside.add(l);
        Object[] outValues = new Object[outside.size()];
        for (int i = 0; i < outside.size(); i++) {
            if (outside.get(i) instanceof Pack.Field) outValues[i] = valueToEncode((Pack.Field) outside.get(i), e, scope);
        }
        long far = 0;
        if (!info.gated) {
            writeLines(buf.b, base, outside, outValues, null, null, e);
        } else {
            far = encodeGated(buf, scope, base, e, outside, outValues, choices);
        }
        // groups: the items back to back; a count locator holds their number, written over any field there
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
                long nested = encodeScope(buf, g.body, pos, items.get(i), choices);
                pos = Math.max(pos + g.itemBits, nested);
            }
            buf.ensure(pos);
            far = Math.max(far, pos);
        }
        return far;
    }

    /** Steps 1 to 5 of the 0.17 encode for one scope with gate blocks; returns the furthest bit of its held blocks. */
    private long encodeGated(Buf buf, Pack.Scope scope, long base, Entity e, List<Pack.Line> outside,
                             Object[] outValues, List<Choice> choices) {
        Info info = (Info) scope.info;
        List<Pack.Line> lines = scope.lines;
        int span = (int) info.all;
        // 1. The open blocks.
        Set<Pack.Gate> open = newGateSet();
        open(lines, e, open);
        // 2. The lines outside any block, on a scratch copy of the scope; the bits a present key, a const, a when
        //    or a group count wrote are written (the union of their ranges, whatever line wrote last).
        byte[] ev = new byte[((span + 7) >>> 3) + 1];
        writeLines(ev, 0, outside, outValues, null, null, e);
        java.util.BitSet written = new java.util.BitSet(span);
        for (int i = 0; i < outside.size(); i++) {
            Pack.Line l = outside.get(i);
            if (l instanceof Pack.When || held((Pack.Field) l, e)) mark(written, (Loc) l.loc);
        }
        for (Pack.Group g : scope.groups) {
            if (g.countLocator == null) continue;
            Loc c = (Loc) g.countLoc;
            List<Entity> items = e.list(g.list);
            writeBits(ev, c.start, c.len, items == null ? 0 : items.size());
            mark(written, c);
        }
        // 3. In line order, depth first, each open block none of whose gate bits is written gets its gate value.
        List<Pack.Gate> all = new ArrayList<>();
        gates(lines, all);
        Map<Pack.Gate, Long> values = new java.util.IdentityHashMap<>();
        for (Pack.Gate g : all) {
            if (!open.contains(g)) continue;
            Loc loc = (Loc) g.loc;
            if (written.get((int) loc.start, (int) loc.end()).cardinality() > 0) continue;
            Long v = g.gateValue();
            if (v == null) continue;   // a `!` list that names every value
            values.put(g, v);
            writeBits(ev, loc.start, loc.len, v);
            mark(written, loc);
        }
        // 4. The held blocks, evaluated as decode evaluates them; bits nothing wrote read as 0.
        Set<Pack.Gate> held = newGateSet();
        evaluate(ev, (long) ev.length * 8, 0, lines, held);
        // 5. The lines outside any block and those of the held blocks; a held block's gate value goes over the
        //    bits of a default or a sentinel and under those of a line with a present key, a const or a when.
        List<Pack.Line> part = new ArrayList<>();
        List<Map<String, Object>> partDefaults = new ArrayList<>();
        List<Pack.Gate> heldInOrder = new ArrayList<>();
        participating(lines, held, scope.defaultValues, part, partDefaults, heldInOrder);
        Object[] partValues = new Object[part.size()];
        java.util.BitSet present = new java.util.BitSet(span);
        Set<String> mapped = new HashSet<>();
        long far = 0;
        int o = 0;
        for (int i = 0; i < part.size(); i++) {
            Pack.Line l = part.get(i);
            boolean isOutside = o < outside.size() && outside.get(o) == l;
            if (isOutside) o++;
            if (!(l instanceof Pack.Field)) {
                if (!isOutside) far = Math.max(far, base + ((Loc) l.loc).end());   // a held block's const counts
                continue;
            }
            Pack.Field f = (Pack.Field) l;
            // Lines of blocks that are not held are never valued: they raise no encode error (ruling 10 of 0.17).
            partValues[i] = isOutside ? outValues[o - 1] : valueToEncode(f, e, partDefaults.get(i));
            // a held block's field counts toward the length; under armor sixbit an optional one only when it is
            // written, by a value, a default or a sentinel (ruling 14 of 0.17); a line suppressed by `with` writes
            // none of them (ruling 1 of 0.18)
            boolean writesSentinel = f.absent != null && !f.suppressed(e);
            if (!isOutside && !(pack.armorSixbit && f.optional && partValues[i] == null && !writesSentinel)) {
                far = Math.max(far, base + ((Loc) f.loc).end());
            }
            if (f.suppressed(e)) continue;   // its key does not count as mapped for step 6 (ruling 1 of 0.18)
            if (e.get(f.key) != null) mark(present, (Loc) f.loc);
            mapped.add(f.key);
        }
        List<long[]> gateValues = new ArrayList<>();
        for (Pack.Gate g : heldInOrder) {
            Loc loc = (Loc) g.loc;
            far = Math.max(far, base + loc.end());   // the gate locators of held blocks count toward the length
            Long v = values.get(g);
            if (v != null) gateValues.add(new long[]{loc.start, loc.len, v});
        }
        // 6 (in part). A key the entity holds that only lines of blocks not held map cannot be written.
        for (Pack.Gate g : all) {
            if (held.contains(g)) continue;
            for (Pack.Line l : g.body.lines) {
                if (!(l instanceof Pack.Field) || ((Pack.Field) l).suppressed(e)) continue;   // ruling 1 of 0.18
                String key = ((Pack.Field) l).key;
                if (e.get(key) != null && !mapped.contains(key)) {
                    throw new GtException(GtException.Code.TRANSFORM_ENCODE, pack.format, l.locator, key
                            + " is mapped only by lines of if blocks that do not hold");
                }
            }
        }
        writeLines(buf.b, base, part, partValues, gateValues, present, e);
        choices.add(new Choice(base, lines, all, held));
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

    /** The {@code len / 6} six-bit values of a {@code sixbit} field, first character first, each in the pack's bit order. */
    static int[] readSixbit(byte[] msg, long start, int len, boolean msb) {
        int[] v = new int[len / 6];
        for (int i = 0; i < v.length; i++) v[i] = (int) readBits(msg, start + 6L * i, 6, msb);
        return v;
    }

    /** Write the six-bit values of a {@code sixbit} field, first character first, each in the pack's bit order. */
    static void writeSixbit(byte[] msg, long start, int[] values, boolean msb) {
        for (int i = 0; i < values.length; i++) writeBits(msg, start + 6L * i, 6, values[i], msb);
    }
}
