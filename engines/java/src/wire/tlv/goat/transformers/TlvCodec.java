package goat.transformers;

import static goat.transformers.TlvLayout.MAX_TAG;

import goat.transformers.TlvLayout.Loc;
import java.io.ByteArrayOutputStream;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * The {@code tlv} wire (0.13): a set of items, each a tag, a length and a value, carried in and out as hex text. A
 * value may itself be a set. The set may follow a fixed key and a length, and may end with a {@code sum16} checksum
 * item. A path {@code 48.2} is the item of tag 2 in the set that is the value of the item of tag 48; a path takes
 * the first occurrence of a tag at every level.
 */
final class TlvCodec extends Codec<TlvCodec.Msg> {

    /** The tags a scope names at each place: a node per set the lines walk into. */
    private static final class Names {
        final Map<Long, Names> children = new HashMap<>();
        /** A field, a numeric when or a const ends here: the item is mapped. */
        boolean leaf;
        /** A line's path goes through here: the item's value is read as a set. */
        boolean walked;
    }

    TlvCodec(Pack pack) {
        super(pack);
        for (Pack.Kind k : pack.kinds) {
            Names root = new Names();
            for (Pack.Line l : k.scope.lines) {
                Loc loc = (Loc) l.loc;
                Names n = root;
                for (int i = 0; i < loc.tags.length; i++) {
                    n = n.children.computeIfAbsent(loc.tags[i], t -> new Names());
                    if (i < loc.tags.length - 1) n.walked = true;
                    else if (!(l instanceof Pack.When && ((Pack.When) l).present)) n.leaf = true;
                }
            }
            k.scope.info = root;
        }
    }

    // ---- decode ----

    /** One item: its tag and its value, bytes {@code from} to {@code to} of {@code b}. */
    static final class Item {
        final long tag;
        final byte[] b;
        final int from, to;
        /** The value read as a set ({@link TSet}), or the {@link GtException} it gave; null until asked for. */
        Object sub;

        Item(long tag, byte[] b, int from, int to) {
            this.tag = tag;
            this.b = b;
            this.from = from;
            this.to = to;
        }
    }

    static final class TSet {
        final List<Item> items = new ArrayList<>();
    }

    static final class Msg {
        final TSet top;
        Msg(TSet top) { this.top = top; }
    }

    @Override
    Msg parse(String text) {
        byte[] b = fromHex(text);
        int start = 0, end = b.length;
        byte[] key = pack.tlvKey;
        if (key != null) {
            if (b.length < key.length) throw malformed("the input is shorter than the key");
            for (int i = 0; i < key.length; i++) {
                if (b[i] != key[i]) throw malformed("the input does not begin with the key");
            }
            int[] pos = { key.length };
            long len = readLength(b, pos, b.length);
            // compared with the bytes left, never added to an offset first
            if (Long.compareUnsigned(len, b.length - pos[0]) > 0) {
                throw malformed("the set states " + Long.toUnsignedString(len) + " bytes, the input has " + (b.length - pos[0]) + " left");
            }
            start = pos[0];
            end = start + (int) len;
        }
        TSet top = parseSet(b, start, end);
        if (pack.tlvChecksum) {
            long t = pack.tlvChecksumTag;
            if (top.items.isEmpty()) throw malformed("the set has no checksum item");
            Item last = top.items.get(top.items.size() - 1);
            if (last.tag != t) throw malformed("the last item has tag " + last.tag + ", not the checksum tag " + t);
            int size = pack.tlvCrc32 ? 4 : 2;
            if (last.to - last.from != size) throw malformed("the checksum item has a value of " + (last.to - last.from) + " bytes, not " + size);
            for (int i = 0; i < top.items.size() - 1; i++) {
                if (top.items.get(i).tag == t) throw malformed("an item of the checksum tag " + t + " stands before the last");
            }
            long want = pack.tlvCrc32 ? crc32(b, last.from) & 0xffffffffL : sum16(b, last.from);
            long have = TlvTransform.unsigned(b, last.from, last.to);
            if (want != have) {
                throw malformed(pack.tlvCrc32 ? String.format("checksum is %08x, the CRC of the bytes is %08x", have, want)
                        : String.format("checksum is %04x, the bytes sum to %04x", have, want));
            }
        }
        return new Msg(top);
    }

