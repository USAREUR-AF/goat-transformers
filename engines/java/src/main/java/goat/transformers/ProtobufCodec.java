package goat.transformers;

import java.io.ByteArrayOutputStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/**
 * The {@code protobuf} wire: a protobuf message carried in and out as hex text. A field locator is a dot-path of
 * field numbers ({@code 2} is field 2 of the top message, {@code 4.1} is field 1 of the submessage in field 4).
 * When a field number repeats on the wire the last occurrence wins. Decode parses the tag/length framing itself;
 * encode writes the canonical form: mapped fields only, each submessage likewise, in ascending field-number order.
 */
final class ProtobufCodec extends Codec<Map<Integer, ProtobufCodec.Val>> {

    ProtobufCodec(Pack pack) {
        super(pack);
        for (Pack.Kind k : pack.kinds) prepare(k.scope);
    }

    private static final int[] ITSELF = new int[0];

    /** The highest protobuf field number, 2^29-1. */
    private static final long MAX_FIELD = 536870911L;

    /** What a group body needs of each occurrence: a scalar ({@code .} fields only) or a submessage. */
    private static final class Body {
        /** True when the body has a line that addresses into the occurrence, so it must be a submessage. */
        boolean submessage;
        /** The first {@code .} field, or null. */
        Pack.Field itself;
    }

    private static void prepare(Pack.Scope scope) {
        for (Pack.Line l : scope.lines) {
            if (l.loc != null) continue;                 // a common line, already done for another kind
            l.loc = l.locator.equals(".") ? ITSELF : parsePath(l.locator);
            if (l instanceof Pack.Group) {
                Pack.Scope body = ((Pack.Group) l).body;
                prepare(body);
                Body b = new Body();
                for (Pack.Line bl : body.lines) {
                    if (((int[]) bl.loc).length > 0) b.submessage = true;
                    else if (b.itself == null) b.itself = (Pack.Field) bl;
                }
                body.info = b;
            }
        }
    }

    /** {@code 4.1} to {@code int[]{4, 1}}. Assumes {@link #checkFieldLocator} has passed. */
    static int[] parsePath(String locator) {
        String[] p = locator.split("\\.", -1);
        int[] out = new int[p.length];
        for (int i = 0; i < p.length; i++) out[i] = Integer.parseInt(p[i]);
        return out;
    }

    /** Null when {@code locator} is a valid protobuf dot-path of field numbers, else the reason. */
    static String checkFieldLocator(String locator) {
        String[] p = locator.split("\\.", -1);
        for (String seg : p) {
            if (seg.isEmpty()) return "protobuf path has an empty field number: " + locator;
            if (!Transform.UNSIGNED.matcher(seg).matches()) return "protobuf path must be dot-separated field numbers: " + locator;
            long n;
            try {
                n = Long.parseLong(seg);
            } catch (NumberFormatException ex) {
                return "protobuf path must be dot-separated field numbers: " + locator;
            }
            if (n < 1 || n > 536870911) return "protobuf field number must be 1..536870911: " + locator;
        }
        return null;
    }

    // ---- decode ----

    /** One parsed field occurrence. */
    static final class Val {
        final int wt;
        final long num;     // wt 0 varint value; wt 1 fixed64 bits; wt 5 fixed32 bits (low 32)
        final byte[] bytes; // wt 2 length-delimited payload
        Map<Integer, Val> sub;  // wt 2: the payload parsed as a submessage, once asked for
        Val prev;           // the occurrence of the same field number before this one, or null
        Val(int wt, long num, byte[] bytes) { this.wt = wt; this.num = num; this.bytes = bytes; }
    }

    @Override
    Map<Integer, Val> parse(String text) {
        byte[] msg = fromHex(text);
        return parseMessage(msg, 0, msg.length);
    }

    /** Thrown inside {@link #find} when a non-final path element is not a submessage. */
    private static final class NotSubmessage extends RuntimeException {
        private static final long serialVersionUID = 1L;
        NotSubmessage(String why) { super(why, null, false, false); }
    }

    /** The value at {@code path}, or null when it does not occur on the wire. */
    private Val find(Map<Integer, Val> top, int[] path) {
        Map<Integer, Val> cur = top;
        for (int s = 0; s < path.length; s++) {
            Val v = cur.get(path[s]);
            if (v == null) return null;
            if (s == path.length - 1) return v;
            if (v.wt != 2) throw new NotSubmessage("path element " + path[s] + " is wire type " + v.wt + ", not a submessage");
            if (v.sub == null) v.sub = parseMessage(v.bytes, 0, v.bytes.length);
            cur = v.sub;
        }
        return null;
    }

