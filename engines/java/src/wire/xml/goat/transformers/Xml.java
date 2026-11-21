package goat.transformers;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;

/** Minimal XML reader (elements, attributes, text, entities, CDATA; skips prolog, PIs, comments; refuses DOCTYPE) and canonical writer. */
public final class Xml {
    private Xml() {}

    public static final class Element {
        public final String name;
        public final LinkedHashMap<String, String> attrs = new LinkedHashMap<>();
        public final List<Element> children = new ArrayList<>();
        public final StringBuilder text = new StringBuilder();

        public Element(String name) { this.name = name; }

        public Element child(String n) {
            for (Element c : children) if (c.name.equals(n)) return c;
            return null;
        }

        public Element ensureChild(String n) {
            Element c = child(n);
            if (c == null) {
                c = new Element(n);
                children.add(c);
            }
            return c;
        }
    }

    public static final class ParseException extends RuntimeException {
        private static final long serialVersionUID = 1L;
        ParseException(String msg, int pos) { super(msg + " at offset " + pos); }
    }

    public static Element parse(String s) {
        P p = new P(s);
        p.misc();
        if (p.pos >= p.s.length() || p.s.charAt(p.pos) != '<') throw new ParseException("no root element", p.pos);
        Element root = p.element();
        p.misc();
        if (p.pos != p.s.length()) throw new ParseException("content after root element", p.pos);
        return root;
    }

    private static final class P {
        final String s;
        int pos;
        int depth;

        P(String s) {
            // One byte order mark at the very start is skipped (ruling 1g of 0.11); then, before anything else is
            // read, each CR LF and each CR alone is one LF (ruling 1h; XML 1.0, section 2.11).
            String t = (s.length() > 0 && s.charAt(0) == '\ufeff') ? s.substring(1) : s;
            if (t.indexOf('\r') >= 0) t = t.replace("\r\n", "\n").replace('\r', '\n');
            this.s = t;
            this.pos = 0;
        }

        boolean at(String t) { return s.startsWith(t, pos); }

        void ws() {
            while (pos < s.length() && isWs(s.charAt(pos))) pos++;
        }

        void skipPast(String end, String what) {
            int i = s.indexOf(end, pos);
            if (i < 0) throw new ParseException("unterminated " + what, pos);
            pos = i + end.length();
        }

        /** Whitespace, prolog / processing instructions, comments and DOCTYPE outside the root. */
        void misc() {
            while (true) {
                ws();
                if (at("<?")) skipPast("?>", "processing instruction");
                else if (at("<!--")) skipPast("-->", "comment");
                else if (at("<!")) throw new ParseException("a document type declaration or other markup declaration", pos);
                else return;
            }
        }

        String name() {
            int start = pos;
            while (pos < s.length()) {
                char c = s.charAt(pos);
                if (isWs(c) || c == '/' || c == '>' || c == '=' || c == '<' || c == '"' || c == '\'') break;
                pos++;
            }
            if (pos == start) throw new ParseException("expected a name", pos);
            return s.substring(start, pos);
        }

        /** One element: the root is level 1 and an element beyond the limit is malformed. */
        Element element() {
            if (++depth > MAX_DEPTH) throw new ParseException("elements nested deeper than " + MAX_DEPTH + " levels", pos);
            try {
                return content();
            } finally {
                depth--;
            }
        }

        Element content() {
            pos++; // '<'
            // comments, CDATA and processing instructions were taken before: this is a declaration, never an element
            if (pos < s.length() && (s.charAt(pos) == '!' || s.charAt(pos) == '?')) {
                throw new ParseException("a document type declaration or other markup declaration", pos - 1);
            }
            Element e = new Element(name());
            while (true) {
                ws();
                if (pos >= s.length()) throw new ParseException("unterminated start tag <" + e.name, pos);
                if (at("/>")) { pos += 2; return e; }
                if (s.charAt(pos) == '>') { pos++; break; }
                int at = pos;
                String an = name();
                ws();
                if (pos >= s.length() || s.charAt(pos) != '=') throw new ParseException("expected '=' after attribute " + an, pos);
                pos++;
                ws();
                if (pos >= s.length()) throw new ParseException("expected attribute value", pos);
                char q = s.charAt(pos);
                if (q != '"' && q != '\'') throw new ParseException("attribute value must be quoted", pos);
                pos++;
                int end = s.indexOf(q, pos);
                if (end < 0) throw new ParseException("unterminated attribute value", pos);
                String raw = s.substring(pos, end);
                if (raw.indexOf('<') >= 0) throw new ParseException("'<' in attribute value", pos);
                pos = end + 1;
                // XML attribute-value normalisation: a literal tab or line feed is a space (ruling 1i of 0.11).
                String norm = raw.replace('\n', ' ').replace('\t', ' ');
                if (e.attrs.containsKey(an)) throw new ParseException("duplicate attribute " + an, at);
                e.attrs.put(an, decodeEntities(norm, at));
            }
            // content
            while (true) {
                if (pos >= s.length()) throw new ParseException("unterminated element <" + e.name + ">", pos);
                if (at("</")) {
                    pos += 2;
                    String n = name();
                    if (!n.equals(e.name)) throw new ParseException("end tag </" + n + "> does not match <" + e.name + ">", pos);
                    ws();
                    if (pos >= s.length() || s.charAt(pos) != '>') throw new ParseException("expected '>'", pos);
                    pos++;
                    return e;
                } else if (at("<!--")) {
                    skipPast("-->", "comment");
                } else if (at("<![CDATA[")) {
                    int start = pos + 9;
                    skipPast("]]>", "CDATA section");
                    e.text.append(s, start, pos - 3);
                } else if (at("<?")) {
                    skipPast("?>", "processing instruction");
                } else if (s.charAt(pos) == '<') {
                    e.children.add(element());
                } else {
                    int start = pos;
                    int end = s.indexOf('<', pos);
                    if (end < 0) end = s.length();
                    pos = end;
                    e.text.append(decodeEntities(s.substring(start, end), start));
                }
            }
        }