    /** sum16 of bytes 0 to {@code to - 1}: a byte at an even offset counts {@code b * 256}, at an odd offset {@code b}. */
    static int sum16(byte[] b, int to) {
        long sum = 0;
        for (int i = 0; i < to; i++) sum += (i % 2 == 0) ? (b[i] & 0xff) << 8 : (b[i] & 0xff);
        return (int) (sum & 0xffff);
    }

    /**
     * CRC-32 of ISO/IEC 13818-1 (0.27) of bytes 0 to {@code to - 1}: polynomial 0x04C11DB7, register from 0xFFFFFFFF,
     * most significant bit first, no reflection, no final XOR. Not java.util.zip.CRC32, which is the reflected CRC.
     */
    static int crc32(byte[] b, int to) {
        int reg = 0xffffffff;
        for (int i = 0; i < to; i++) {
            reg ^= (b[i] & 0xff) << 24;
            for (int k = 0; k < 8; k++) reg = reg < 0 ? (reg << 1) ^ 0x04c11db7 : reg << 1;
        }
        return reg;
    }

    /** The items of bytes {@code from} to {@code to}, read whole. */
    private TSet parseSet(byte[] b, int from, int to) {
        TSet set = new TSet();
        int[] pos = { from };
        while (pos[0] < to) {
            long tag = readTag(b, pos, to);
            long len = readLength(b, pos, to);
            if (Long.compareUnsigned(len, to - pos[0]) > 0) {
                throw malformed("item " + tag + " states " + Long.toUnsignedString(len) + " bytes, its set has " + (to - pos[0]) + " left");
            }
            int at = pos[0];
            pos[0] = at + (int) len;
            set.items.add(new Item(tag, b, at, pos[0]));
        }
        return set;
    }

    private long readTag(byte[] b, int[] pos, int end) {
        int n = pack.tlvTagSize;
        if (n > 0) {
            if (end - pos[0] < n) throw malformed("a tag runs past its set");
            long v = TlvTransform.unsigned(b, pos[0], pos[0] + n);
            pos[0] += n;
            return v;
        }
        long v = 0;
        for (int k = 0; ; k++) {
            if (k == 4) throw malformed("a BER-OID tag of more than four bytes");
            if (pos[0] >= end) throw malformed("a tag runs past its set");
            int by = b[pos[0]++] & 0xff;
            if (k == 0 && by == 0x80) throw malformed("a BER-OID tag whose first byte is 0x80");
            v = (v << 7) | (by & 0x7f);
            if ((by & 0x80) == 0) return v;
        }
    }

    private long readLength(byte[] b, int[] pos, int end) {
        int n = pack.tlvLengthSize;
        if (n > 0) {
            if (end - pos[0] < n) throw malformed("a length runs past its set");
            long v = TlvTransform.unsigned(b, pos[0], pos[0] + n);
            pos[0] += n;
            return v;
        }
        if (pos[0] >= end) throw malformed("a length runs past its set");
        int first = b[pos[0]++] & 0xff;
        if (first < 0x80) return first;
        if (first == 0x80 || first > 0x88) throw malformed(String.format("a BER length whose first byte is 0x%02x", first));
        int k = first - 0x80;
        if (end - pos[0] < k) throw malformed("a length runs past its set");
        long v = TlvTransform.unsigned(b, pos[0], pos[0] + k);
        pos[0] += k;
        return v;
    }

