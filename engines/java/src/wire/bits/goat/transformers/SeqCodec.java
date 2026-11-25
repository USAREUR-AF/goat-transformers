package goat.transformers;

import java.math.BigInteger;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;

/**
 * The {@code bits} wire with {@code layout sequential} (engine-spec 0.8): the lines of the pack are read, and
 * written, in file order from a cursor. Hex text in and out; a message is a whole number of bytes. With
 * {@code armor sixbit} (engine-spec 0.14) armored text in and out: a message is any number of bits, and encode
 * writes the bits up to the cursor. With {@code encoding uper} (engine-spec 0.19) the lines also hold the X.691
 * unaligned PER forms: constrained, semi-constrained and unconstrained integers, enumerations, character and octet
 * strings, extensible SEQUENCEs ({@code ext}), CHOICE and SEQUENCE OF ({@code group ... size}).
 */
final class SeqCodec extends BitsWire<byte[]> {
    /** The pack's bit order (BitsLayout.LSB, MSB or MSB_LSB). */
    private final int msb;
    private final Seq.Body root;

    SeqCodec(Pack pack) {
        super(pack);
        this.msb = pack.bitOrder;
        this.root = pack.seq;
        for (Seq.Kind k : root.kinds) {
            for (Seq.Node n : Seq.innerLines(k.all)) inReach.computeIfAbsent(n, x -> new java.util.HashSet<>()).addAll(Seq.ownKeys(k.all));
        }
    }

    /**
     * Each {@code inner} line and the keys of its lines in reach (ruling 20 of 0.52): the common lines and those of
     * its kind, or of every kind for a line in the common lines, which each kind's lines hold.
     */
    private final Map<Seq.Node, java.util.Set<String>> inReach = new IdentityHashMap<>();

    /** The inner pack an {@code inner} line last passed the key check with; a pack does not change once loaded. */
    private final Map<Seq.Node, Pack> keysChecked = new java.util.concurrent.ConcurrentHashMap<>();

    /**
     * The codec of an {@code inner} line that is reached: the four checks of engine-spec 0.34, then that no key its
     * lines in reach map is one of the inner pack's {@code model_keys} (ruling 20 of 0.52).
     */
    private BitsWire<?> reachInner(Seq.Node n) {
        Codec<?> inner = engine.innerCodec(pack, n.name);
        if (keysChecked.get(n) != inner.pack) {
            for (String key : inner.pack.modelKeys()) {
                if (inReach.get(n).contains(key)) {
                    throw new GtException(GtException.Code.BAD_DIRECTIVE, pack.format, null, "the inner line of " + pack.format
                            + " (line " + n.line + ") names " + n.name + ", which also maps " + key);
                }
            }
            keysChecked.put(n, inner.pack);
        }
        return (BitsWire<?>) inner;   // a bits pack, by check 2
    }

    // Kind selection needs the cursor, so decode and encode are whole here and the per-kind hooks are not used.

    @Override
    byte[] parse(String text) { return fromHex(text); }

    @Override
    boolean holds(byte[] wire, Pack.When when) { throw new IllegalStateException(); }

    @Override
    Entity decodeKind(byte[] wire, Pack.Kind kind) { throw new IllegalStateException(); }

    @Override
    String encodeKind(Entity e, Pack.Kind kind) { throw new IllegalStateException(); }

    // ---- decode ----

    /** One decode: the input, the cursor, the end of the input and of the innermost {@code length} extent. */
    private final class Reader {
        final byte[] msg;
        long pos;
        /** The end of the input in bits; a {@code length ... whole} line moves it in. */
        long end;
        /** The end of the innermost open {@code length} extent, or -1 outside every extent. */
        long soft = -1;
        /** The innermost open {@code length} extent is counted in bits (engine-spec 0.21). */
        boolean softBits;
        /** The number of items each {@code count} line read last; -1 when it lay at or past an extent's end. */
        final Map<Seq.Node, Long> counts = new IdentityHashMap<>();
        /** The item number of each count read, exact (engine-spec 0.31, ruling 5: two counts compare without wrapping). */
        final Map<Seq.Node, BigInteger> exactCounts = new IdentityHashMap<>();
        final boolean[][] presence = new boolean[pack.seqPresences][];
        final Failures fails = new Failures(pack.format);
        /** The cases read so far, in reading order (engine-spec 0.20). */
        final List<Seq.Case> casesRead = new ArrayList<>();
        /**
         * Presence bits that are 1 and are named only by {@code if} lines inside cases: {presence, bit, index into
         * {@link #casesRead} when the presence was read}. Checked when the body that read them ends (ruling 21).
         */
        final List<Object[]> pending = new ArrayList<>();
        /** A {@code length ... whole} line was read: {@link #end} is the smallest length stated. */
        boolean wholeRead;
        /** The lists the inner decode gave the entity: no later outer group replaces them (engine-spec 0.34, step 4). */
        final java.util.Set<String> innerLists = new java.util.HashSet<>();
        /** The message's entity, whose lists an inner decode compares with the outer entity's. */
        Entity rootEntity;
        /** Above 0 while the items of a list that decode discards are read: they are not counted (7g of 0.11). */
        int discarding;

        Reader(BitMsg in) {
            this.msg = in.b;
            this.end = in.bits;
        }

        long limit() { return soft >= 0 ? soft : end; }

        /**
         * True when a line of {@code len} bits can be read at the cursor. Inside a {@code length} extent a line that
         * starts at or after its end reads as absent (false) and one that straddles the end is malformed; outside
         * one, a line that runs past the input is malformed.
         */
        boolean line(int len, String what) {
            if (soft >= 0) {
                if (pos >= soft) return false;
                if (pos + len > soft) throw malformed(what + " runs past the end of its length extent");
                return true;
            }
            if (pos + len > end) throw malformed("the input ends before " + what);
            return true;
        }

        /** Bits a line needs once it has started: past the extent or the input they are malformed. */
        void need(int len, String what) {
            if (pos + len > limit()) throw malformed((soft >= 0 ? "the length extent" : "the input") + " ends before " + what);
        }

        /**
         * The indicator bit of a {@code while}, {@code more} or {@code fx} group: at or after the end of a
         * {@code length} extent it reads as 0 (ruling 21 of 0.8); past the end of the input it is malformed.
         */
        long indicator(String what) {
            if (soft >= 0 && pos >= soft) return 0;
            need(1, what);
            return take(1);
        }

        long take(int len) {
            long v = BitsCodec.readBits(msg, pos, len, msb);
            pos += len;
            return v;
        }

        // ---- the X.691 forms (0.19); every read checks the input or extent first ----

        /** {@code len} more bits at the cursor are within the input or extent, else malformed. */
        void needBits(long len, String what) {
            if (len < 0 || len > limit() - pos) throw malformed((soft >= 0 ? "the length extent" : "the input") + " ends before " + what);
        }

        long bits(int len, String what) {
            need(len, what);
            return take(len);
        }

        /** A length determinant: {@code 0} and 7 bits, or {@code 10} and 14 bits; {@code 11} (fragmented) is malformed. */
        long lengthDet(String what) {
            long b = bits(8, "the length of " + what);
            if (b < 0x80) return b;
            if ((b & 0x40) == 0) return ((b & 0x3f) << 8) | bits(8, "the length of " + what);
            throw malformed("the length of " + what + " is fragmented (first bits 11), which this engine does not read");
        }

        /** A constrained whole number in {@code lb..ub}; a value above {@code ub} is malformed. */
        long constrained(long lb, long ub, String what) {
            long raw = bits(Seq.rangeBits(lb, ub), what);
            if (Long.compareUnsigned(raw, ub - lb) > 0) {
                throw malformed(what + " reads " + Long.toUnsignedString(raw) + " above its constraint, whose range is " + Long.toUnsignedString(ub - lb));
            }
            return lb + raw;
        }

        /**
         * {@code octets} octets of an integer, checked in the order of ruling 20 of 0.19: the input holds them
         * (malformed), the count is not 0 (malformed), the value fits; more than 8 octets are skipped and then refused
         * as IllegalArgumentException (transform-decode, ruling 5). The bits, unsigned.
         */
        long intOctets(long octets, String what) {
            needBits(octets * 8, what);
            if (octets == 0) throw malformed(what + " is an integer of 0 octets");
            if (octets > 8) {
                pos += octets * 8;
                throw new IllegalArgumentException(what + " is an integer of " + octets + " octets, more than 8");
            }
            return take((int) octets * 8);
        }

        /** A normally small non-negative whole number; one that does not fit 64 signed bits is IllegalArgumentException. */
        long normallySmall(String what) {
            if (bits(1, what) == 0) return bits(6, what);
            long octets = lengthDet(what);
            long v = intOctets(octets, what);
            if (v < 0) throw new IllegalArgumentException(what + " does not fit a signed 64-bit integer");
            return v;
        }

        /** A length determinant of an octet count, then a two's-complement integer of that many octets. */
        long signed(String what) {
            long octets = lengthDet(what);
            long raw = intOctets(octets, what);
            return BitsTransform.twosValue(raw, (int) octets * 8);
        }

        void skipOctets(long octets, String what) {
            needBits(octets * 8, what);
            pos += octets * 8;
        }
    }

    @Override
    Entity decodeMessage(String text) {
        Reader r = new Reader(parseBits(text));
        Entity e = new Entity();
        read(r, e);
        finishDecode(e, r.fails);
        return e;
    }

    /** The lines of one message, into {@code e}; its transform failures are left in {@code r.fails}. */
    private void read(Reader r, Entity e) {
        r.rootEntity = e;
        Seq.Kind kind = decodeBody(root, r, e);
        checkPending(r);
        if (root.hasKinds) e.setKind(pack.format, kind.name);
    }

