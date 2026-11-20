package goat.transformers;

import java.io.ByteArrayOutputStream;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * The pack language of the {@code cbor} wire (engine-spec 0.28): its transform table, its paths, the checks of a
 * pack's lines and the CBOR item of a {@code when} or {@code const} value. They belong to the pack reader, not to the
 * codec: every build has them, so a pack is read the same way whatever wires the build has (ruling 1b of 0.24). The
 * codec, {@link CborCodec}, is in src/wire/cbor and is compiled only into a build with the cbor wire.
 */
final class CborLayout {
    private CborLayout() {}

    // ---- transforms ----

    /** The transforms of the {@code cbor} table. */
    enum CT {
        UINT("uint", "int"), INT("int", "int"), FLOAT("float", "float"), TEXT("text", "string"),
        BYTES("bytes", "string"), BOOL("bool", "int"), EPOCH_S("epoch_s", "int");

        final String wireName;
        final String yields;

        CT(String wireName, String yields) {
            this.wireName = wireName;
            this.yields = yields;
        }

        /** The transform of this name, or null when the name is not in the table (parameters included). */
        static CT byName(String name) {
            for (CT t : values()) if (t.wireName.equals(name)) return t;
            return null;
        }
    }

    // ---- paths ----

    static final int KEY_INT = 1, KEY_TEXT = 2, POS = 3;
    /** How a scope's lines use an item: as a map or as an array; 0 when no line walks into it. */
    static final int MAP = 1, ARRAY = 2;

    /** One step of a path. */
    static final class Step {
        final int kind;
        /** An integer key: its major type (0 or 1) and argument, as the key's head holds them. */
        final int mt;
        final long arg;
        /** A text key's UTF-8 bytes. */
        final byte[] text;
        /** A position. */
        final int pos;
        /** The step as a path writes it: the tree key and the residue key's step. */
        final String repr;
        /** The key's core deterministic encoding as lowercase hex (a key step only). */
        final String keyHex;

        Step(int kind, int mt, long arg, byte[] text, int pos, String repr) {
            this.kind = kind;
            this.mt = mt;
            this.arg = arg;
            this.text = text;
            this.pos = pos;
            this.repr = repr;
            if (kind == KEY_INT) {
                ByteArrayOutputStream o = new ByteArrayOutputStream();
                head(o, mt, arg);
                keyHex = Codec.toHex(o.toByteArray());
            } else if (kind == KEY_TEXT) {
                ByteArrayOutputStream o = new ByteArrayOutputStream();
                head(o, 3, text.length);
                o.write(text, 0, text.length);
                keyHex = Codec.toHex(o.toByteArray());
            } else {
                keyHex = null;
            }
        }

        int needs() { return kind == POS ? ARRAY : MAP; }
    }

    static final BigInteger MIN_KEY = BigInteger.valueOf(Long.MIN_VALUE);
    static final BigInteger MAX_KEY = BigInteger.ONE.shiftLeft(64).subtract(BigInteger.ONE);

    /** A text key step: ASCII letters, digits, {@code _} and {@code -}, not beginning with a digit or {@code -}. */
    static boolean isTextKey(String s) {
        if (s.isEmpty()) return false;
        char c0 = s.charAt(0);
        if (!((c0 >= 'A' && c0 <= 'Z') || (c0 >= 'a' && c0 <= 'z') || c0 == '_')) return false;
        for (int i = 1; i < s.length(); i++) {
            char c = s.charAt(i);
            if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_' || c == '-')) return false;
        }
        return true;
    }

    private static boolean noLeadingZeroDigits(String d) {
        if (d.isEmpty()) return false;
        for (int i = 0; i < d.length(); i++) if (d.charAt(i) < '0' || d.charAt(i) > '9') return false;
        return d.length() == 1 || d.charAt(0) != '0';
    }

    /** One step, or null when the text is not a step of the grammar. */
    static Step parseStep(String s) {
        if (s.startsWith("[")) {
            if (!s.endsWith("]") || s.length() < 3) return null;
            String d = s.substring(1, s.length() - 1);
            if (!noLeadingZeroDigits(d) || d.length() > 5) return null;
            int p = Integer.parseInt(d);
            if (p > 65535) return null;
            return new Step(POS, 0, 0, null, p, "[" + p + "]");
        }
        if (isTextKey(s)) return new Step(KEY_TEXT, 3, 0, s.getBytes(StandardCharsets.US_ASCII), 0, s);
        boolean neg = s.startsWith("-");
        String d = neg ? s.substring(1) : s;
        if (!noLeadingZeroDigits(d) || d.length() > 20) return null;
        if (neg && d.equals("0")) return null;
        BigInteger v = new BigInteger(s);
        if (v.compareTo(MIN_KEY) < 0 || v.compareTo(MAX_KEY) > 0) return null;
        if (neg) return new Step(KEY_INT, 1, v.negate().subtract(BigInteger.ONE).longValue(), null, 0, s);
        return new Step(KEY_INT, 0, v.longValue(), null, 0, s);
    }