    /** The item's value read as a set, its items whole. Throws malformed-wire when it is not a well-formed set. */
    private TSet subset(Item it) {
        if (it.sub == null) {
            try {
                it.sub = parseSet(it.b, it.from, it.to);
            } catch (GtException ex) {
                it.sub = ex;
            }
        }
        if (it.sub instanceof GtException) {
            GtException ex = (GtException) it.sub;
            throw malformed("the value of item " + it.tag + " is not a well-formed set: " + ex.getMessage());
        }
        return (TSet) it.sub;
    }

    private static Item first(TSet set, long tag) {
        for (Item it : set.items) if (it.tag == tag) return it;
        return null;
    }

    /** The first occurrence at the path, or null. Throws malformed-wire when a set on the path is not well formed. */
    private Item find(TSet top, long[] tags) {
        TSet cur = top;
        for (int i = 0; i < tags.length - 1; i++) {
            Item it = first(cur, tags[i]);
            if (it == null) return null;
            cur = subset(it);
        }
        return first(cur, tags[tags.length - 1]);
    }

    @Override
    boolean holds(Msg msg, Pack.When when) {
        Item it;
        try {
            it = find(msg.top, ((Loc) when.loc).tags);
        } catch (GtException ex) {
            return false;   // the item lies in a value that is not a well-formed set
        }
        if (it == null) return false;
        if (when.present) return true;
        int len = it.to - it.from;
        return len >= 1 && len <= 8 && TlvTransform.unsigned(it.b, it.from, it.to) == when.number;
    }

    @Override
    Entity decodeKind(Msg msg, Pack.Kind kind) {
        Entity e = new Entity();
        Failures fails = new Failures();
        for (Pack.Line l : kind.scope.lines) {
            // every set on the path of every line is walked into and read whole
            Item it = find(msg.top, ((Loc) l.loc).tags);
            if (!(l instanceof Pack.Field)) continue;
            Pack.Field f = (Pack.Field) l;
            if (e.get(f.key) != null || it == null) continue;
            if (it.from == it.to && !f.tlv.text()) continue;   // an empty value is absent (ruling 1 of 0.13)
            Object v;
            try {
                v = f.tlv.decode(it.b, it.from, it.to);
            } catch (IllegalArgumentException ex) {
                fails.add(f, ex.getMessage(), e);
                continue;
            }
            putDecoded(f, v, e, fails);
        }
        residue(msg.top, (Names) kind.scope.info, "", true, e, new HashMap<>());
        finishDecode(e, fails);
        return e;
    }

    /**
     * Every item of a walked set whose tag no line names there is residue, every occurrence, keyed by its path; the
     * second and later occurrences of one path are keyed {@code <path>#<k>}. The later occurrences of a named tag
     * are dropped; the first occurrence of a walked tag is a set whose residue is taken in turn.
     */
    private void residue(TSet set, Names names, String prefix, boolean top, Entity e, Map<String, Integer> counts) {
        int n = set.items.size();
        if (top && pack.tlvChecksum) n--;                     // the checksum item is neither mapped nor residue
        Set<Long> seen = new HashSet<>();
        for (int i = 0; i < n; i++) {
            Item it = set.items.get(i);
            String path = prefix + it.tag;
            Names c = names.children.get(it.tag);
            if (c != null && (c.leaf || c.walked)) {
                if (!seen.add(it.tag)) continue;
                if (c.walked) residue(subset(it), c, path + ".", false, e, counts);
                continue;
            }
            int k = counts.merge(path, 1, Integer::sum);
            e.putResidue(pack.format, k == 1 ? path : path + "#" + k, toHex(java.util.Arrays.copyOfRange(it.b, it.from, it.to)));
        }
    }

    // ---- encode ----

    /** An item being written: a value, or a nested set. */
    private static final class Out {
        final long tag;
        /** A nested set, or null for a value. */
        final OSet set;
        byte[] value;
        /** A {@code when … present} stands here: an empty item when nothing else writes one at the path. */
        boolean present;
        /** The when or const line whose value is written here (the earliest of the scope), or null. */
        Pack.When fixed;
        /** The field lines on this path, in line order. */
        final List<Pack.Field> fields = new ArrayList<>();