    @Override
    Layer decodeLayer(byte[] msg) {
        Reader r = new Reader(new BitMsg(msg, (long) msg.length * 8));
        Layer l = new Layer();
        l.fails = r.fails;
        try {
            read(r, l.entity);
        } catch (GtException ex) {
            if (ex.code() != GtException.Code.TRANSFORM_DECODE) throw ex;
            l.stopped = ex;
        }
        l.end = r.wholeRead ? r.end : r.pos;   // ruling 13 of 0.34
        return l;
    }

    /**
     * A presence bit named only inside cases is 1: some case naming it must have been read after it, anywhere later
     * in the decode, a later group item included (ruling 36 of 0.20).
     */
    private void checkPending(Reader r) {
        for (int i = 0; i < r.pending.size(); i++) {
            Object[] p = r.pending.get(i);
            Seq.Node n = (Seq.Node) p[0];
            int bit = (Integer) p[1];
            List<Seq.Case> named = n.caseNamed.get(bit);
            boolean read = false;
            for (int j = (Integer) p[2]; j < r.casesRead.size() && !read; j++) {
                for (Seq.Case c : named) if (c == r.casesRead.get(j)) { read = true; break; }
            }
            if (!read) throw malformed("presence bit " + n.name + "." + bit + " is 1 and no if of the cases read names it");
        }
    }

    private Seq.Kind decodeBody(Seq.Body body, Reader r, Entity e) {
        decodeLines(body.common, r, e);
        Seq.Kind kind = body.kinds.get(0);
        if (body.hasKinds) {
            kind = null;
            long at = r.pos;
            long[] read = null;
            for (Seq.Kind k : body.kinds) {
                r.pos = at;
                boolean all = true;
                read = new long[k.whens.size()];
                for (int i = 0; i < read.length; i++) {
                    Seq.Node w = k.whens.get(i);
                    if (w.hasAt) {
                        // engine-spec 0.33: len bits at kind start plus the offset; the cursor does not move. A window
                        // any of whose bits lies beyond the input or the extent does not hold (rulings 6 and 7)
                        long room = r.limit() - at - w.len;
                        if (room < 0 || Long.compareUnsigned(w.at, room) > 0
                                || !matches(w, read[i] = BitsCodec.readBits(r.msg, at + w.at, w.len, msb))) { all = false; break; }
                        continue;
                    }
                    // a when any of whose bits lies beyond the input does not hold
                    if (r.pos + w.len > r.limit() || !matches(w, read[i] = r.take(w.len))) { all = false; break; }
                }
                if (all) { kind = k; break; }
            }
            if (kind == null) {
                r.pos = at;
                throw new GtException(GtException.Code.NO_KIND, pack.format, null,
                        (body == root ? "the message" : "an item") + " matches no kind at bit " + at);
            }
            // engine-spec 0.30: the when ... as lines of the selected kind, and only of it, set their keys (ruling 12)
            for (int i = 0; i < read.length; i++) {
                Seq.Node w = kind.whens.get(i);
                if (w.as != null) putDecoded(w.as, read[i], e, r.fails);
            }
        }
        decodeLines(kind.lines, r, e);
        return kind;
    }

    /** True when a {@code when} line holds for the value read: one of its values, or within one of its ranges. */
    private static boolean matches(Seq.Node w, long v) {
        return w.ranges == null ? v == w.value : Pack.inRanges(w.ranges, v);
    }

    private static boolean bit(boolean[] bits, int i) { return bits != null && i < bits.length && bits[i]; }

    /** True when every bit the {@code if} names is 1, and every bit it names with {@code !} is 0. */
    private static boolean holds(Seq.Node n, boolean[][] presence) {
        for (int i = 0; i < n.refBit.length; i++) {
            if (bit(presence[n.refPresence[i].id], n.refBit[i]) == n.refNot[i]) return false;
        }
        return true;
    }

    private void decodeLines(List<Seq.Node> nodes, Reader r, Entity e) {
        for (Seq.Node n : nodes) {
            switch (n.op) {
                case FIELD: {
                    Pack.Field f = n.keys.get(0);
                    if (n.until >= 0) {
                        // 0.22: at or after a length extent's end the field is absent; at the end of the input it is
                        // malformed (ruling 4)
                        if (!r.line(1, f.key)) break;
                        List<Integer> codes = untilCodes(n, f, r.msg, r.pos, r.limit(), r.soft >= 0);
                        r.pos += (long) (codes.size() + 1) * f.bits.charWidth();   // past the terminator (ruling 5)
                        Object v;
                        try {
                            v = untilText(f, codes);
                        } catch (IllegalArgumentException ex) {
                            for (Pack.Field k : n.keys) r.fails.add(k, ex.getMessage(), e);
                            break;
                        }
                        for (Pack.Field k : n.keys) putDecoded(k, v, e, r.fails);
                        break;
                    }
                    if (!r.line(n.len, f.key)) break;
                    if (f.absent != null) {
                        // the raw value after swap; a sentinel gives no key of the line a value (Version 0.9)
                        long raw = BitsCodec.readBits(r.msg, r.pos, n.len, msb);
                        if (f.absent.matches(f.swap ? BitsCodec.swapBytes(raw, n.len) : raw)) {
                            r.pos += n.len;
                            break;
                        }
                    }
                    Object v;
                    long at = r.pos;
                    // the cursor moves on whether or not the transform succeeds; a UPER field moves it as it reads
                    if (n.u == null) r.pos += n.len;
                    try {
                        v = n.u != null ? readUper(n.u, f, r) : valueAt(f, r.msg, at, n.len);
                    } catch (IllegalArgumentException ex) {
                        for (Pack.Field k : n.keys) r.fails.add(k, ex.getMessage(), e);
                        break;
                    }
                    // the field line and its also lines: decode fills every key
                    for (Pack.Field k : n.keys) putDecoded(k, v, e, r.fails);
                    break;
                }
                case CONST:
                case PAD:
                    if (r.line(n.len, n.op == Seq.Op.PAD ? "a pad" : "a const")) r.pos += n.len;
                    break;
                case WHEN: {
                    // a common when: it must hold for every message (or item) of the format
                    boolean beyond = r.pos + n.len > r.limit();
                    long v = beyond ? 0 : r.take(n.len);
                    if (beyond || !matches(n, v)) {
                        throw new GtException(GtException.Code.NO_KIND, pack.format, null,
                                "the common when line " + n.len + " " + Long.toUnsignedString(n.value) + " does not hold");
                    }
                    if (n.as != null) putDecoded(n.as, v, e, r.fails);   // engine-spec 0.30: the key holds the bits as uint
                    break;
                }
                case ALIGN: {
                    long to = (r.pos + n.len - 1) / n.len * n.len;
                    r.pos = Math.max(r.pos, Math.min(to, r.limit()));   // stops at the end of the input or extent (ruling 20)
                    break;
                }
                case PRESENCE:
                    r.presence[n.id] = readPresence(n, r);
                    break;
                case IF:
                    if (holds(n, r.presence)) decodeLines(n.body, r, e);
                    break;
                case OPT:
                    if (r.line(1, "an opt bit") && r.take(1) == 1) decodeLines(n.body, r, e);
                    break;
                case CHAIN: {
                    int last = n.parts.size() - 1;
                    for (int k = 0; k <= last; k++) {
                        decodeLines(n.parts.get(k), r, e);
                        if (k == last && !n.endsWithFx) break;
                        if (!r.line(1, "an fx bit") || r.take(1) == 0) break;
                        if (k == last) throw malformed("the chain ends with an fx line and its bit is 1");
                    }
                    break;
                }
                case LENGTH: {
                    if (!r.line(n.len, "a length")) break;
                    long units = r.take(n.len);
                    long bits = extent(units, n, r.limit() - r.pos);
                    long outer = r.soft;
                    boolean outerBits = r.softBits;
                    r.soft = r.pos + bits;
                    r.softBits = n.inBits;
                    decodeLines(n.body, r, e);
                    r.pos = r.soft;   // content of the extent no line reads is skipped
                    r.soft = outer;
                    r.softBits = outerBits;
                    break;
                }
                case COUNT: {
                    // engine-spec 0.21: the number of items is the value less n; at or past an extent's end the group is absent
                    if (!r.line(n.len, "count " + n.name)) {
                        r.counts.put(n, -1L);
                        break;
                    }
                    BigInteger items = new BigInteger(Long.toUnsignedString(r.take(n.len))).subtract(BigInteger.valueOf(n.plus));
                    if (items.signum() < 0) {
                        throw malformed("count " + n.name + " holds " + items.add(BigInteger.valueOf(n.plus)) + ", below its plus " + n.plus);
                    }
                    r.counts.put(n, items.bitLength() > 63 ? Long.MAX_VALUE : items.longValue());
                    r.exactCounts.put(n, items);
                    break;
                }
                case WHOLE: {
                    if (!r.line(n.len, "the length of the message")) break;
                    long units = r.take(n.len);
                    if (units < 0 || units - n.plus < 0 || units - n.plus > r.msg.length) {
                        throw malformed("the message states a length of " + Long.toUnsignedString(units) + (n.plus == 0 ? "" : " less " + n.plus)
                                + " bytes and the input has " + r.msg.length);
                    }
                    long total = (units - n.plus) * 8;
                    if (total < r.pos) throw malformed("the stated length of the message is shorter than what was already read");
                    if (total > r.end) throw malformed("the input is shorter than the stated length of the message");
                    r.end = total;
                    r.wholeRead = true;
                    if (r.soft > total) r.soft = total;
                    break;
                }
                case GROUP:
                    decodeGroup(n, r, e);
                    break;
                case EXT: {
                    if (!r.line(1, "the extension bit of a SEQUENCE")) break;
                    boolean additions = r.take(1) == 1;
                    decodeLines(n.body, r, e);
                    if (additions) skipAdditions(r);
                    break;
                }
                case CHOICE: {
                    if (!r.line(n.ext ? 1 : 0, "a choice")) break;
                    if (n.ext && r.take(1) == 1) {
                        // an extension alternative: its index and its open type are skipped
                        try {
                            r.normallySmall("the index of an extension alternative");
                        } catch (IllegalArgumentException ex) {
                            throw new GtException(GtException.Code.TRANSFORM_DECODE, pack.format, null, ex.getMessage());
                        }
                        r.skipOctets(r.lengthDet("the open type of an extension alternative"), "the open type of an extension alternative");
                        break;
                    }
                    long i = r.constrained(0, n.alts - 1, "the index of a choice");
                    Integer at = n.altAt.get((int) i);
                    if (at == null) throw malformed("the choice index " + i + " has no alt");
                    decodeLines(n.altLines.get(at), r, e);
                    break;
                }
                case INNER:
                    decodeInner(n, r, e);
                    break;
                case SWITCH: {
                    // a key line that failed its transform fails the decode, whatever the switch would read (ruling 35)
                    for (int i = 0; i < r.fails.fields.size(); i++) {
                        if (r.fails.into.get(i) == e && r.fails.fields.get(i).key.equals(n.switchKey)
                                && (r.fails.hard.get(i) || e.get(n.switchKey) == null)) {
                            finishDecode(e, r.fails);
                        }
                    }
                    // the key's decoded value when the cursor reaches the switch selects the case (engine-spec 0.20)
                    Seq.Case c = Seq.select(n, e.get(n.switchKey));
                    if (c == null) throw noCase(n, e.get(n.switchKey));
                    r.casesRead.add(c);
                    decodeLines(c.body, r, e);
                    break;
                }
                default:
                    throw new IllegalStateException(n.op.name());
            }
        }
    }