    /** The steps of a path ({@code .} is the empty path), or null when the text is not a path. */
    static Step[] parsePath(String loc) {
        if (loc.equals(".")) return new Step[0];
        String[] parts = loc.split("\\.", -1);
        Step[] out = new Step[parts.length];
        for (int i = 0; i < parts.length; i++) {
            out[i] = parseStep(parts[i]);
            if (out[i] == null) return null;
        }
        return out;
    }

    /**
     * Null when {@code loc} is a path of this wire, else the reason (step 8 of 5b of 0.11). {@code dot}: the line
     * may name {@code .} (a field in a group body, a group outside one; ruling 22 of 0.28).
     */
    static String checkPath(String loc, boolean dot) {
        if (loc.equals(".")) return dot ? null : "the path . names the item itself, only on a field in a group body or a group outside one";
        return parsePath(loc) == null ? "not a cbor path of integer keys, text keys and positions [i]: \"" + loc + "\"" : null;
    }

    static String pathText(Step[] p) {
        StringBuilder b = new StringBuilder();
        for (int i = 0; i < p.length; i++) {
            if (i > 0) b.append('.');
            b.append(p[i].repr);
        }
        return b.toString();
    }

    // ---- the lines of a scope as a tree ----

    /** One place the lines of a scope name: the steps under it, how they use it, whether a line maps it. */
    static final class PNode {
        final Map<String, PNode> kids = new LinkedHashMap<>();
        /** MAP or ARRAY: how the lines' next steps use the item here; 0 when no line walks into it. */
        int as;
        /** A line passes through this place (walks into the item). */
        boolean walked;
        /** A field, a when with a value, a const or a group ends here: the item is mapped, never residue. */
        boolean mapped;
        /** A group's own path. */
        boolean group;
    }

    /** The tree of one scope's lines; a step used as a map and as an array is {@code bad-directive}. */
    static PNode tree(List<Pack.Line> lines, String format, String source) {
        PNode root = new PNode();
        for (Pack.Line l : lines) {
            Step[] p = (Step[]) l.loc;
            PNode n = root;
            for (int i = 0; i < p.length; i++) {
                int as = p[i].needs();
                if (n.as != 0 && n.as != as) throw conflict(l, format, source);
                n.as = as;
                n.walked = true;
                n = n.kids.computeIfAbsent(p[i].repr, k -> new PNode());
            }
            if (l instanceof Pack.Group) {
                // the item at a group's path is an array, and the group line maps it (ruling 24)
                if (n.as == MAP) throw conflict(l, format, source);
                n.as = ARRAY;
                n.group = true;
                n.mapped = true;
            } else if (l instanceof Pack.Field || !((Pack.When) l).present) {
                n.mapped = true;
            }
        }
        return root;
    }

    private static GtException conflict(Pack.Line l, String format, String source) {
        return new GtException(GtException.Code.BAD_DIRECTIVE, format, l.locator, source + ":" + l.line + ": path "
                + l.locator + " uses an item both as a map and as an array in one scope");
    }

    /**
     * The checks of "Types" and of rulings 13 and 22 of 0.28, after the file is read: within one scope a line whose
     * path is a proper prefix of another's (a {@code when … present} exempt when it is the shorter), a line at or
     * under a group's path, a step used as a map and as an array; across the pack, top-level paths that decide the
     * top item differently. Every failure is {@code bad-directive}. Stores each scope's tree in {@code scope.info}.
     */
    static void checkPack(List<Pack.Kind> kinds, String format, String source) {
        int top = 0;
        Pack.Line topLine = null;
        for (Pack.Kind k : kinds) {
            PNode root = checkScope(k.scope, format, source);
            for (Pack.Line l : k.scope.lines) {
                Step[] p = (Step[]) l.loc;
                int decides = p.length > 0 ? p[0].needs() : l instanceof Pack.Group ? ARRAY : 0;
                if (decides == 0) continue;
                if (top != 0 && top != decides) {
                    Pack.Line later = topLine.line > l.line ? topLine : l;
                    throw new GtException(GtException.Code.BAD_DIRECTIVE, format, later.locator, source + ":" + later.line
                            + ": the paths of the pack decide the top item both as a map and as an array (lines "
                            + topLine.line + " and " + l.line + ")");
                }
                top = decides;
                topLine = l;
            }
            k.scope.info = root;
        }
    }