    @Override
    boolean holds(Map<Integer, Val> top, Pack.When when) {
        Val v;
        try {
            v = find(top, (int[]) when.loc);
        } catch (NotSubmessage ex) {
            return false;   // a when path whose prefix is not a submessage does not hold (ruling 31 of 0.8)
        } catch (GtException ex) {
            // a prefix whose bytes do not parse as a message: a when path never fails a decode (ruling 9b of 0.11)
            if (ex.code() == GtException.Code.MALFORMED_WIRE) return false;
            throw ex;
        }
        if (v == null) return false;
        if (when.present) return true;
        return v.wt == 0 && when.matches(v.num);
    }

    @Override
    Entity decodeKind(Map<Integer, Val> top, Pack.Kind kind) {
        Entity e = new Entity();
        Failures fails = new Failures();
        decodeScope(top, kind.scope, e, fails);
        finishDecode(e, fails);
        return e;
    }

    /** Decode the lines of one scope from a parsed message: the top message, or one item's submessage. */
    private void decodeScope(Map<Integer, Val> top, Pack.Scope scope, Entity e, Failures fails) {
        for (Pack.Line l : scope.lines) {
            int[] path = (int[]) l.loc;
            if (path.length == 0) continue;                         // `.`: read by decodeItems
            if (l instanceof Pack.Group) {
                Pack.Group g = (Pack.Group) l;
                Val last;
                try {
                    last = find(top, path);
                } catch (NotSubmessage ex) {
                    throw malformed("group " + g.list + " at " + g.locator + ": " + ex.getMessage());
                }
                if (last == null) continue;                         // no item occurs: the list is absent
                List<Entity> items = decodeItems(g, last, fails);
                if (!items.isEmpty()) e.putList(g.list, items);     // a packed occurrence with no values: absent
                continue;
            }
            if (!(l instanceof Pack.Field)) continue;
            Pack.Field f = (Pack.Field) l;
            // Every path is walked, also that of a line whose key already has its value: the submessages on the way
            // are checked whatever the lines before it gave (ruling 38 of 0.8).
            Val val;
            try {
                val = find(top, path);
            } catch (NotSubmessage ex) {
                // a path prefix that is not a submessage (ruling 13 of 0.7)
                throw malformed(f.key + " at " + f.locator + ": " + ex.getMessage());
            }
            if (e.get(f.key) != null) continue;                     // an earlier line already gave the key its value
            if (val == null) continue;                              // a field absent from the wire is not an error
            decodeValue(f, val.wt, val.num, val.bytes, e, fails);
        }
    }

    private void decodeValue(Pack.Field f, int wt, long num, byte[] bytes, Entity e, Failures fails) {
        if (wt != f.pb.wireType()) {
            fails.add(f, "wire type " + wt + " on the wire, transform " + f.pb.wireName()
                    + " expects wire type " + f.pb.wireType(), e);
            return;
        }
        // after the wire type check (ruling 15 of 0.9), before zig-zag and the transform: a sentinel yields no value
        if (f.absent != null && (wt == 2 ? f.absent.matches(new String(bytes, java.nio.charset.StandardCharsets.UTF_8))
                                         : f.absent.matches(num))) {
            return;
        }
        Object v;
        try {
            v = f.pb.decode(num, bytes);
        } catch (IllegalArgumentException ex) {
            fails.add(f, ex.getMessage(), e);
            return;
        }
        putDecoded(f, v, e, fails);
    }