    /**
     * An {@code inner} line (engine-spec 0.34): the bytes from the cursor to the end of the extent are one message of
     * the inner pack, decoded by its own rules into the same entity. A key or list read earlier is kept.
     */
    private void decodeInner(Seq.Node n, Reader r, Entity e) {
        BitsWire<?> inner = reachInner(n);
        if (r.pos % 8 != 0) throw malformed("the inner line of " + n.name + " is reached at bit " + r.pos + ", not on a whole byte");
        long lim = r.limit();
        if (lim > (long) r.msg.length * 8) throw malformed("the extent of the inner line ends beyond the input");
        if (lim % 8 != 0) throw malformed("the length extent of the inner line of " + n.name + " does not end on a whole byte");
        byte[] bytes = Arrays.copyOfRange(r.msg, (int) (r.pos / 8), (int) (lim / 8));
        r.pos = lim;
        Layer layer;
        // the inner decode starts with the budget the outer lines have left (it shares this thread's budget); the
        // items of a list the outer entity holds are discarded, so its counts are checked but its items not counted
        long before = itemsLeft();
        java.util.Set<String> was = setOuterHeld(new java.util.HashSet<>(e.lists().keySet()));
        try {
            layer = inner.decodeLayer(bytes);
        } finally {
            setOuterHeld(was);
        }
        // the check of step 3, before the keys join (ruling 17); a transform-decode that did not stop ranks after it
        if (layer.stopped == null && !n.partial && layer.leftOver(bytes.length)) {
            throw malformed("the " + bytes.length + " bytes of the inner line of " + n.name + " go on after the end of its message");
        }
        Entity got = layer.entity;
        r.fails.addInner(layer.fails, got, e);
        r.fails.joined = e;
        for (Map.Entry<String, Object> kv : got.fields().entrySet()) {
            if (e.get(kv.getKey()) != null) continue;
            e.put(kv.getKey(), kv.getValue());
            r.fails.innerKeys.add(kv.getKey());
        }
        long kept = 0;
        for (Map.Entry<String, List<Entity>> l : got.lists().entrySet()) {
            if (e.list(l.getKey()) != null) continue;   // the outer list read first is kept whole
            e.putList(l.getKey(), l.getValue());
            r.innerLists.add(l.getKey());
            kept += deepCount(l.getValue());
        }
        // the entity holds the inner items kept and no other (7g of 0.11)
        if (before >= 0) setItemsLeft(Math.max(0, before - kept));
        if (got.kindFormat() != null) e.setInnerKind(got.kindFormat(), got.kindName());
        if (layer.stopped != null) {
            finishDecode(e, r.fails);   // the earliest transform-decode in reading order
            throw layer.stopped;
        }
    }

    /**
     * The extension additions of a SEQUENCE whose extension bit is 1: their number as a normally small length, the
     * presence bits, one open type for each bit that is 1. All are skipped.
     */
    private void skipAdditions(Reader r) {
        String what = "the number of extension additions";
        long m = r.bits(1, what) == 0 ? r.bits(6, what) + 1 : r.lengthDet(what);
        r.needBits(m, "the presence bits of the extension additions");
        boolean[] present = new boolean[(int) m];
        for (int i = 0; i < m; i++) present[i] = r.take(1) == 1;
        for (boolean p : present) {
            if (p) r.skipOctets(r.lengthDet("the open type of an extension addition"), "the open type of an extension addition");
        }
    }

    /** One field with a UPER locator: the model value, or IllegalArgumentException (transform-decode) once its bits are read. */
    private Object readUper(Seq.Uper u, Pack.Field f, Reader r) {
        String what = f.key;
        switch (u.kind) {
            case INT: {
                long v;
                if (u.ext && r.bits(1, what) == 1) v = r.signed(what);
                else v = r.constrained(u.lb, u.ub, what);
                return f.bits.decodeInteger(v);
            }
            case INT_SEMI: {
                long raw = r.intOctets(r.lengthDet(what), what);
                if (Long.compareUnsigned(raw, Long.MAX_VALUE - u.lb) > 0) {
                    throw new IllegalArgumentException(what + ": " + Long.toUnsignedString(raw) + " above " + u.lb + " does not fit a signed 64-bit integer");
                }
                return f.bits.decodeInteger(u.lb + raw);
            }
            case INT_FREE:
                return f.bits.decodeInteger(r.signed(what));
            case ENUM: {
                if (u.ext && r.bits(1, what) == 1) {
                    long i = r.normallySmall(what);
                    if (i > Long.MAX_VALUE - u.ub) throw new IllegalArgumentException(what + ": the extension index does not fit a signed 64-bit integer");
                    return f.bits.decodeInteger(u.ub + i);
                }
                return f.bits.decodeInteger(r.constrained(0, u.ub - 1, what));
            }
            case CHARS: {
                long count = u.sized ? r.constrained(u.lb, u.ub, "the character count of " + what) : r.lengthDet(what);
                r.needBits(count * 7, "the characters of " + what);
                char[] c = new char[(int) count];
                for (int i = 0; i < c.length; i++) c[i] = (char) r.take(7);
                return new String(c);
            }
            default: {
                long count = u.sized ? r.constrained(u.lb, u.ub, "the octet count of " + what) : r.lengthDet(what);
                r.needBits(count * 8, "the octets of " + what);
                byte[] b = new byte[(int) count];
                for (int i = 0; i < b.length; i++) b[i] = (byte) r.take(8);
                return f.tlv.decode(b, 0, b.length);
            }
        }
    }

    private GtException noCase(Seq.Node n, Object v) {
        return new GtException(GtException.Code.NO_KIND, pack.format, null, "switch " + n.switchKey + " (line " + n.line + "): "
                + (v == null ? "the key is absent" : "no case lists " + Pack.canonText(v)) + " and there is no else");
    }

    /** The value of a field line's bits at {@code at}, by its transform ({@code swap} included). Throws IllegalArgumentException. */
    private Object valueAt(Pack.Field f, byte[] msg, long at, int len) {
        if (f.bits.isChars()) {
            int cw = f.bits.charWidth();
            int[] codes = new int[len / cw];
            for (int i = 0; i < codes.length; i++) codes[i] = (int) BitsCodec.readBits(msg, at + (long) i * cw, cw, msb);
            return f.bits.decodeChars(codes);
        }
        if (f.bits.isAscii()) {
            byte[] bytes = new byte[len / 8];
            for (int i = 0; i < bytes.length; i++) bytes[i] = (byte) BitsCodec.readBits(msg, at + 8L * i, 8, msb);
            if (f.swap) BitsCodec.reverseBytes(bytes);
            return f.bits.decodeAscii(bytes, f.trim);
        }
        if (f.bits.isSixbit()) return BitsTransform.decodeSixbit(BitsCodec.readSixbit(msg, at, len, msb), f.trim);
        long raw = BitsCodec.readBits(msg, at, len, msb);
        return f.bits.decode(f.swap ? BitsCodec.swapBytes(raw, len) : raw, len);
    }

    /**
     * The codes of an {@code until:} field from bit {@code at} up to its terminator, which is not included
     * (engine-spec 0.22). The terminator is found from the codes alone: none before {@code limit}, or more than
     * {@code floor(2040 / w)} characters before it, is malformed-wire (rulings 5 and 8).
     */
    private List<Integer> untilCodes(Seq.Node n, Pack.Field f, byte[] msg, long at, long limit, boolean inExtent) {
        int w = f.bits.charWidth();
        int max = 2040 / w;
        List<Integer> codes = new ArrayList<>();
        for (long p = at; ; p += w) {
            if (p + w > limit) {
                throw malformed((inExtent ? "the length extent" : "the input") + " ends before the terminator " + n.until + " of " + f.key);
            }
            int c = (int) BitsCodec.readBits(msg, p, w, msb);
            if (c == n.until) return codes;
            if (codes.size() == max) throw malformed(f.key + " has more than " + max + " characters before its terminator " + n.until);
            codes.add(c);
        }
    }

    /** The text before an {@code until:} terminator, exactly; a code the set does not hold is transform-decode. */
    private static Object untilText(Pack.Field f, List<Integer> codes) {
        int[] c = new int[codes.size()];
        for (int i = 0; i < c.length; i++) c[i] = codes.get(i);
        return f.bits.decodeExact(c);
    }

