package goat.transformers;

import java.util.ArrayList;
import java.util.List;

/**
 * The layout checks of a fixed-layout {@code bits} pack (engine-spec 0.7 and 0.17), run when the pack is read, and
 * the parsed locators and scope extents they leave for the codec. They are load checks of the pack language, so they
 * are in every build; the codec that reads and writes bits messages is {@code BitsCodec}, in the bits wire only.
 */
final class BitsLayout {
    private BitsLayout() {}

    /** Bit orders: positions and values from the low bit, from the high bit, or high-bit positions with low-bit values. */
    static final int LSB = 0, MSB = 1, MSB_LSB = 2;

    /** A parsed locator: first bit, counted from the start of its scope (the message, or one item), and bit length. */
    static final class Loc {
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
    static final class Info {
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

    static Loc loc(String locator, int wordBytes) {
        int[] wpl = Locators.bitsParse(locator);
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
    static List<Pack.Line> gateLines(Pack.Gate g, List<Pack.Line> out) {
        out.add(g);
        for (Pack.Line b : g.body.lines) {
            if (b instanceof Pack.Gate) gateLines((Pack.Gate) b, out);
            else out.add(b);
        }
        return out;
    }

}