    /**
     * The items of a group: one per occurrence of its field number, in wire order ({@code last} is the last one).
     * A {@code .} field with a numeric transform also reads the packed form, one item per value.
     */
    private List<Entity> decodeItems(Pack.Group g, Val last, Failures fails) {
        int n = 0;
        for (Val v = last; v != null; v = v.prev) n++;
        Val[] occ = new Val[n];
        for (Val v = last; v != null; v = v.prev) occ[--n] = v;
        Body body = (Body) g.body.info;
        List<Entity> items = new ArrayList<>(occ.length);
        for (Val v : occ) {
            if (body.submessage) {
                if (v.wt != 2) {
                    throw malformed("an item of " + g.list + " at " + g.locator + " is wire type " + v.wt + ", not a submessage");
                }
                takeItems(1);
                if (v.sub == null) v.sub = parseMessage(v.bytes, 0, v.bytes.length);
                Entity item = new Entity();
                decodeScope(v.sub, g.body, item, fails);
                items.add(item);
                continue;
            }
            int wt = body.itself == null ? -1 : body.itself.pb.wireType();
            if (v.wt == 2 && wt != 2 && wt >= 0) {
                // packed: the values back to back
                byte[] b = v.bytes;
                int[] pos = { 0 };
                if (wt != 0 && b.length % (wt == 1 ? 8 : 4) != 0) {
                    throw malformed("packed " + g.list + " at " + g.locator + ": " + b.length
                            + " bytes do not hold whole values of " + (wt == 1 ? 8 : 4) + " bytes");
                }
                while (pos[0] < b.length) {
                    long num = wt == 0 ? readVarint(b, pos, b.length) : readFixed(b, pos, b.length, wt == 1 ? 8 : 4);
                    takeItems(1);
                    items.add(scalarItem(g, wt, num, null, fails));
                }
                continue;
            }
            takeItems(1);
            items.add(scalarItem(g, v.wt, v.num, v.bytes, fails));
        }
        return items;
    }

    /** One item of scalar occurrences: every {@code .} field of the body reads the value. */
    private Entity scalarItem(Pack.Group g, int wt, long num, byte[] bytes, Failures fails) {
        Entity item = new Entity();
        for (Pack.Line l : g.body.lines) {
            Pack.Field f = (Pack.Field) l;
            if (item.get(f.key) != null) continue;
            decodeValue(f, wt, num, bytes, item, fails);
        }
        return item;
    }

    /** Parse a (sub)message into field-number to its last occurrence (repeated numbers: last wins). */
    private Map<Integer, Val> parseMessage(byte[] b, int start, int end) {
        LinkedHashMap<Integer, Val> out = new LinkedHashMap<>();
        int[] pos = { start };
        while (pos[0] < end) {
            long tag = readVarint(b, pos, end);
            long number = tag >>> 3;
            int wt = (int) (tag & 7);
            if (number == 0) throw malformed("protobuf field number 0 is invalid");
            if (number > MAX_FIELD) throw malformed("protobuf field number " + Long.toUnsignedString(number) + " is above " + MAX_FIELD);
            int field = (int) number;
            Val v;
            switch (wt) {
                case 0:
                    v = new Val(0, readVarint(b, pos, end), null);
                    break;
                case 1:
                    v = new Val(1, readFixed(b, pos, end, 8), null);
                    break;
                case 2: {
                    long len = readVarint(b, pos, end);
                    if (len < 0 || len > end - pos[0]) {      // unsigned: a length of 2^63 or more reads negative
                        throw malformed("protobuf length-delimited field runs past the message");
                    }
                    int from = pos[0];
                    pos[0] += (int) len;
                    v = new Val(2, 0, Arrays.copyOfRange(b, from, pos[0]));
                    break;
                }
                case 5:
                    v = new Val(5, readFixed(b, pos, end, 4), null);
                    break;
                case 3:
                case 4:
                    throw malformed("protobuf wire type " + wt + " (deprecated group) is not supported");
                default:
                    throw malformed("protobuf wire type " + wt + " is invalid");
            }
            v.prev = out.put(field, v);
        }
        return out;
    }

    private long readVarint(byte[] b, int[] pos, int end) {
        long v = 0;
        int shift = 0;
        while (true) {
            if (pos[0] >= end) throw malformed("protobuf varint runs past the message");
            if (shift >= 64) throw malformed("protobuf varint is longer than ten bytes");
            int by = b[pos[0]++] & 0xff;
            // the tenth byte holds bit 63 alone: more is a value beyond 64 bits (ruling 40 of 0.8)
            if (shift == 63 && by > 1) throw malformed("protobuf varint is longer than ten bytes or holds more than 64 bits");
            v |= (long) (by & 0x7f) << shift;
            if ((by & 0x80) == 0) break;
            shift += 7;
        }
        return v;
    }

    private long readFixed(byte[] b, int[] pos, int end, int n) {
        if (n > end - pos[0]) throw malformed("protobuf fixed" + (n * 8) + " runs past the message");
        long v = 0;
        for (int i = 0; i < n; i++) v |= (long) (b[pos[0]++] & 0xff) << (8 * i);
        return v;
    }

    // ---- encode ----