    private static PNode checkScope(Pack.Scope scope, String format, String source) {
        PNode root = tree(scope.lines, format, source);
        Map<String, Pack.Line> nonExempt = new java.util.HashMap<>(), groups = new java.util.HashMap<>();
        for (Pack.Line l : scope.lines) {
            String p = pathText((Step[]) l.loc);
            if (!(l instanceof Pack.When && ((Pack.When) l).present)) nonExempt.putIfAbsent(p, l);
            if (l instanceof Pack.Group) {
                Pack.Line had = groups.putIfAbsent(p, l);
                if (had != null) throw prefix(had, l, format, source, "two groups at one path");
            }
        }
        for (Pack.Line l : scope.lines) {
            Step[] p = (Step[]) l.loc;
            Pack.Line g = groups.get(pathText(p));
            if (g != null && g != l) throw prefix(g, l, format, source, "a line at a group's path");
            StringBuilder b = new StringBuilder();
            for (int i = 0; i < p.length; i++) {
                // every proper prefix of the path, the empty path (`.`) included
                Pack.Line at = nonExempt.get(b.toString());
                if (at != null) {
                    throw prefix(at, l, format, source, "path " + (b.length() == 0 ? "." : b.toString())
                            + " is a value or a group and a container of another line in one scope");
                }
                if (i > 0) b.append('.');
                b.append(p[i].repr);
            }
        }
        for (Pack.Line l : scope.lines) {
            if (l instanceof Pack.Group) {
                Pack.Scope body = ((Pack.Group) l).body;
                body.info = checkScope(body, format, source);
            }
        }
        return root;
    }

    private static GtException prefix(Pack.Line a, Pack.Line b, String format, String source, String why) {
        Pack.Line later = a.line > b.line ? a : b;
        return new GtException(GtException.Code.BAD_DIRECTIVE, format, later.locator, source + ":" + later.line + ": "
                + why + " (lines " + Math.min(a.line, b.line) + " and " + Math.max(a.line, b.line) + ")");
    }

    /**
     * A {@code when} or {@code const} value as its CBOR item, core deterministic: an integer when 2a of 0.11 reads
     * it (sign and leading zeros allowed) within -2^63 to 2^64-1, a bool for {@code true} and {@code false}, any other
     * value a text string with one leading {@code =} stripped (rulings 8 and 19 of 0.28).
     */
    static byte[] whenValue(String v) {
        ByteArrayOutputStream o = new ByteArrayOutputStream();
        if (Transform.INT_TEXT.matcher(v).matches()) {
            BigInteger n = new BigInteger(v);
            if (n.compareTo(MIN_KEY) >= 0 && n.compareTo(MAX_KEY) <= 0) {
                if (n.signum() >= 0) head(o, 0, n.longValue());
                else head(o, 1, n.negate().subtract(BigInteger.ONE).longValue());
                return o.toByteArray();
            }
        }
        if (v.equals("true")) return new byte[]{(byte) 0xf5};
        if (v.equals("false")) return new byte[]{(byte) 0xf4};
        byte[] t = (v.startsWith("=") ? v.substring(1) : v).getBytes(StandardCharsets.UTF_8);
        head(o, 3, t.length);
        o.write(t, 0, t.length);
        return o.toByteArray();
    }

    /** A head in its shortest form. */
    static void head(ByteArrayOutputStream o, int mt, long arg) {
        int m = mt << 5;
        if (Long.compareUnsigned(arg, 24) < 0) {
            o.write(m | (int) arg);
        } else if (Long.compareUnsigned(arg, 0xffL) <= 0) {
            o.write(m | 24);
            o.write((int) arg);
        } else if (Long.compareUnsigned(arg, 0xffffL) <= 0) {
            o.write(m | 25);
            for (int s = 8; s >= 0; s -= 8) o.write((int) (arg >>> s) & 0xff);
        } else if (Long.compareUnsigned(arg, 0xffffffffL) <= 0) {
            o.write(m | 26);
            for (int s = 24; s >= 0; s -= 8) o.write((int) (arg >>> s) & 0xff);
        } else {
            o.write(m | 27);
            for (int s = 56; s >= 0; s -= 8) o.write((int) (arg >>> s) & 0xff);
        }
    }
}