    /** The bits of the block a length field of value {@code units} counts; malformed when it is not within {@code left} bits. */
    private long extent(long units, Seq.Node n, long left) {
        long block = units - n.plus;
        if (units < 0 || block < 0 || block > left) {
            throw malformed("a length of " + Long.toUnsignedString(units) + (n.plus == 0 ? "" : " less " + n.plus) + (n.inBits ? " bits" : " bytes")
                    + " does not lie within the " + left + " bits left");
        }
        long bits = n.inBits ? block : block * 8;
        if (bits > left) throw malformed("a length of " + block + " bytes runs past the " + left + " bits left");
        return bits;
    }

    /** The presence bits at the cursor, numbered from 1 in reading order ({@code [0]} is unused). */
    private boolean[] readPresence(Seq.Node n, Reader r) {
        boolean[] bits;
        if (!n.fx) {
            bits = new boolean[n.len + 1];
            if (!r.line(n.len, "presence " + n.name)) return bits;
            for (int i = 1; i <= n.len; i++) bits[i] = r.take(1) == 1;
        } else {
            bits = new boolean[8];
            if (!r.line(8, "presence " + n.name)) return bits;
            int count = 0;
            while (true) {
                r.need(8, "an octet of presence " + n.name);
                if (count + 8 > bits.length) bits = Arrays.copyOf(bits, bits.length * 2);
                for (int i = 0; i < 7; i++) bits[++count] = r.take(1) == 1;
                if (r.take(1) == 0) break;
            }
        }
        for (int i = 1; i < bits.length; i++) {
            if (!bits[i] || n.named.get(i)) continue;
            // a bit named only inside cases counts when one of those cases is read (ruling 21 of 0.20)
            if (n.caseNamed.containsKey(i)) r.pending.add(new Object[]{n, i, r.casesRead.size()});
            else throw malformed("presence bit " + n.name + "." + i + " is 1 and no if block names it");
        }
        return bits;
    }

    private void decodeGroup(Seq.Node g, Reader r, Entity e) {
        if (e == r.rootEntity && (r.innerLists.contains(g.list) || heldByOuter(g.list))) {
            // a list read first by the other pack of a layered decode is kept: this group's items are read and
            // discarded (engine-spec 0.34, Decode step 4); its counts are checked, its items not counted (ruling 7)
            r.discarding++;
            int mark = r.fails.size();
            try {
                decodeGroupInto(g, r, new Entity());
            } finally {
                r.discarding--;
            }
            r.fails.dropSoft(mark);   // ruling 21
            return;
        }
        decodeGroupInto(g, r, e);
    }

    /** Take {@code n} items of a count before they are read; only check them for a list decode discards. */
    private void countItems(Reader r, long n) {
        if (r.discarding > 0) checkItems(n);
        else takeItems(n);
    }

    /** Take one item read without a count; nothing for a list decode discards. */
    private void oneItem(Reader r) {
        if (r.discarding == 0) takeItems(1);
    }

    /** Give back the items of a list a later group replaces; nothing inside a list decode discards. */
    private void giveBack(Reader r, List<Entity> items) {
        if (r.discarding == 0) giveBackItems(items);
    }

    private void decodeGroupInto(Seq.Node g, Reader r, Entity e) {
        List<Entity> items = new ArrayList<>();
        switch (g.repeat) {
            case COUNT: {
                if (!r.line(g.len, "the count of " + g.list)) return;   // beyond the extent: an absent list
                long n = r.take(g.len);
                giveBack(r, e.list(g.list));   // a later group of the list replaces the earlier one's items
                countItems(r, n);                // before any item is read (ruling 7d of 0.11)
                long left = r.limit() - r.pos;
                if (n < 0 || n > left) {
                    throw malformed("the count of " + g.list + " is " + Long.toUnsignedString(n) + " and " + left + " bits are left");
                }
                for (long i = 0; i < n; i++) items.add(decodeItem(g, r));
                break;
            }
            case SIZE: {
                if (!r.line(0, "the count of " + g.list)) return;   // at the end of the extent: an absent list
                long n = g.sized ? r.constrained(g.lb, g.ub, "the count of " + g.list) : r.lengthDet(g.list);
                giveBack(r, e.list(g.list));
                countItems(r, n);   // before any item is read (7d of 0.11)
                long left = r.limit() - r.pos;
                if (n > left) throw malformed("the count of " + g.list + " is " + n + " and " + left + " bits are left");
                for (long i = 0; i < n; i++) items.add(decodeItem(g, r));
                break;
            }
            case REF: {
                // the count line read earlier in this body; the bits left are those at the group (ruling 20 of 0.21)
                Long c = r.counts.get(g.countRef);
                if (c == null || c < 0) return;
                Long c2 = g.countRef2 == null ? null : r.counts.get(g.countRef2);
                if (g.countRef2 != null && (c2 == null || c2 < 0)) return;
                if (r.soft >= 0 && r.pos >= r.soft) return;   // the group past an extent's end: absent (ruling 6)
                if (g.countRef2 != null) {
                    // engine-spec 0.31: the two numbers of items agree, as exact integers, before the bits left (ruling 4)
                    BigInteger a = r.exactCounts.get(g.countRef), b = r.exactCounts.get(g.countRef2);
                    if (!a.equals(b)) {
                        throw malformed("count " + g.countRef.name + " gives " + a + " items of " + g.list + " and count "
                                + g.countRef2.name + " gives " + b);
                    }
                }
                giveBack(r, e.list(g.list));
                countItems(r, c);   // before any item is read (7d of 0.11)
                long left = r.limit() - r.pos;
                if (c > left) throw malformed("count " + g.countRef.name + " of " + g.list + " is " + c + " and " + left + " bits are left");
                for (long i = 0; i < c; i++) items.add(decodeItem(g, r));
                break;
            }
            case REST: {
                // items while bits remain in the extent: 8 when it is counted in bytes, 1 when in bits; fewer are padding
                long unit = r.soft >= 0 && r.softBits ? 1 : 8;
                giveBack(r, e.list(g.list));
                while (r.limit() - r.pos >= unit) {
                    long at = r.pos;
                    oneItem(r);   // each item counts (7a of 0.11)
                    items.add(decodeItem(g, r));
                    if (r.pos == at) throw malformed("an item of " + g.list + " reads no bits (ruling 1 of 0.21)");
                }
                break;
            }
            case LAST:
                // the first bit at an extent's end: an absent list (ruling 34 of 0.8); a later one there is malformed (ruling 13)
                if (r.soft >= 0 && r.pos >= r.soft) return;
                giveBack(r, e.list(g.list));
                while (true) {
                    r.need(1, "the bit before an item of " + g.list);
                    long last = r.take(1);
                    oneItem(r);   // each item counts (7a of 0.11)
                    items.add(decodeItem(g, r));
                    if (last == 1) break;
                }
                break;
            case WHILE:
                if (r.soft >= 0 && r.pos >= r.soft) return;
                giveBack(r, e.list(g.list));
                while (true) {
                    if (r.indicator("the bit before an item of " + g.list) == 0) break;
                    oneItem(r);
                    items.add(decodeItem(g, r));
                }
                break;
            case MORE:
                if (r.soft >= 0 && r.pos >= r.soft) return;
                giveBack(r, e.list(g.list));
                while (true) {
                    long more = r.indicator("the bit before an item of " + g.list);
                    oneItem(r);
                    items.add(decodeItem(g, r));
                    if (more == 0) break;
                }
                break;
            default:
                if (r.soft >= 0 && r.pos >= r.soft) return;
                giveBack(r, e.list(g.list));
                while (true) {
                    oneItem(r);
                    items.add(decodeItem(g, r));
                    if (r.indicator("the bit after an item of " + g.list) == 0) break;
                }
        }
        e.putList(g.list, items);
    }

    private Entity decodeItem(Seq.Node g, Reader r) {
        Entity item = new Entity();
        Seq.Kind kind = decodeBody(g.items, r, item);
        if (g.items.hasKinds) item.setKind(pack.format, kind.name);   // Item.kind
        return item;
    }

    // ---- encode ----

    /** One encode: the message so far (bits not written are zero), the cursor, and the presence bits computed. */
    private final class Writer {
        byte[] b = new byte[64];
        long pos;
        final boolean[][] presence = new boolean[pack.seqPresences][];
        /** {@code length ... whole} fields to write once the message is laid out. */
        final List<Seq.Node> wholes = new ArrayList<>();
        final List<Long> wholeAt = new ArrayList<>();
        /** {@code count} fields to fill in once the message is laid out, and the latest of each count line. */
        final List<CountSlot> slots = new ArrayList<>();
        final Map<Seq.Node, CountSlot> slotOf = new IdentityHashMap<>();
        /** The open extents, innermost first: the message, then each {@code length} block being written. */
        final ArrayDeque<Extent> extents = new ArrayDeque<>();
        /**
         * The case of each switch, per entity or item, assumed where a presence, {@code opt} or {@code fx} bit is
         * computed before the switch is reached: the case the previous pass selected, else an estimate.
         */
        final Map<Entity, Map<Seq.Node, Seq.Case>> assumed;
        /** The case each switch selected in this pass, from the bits its key's line wrote. */
        final Map<Entity, Map<Seq.Node, Seq.Case>> actual = new IdentityHashMap<>();
        /** True when a switch selected a case other than the one assumed: the pass is run again. */
        boolean mismatch;
        /** Per shadow entity: the keys whose bits did not read back through their transform or table. */
        final Map<Entity, java.util.Set<String>> failed = new IdentityHashMap<>();
        /** engine-spec 0.33: the bit positions a held key wrote (ruling 12). */
        final java.util.BitSet held = new java.util.BitSet();

        Writer(Map<Entity, Map<Seq.Node, Seq.Case>> assumed) {
            this.assumed = assumed;
            extents.push(new Extent(0, false));
        }