        Out(long tag, OSet set) {
            this.tag = tag;
            this.set = set;
        }
    }

    private static final class OSet {
        /** The items of the lines, at the position of the first line naming each. */
        final List<Out> mapped = new ArrayList<>();
        final Map<Long, Out> byTag = new HashMap<>();
        /** Residue of this set, in input order. */
        final List<Out> residue = new ArrayList<>();
    }

    @Override
    String encodeKind(Entity e, Pack.Kind kind) {
        OSet top = new OSet();
        List<Out> slots = new ArrayList<>();
        for (Pack.Line l : kind.scope.lines) {
            long[] tags = ((Loc) l.loc).tags;
            OSet cur = top;
            for (int i = 0; i < tags.length - 1; i++) {
                Out o = cur.byTag.get(tags[i]);
                if (o == null) {
                    o = new Out(tags[i], new OSet());
                    cur.byTag.put(tags[i], o);
                    cur.mapped.add(o);
                }
                cur = o.set;   // a value and a set on one path is refused at load (ruling 5 of 0.13)
            }
            long last = tags[tags.length - 1];
            Out o = cur.byTag.get(last);
            if (o == null) {
                o = new Out(last, null);
                cur.byTag.put(last, o);
                cur.mapped.add(o);
                slots.add(o);
            }
            if (l instanceof Pack.Field) {
                o.fields.add((Pack.Field) l);
            } else {
                Pack.When w = (Pack.When) l;
                if (w.present) o.present = true;
                else if (o.fixed == null) o.fixed = w;   // the earliest when or const (ruling 9 of 0.13)
            }
        }
        for (Out o : slots) {
            if (o.fixed != null) {
                o.value = TlvTransform.bigEndian(o.fixed.number, ((Loc) o.fixed.loc).size);
                continue;
            }
            for (Pack.Field f : o.fields) {
                Object v = valueToEncode(f, e, kind.scope);
                if (v == null) continue;
                try {
                    o.value = f.tlv.encode(v, ((Loc) f.loc).size);
                } catch (IllegalArgumentException ex) {
                    throw encodeFailure(f, ex);
                }
                break;
            }
        }
        for (Map.Entry<String, String> r : e.residue(pack.format).entrySet()) addResidue(top, r.getKey(), r.getValue());

        ByteArrayOutputStream body = new ByteArrayOutputStream();
        writeSet(body, top);
        if (pack.tlvChecksum) {
            writeTag(body, pack.tlvChecksumTag);
            writeLength(body, pack.tlvCrc32 ? 4 : 2);
        }
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        if (pack.tlvKey != null) {
            out.write(pack.tlvKey, 0, pack.tlvKey.length);
            writeLength(out, body.size() + (pack.tlvChecksum ? (pack.tlvCrc32 ? 4 : 2) : 0));
        }
        byte[] set = body.toByteArray();
        out.write(set, 0, set.length);
        if (pack.tlvChecksum) {
            byte[] sofar = out.toByteArray();
            if (pack.tlvCrc32) {
                int crc = crc32(sofar, sofar.length);
                out.write(crc >>> 24);
                out.write((crc >>> 16) & 0xff);
                out.write((crc >>> 8) & 0xff);
                out.write(crc & 0xff);
            } else {
                int sum = sum16(sofar, sofar.length);
                out.write(sum >>> 8);
                out.write(sum & 0xff);
            }
        }
        return toHex(out.toByteArray());
    }