    /** A node in the canonical tree: a leaf (wire type + payload) or a submessage. */
    private static final class Node {
        Integer wt;                   // leaf only
        byte[] payload;               // leaf only
        TreeMap<Integer, Node> sub;   // submessage only
        List<Node> items;             // a group: one occurrence per node, in order
    }

    /** The submessage that holds the last element of {@code path}, creating the submessages on the way. */
    private TreeMap<Integer, Node> parent(TreeMap<Integer, Node> root, int[] path, Pack.Line l) {
        TreeMap<Integer, Node> cur = root;
        for (int s = 0; s < path.length - 1; s++) {
            Node n = cur.get(path[s]);
            if (n == null) {
                n = new Node();
                n.sub = new TreeMap<>();
                cur.put(path[s], n);
            } else if (n.sub == null) {
                throw new GtException(GtException.Code.TRANSFORM_ENCODE, pack.format, l.locator,
                        "field number " + path[s] + " is used both as a value and as a submessage");
            }
            cur = n.sub;
        }
        return cur;
    }

    @Override
    String encodeKind(Entity e, Pack.Kind kind) {
        TreeMap<Integer, Node> root = new TreeMap<>();
        encodeScope(root, kind.scope, e);
        return toHex(serialize(root));
    }

    private byte[] encodeValue(Pack.Field f, Object v) {
        try {
            return f.pb.encode(v);
        } catch (IllegalArgumentException ex) {
            throw encodeFailure(f, ex);
        }
    }

    /** The payload of a field's first sentinel: the integer as a varint (no zig-zag) or fixed bytes, or the text. */
    static byte[] sentinelPayload(Pack.Field f) {
        switch (f.pb.wireType()) {
            case 2: return f.absent.firstText().getBytes(java.nio.charset.StandardCharsets.UTF_8);
            case 1: return PbTransform.fixed64(f.absent.firstNum());
            case 5: return PbTransform.fixed32((int) f.absent.firstNum());
            default: return PbTransform.varint(f.absent.firstNum());
        }
    }

    /** Write the lines of one scope into a message: the top message, or one item's submessage. */
    private void encodeScope(TreeMap<Integer, Node> root, Pack.Scope scope, Entity e) {
        // Values first, then the sentinels of absent keys where no value was written (ruling 16 of 0.9).
        List<Pack.Field> sentinels = new ArrayList<>();
        for (Pack.Line l : scope.lines) {
            if (!(l instanceof Pack.Field)) continue;
            Pack.Field f = (Pack.Field) l;
            if (((int[]) f.loc).length == 0) continue;            // `.`: written by encodeItems
            Object v = valueToEncode(f, e, scope);
            if (v != null) writeField(root, f, encodeValue(f, v));
            else if (f.absent != null && !f.suppressed(e)) sentinels.add(f);          // absent key and no default: protobuf omits it
        }
        for (Pack.Field f : sentinels) writeField(root, f, sentinelPayload(f));
        encodeRest(root, scope, e);
    }

    /** Write one field's payload at its locator, unless an earlier write holds the place. */
    private void writeField(TreeMap<Integer, Node> root, Pack.Field f, byte[] payload) {
        {
            int[] path = (int[]) f.loc;
            TreeMap<Integer, Node> cur = parent(root, path, f);
            int last = path[path.length - 1];
            Node have = cur.get(last);
            if (have != null) {
                if (have.sub != null) {
                    throw new GtException(GtException.Code.TRANSFORM_ENCODE, pack.format, f.locator,
                            "field number " + last + " is used both as a value and as a submessage");
                }
                return;                                            // an earlier line on this locator already wrote it
            }
            Node leaf = new Node();
            leaf.wt = f.pb.wireType();
            leaf.payload = payload;
            cur.put(last, leaf);
        }
    }

    /**
     * Ruling 3 of 0.20: a field line on the {@code when}'s path whose key the entity holds (a default does not
     * count) wrote a varint that matches the {@code when}'s list or ranges: that value stays.
     */
    private static boolean keptByField(Pack.Scope scope, Pack.When w, Node have, Entity e) {
        if (have == null || have.sub != null || have.wt == null || have.wt != 0) return false;
        boolean held = false;
        for (Pack.Line l : scope.lines) {
            if (!(l instanceof Pack.Field) || !l.locator.equals(w.locator)) continue;
            Pack.Field f = (Pack.Field) l;
            if (e.get(f.key) != null && !f.suppressed(e)) { held = true; break; }
        }
        if (!held) return false;
        long v = 0;
        byte[] p = have.payload;
        for (int i = 0; i < p.length && i < 10; i++) v |= (long) (p[i] & 0x7f) << (7 * i);
        return w.matches(v);
    }