        void ensure(long bits) {
            long bytes = (bits + 7) >>> 3;
            if (bytes <= b.length) return;
            if (bytes > Integer.MAX_VALUE - 16) {
                throw new GtException(GtException.Code.TRANSFORM_ENCODE, pack.format, null, "the message is too long: " + bytes + " bytes");
            }
            b = Arrays.copyOf(b, (int) Math.max(bytes, b.length * 2L));
        }

        void put(int len, long value) {
            ensure(pos + len);
            BitsCodec.writeBits(b, pos, len, value, msb);
            pos += len;
        }

        void skip(long len) {
            pos += len;
            ensure(pos);
        }

        /** A length determinant; 16384 or more would need a fragmented form (IllegalArgumentException, transform-encode). */
        void lengthDet(long n) {
            if (n < 0x80) put(8, n);
            else if (n < 0x4000) put(16, 0x8000 | n);
            else throw new IllegalArgumentException("a length of " + n + " needs a fragmented form, which this engine does not write");
        }

        void normallySmall(long v) {
            if (v <= 63) {
                put(1, 0);
                put(6, v);
            } else {
                put(1, 1);
                int octets = unsignedOctets(v);
                lengthDet(octets);
                put(8 * octets, v);
            }
        }

        /** The case assumed for switch {@code sw} of entity {@code e}. */
        Seq.Case assumedCase(Seq.Node sw, Entity e, Map<String, Object> defs) {
            Map<Seq.Node, Seq.Case> m = assumed.get(e);
            if (m != null && m.containsKey(sw)) return m.get(sw);
            // no earlier pass reached it: what the first line mapping the key would write, read back (ruling 37)
            return Seq.select(sw, predict(sw, e, defs));
        }
    }

    /** The fewest octets, at least one, that hold {@code v} as an unsigned number. */
    private static int unsignedOctets(long v) { return Math.max(1, (64 - Long.numberOfLeadingZeros(v) + 7) / 8); }

    /** The fewest octets that hold {@code v} as a two's-complement number. */
    private static int twosOctets(long v) {
        int n = 1;
        while (n < 8 && (v < -(1L << (8 * n - 1)) || v >= (1L << (8 * n - 1)))) n++;
        return n;
    }

    /** A {@code count} field written as {@code n} and filled in by its group (engine-spec 0.21). */
    private static final class CountSlot {
        final Seq.Node node;
        final long at;
        BigInteger value;

        CountSlot(Seq.Node node, long at) {
            this.node = node;
            this.at = at;
            this.value = BigInteger.valueOf(node.plus);
        }
    }

    /** An extent being written: where it starts, whether it counts bits, the starts of the rest items in it. */
    private static final class Extent {
        final long start;
        final boolean bits;
        final List<Long> restItems = new ArrayList<>();
        /** A rest group of this extent has been written: within an item of an outer rest group, it ends the list. */
        boolean restReached;

        Extent(long start, boolean bits) {
            this.start = start;
            this.bits = bits;
        }
    }

    /**
     * Ruling 4 (with 21 and 34) of 0.21: in an extent counted in bytes, no rest item starts with fewer than 8 bits
     * left before its byte-padded end.
     */
    private void checkRestItems(Extent x, long end) {
        for (long at : x.restItems) {
            if (end - at < 8) {
                throw encodeError("an item of a rest group starts " + (end - at) + " bits before the end of its extent;"
                        + " decode reads an item only while 8 bits remain");
            }
        }
    }

    /** The value decode would read from what the switch's first key line writes for {@code e}, or null. */
    private Object predict(Seq.Node sw, Entity e, Map<String, Object> defs) {
        Seq.Node line = sw.keyLine;
        if (line.op == Seq.Op.WHEN) {
            // a when ... as line is the key's line (ruling 19 of 0.30): the value it writes, read back as uint
            try {
                return asWritten(line, e);
            } catch (GtException ex) {
                return null;
            }
        }
        Writer scratch = new Writer(new IdentityHashMap<>());
        Entity shadow = new Entity();
        try {
            encodeField(line, scratch, e, defs);
            scratch.ensure(line.len);
            readBack(line, scratch, 0, shadow);
        } catch (GtException ex) {
            return null;
        }
        return shadow.get(sw.switchKey);
    }

    private GtException encodeError(String why) {
        return new GtException(GtException.Code.TRANSFORM_ENCODE, pack.format, null, why);
    }

    /** At most this many passes settle the cases a switch selects. */
    private static final int PASSES = 8;

    @Override
    String encode(Entity e, boolean layer) {
        Seq.Kind kind = selectRoot(e, layer);
        Map<Entity, Map<Seq.Node, Seq.Case>> assumed = new IdentityHashMap<>();
        for (int pass = 1; ; pass++) {
            Writer w = new Writer(assumed);
            try {
                encodeKind(root, kind, w, e);
            } catch (GtException ex) {
                // the errors of a pass whose prediction is discarded are not reported (ruling 34)
                if (!w.mismatch) throw ex;
            }
            if (!w.mismatch) return finish(w);
            if (pass >= PASSES) {
                // a prediction that never settles (ruling 33)
                throw encodeError("the cases the switches select do not settle after " + PASSES + " passes");
            }
            assumed = w.actual;
        }
    }

    private String finish(Writer w) {
        int bytes = (int) ((w.pos + 7) >>> 3);   // a whole number of bytes; the remaining bits are zero
        if (pack.uper && bytes == 0) bytes = 1;   // an encoding of no bits is one octet 00 (X.691 10.1.3)
        w.ensure(w.pos);
        // under armor sixbit the message stays counted in bytes for rest (ruling 43 of 0.21)
        checkRestItems(w.extents.getLast(), (long) bytes * 8);
        for (CountSlot c : w.slots) {
            // the range check runs once the message is finished (ruling 30 of 0.21)
            Seq.Node n = c.node;
            if (c.value.signum() < 0 || c.value.bitLength() > n.len) {
                throw encodeError("count " + n.name + " holds " + c.value + ", which does not fit its " + n.len + " bits");
            }
            BitsCodec.writeBits(w.b, c.at, n.len, c.value.longValue(), msb);
        }
        for (int i = 0; i < w.wholes.size(); i++) {
            Seq.Node n = w.wholes.get(i);
            long value = bytes + n.plus;
            if (value < 0 || (n.len < 63 && value > BitsTransform.mask(n.len))) {
                throw encodeError("the length of the message, " + value + ", does not fit its " + n.len + " bits");
            }
            BitsCodec.writeBits(w.b, w.wholeAt.get(i), n.len, value, msb);
        }
        // armored text: the bits up to the cursor, not rounded to a byte (`length ... whole` is refused at load);
        // the counts of 0.21 are filled in first
        if (pack.armorSixbit) return toArmor(w.b, w.pos);
        return toHex(Arrays.copyOf(w.b, bytes));
    }

    /**
     * The message's kind: by the record that names this format, in the order of {@link #recordedKind} (engine-spec
     * 0.34), else the first kind whose {@code requires} the entity has, with the implicit term of each {@code when ... as}
     * line (engine-spec 0.30). A named kind the pack lacks is no-kind.
     */
    private Seq.Kind selectRoot(Entity e, boolean layer) {
        if (!root.hasKinds) return root.kinds.get(0);
        String named = recordedKind(e, layer);
        if (named != null) {
            Seq.Kind k = root.kind(named);
            if (k == null) {
                throw new GtException(GtException.Code.NO_KIND, pack.format, null,
                        "the entity names kind " + named + ", which is not a kind here");
            }
            return k;
        }
        for (Seq.Kind k : root.kinds) {
            if (Pack.allHold(k.requires, e) && asTermsHold(k, e)) return k;   // with the as terms of 0.30
        }
        throw new GtException(GtException.Code.NO_KIND, pack.format, null, "the entity has the required keys of no kind");
    }

    /**
     * By the kind the entity or item recorded for this format, else the first kind whose {@code requires} it has.
     * An item that names a kind its group does not have selects by {@code requires} (ruling 26 of 0.8).
     */
    private Seq.Kind selectForEncode(Seq.Body body, Entity e, String what) {
        if (!body.hasKinds) return body.kinds.get(0);
        if (pack.format.equals(e.kindFormat())) {
            Seq.Kind k = e.kindName() == null ? null : body.kind(e.kindName());
            if (k != null) return k;
            if (body == root) {
                throw new GtException(GtException.Code.NO_KIND, pack.format, null,
                        what + " names kind " + e.kindName() + ", which is not a kind here");
            }
        }
        for (Seq.Kind k : body.kinds) {
            if (Pack.allHold(k.requires, e) && asTermsHold(k, e)) return k;
        }
        throw new GtException(GtException.Code.NO_KIND, pack.format, null, what + " has the required keys of no kind");
    }

    /**
     * The implicit {@code requires} term of each {@code when ... as <k>} line of the kind (engine-spec 0.30): the
     * entity holds {@code <k>} and its value matches the when. A default does not count (ruling 6).
     */
    private static boolean asTermsHold(Seq.Kind k, Entity e) {
        for (Seq.Node w : k.whens) {
            if (w.as == null) continue;
            Object v = e.get(w.as.key);
            if (v == null ? !w.asOptional : !asMatches(w, v)) return false;   // optional: engine-spec 0.52
        }
        return true;
    }

    /**
     * True when the entity's value of a {@code when ... as} key matches the when: read as an unsigned 64-bit pattern,
     * it is a listed value or within a listed range (ruling 7 of 0.30).
     */
    private static boolean asMatches(Seq.Node w, Object v) {
        if (!(v instanceof Long || v instanceof Integer)) return false;
        return matches(w, ((Number) v).longValue());
    }

