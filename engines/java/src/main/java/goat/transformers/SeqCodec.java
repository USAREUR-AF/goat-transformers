package goat.transformers;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/**
 * The {@code bits} wire with {@code layout sequential} (engine-spec 0.8): the lines of the pack are read, and
 * written, in file order from a cursor. Hex text in and out; a message is a whole number of bytes. With
 * {@code armor sixbit} (engine-spec 0.14) armored text in and out: a message is any number of bits, and encode
 * writes the bits up to the cursor.
 */
final class SeqCodec extends Codec<byte[]> {
    private final boolean msb;
    private final Seq.Body root;

    SeqCodec(Pack pack) {
        super(pack);
        this.msb = pack.msbFirst;
        this.root = pack.seq;
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
        final boolean[][] presence = new boolean[pack.seqPresences][];
        final Failures fails = new Failures();

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
    }

    @Override
    Entity decodeMessage(String text) {
        Reader r = new Reader(parseBits(text));
        Entity e = new Entity();
        Seq.Kind kind = decodeBody(root, r, e);
        finishDecode(e, r.fails);
        if (root.hasKinds) e.setKind(pack.format, kind.name);
        return e;
    }

    /** Decode the common lines, select the kind at the cursor, decode its lines. */
    private Seq.Kind decodeBody(Seq.Body body, Reader r, Entity e) {
        decodeLines(body.common, r, e);
        Seq.Kind kind = body.kinds.get(0);
        if (body.hasKinds) {
            kind = null;
            long at = r.pos;
            for (Seq.Kind k : body.kinds) {
                r.pos = at;
                boolean all = true;
                for (Seq.Node w : k.whens) {
                    // a when any of whose bits lies beyond the input does not hold
                    if (r.pos + w.len > r.limit() || r.take(w.len) != w.value) { all = false; break; }
                }
                if (all) { kind = k; break; }
            }
            if (kind == null) {
                r.pos = at;
                throw new GtException(GtException.Code.NO_KIND, pack.format, null,
                        (body == root ? "the message" : "an item") + " matches no kind at bit " + at);
            }
        }
        decodeLines(kind.lines, r, e);
        return kind;
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
                    try {
                        if (f.bits.isAscii()) {
                            byte[] bytes = new byte[n.len / 8];
                            for (int i = 0; i < bytes.length; i++) bytes[i] = (byte) r.take(8);
                            if (f.swap) BitsCodec.reverseBytes(bytes);
                            v = f.bits.decodeAscii(bytes, f.trim);
                        } else if (f.bits.isSixbit()) {
                            long at = r.pos;
                            r.pos += n.len;
                            v = BitsTransform.decodeSixbit(BitsCodec.readSixbit(r.msg, at, n.len, msb), f.trim);
                        } else {
                            long at = r.pos;
                            r.pos += n.len;   // the cursor moves on whether or not the transform succeeds
                            long raw = BitsCodec.readBits(r.msg, at, n.len, msb);
                            v = f.bits.decode(f.swap ? BitsCodec.swapBytes(raw, n.len) : raw, n.len);
                        }
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
                case WHEN:
                    // a common when: it must hold for every message (or item) of the format
                    if (r.pos + n.len > r.limit() || r.take(n.len) != n.value) {
                        throw new GtException(GtException.Code.NO_KIND, pack.format, null,
                                "the common when line " + n.len + " " + Long.toUnsignedString(n.value) + " does not hold");
                    }
                    break;
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
                    r.soft = r.pos + bits;
                    decodeLines(n.body, r, e);
                    r.pos = r.soft;   // content of the extent no line reads is skipped
                    r.soft = outer;
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
                    if (r.soft > total) r.soft = total;
                    break;
                }
                case GROUP:
                    decodeGroup(n, r, e);
                    break;
                default:
                    throw new IllegalStateException(n.op.name());
            }
        }
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
            if (bits[i] && !n.named.get(i)) {
                throw malformed("presence bit " + n.name + "." + i + " is 1 and no if block names it");
            }
        }
        return bits;
    }

    private void decodeGroup(Seq.Node g, Reader r, Entity e) {
        List<Entity> items = new ArrayList<>();
        switch (g.repeat) {
            case COUNT: {
                if (!r.line(g.len, "the count of " + g.list)) return;   // beyond the extent: an absent list
                long n = r.take(g.len);
                giveBackItems(e.list(g.list));   // a later group of the list replaces the earlier one's items
                takeItems(n);                    // before any item is read (ruling 7d of 0.11)
                long left = r.limit() - r.pos;
                if (n < 0 || n > left) {
                    throw malformed("the count of " + g.list + " is " + Long.toUnsignedString(n) + " and " + left + " bits are left");
                }
                for (long i = 0; i < n; i++) items.add(decodeItem(g, r));
                break;
            }
            case WHILE:
                if (r.soft >= 0 && r.pos >= r.soft) return;
                giveBackItems(e.list(g.list));
                while (true) {
                    if (r.indicator("the bit before an item of " + g.list) == 0) break;
                    takeItems(1);
                    items.add(decodeItem(g, r));
                }
                break;
            case MORE:
                if (r.soft >= 0 && r.pos >= r.soft) return;
                giveBackItems(e.list(g.list));
                while (true) {
                    long more = r.indicator("the bit before an item of " + g.list);
                    takeItems(1);
                    items.add(decodeItem(g, r));
                    if (more == 0) break;
                }
                break;
            default:
                if (r.soft >= 0 && r.pos >= r.soft) return;
                giveBackItems(e.list(g.list));
                while (true) {
                    takeItems(1);
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
    }

    private GtException encodeError(String why) {
        return new GtException(GtException.Code.TRANSFORM_ENCODE, pack.format, null, why);
    }

    @Override
    String encode(Entity e) {
        Writer w = new Writer();
        Seq.Kind kind = selectForEncode(root, e, "the entity");
        encodeLines(kind.all, w, e, kind.scope);
        // armored text: the bits up to the cursor, not rounded to a byte (`length ... whole` is refused at load)
        if (pack.armorSixbit) return toArmor(w.b, w.pos);
        int bytes = (int) ((w.pos + 7) >>> 3);   // a whole number of bytes; the remaining bits are zero
        w.ensure(w.pos);
        for (int i = 0; i < w.wholes.size(); i++) {
            Seq.Node n = w.wholes.get(i);
            long value = bytes + n.plus;
            if (value < 0 || (n.len < 63 && value > BitsTransform.mask(n.len))) {
                throw encodeError("the length of the message, " + value + ", does not fit its " + n.len + " bits");
            }
            BitsCodec.writeBits(w.b, w.wholeAt.get(i), n.len, value, msb);
        }
        return toHex(Arrays.copyOf(w.b, bytes));
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
            boolean all = true;
            for (String key : k.requires) {
                if (e.get(key) != null) continue;
                List<Entity> items = e.list(key);
                if (items == null || items.isEmpty()) { all = false; break; }
            }
            if (all) return k;
        }
        throw new GtException(GtException.Code.NO_KIND, pack.format, null, what + " has the required keys of no kind");
    }

    /**
     * True when the lines would write a present key (a key with a default counts as present), a non-empty list, or
     * a nested presence that is not all zero: what sets a presence bit, an {@code opt} bit and an {@code fx} bit.
     */
    private static boolean content(List<Seq.Node> nodes, Entity e, Pack.Scope scope) {
        for (Seq.Node n : nodes) {
            switch (n.op) {
                case FIELD:
                    for (Pack.Field f : n.keys) {
                        if (e.get(f.key) != null || scope.defaultValues.containsKey(f.key)) return true;
                    }
                    break;
                case IF:
                case OPT:
                case LENGTH:
                    if (content(n.body, e, scope)) return true;
                    break;
                case CHAIN:
                    for (List<Seq.Node> part : n.parts) if (content(part, e, scope)) return true;
                    break;
                case GROUP: {
                    List<Entity> items = e.list(n.list);
                    if (items != null && !items.isEmpty()) return true;
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
     * the bit.
     */
    private void collect(List<Seq.Node> nodes, int from, Entity e, Pack.Scope scope, Seq.Node p, boolean[] bits) {
        for (int i = from; i < nodes.size(); i++) {
            Seq.Node n = nodes.get(i);
            switch (n.op) {
                case IF: {
                    boolean has = false, known = false;
                    for (int k = 0; k < n.refBit.length; k++) {
                        if (n.refPresence[k] != p || n.refNot[k]) continue;
                        if (!known) {
                            has = content(n.body, e, scope);
                            known = true;
                        }
                        if (has) bits[n.refBit[k]] = true;
                    }
                    collect(n.body, 0, e, scope, p, bits);
                    break;
                }
                case OPT:
                case LENGTH:
                    collect(n.body, 0, e, scope, p, bits);
                    break;
                case CHAIN:
                    for (List<Seq.Node> part : n.parts) collect(part, 0, e, scope, p, bits);
                    break;
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
                        collect(kind.all, 0, item, kind.scope, p, bits);
                    }
                    break;
                }
                default:
                    break;
            }
        }
    }

    private void encodeLines(List<Seq.Node> nodes, Writer w, Entity e, Pack.Scope scope) {
        for (int idx = 0; idx < nodes.size(); idx++) {
            Seq.Node n = nodes.get(idx);
            switch (n.op) {
                case FIELD:
                    encodeField(n, w, e, scope);
                    break;
                case CONST:
                case WHEN:
                    w.put(n.len, n.value);
                    break;
                case PAD:
                    w.skip(n.len);
                    break;
                case ALIGN:
                    w.skip((w.pos + n.len - 1) / n.len * n.len - w.pos);
                    break;
                case PRESENCE: {
                    boolean[] bits = new boolean[(n.fx ? Math.max(n.named.length(), 1) : n.len + 1)];
                    collect(nodes, idx + 1, e, scope, n, bits);
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
                    if (holds(n, w.presence)) encodeLines(n.body, w, e, scope);
                    break;
                case OPT:
                    if (content(n.body, e, scope)) {
                        w.put(1, 1);
                        encodeLines(n.body, w, e, scope);
                    } else {
                        w.put(1, 0);
                    }
                    break;
                case CHAIN: {
                    int last = n.parts.size() - 1;
                    for (int k = 0; k <= last; k++) {
                        encodeLines(n.parts.get(k), w, e, scope);
                        if (k == last && !n.endsWithFx) break;
                        // an fx bit is 1 when any line after it in the chain would write a present key
                        boolean more = false;
                        for (int j = k + 1; j <= last && !more; j++) more = content(n.parts.get(j), e, scope);
                        w.put(1, more ? 1 : 0);
                        if (!more) break;
                    }
                    break;
                }
                case LENGTH: {
                    long at = w.pos;
                    w.skip(n.len);
                    long start = w.pos;
                    encodeLines(n.body, w, e, scope);
                    long units = w.pos - start;
                    if (!n.inBits) {
                        units = (units + 7) / 8;
                        w.skip(start + units * 8 - w.pos);   // a block counted in bytes is padded to a whole byte
                    }
                    long value = units + n.plus;
                    if (value < 0 || (n.len < 63 && value > BitsTransform.mask(n.len))) {
                        throw encodeError("a length of " + value + " does not fit its " + n.len + " bits");
                    }
                    BitsCodec.writeBits(w.b, at, n.len, value, msb);
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
                default:
                    throw new IllegalStateException(n.op.name());
            }
        }
    }

    /**
     * The value of the earliest key of the line that the entity holds; when it holds none, the default of the
     * earliest key that has one (ruling 16 of 0.8); zero bits when there is neither.
     */
    private void encodeField(Seq.Node n, Writer w, Entity e, Pack.Scope scope) {
        Pack.Field f = null;
        for (Pack.Field k : n.keys) {
            if (e.get(k.key) != null) { f = k; break; }
        }
        if (f == null) {
            for (Pack.Field k : n.keys) {
                if (scope.defaultValues.containsKey(k.key)) { f = k; break; }
            }
        }
        Object v = f == null ? null : valueToEncode(f, e, scope);
        if (v != null) {
            try {
                if (f.bits.isAscii()) {
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
        if (first.absent != null) {
            long raw = first.absent.firstNum();
            w.put(n.len, first.swap ? BitsCodec.swapBytes(raw, n.len) : raw);
            return;
        }
        w.skip(n.len);
    }

    private void encodeGroup(Seq.Node g, Writer w, Entity e) {
        List<Entity> items = e.list(g.list);
        int n = items == null ? 0 : items.size();
        switch (g.repeat) {
            case COUNT:
                if (g.len < 63 && n > BitsTransform.mask(g.len)) {
                    throw new GtException(GtException.Code.TRANSFORM_ENCODE, pack.format, null,
                            g.list + ": " + n + " items do not fit the " + g.len + "-bit count");
                }
                w.put(g.len, n);   // an absent list writes a count of 0
                for (int i = 0; i < n; i++) encodeItem(g, w, items.get(i));
                break;
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
                            + (g.repeat == Seq.Repeat.MORE ? "more" : "fx") + " has at least one item on the wire");
                }
                for (int i = 0; i < n; i++) {
                    if (g.repeat == Seq.Repeat.MORE) w.put(1, i + 1 < n ? 1 : 0);
                    encodeItem(g, w, items.get(i));
                    if (g.repeat == Seq.Repeat.FX) w.put(1, i + 1 < n ? 1 : 0);
                }
        }
    }

    private void encodeItem(Seq.Node g, Writer w, Entity item) {
        Seq.Kind kind = selectForEncode(g.items, item, "an item of " + g.list);
        encodeLines(kind.all, w, item, kind.scope);
    }
}