        String decodeEntities(String t, int at) {
            if (t.indexOf('&') < 0) return t;
            StringBuilder b = new StringBuilder();
            int i = 0;
            while (i < t.length()) {
                char c = t.charAt(i);
                if (c != '&') { b.append(c); i++; continue; }
                int semi = t.indexOf(';', i);
                if (semi < 0) throw new ParseException("unterminated entity", at + i);
                String ent = t.substring(i + 1, semi);
                switch (ent) {
                    case "amp": b.append('&'); break;
                    case "lt": b.append('<'); break;
                    case "gt": b.append('>'); break;
                    case "quot": b.append('"'); break;
                    case "apos": b.append('\''); break;
                    default:
                        if (!ent.startsWith("#")) throw new ParseException("unknown entity &" + ent + ";", at + i);
                        int cp = charRef(ent);
                        if (cp < 0) throw new ParseException("bad character reference &" + ent + ";", at + i);
                        b.appendCodePoint(cp);
                }
                i = semi + 1;
            }
            return b.toString();
        }
    }

    /** The nesting limit of a document (engine-spec 0.8, ruling 35): elements, the root is level 1. */
    static final int MAX_DEPTH = 64;

    /**
     * The code point of a character reference {@code #<digits>} or {@code #x<hex digits>}, or -1 when it is not one:
     * no digits, a sign, a digit of another script, or a number that is not a character XML 1.0 allows.
     */
    static int charRef(String ent) {
        boolean hex = ent.startsWith("#x");
        int from = hex ? 2 : 1;
        if (ent.length() == from) return -1;
        int cp = 0;
        for (int i = from; i < ent.length(); i++) {
            int d = Json.hexDigit(ent.charAt(i));
            if (d < 0 || (!hex && d > 9)) return -1;
            cp = cp * (hex ? 16 : 10) + d;
            if (cp > Character.MAX_CODE_POINT) return -1;
        }
        // the Char production of XML 1.0
        boolean allowed = cp == 0x9 || cp == 0xA || cp == 0xD || (cp >= 0x20 && cp <= 0xD7FF)
                || (cp >= 0xE000 && cp <= 0xFFFD) || cp >= 0x10000;
        return allowed ? cp : -1;
    }

    static boolean isWs(char c) { return c == ' ' || c == '\t' || c == '\n' || c == '\r'; }

    static boolean isBlank(CharSequence t) {
        for (int i = 0; i < t.length(); i++) if (!isWs(t.charAt(i))) return false;
        return true;
    }

    /** Canonical form: attributes in insertion order, one space apart, self-closing when empty, no prolog. */
    public static String write(Element e) {
        StringBuilder b = new StringBuilder();
        write(b, e);
        return b.toString();
    }

    static void write(StringBuilder b, Element e) {
        b.append('<').append(e.name);
        for (var a : e.attrs.entrySet()) {
            b.append(' ').append(a.getKey()).append("=\"");
            escape(b, a.getValue(), true);
            b.append('"');
        }
        if (e.children.isEmpty() && e.text.length() == 0) {
            b.append("/>");
            return;
        }
        b.append('>');
        escape(b, e.text, false);
        for (Element c : e.children) write(b, c);
        b.append("</").append(e.name).append('>');
    }

    /** A character XML 1.0 cannot hold in a string to be written (ruling 1d of 0.11). */
    public static final class Unwritable extends RuntimeException {
        private static final long serialVersionUID = 1L;
        Unwritable(String msg) { super(msg); }
    }

    static void escape(StringBuilder b, CharSequence t, boolean attr) {
        for (int i = 0; i < t.length(); i++) {
            char c = t.charAt(i);
            if ((c < 0x20 && c != '\t' && c != '\n' && c != '\r') || c == '\ufffe' || c == '\uffff') {
                throw new Unwritable(String.format("the character U+%04X cannot be written in XML 1.0", (int) c));
            }
            switch (c) {
                case '&': b.append("&amp;"); break;
                case '<': b.append("&lt;"); break;
                case '>': b.append("&gt;"); break;
                case '"': if (attr) b.append("&quot;"); else b.append(c); break;
                case '\t': if (attr) b.append("&#9;"); else b.append(c); break;
                case '\n': if (attr) b.append("&#10;"); else b.append(c); break;
                case '\r': b.append("&#13;"); break;
                default: b.append(c);
            }
        }
    }
}