    /**
     * The bits a {@code when ... as} line writes (engine-spec 0.30): the entity's value of the key when it matches;
     * the first listed value when the entity does not hold the key; a held value that does not match is
     * transform-encode (the output would decode a different value).
     */
    private long asWritten(Seq.Node w, Entity e) {
        Object v = e.get(w.as.key);
        if (v == null) return w.value;
        if (!asMatches(w, v)) {
            throw encodeError(w.as.key + " holds " + Pack.canonText(v) + ", which the when line " + w.len + " "
                    + whenText(w) + " (line " + w.line + ") does not match: the output would decode a different value");
        }
        return ((Number) v).longValue();
    }

    private static String whenText(Seq.Node w) {
        if (w.ranges == null) return Long.toUnsignedString(w.value);
        StringBuilder b = new StringBuilder();
        for (int i = 0; i < w.ranges.length; i += 2) {
            if (b.length() > 0) b.append(',');
            b.append(Long.toUnsignedString(w.ranges[i]));
            if (w.ranges[i] != w.ranges[i + 1]) b.append("..").append(Long.toUnsignedString(w.ranges[i + 1]));
        }
        return b.toString();
    }

    /** The defaults in force inside a case: those around it, replaced by the case's own (ruling 22 of 0.20). */
    private static Map<String, Object> merge(Map<String, Object> defs, Seq.Case c) {
        if (c.scope.defaultValues.isEmpty()) return defs;
        Map<String, Object> m = new HashMap<>(defs);
        m.putAll(c.scope.defaultValues);
        return m;
    }

    /**
     * True when the lines would write a present key (a key with a default counts as present), a non-empty list, or
     * a nested presence that is not all zero: what sets a presence bit, an {@code opt} bit and an {@code fx} bit.
     * Of a switch only the selected case counts (engine-spec 0.20).
     */
    private boolean content(List<Seq.Node> nodes, Entity e, Map<String, Object> defs, Writer w) {
        for (Seq.Node n : nodes) {
            switch (n.op) {
                case FIELD:
                    for (Pack.Field f : n.keys) {
                        if (f.suppressed(e)) continue;   // neither its value nor its default is content (ruling 1 of 0.18)
                        // in a UPER pack no default counts as content (rulings 2 and 19 of 0.19)
                        if (e.get(f.key) != null || (!pack.uper && defs.containsKey(f.key))) return true;
                    }
                    break;
                case IF:
                case OPT:
                case LENGTH:
                case EXT:
                    if (content(n.body, e, defs, w)) return true;
                    break;
                case CHOICE:
                    for (List<Seq.Node> alt : n.altLines) if (content(alt, e, defs, w)) return true;
                    break;
                case CHAIN:
                    for (List<Seq.Node> part : n.parts) if (content(part, e, defs, w)) return true;
                    break;
                case GROUP: {
                    List<Entity> items = e.list(n.list);
                    if (items != null && !items.isEmpty()) return true;
                    break;
                }
                case SWITCH: {
                    Seq.Case c = w.assumedCase(n, e, defs);
                    if (c != null && content(c.body, e, merge(defs, c), w)) return true;
                    break;
                }
                default:
                    break;
            }
        }
        return false;
    }

    /**
     * Compute the bits of presence {@code p} from the lines after it: a bit is 1 when some {@code if} block naming
     * it without {@code !} has content. The blocks may lie in the items of a group: any item with the content sets
     * the bit. Of a switch only the selected case's lines set a bit.
     */
    private void collect(List<Seq.Node> nodes, int from, Entity e, Map<String, Object> defs, Seq.Node p, boolean[] bits, Writer w) {
        for (int i = from; i < nodes.size(); i++) {
            Seq.Node n = nodes.get(i);
            switch (n.op) {
                case IF: {
                    boolean has = false, known = false;
                    for (int k = 0; k < n.refBit.length; k++) {
                        if (n.refPresence[k] != p || n.refNot[k]) continue;
                        if (!known) {
                            has = content(n.body, e, defs, w);
                            known = true;
                        }
                        if (has) bits[n.refBit[k]] = true;
                    }
                    collect(n.body, 0, e, defs, p, bits, w);
                    break;
                }
                case OPT:
                case LENGTH:
                case EXT:
                    collect(n.body, 0, e, defs, p, bits, w);
                    break;
                case CHOICE:
                    for (List<Seq.Node> alt : n.altLines) collect(alt, 0, e, defs, p, bits, w);
                    break;
                case CHAIN:
                    for (List<Seq.Node> part : n.parts) collect(part, 0, e, defs, p, bits, w);
                    break;
                case SWITCH: {
                    Seq.Case c = w.assumedCase(n, e, defs);
                    if (c != null) collect(c.body, 0, e, merge(defs, c), p, bits, w);
                    break;
                }
                case GROUP: {
                    List<Entity> items = e.list(n.list);
                    if (items == null) break;
                    for (Entity item : items) {
                        Seq.Kind kind;
                        try {
                            kind = selectForEncode(n.items, item, "an item of " + n.list);
                        } catch (GtException ex) {
                            continue;   // reported when the item is written
                        }
                        collect(kind.all, 0, item, kind.scope.defaultValues, p, bits, w);
                    }
                    break;
                }
                default:
                    break;
            }
        }
    }

    /**
     * Write {@code nodes}. {@code shadow} is what decode would read back from the bits written so far for this
     * entity or item: a switch selects its case from it.
     */
    private void encodeLines(List<Seq.Node> nodes, Writer w, Entity e, Map<String, Object> defs, Entity shadow) {
        encodeLines(nodes, w, e, defs, shadow, null);
    }

    /**
     * The lines of one message or item of kind {@code kind}: its common lines, then its own. A kind with
     * {@code when ... at} lines (engine-spec 0.33) settles its windows once the lines covering them are written,
     * before any later line (a switch included) reads its key back.
     */
    private void encodeKind(Seq.Body body, Seq.Kind kind, Writer w, Entity e) {
        Settle st = kind.windows.isEmpty() ? null : new Settle(kind, body.common.size());
        encodeLines(kind.all, w, e, kind.scope.defaultValues, new Entity(), st);
    }

    /** The windows of one kind being written: where its own lines start, and the shadow as it stood there. */
    private static final class Settle {
        final Seq.Kind kind;
        final int common;
        long start;
        Map<String, Object> shadowAtStart;
        java.util.Set<String> failedAtStart;

        Settle(Seq.Kind kind, int common) {
            this.kind = kind;
            this.common = common;
        }
    }

    /** Called before line {@code idx} of the kind's lines (and once after the last): marks kind start, settles windows. */
    private void settlePoint(Settle st, int idx, Writer w, Entity e, Entity shadow) {
        if (idx == st.common) {
            st.start = w.pos;
            st.shadowAtStart = new HashMap<>(shadow.fields());
            java.util.Set<String> f = w.failed.get(shadow);
            st.failedAtStart = f == null ? null : new java.util.HashSet<>(f);
        }
        if (idx == st.common + st.kind.prefix) settleWindows(st, w, e, shadow);
    }

    /**
     * engine-spec 0.33, Encode: each window of the kind in line order. Bits that match the when, and agree with a
     * held {@code as} key, stand; otherwise the window takes the {@code as} key's value or the first listed value,
     * and a bit of it that differs from a bit a held key wrote is transform-encode (rulings 1, 12, 13 and 26). Then
     * the shadow is read again from the bits as they stand, so a switch reads its key from them.
     */
    private void settleWindows(Settle st, Writer w, Entity e, Entity shadow) {
        Seq.Kind kind = st.kind;
        for (Seq.Node win : kind.windows) {
            long pos = st.start + win.at;
            int len = win.len;
            long cur = BitsCodec.readBits(w.b, pos, len, msb);
            long target = win.as == null ? win.value : asWritten(win, e);   // the held as value (transform-encode when it does not match), or the first value
            boolean heldAs = win.as != null && e.get(win.as.key) != null;
            if (matches(win, cur) && (!heldAs || cur == target)) {   // the bits stand
                if (heldAs) w.held.set((int) pos, (int) (pos + len));
                continue;
            }
            byte[] tmp = w.b.clone();
            BitsCodec.writeBits(tmp, pos, len, target, msb);
            for (long p = pos; p < pos + len; p++) {
                if (w.held.get((int) p) && BitsCodec.readBits(tmp, p, 1, msb) != BitsCodec.readBits(w.b, p, 1, msb)) {
                    throw encodeError("the window of when " + len + " at " + Long.toUnsignedString(win.at) + " (line " + win.line
                            + ") would change bit " + (p - st.start) + " of the kind, which a held key wrote: the output would decode a different value");
                }
            }
            BitsCodec.writeBits(w.b, pos, len, target, msb);
            // the bits of a held as key are bits that key wrote; a window takes none away (ruling 16 of 0.52)
            if (heldAs) w.held.set((int) pos, (int) (pos + len));
        }
        // the shadow as decode would read the kind's first lines back, windows written
        shadow.fields().clear();
        shadow.fields().putAll(st.shadowAtStart);
        if (st.failedAtStart == null) w.failed.remove(shadow);
        else w.failed.put(shadow, new java.util.HashSet<>(st.failedAtStart));
        Failures fails = new Failures(pack.format);
        long pos = st.start;
        List<Seq.Node> own = kind.all.subList(st.common, kind.all.size());
        for (int i = 0; i < own.size(); i++) {
            Seq.Node n = own.get(i);
            if (n.op == Seq.Op.WHEN && n.hasAt) {
                if (n.as != null) putDecoded(n.as, BitsCodec.readBits(w.b, st.start + n.at, n.len, msb), shadow, fails);
                continue;
            }
            if (i >= kind.prefix) continue;
            if (n.op == Seq.Op.WHEN && n.as != null) putDecoded(n.as, BitsCodec.readBits(w.b, pos, n.len, msb), shadow, fails);
            if (n.op == Seq.Op.FIELD) readBack(n, w, pos, shadow);
            pos += n.len;
        }
    }