    /** Place one residue entry: its value as the last item of the set its path names. Entries that do not parse are skipped. */
    private static void addResidue(OSet top, String key, String hex) {
        int hash = key.indexOf('#');
        String path = hash < 0 ? key : key.substring(0, hash);
        Object parsed = TlvLayout.parseLocator(path, 0);
        if (!(parsed instanceof Loc) || ((Loc) parsed).size != 0 || hex.length() % 2 != 0) return;
        byte[] value = new byte[hex.length() / 2];
        for (int i = 0; i < value.length; i++) {
            int hi = Character.digit(hex.charAt(2 * i), 16), lo = Character.digit(hex.charAt(2 * i + 1), 16);
            if (hi < 0 || lo < 0) return;
            value[i] = (byte) ((hi << 4) | lo);
        }
        long[] tags = ((Loc) parsed).tags;
        OSet cur = top;
        for (int i = 0; i < tags.length - 1; i++) {
            Out o = cur.byTag.get(tags[i]);
            if (o == null || o.set == null) {
                o = null;
                for (Out r : cur.residue) if (r.tag == tags[i] && r.set != null) o = r;
                if (o == null) {
                    o = new Out(tags[i], new OSet());
                    cur.residue.add(o);
                }
            }
            cur = o.set;
        }
        Out leaf = new Out(tags[tags.length - 1], null);
        leaf.value = value;
        cur.residue.add(leaf);
    }

    /** Write the items of a set; returns how many were written. */
    private int writeSet(ByteArrayOutputStream out, OSet s) {
        int n = 0;
        for (Out o : s.mapped) {
            if (o.set == null && o.value == null) {
                if (!o.present) continue;
                boolean inResidue = false;
                for (Out r : s.residue) inResidue |= r.tag == o.tag;
                if (inResidue) continue;   // ruling 2 of 0.13: the residue item stands at the residue position
                o.value = new byte[0];
            }
            if (writeItem(out, o)) n++;
        }
        for (Out o : s.residue) if (writeItem(out, o)) n++;
        return n;
    }

    private boolean writeItem(ByteArrayOutputStream out, Out o) {
        byte[] value = o.value;
        if (o.set != null) {
            ByteArrayOutputStream inner = new ByteArrayOutputStream();
            if (writeSet(inner, o.set) == 0) return false;   // a nested set with no items is not written
            value = inner.toByteArray();
        }
        writeTag(out, o.tag);
        writeLength(out, value.length);
        out.write(value, 0, value.length);
        return true;
    }

    private void writeTag(ByteArrayOutputStream out, long tag) {
        int n = pack.tlvTagSize;
        if (n > 0) {
            if (n < 8 && (tag < 0 || tag >= (1L << (8 * n)))) {
                throw new GtException(GtException.Code.TRANSFORM_ENCODE, pack.format, null, "tag " + tag + " does not fit tag " + n);
            }
            byte[] b = TlvTransform.bigEndian(tag, n);
            out.write(b, 0, n);
            return;
        }
        if (tag < 0 || tag > MAX_TAG) {
            throw new GtException(GtException.Code.TRANSFORM_ENCODE, pack.format, null, "tag " + tag + " does not fit a BER-OID tag of four bytes");
        }
        int groups = 1;
        while (groups < 4 && (tag >>> (7 * groups)) != 0) groups++;
        for (int g = groups - 1; g >= 0; g--) {
            int by = (int) ((tag >>> (7 * g)) & 0x7f);
            out.write(g > 0 ? by | 0x80 : by);
        }
    }

    private void writeLength(ByteArrayOutputStream out, long len) {
        int n = pack.tlvLengthSize;
        if (n > 0) {
            if (len >= (1L << (8 * n))) {
                throw new GtException(GtException.Code.TRANSFORM_ENCODE, pack.format, null, "length " + len + " does not fit length " + n);
            }
            byte[] b = TlvTransform.bigEndian(len, n);
            out.write(b, 0, n);
            return;
        }
        if (len < 0x80) {
            out.write((int) len);
            return;
        }
        int k = 1;
        while (k < 8 && (len >>> (8 * k)) != 0) k++;
        out.write(0x80 + k);
        byte[] b = TlvTransform.bigEndian(len, k);
        out.write(b, 0, k);
    }
}
