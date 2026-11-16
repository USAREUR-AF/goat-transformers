package goat.transformers;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;

/** Minimal XML reader (elements, attributes, text, entities, CDATA; skips prolog, PIs, comments, DOCTYPE) and canonical writer. */
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
        if (p.pos >= s.length() || s.charAt(p.pos) != '<') throw new ParseException("no root element", p.pos);
        Element root = p.element();
        p.misc();
        if (p.pos != s.length()) throw new ParseException("content after root element", p.pos);
        return root;
    }

    private static final class P {
        final String s;
        int pos;

        P(String s) {
            this.s = s;
            this.pos = (s.length() > 0 && s.charAt(0) == '﻿') ? 1 : 0;
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
                else if (at("<!DOCTYPE")) doctype();
                else return;
            }
        }

        void doctype() {
            int depth = 0;
            while (pos < s.length()) {
                char c = s.charAt(pos++);
                if (c == '[') depth++;
                else if (c == ']') depth--;
                else if (c == '>' && depth <= 0) return;
            }
            throw new ParseException("unterminated DOCTYPE", pos);
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

        Element element() {
            pos++; // '<'
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
                // XML attribute-value normalisation: literal tab / newline / CR become a space.
                String norm = raw.replace("\r\n", " ").replace('\r', ' ').replace('\n', ' ').replace('\t', ' ');
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
                    e.text.append(decodeEntities(s.substring(start, end).replace("\r\n", "\n").replace('\r', '\n'), start));
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
                        try {
                            int cp;
                            if (ent.startsWith("#x")) cp = Integer.parseInt(ent.substring(2), 16);
                            else if (ent.startsWith("#")) cp = Integer.parseInt(ent.substring(1));
                            else throw new ParseException("unknown entity &" + ent + ";", at + i);
                            b.appendCodePoint(cp);
                        } catch (IllegalArgumentException ex) {
                            throw new ParseException("bad character reference &" + ent + ";", at + i);
                        }
                }
                i = semi + 1;
            }
            return b.toString();
        }
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

    static void escape(StringBuilder b, CharSequence t, boolean attr) {
        for (int i = 0; i < t.length(); i++) {
            char c = t.charAt(i);
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