    private void encodeLines(List<Seq.Node> nodes, Writer w, Entity e, Map<String, Object> defs, Entity shadow, Settle st) {
        for (int idx = 0; idx <= nodes.size(); idx++) {
            if (st != null) settlePoint(st, idx, w, e, shadow);
            if (idx == nodes.size()) break;
            Seq.Node n = nodes.get(idx);
            switch (n.op) {
                case FIELD: {
                    long at = w.pos;
                    encodeField(n, w, e, defs);
                    readBack(n, w, at, shadow);
                    // engine-spec 0.33, ruling 12: bits a held key wrote, which a window may not change silently
                    if (n.u == null && n.until < 0) {
                        for (Pack.Field k : n.keys) {
                            if (e.get(k.key) != null && !k.suppressed(e)) {
                                w.held.set((int) at, (int) w.pos);
                                break;
                            }
                        }
                    }
                    break;
                }
                case CONST:
                    w.put(n.len, n.value);
                    break;
                case WHEN:
                    if (n.hasAt) {
                        break;   // engine-spec 0.33: a look-ahead occupies no bits; its window is settled later
                    } else if (n.as == null) {
                        w.put(n.len, n.value);
                    } else {
                        long v = asWritten(n, e);
                        w.put(n.len, v);
                        if (e.get(n.as.key) != null) w.held.set((int) (w.pos - n.len), (int) w.pos);   // ruling 16 of 0.52
                        shadow.put(n.as.key, v);   // decode would read it back: a switch on the key selects by it
                    }
                    break;
                case PAD:
                    w.skip(n.len);
                    break;
                case ALIGN:
                    w.skip((w.pos + n.len - 1) / n.len * n.len - w.pos);
                    break;
                case PRESENCE: {
                    boolean[] bits = new boolean[(n.fx ? Math.max(n.anyNamed.length(), 1) : n.len + 1)];
                    collect(nodes, idx + 1, e, defs, n, bits, w);
                    w.presence[n.id] = bits;
                    if (!n.fx) {
                        for (int i = 1; i <= n.len; i++) w.put(1, bits[i] ? 1 : 0);
                    } else {
                        // trailing octets that are all zero are not written, and at least one octet is
                        int top = 0;
                        for (int i = 1; i < bits.length; i++) if (bits[i]) top = i;
                        int octets = Math.max(1, (top + 6) / 7);
                        for (int o = 0; o < octets; o++) {
                            for (int i = o * 7 + 1; i <= o * 7 + 7; i++) w.put(1, bit(bits, i) ? 1 : 0);
                            w.put(1, o + 1 < octets ? 1 : 0);
                        }
                    }
                    break;
                }
                case IF:
                    if (holds(n, w.presence)) encodeLines(n.body, w, e, defs, shadow);
                    break;
                case OPT:
                    if (content(n.body, e, defs, w)) {
                        w.put(1, 1);
                        encodeLines(n.body, w, e, defs, shadow);
                    } else {
                        w.put(1, 0);
                    }
                    break;
                case CHAIN: {
                    int last = n.parts.size() - 1;
                    for (int k = 0; k <= last; k++) {
                        encodeLines(n.parts.get(k), w, e, defs, shadow);
                        if (k == last && !n.endsWithFx) break;
                        // an fx bit is 1 when any line after it in the chain would write a present key
                        boolean more = false;
                        for (int j = k + 1; j <= last && !more; j++) more = content(n.parts.get(j), e, defs, w);
                        w.put(1, more ? 1 : 0);
                        if (!more) break;
                    }
                    break;
                }
                case LENGTH: {
                    long at = w.pos;
                    w.skip(n.len);
                    long start = w.pos;
                    Extent x = new Extent(start, n.inBits);
                    w.extents.push(x);
                    encodeLines(n.body, w, e, defs, shadow);
                    w.extents.pop();
                    long units = w.pos - start;
                    if (!n.inBits) {
                        units = (units + 7) / 8;
                        w.skip(start + units * 8 - w.pos);   // a block counted in bytes is padded to a whole byte
                        checkRestItems(x, w.pos);
                    }
                    long value = units + n.plus;
                    if (value < 0 || (n.len < 63 && value > BitsTransform.mask(n.len))) {
                        throw encodeError("a length of " + value + " does not fit its " + n.len + " bits");
                    }
                    BitsCodec.writeBits(w.b, at, n.len, value, msb);
                    break;
                }
                case COUNT: {
                    // written as n; the group that names it fills it in (engine-spec 0.21)
                    CountSlot c = new CountSlot(n, w.pos);
                    w.slots.add(c);
                    w.slotOf.put(n, c);
                    w.skip(n.len);
                    break;
                }
                case WHOLE:
                    w.wholes.add(n);
                    w.wholeAt.add(w.pos);
                    w.skip(n.len);
                    break;
                case GROUP:
                    encodeGroup(n, w, e);
                    break;
                case EXT:
                    w.put(1, 0);   // extension additions are never written
                    encodeLines(n.body, w, e, defs, shadow);
                    break;
                case CHOICE: {
                    // the first alt in line order with content, else the first alt
                    int pick = 0;
                    for (int k = 0; k < n.altLines.size(); k++) {
                        if (content(n.altLines.get(k), e, defs, w)) { pick = k; break; }
                    }
                    if (n.ext) w.put(1, 0);
                    w.put(Seq.rangeBits(0, n.alts - 1), n.altIndex.get(pick));
                    encodeLines(n.altLines.get(pick), w, e, defs, shadow);
                    break;
                }
                case INNER: {
                    // engine-spec 0.34: the checks, then a whole byte, then the inner pack's message of the same entity
                    BitsWire<?> inner = reachInner(n);
                    if (w.pos % 8 != 0) throw encodeError("the inner line of " + n.name + " is reached at bit " + w.pos + ", not on a whole byte");
                    byte[] bytes = fromHex(inner.encode(e, true));
                    w.ensure(w.pos + 8L * bytes.length);
                    System.arraycopy(bytes, 0, w.b, (int) (w.pos / 8), bytes.length);
                    w.pos += 8L * bytes.length;
                    break;
                }
                case SWITCH: {
                    // the case decode would select from the bits the key's line wrote (engine-spec 0.20)
                    Object v = shadow.get(n.switchKey);
                    java.util.Set<String> bad = w.failed.get(shadow);
                    if (v == null && bad != null && bad.contains(n.switchKey)) {
                        // the key's bits would not decode: the output would not decode either (ruling 31)
                        throw encodeError("switch " + n.switchKey + " (line " + n.line
                                + "): the value written for the key does not read back through its transform or table");
                    }
                    Seq.Case c = Seq.select(n, v);
                    if (c != w.assumedCase(n, e, defs)) w.mismatch = true;
                    w.actual.computeIfAbsent(e, k -> new IdentityHashMap<>()).put(n, c);
                    if (c == null) throw noCase(n, v);
                    encodeLines(c.body, w, e, merge(defs, c), shadow);
                    break;
                }
                default:
                    throw new IllegalStateException(n.op.name());
            }
        }
    }

    /** Decode the bits a field line just wrote into {@code shadow}, as decode would read them. */
    private void readBack(Seq.Node n, Writer w, long at, Entity shadow) {
        Pack.Field f = n.keys.get(0);
        if (n.until >= 0) {
            Object v;
            try {
                v = untilText(f, untilCodes(n, f, w.b, at, w.pos, false));
            } catch (IllegalArgumentException ex) {
                for (Pack.Field k : n.keys) if (shadow.get(k.key) == null) w.failed.computeIfAbsent(shadow, x -> new java.util.HashSet<>()).add(k.key);
                return;
            }
            Failures fails = new Failures(pack.format);
            for (Pack.Field k : n.keys) putDecoded(k, v, shadow, fails);
            for (Pack.Field k : fails.fields) w.failed.computeIfAbsent(shadow, x -> new java.util.HashSet<>()).add(k.key);
            return;
        }
        if (n.u != null) {
            // a UPER field (0.19): read back from the bits it wrote, at its variable length
            Reader rr = new Reader(new BitMsg(w.b, w.pos));
            rr.pos = at;
            Object v;
            try {
                v = readUper(n.u, f, rr);
            } catch (IllegalArgumentException ex) {
                for (Pack.Field k : n.keys) if (shadow.get(k.key) == null) w.failed.computeIfAbsent(shadow, x -> new java.util.HashSet<>()).add(k.key);
                return;
            }
            Failures fails = new Failures(pack.format);
            for (Pack.Field k : n.keys) putDecoded(k, v, shadow, fails);
            for (Pack.Field k : fails.fields) w.failed.computeIfAbsent(shadow, x -> new java.util.HashSet<>()).add(k.key);
            return;
        }
        if (f.absent != null) {
            long raw = BitsCodec.readBits(w.b, at, n.len, msb);
            if (f.absent.matches(f.swap ? BitsCodec.swapBytes(raw, n.len) : raw)) return;   // a sentinel: absent
        }
        Object v;
        try {
            v = valueAt(f, w.b, at, n.len);
        } catch (IllegalArgumentException ex) {
            // decode would fail the line: its keys do not read back
            for (Pack.Field k : n.keys) if (shadow.get(k.key) == null) w.failed.computeIfAbsent(shadow, x -> new java.util.HashSet<>()).add(k.key);
            return;
        }
        Failures fails = new Failures(pack.format);
        for (Pack.Field k : n.keys) putDecoded(k, v, shadow, fails);
        for (Pack.Field k : fails.fields) w.failed.computeIfAbsent(shadow, x -> new java.util.HashSet<>()).add(k.key);
    }