    /** The groups, then the when and const values, of one scope. */
    private void encodeRest(TreeMap<Integer, Node> root, Pack.Scope scope, Entity e) {
        // groups: one occurrence per item; an absent or empty list writes nothing.
        for (Pack.Group g : scope.groups) {
            List<Entity> items = e.list(g.list);
            if (items == null || items.isEmpty()) continue;
            Node n = encodeItems(g, items);
            if (n == null) continue;                               // a packed list whose items all lack the value
            int[] path = (int[]) g.loc;
            TreeMap<Integer, Node> cur = parent(root, path, g);
            cur.putIfAbsent(path[path.length - 1], n);
        }
        // when and const values: an integer is written as a varint over any field; `present` writes an empty
        // length-delimited field when nothing under its path was written.
        for (Pack.Line l : scope.lines) {
            if (!(l instanceof Pack.When)) continue;
            Pack.When w = (Pack.When) l;
            int[] path = (int[]) w.loc;
            TreeMap<Integer, Node> cur = parent(root, path, w);
            int last = path[path.length - 1];
            if (w.present) {
                if (!cur.containsKey(last)) {
                    Node empty = new Node();
                    empty.sub = new TreeMap<>();
                    cur.put(last, empty);
                }
            } else {
                if (w.isList() && keptByField(scope, w, cur.get(last), e)) continue;
                Node leaf = new Node();
                leaf.wt = 0;
                leaf.payload = PbTransform.varint(w.number);
                cur.put(last, leaf);
            }
        }
    }

    /**
     * The node a group writes. Submessage items: one occurrence each (an item with nothing written is an empty
     * length-delimited occurrence). A {@code .} field with a numeric transform: the packed form. A {@code .}
     * {@code pstring}: one occurrence per item.
     */
    private Node encodeItems(Pack.Group g, List<Entity> items) {
        Body body = (Body) g.body.info;
        Node out = new Node();
        if (!body.submessage && body.itself != null && body.itself.pb.wireType() != 2) {
            ByteArrayOutputStream packed = new ByteArrayOutputStream();
            for (Entity item : items) {
                Object v = valueToEncode(body.itself, item, g.body);
                if (v != null) writeBytes(packed, encodeValue(body.itself, v));
                else if (body.itself.absent != null) writeBytes(packed, sentinelPayload(body.itself));   // ruling 5 of 0.9
            }
            if (packed.size() == 0) return null;
            out.wt = 2;
            out.payload = packed.toByteArray();
            return out;
        }
        out.items = new ArrayList<>(items.size());
        for (Entity item : items) {
            Node n = new Node();
            if (body.submessage) {
                n.sub = new TreeMap<>();
                encodeScope(n.sub, g.body, item);
            } else {
                Object v = body.itself == null ? null : valueToEncode(body.itself, item, g.body);
                n.wt = 2;
                n.payload = v != null ? encodeValue(body.itself, v)
                        : body.itself != null && body.itself.absent != null && !body.itself.suppressed(item) ? sentinelPayload(body.itself) : new byte[0];
            }
            out.items.add(n);
        }
        return out;
    }

    private byte[] serialize(TreeMap<Integer, Node> msg) {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        for (Map.Entry<Integer, Node> en : msg.entrySet()) {
            Node n = en.getValue();
            if (n.items != null) {
                for (Node item : n.items) serialize(out, en.getKey(), item);
            } else {
                serialize(out, en.getKey(), n);
            }
        }
        return out.toByteArray();
    }

    private void serialize(ByteArrayOutputStream out, int field, Node n) {
        if (n.sub != null) {
            byte[] body = serialize(n.sub);
            writeBytes(out, PbTransform.varint(((long) field << 3) | 2));
            writeBytes(out, PbTransform.varint(body.length));
            writeBytes(out, body);
        } else {
            int wt = n.wt;
            writeBytes(out, PbTransform.varint(((long) field << 3) | wt));
            if (wt == 2) writeBytes(out, PbTransform.varint(n.payload.length));
            writeBytes(out, n.payload);
        }
    }

    private static void writeBytes(ByteArrayOutputStream out, byte[] b) { out.write(b, 0, b.length); }

}