    /**
     * The value of the earliest key of the line that the entity holds; when it holds none, the default of the
     * earliest key that has one (ruling 16 of 0.8); zero bits when there is neither.
     */
    private void encodeField(Seq.Node n, Writer w, Entity e, Map<String, Object> defs) {
        Pack.Field f = null;
        // a field line suppressed by `with` is no candidate; its `also` keys stay candidates (ruling 5 of 0.18)
        for (Pack.Field k : n.keys) {
            if (e.get(k.key) != null && !k.suppressed(e)) { f = k; break; }
        }
        if (f == null) {
            for (Pack.Field k : n.keys) {
                if (defs.containsKey(k.key) && !k.suppressed(e)) { f = k; break; }
            }
        }
        Object v = f == null ? null : valueToEncode(f, e, defs);
        if (n.until >= 0) {
            // 0.22: the text's characters, then the terminator; an absent key (no default) the terminator alone
            Pack.Field k = f == null ? n.keys.get(0) : f;
            int cw = k.bits.charWidth();
            if (v != null) {
                String text = v instanceof Double ? Transform.formatDouble((Double) v) : String.valueOf(v);
                int[] codes;
                try {
                    codes = k.bits.encodeExact(text, n.until);
                    if (codes.length > 2040 / cw) {
                        throw new IllegalArgumentException("text of " + codes.length + " characters is longer than " + (2040 / cw));
                    }
                } catch (IllegalArgumentException ex) {
                    throw encodeFailure(k, ex);
                }
                for (int c : codes) w.put(cw, c);
            }
            w.put(cw, n.until);
            return;
        }
        if (n.u != null) {
            Pack.Field k = f == null ? n.keys.get(0) : f;
            try {
                writeUper(n.u, k, v, w);
            } catch (IllegalArgumentException ex) {
                throw encodeFailure(k, ex);
            }
            return;
        }
        if (v != null) {
            try {
                if (f.bits.isChars()) {
                    int cw = f.bits.charWidth();
                    for (int c : f.bits.encodeChars(v, n.len / cw)) w.put(cw, c);
                } else if (f.bits.isAscii()) {
                    byte[] bytes = f.bits.encodeAscii(v, n.len / 8);
                    if (f.swap) BitsCodec.reverseBytes(bytes);
                    for (byte b : bytes) w.put(8, b & 0xffL);
                } else if (f.bits.isSixbit()) {
                    for (int c : BitsTransform.encodeSixbit(v, n.len / 6)) w.put(6, c);
                } else {
                    long raw = f.bits.encode(v, n.len);
                    w.put(n.len, f.swap ? BitsCodec.swapBytes(raw, n.len) : raw);
                }
            } catch (IllegalArgumentException ex) {
                throw encodeFailure(f, ex);
            }
            return;
        }
        // No key has a value: the field's first sentinel, else zero bits. A sentinel is never content (ruling 4 of 0.9).
        Pack.Field first = n.keys.get(0);
        if (first.absent != null && !first.suppressed(e)) {
            long raw = first.absent.firstNum();
            w.put(n.len, first.swap ? BitsCodec.swapBytes(raw, n.len) : raw);
            return;
        }
        w.skip(n.len);
    }

    /** One field with a UPER locator; {@code v} null for an absent key (ruling 1 of 0.19). Throws IllegalArgumentException. */
    private static void writeUper(Seq.Uper u, Pack.Field f, Object v, Writer w) {
        switch (u.kind) {
            case INT: {
                long x = v == null ? u.lb : f.bits.encodeInteger(v);
                boolean root = x >= u.lb && x <= u.ub;
                if (!root && !u.ext) throw new IllegalArgumentException("value " + x + " is outside " + u.lb + ".." + u.ub);
                if (u.ext) w.put(1, root ? 0 : 1);
                if (root) {
                    w.put(Seq.rangeBits(u.lb, u.ub), x - u.lb);
                } else {
                    int octets = twosOctets(x);
                    w.lengthDet(octets);
                    w.put(8 * octets, x);
                }
                break;
            }
            case INT_SEMI: {
                long x = v == null ? u.lb : f.bits.encodeInteger(v);
                if (x < u.lb) throw new IllegalArgumentException("value " + x + " is below " + u.lb);
                long d = x - u.lb;
                int octets = unsignedOctets(d);
                w.lengthDet(octets);
                w.put(8 * octets, d);
                break;
            }
            case INT_FREE: {
                long x = v == null ? 0 : f.bits.encodeInteger(v);
                int octets = twosOctets(x);
                w.lengthDet(octets);
                w.put(8 * octets, x);
                break;
            }
            case ENUM: {
                long i = v == null ? 0 : f.bits.encodeInteger(v);
                if (i < 0) throw new IllegalArgumentException("enumeration index " + i + " is negative");
                if (i < u.ub) {
                    if (u.ext) w.put(1, 0);
                    w.put(Seq.rangeBits(0, u.ub - 1), i);
                } else if (u.ext) {
                    w.put(1, 1);
                    w.normallySmall(i - u.ub);
                } else {
                    throw new IllegalArgumentException("enumeration index " + i + " is outside the " + u.ub + " root values and the enumeration is not extensible");
                }
                break;
            }
            case CHARS: {
                String s = v == null ? "\0".repeat((int) u.lb) : v instanceof Double ? Transform.formatDouble((Double) v) : String.valueOf(v);
                for (int i = 0; i < s.length(); i++) {
                    if (s.charAt(i) > 127) throw new IllegalArgumentException(String.format("character U+%04X at offset %d is above 127", (int) s.charAt(i), i));
                }
                writeCount(u, s.length(), w, "characters");
                for (int i = 0; i < s.length(); i++) w.put(7, s.charAt(i));
                break;
            }
            default: {
                byte[] b = v == null ? new byte[(int) u.lb] : f.tlv.encode(v, 0);
                writeCount(u, b.length, w, "octets");
                for (byte x : b) w.put(8, x & 0xff);
            }
        }
    }

    private static void writeCount(Seq.Uper u, long count, Writer w, String what) {
        if (u.sized) {
            if (count < u.lb || count > u.ub) throw new IllegalArgumentException(count + " " + what + " are outside " + u.lb + ".." + u.ub);
            w.put(Seq.rangeBits(u.lb, u.ub), count - u.lb);
        } else {
            w.lengthDet(count);
        }
    }

    private void encodeGroup(Seq.Node g, Writer w, Entity e) {
        List<Entity> items = e.list(g.list);
        int n = items == null ? 0 : items.size();
        switch (g.repeat) {
            case SIZE: {
                if (items == null) {
                    // an absent list: lb items with no keys
                    items = new ArrayList<>();
                    for (long i = 0; g.sized && i < g.lb; i++) items.add(new Entity());
                    n = items.size();
                }
                if (g.sized ? (n < g.lb || n > g.ub) : n >= 0x4000) {
                    throw new GtException(GtException.Code.TRANSFORM_ENCODE, pack.format, null, g.list + ": " + n + " items are outside "
                            + (g.sized ? g.lb + ".." + g.ub : "the lengths written without fragments (below 16384)"));
                }
                if (g.sized) w.put(Seq.rangeBits(g.lb, g.ub), n - g.lb);
                else w.lengthDet(n);
                for (int i = 0; i < n; i++) encodeItem(g, w, items.get(i));
                break;
            }
            case COUNT:
                if (g.len < 63 && n > BitsTransform.mask(g.len)) {
                    throw new GtException(GtException.Code.TRANSFORM_ENCODE, pack.format, null,
                            g.list + ": " + n + " items do not fit the " + g.len + "-bit count");
                }
                w.put(g.len, n);   // an absent list writes a count of 0
                for (int i = 0; i < n; i++) encodeItem(g, w, items.get(i));
                break;
            case REF: {
                CountSlot c = w.slotOf.get(g.countRef);
                if (c != null) c.value = BigInteger.valueOf(n).add(BigInteger.valueOf(g.countRef.plus));
                // engine-spec 0.31: the second count holds the same number of items plus its own plus
                CountSlot c2 = g.countRef2 == null ? null : w.slotOf.get(g.countRef2);
                if (c2 != null) c2.value = BigInteger.valueOf(n).add(BigInteger.valueOf(g.countRef2.plus));
                for (int i = 0; i < n; i++) encodeItem(g, w, items.get(i));
                break;
            }
            case REST: {
                Extent x = w.extents.peek();
                for (int i = 0; i < n; i++) {
                    long at = w.pos;
                    if (!x.bits) x.restItems.add(at);
                    x.restReached = false;
                    encodeItem(g, w, items.get(i));
                    if (w.pos == at) throw encodeError("an item of " + g.list + " writes no bits (ruling 29 of 0.21)");
                    if (x.restReached && i + 1 < n) {
                        // the item's own rest group reads to the end of the extent: no item can follow it (ruling 10)
                        throw encodeError(g.list + ": item " + i + " writes a rest group that runs to the end of the extent,"
                                + " and another item follows it (ruling 10 of 0.21)");
                    }
                }
                x.restReached = true;
                break;
            }
            case WHILE:
                for (int i = 0; i < n; i++) {
                    w.put(1, 1);
                    encodeItem(g, w, items.get(i));
                }
                w.put(1, 0);
                break;
            default:
                if (n == 0) {
                    throw new GtException(GtException.Code.TRANSFORM_ENCODE, pack.format, null, g.list + ": the list is "
                            + (items == null ? "absent" : "empty") + " and a group with "
                            + g.repeat.name().toLowerCase(java.util.Locale.ROOT) + " has at least one item on the wire");
                }
                for (int i = 0; i < n; i++) {
                    if (g.repeat == Seq.Repeat.MORE) w.put(1, i + 1 < n ? 1 : 0);
                    if (g.repeat == Seq.Repeat.LAST) w.put(1, i + 1 < n ? 0 : 1);
                    encodeItem(g, w, items.get(i));
                    if (g.repeat == Seq.Repeat.FX) w.put(1, i + 1 < n ? 1 : 0);
                }
        }
    }

    private void encodeItem(Seq.Node g, Writer w, Entity item) {
        Seq.Kind kind = selectForEncode(g.items, item, "an item of " + g.list);
        encodeKind(g.items, kind, w, item);
    }
}
