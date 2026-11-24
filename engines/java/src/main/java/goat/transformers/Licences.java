package goat.transformers;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Licence profiles of spec Version 0.29: the files of ruling 1 ({@code licences.toml}, a pack's
 * {@code REUSE.toml}, a module's {@code .def.license}), read by their exact line forms, and the profile of a
 * licence, a module and a pack (ruling 2). A profile is held as a rank: 0 {@code open}, 1 {@code open+copyleft},
 * 2 {@code everything}, 3 none; a profile holds every rank up to its own.
 */
final class Licences {
    private Licences() {}

    static final int OPEN = 0, OPEN_COPYLEFT = 1, EVERYTHING = 2, NONE = 3;
    private static final String[] NAMES = {"open", "open+copyleft", "everything", "none"};

    /** The rank of a profile name of ruling 3a, or -1 when it is not one of the three. */
    static int rankOf(String profile) {
        if (profile == null) return -1;
        for (int i = 0; i < EVERYTHING + 1; i++) if (NAMES[i].equals(profile)) return i;
        return -1;
    }

    /** The name of a rank: {@code open}, {@code open+copyleft}, {@code everything} or {@code none}. */
    static String name(int rank) { return NAMES[rank]; }

    private static final String ID = "[A-Za-z0-9.+-]+";
    private static final String WS = "[ \\t]*";
    // REUSE-IgnoreStart: the quoted licence lines below are data
    private static final Pattern PACK_LINE = Pattern.compile("SPDX-License-Identifier" + WS + "=" + WS + "\"(" + ID + ")\"");
    private static final Pattern MODULE_LINE = Pattern.compile("SPDX-License-Identifier:[ \\t]+(" + ID + ")");
    private static final Pattern ROW = Pattern.compile("\\[licences\\.\"(" + ID + ")\"\\]");
    private static final Pattern COMMERCIAL = Pattern.compile("commercial" + WS + "=" + WS + "\"(yes|no|unknown)\"");
    private static final Pattern SHARE_ALIKE = Pattern.compile("share_alike" + WS + "=" + WS + "(true|false)");
    private static final Pattern FIELD_OF_USE = Pattern.compile("field_of_use" + WS + "=" + WS + "(\\[\\]|\\[\".*\"\\])");
    private static final Pattern DISTRIBUTION = Pattern.compile("distribution" + WS + "=" + WS + "\"(public|controlled)\"");
    private static final Pattern MODULE = Pattern.compile("module[ \\t]+([A-Za-z0-9_-]+)");
    private static final Pattern USES = Pattern.compile("uses[ \\t]+([A-Za-z0-9_-]+)");
    private static final String[] SKIPPED = {"name", "url", "attribution"};

    private static GtException bad(Path file, String why) {
        return new GtException(GtException.Code.BAD_LICENCE, null, null, file + ": " + why);
    }

    /**
     * The bytes of {@code file}, or null when it does not exist (no entry of that name, or a part of the path before
     * the last is not a directory or does not exist). Any other failure to read it is {@code bad-licence}.
     */
    static byte[] readIfExists(Path file) {
        if (file == null) return null;   // a path the operating system cannot name: no entry has that name
        try {
            return Files.readAllBytes(file);
        } catch (NoSuchFileException ex) {
            return null;
        } catch (IOException | SecurityException ex) {
            Path parent = file.getParent();
            if (parent != null && !Files.isDirectory(parent)) return null;   // ENOTDIR on a part before the last
            throw bad(file, "cannot be read (" + ex + ")");
        }
    }

    /** UTF-8 text, or null when the bytes are not UTF-8. */
    static String utf8(byte[] bytes) {
        try {
            return StandardCharsets.UTF_8.newDecoder()
                    .onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT)
                    .decode(ByteBuffer.wrap(bytes)).toString();
        } catch (CharacterCodingException ex) {
            return null;
        }
    }

    /** The lines of ruling 1: cut at each line feed, one carriage return before it or at the end removed, trimmed of spaces and tabs. */
    static List<String> lines(String text) {
        List<String> out = new ArrayList<>();
        int start = 0;
        while (true) {
            int nl = text.indexOf('\n', start);
            String line = nl < 0 ? text.substring(start) : text.substring(start, nl);
            if (line.endsWith("\r")) line = line.substring(0, line.length() - 1);
            out.add(trim(line));
            if (nl < 0) break;
            start = nl + 1;
        }
        return out;
    }

    private static String trim(String s) {
        int a = 0, b = s.length();
        while (a < b && (s.charAt(a) == ' ' || s.charAt(a) == '\t')) a++;
        while (b > a && (s.charAt(b - 1) == ' ' || s.charAt(b - 1) == '\t')) b--;
        return s.substring(a, b);
    }

    private static List<String> licenceFileLines(Path file, byte[] bytes) {
        String text = utf8(bytes);
        if (text == null) throw bad(file, "is not UTF-8");
        return lines(text);
    }

    /** 1a: the licence of the pack in {@code packDir}; {@code Apache-2.0} when it has no {@code REUSE.toml}. */
    static String packLicence(Path packDir) {
        Path file = packDir.resolve("REUSE.toml");
        byte[] bytes = readIfExists(file);
        if (bytes == null) return "Apache-2.0";
        String found = null;
        for (String line : licenceFileLines(file, bytes)) {
            Matcher m = PACK_LINE.matcher(line);
            if (m.matches()) {
                if (found != null) throw bad(file, "holds more than one licence line");
                found = m.group(1);
            } else if (line.startsWith("SPDX-License-Identifier")) {
                String rest = line.substring("SPDX-License-Identifier".length());
                if (rest.startsWith(" ") || rest.startsWith("\t") || rest.startsWith("=")) {
                    throw bad(file, "a SPDX-License-Identifier line is not a licence line: " + line);
                }
            }
        }
        if (found == null) throw bad(file, "holds no licence line");
        return found;
    }

    /** 1b: the licence of the module file {@code defFile}, from {@code <defFile>.license}; {@code Apache-2.0} when there is none. */
    static String moduleLicence(Path defFile) {
        Path file = defFile.resolveSibling(defFile.getFileName().toString() + ".license");
        byte[] bytes = readIfExists(file);
        if (bytes == null) return "Apache-2.0";
        String found = null;
        for (String line : licenceFileLines(file, bytes)) {
            Matcher m = MODULE_LINE.matcher(line);
            if (m.matches()) {
                if (found != null) throw bad(file, "holds more than one licence line");
                found = m.group(1);
            } else if (line.startsWith("SPDX-License-Identifier:")) {
                throw bad(file, "a SPDX-License-Identifier: line is not a licence line: " + line);
                // REUSE-IgnoreEnd
            }
        }
        if (found == null) throw bad(file, "holds no licence line");
        return found;
    }

    /** 1c and 2a: the profile rank of every licence of {@code licences.toml}; when the file does not exist, Apache-2.0 alone, {@code open}. */
    static Map<String, Integer> table(Path file) {
        Map<String, Integer> out = new HashMap<>();
        byte[] bytes = readIfExists(file);
        if (bytes == null) {
            out.put("Apache-2.0", OPEN);
            return out;
        }
        String id = null;
        String[] values = null;   // commercial, share_alike, field_of_use, distribution
        Set<String> skipped = new HashSet<>();
        for (String line : licenceFileLines(file, bytes)) {
            if (line.isEmpty() || line.startsWith("#")) continue;
            Matcher row = ROW.matcher(line);
            if (row.matches()) {
                if (id != null) out.put(id, rowRank(file, id, values));
                id = row.group(1);
                if (out.containsKey(id)) throw bad(file, "a second row of " + id);
                values = new String[4];
                skipped.clear();
                continue;
            }
            if (id == null) throw bad(file, "a line before the first row: " + line);
            Pattern[] keys = {COMMERCIAL, SHARE_ALIKE, FIELD_OF_USE, DISTRIBUTION};
            boolean done = false;
            for (int k = 0; k < keys.length && !done; k++) {
                Matcher m = keys[k].matcher(line);
                if (m.matches()) {
                    if (values[k] != null) throw bad(file, "row " + id + " gives a line twice: " + line);
                    values[k] = m.group(1);
                    done = true;
                }
            }
            for (int k = 0; k < SKIPPED.length && !done; k++) {
                String s = SKIPPED[k];
                if (line.startsWith(s) && line.length() > s.length()) {
                    char c = line.charAt(s.length());
                    if (c == ' ' || c == '\t' || c == '=') {
                        if (!skipped.add(s)) throw bad(file, "row " + id + " gives " + s + " twice");
                        done = true;
                    }
                }
            }
            if (!done) throw bad(file, "row " + id + ": a line that is not one of the row: " + line);
        }
        if (id != null) out.put(id, rowRank(file, id, values));
        return out;
    }

    private static int rowRank(Path file, String id, String[] v) {
        String[] names = {"commercial", "share_alike", "field_of_use", "distribution"};
        for (int k = 0; k < 4; k++) if (v[k] == null) throw bad(file, "row " + id + " has no " + names[k] + " line");
        if (v[3].equals("controlled")) return NONE;
        if (v[0].equals("yes") && v[2].equals("[]")) return v[1].equals("true") ? OPEN_COPYLEFT : OPEN;
        return EVERYTHING;
    }

    /** 2a: the rank of a licence; one not in the table is {@code everything}. */
    static int rankOfLicence(Map<String, Integer> table, String licence) {
        Integer r = table.get(licence);
        return r == null ? EVERYTHING : r;
    }

    /**
     * 2b: the name (element 0, null when none) and the {@code uses} names of a module file or {@code pack.def}, read
     * by the two line forms of ruling 2b. Null text (not readable, not UTF-8) adds no line.
     */
    static List<String> heads(String text) {
        List<String> out = new ArrayList<>();
        out.add(null);
        if (text == null) return out;
        for (String line : lines(text)) {
            Matcher m = MODULE.matcher(line);
            if (m.matches()) {
                if (out.get(0) == null) out.set(0, m.group(1));
                continue;
            }
            Matcher u = USES.matcher(line);
            if (u.matches()) out.add(u.group(1));
        }
        return out;
    }

    private static final Pattern SHOWN_PUBLIC = Pattern.compile("distribution[ \\t]+public");

    /**
     * Ruling 1 of 0.93: true when the text of a module file or {@code pack.def} is <b>shown public</b>. It holds no
     * U+0000, no U+FEFF and no carriage return that is not directly before a line feed or at the end; at least one
     * of its lines (cut and trimmed as ruling 1 of 0.29) is exactly {@code distribution}, spaces or tabs, and
     * {@code public}; and no line is doubtful: with every double quote removed, then spaces, tabs and carriage
     * returns removed at its ends, it begins with {@code distribution}, and it is not that exact line. Null text (a
     * file that cannot be read or is not UTF-8) is not shown public.
     */
    static boolean shownPublic(String text) {
        if (text == null) return false;
        int n = text.length();
        for (int i = 0; i < n; i++) {
            char c = text.charAt(i);
            if (c == '\0' || c == '\uFEFF') return false;
            if (c == '\r' && i + 1 < n && text.charAt(i + 1) != '\n') return false;
        }
        boolean found = false;
        for (String line : lines(text)) {
            if (SHOWN_PUBLIC.matcher(line).matches()) {
                found = true;
                continue;
            }
            String bare = line.replace("\"", "");
            int a = 0, b = bare.length();
            while (a < b && " \t\r".indexOf(bare.charAt(a)) >= 0) a++;
            while (b > a && " \t\r".indexOf(bare.charAt(b - 1)) >= 0) b--;
            if (bare.startsWith("distribution", a) && b - a >= "distribution".length()) return false;
        }
        return found;
    }

    /** Ruling 2 of 0.93: the rank of a file from its licence's rank; none when the file is not shown public. */
    static int fileRank(int licenceRank, String text) { return shownPublic(text) ? licenceRank : NONE; }

    /** UTF-8 text of a file, or null when it cannot be read or is not UTF-8 (ruling 2b: no line, never bad-licence). */
    static String textOrNull(byte[] bytes) { return bytes == null ? null : utf8(bytes); }

    /**
     * What 3b reads before any module is loaded: the table, and for each module file in load-listing order its
     * licence and its {@code module} and {@code uses} lines; then every module's profile (2b).
     */
    static final class Profiles {
        final Map<String, Integer> table;
        /** The module files in the order of 0.23 Loading 1, with the rank of each file. */
        final List<Path> files = new ArrayList<>();
        final Map<Path, Integer> fileRank = new HashMap<>();
        /** The text of each module file read (null when it could not be read), so no file is read twice. */
        final Map<String, String> texts = new HashMap<>();
        /** The widest rank of the module files of each name. */
        final Map<String, Integer> nameRank = new HashMap<>();

        /** {@code table} is the table already read (1c); {@code moduleFiles} are read in the order given. */
        Profiles(Map<String, Integer> table, List<Path> moduleFiles) {
            this.table = table;
            List<List<String>> heads = new ArrayList<>();
            List<Integer> ranks = new ArrayList<>();
            for (Path f : moduleFiles) {
                int lic = rankOfLicence(table, moduleLicence(f));
                byte[] bytes;
                try {
                    bytes = Files.readAllBytes(f);
                } catch (IOException | SecurityException ex) {
                    bytes = null;
                }
                String text = textOrNull(bytes);
                if (text != null) texts.put(f.toString(), text);
                files.add(f);
                List<String> head = heads(text);
                heads.add(head);
                // 0.93, ruling 2: a file not shown public is in no profile; with a profile, a module file that 2b gives
                // no name is not loaded, shown public or not (what uses it then finds no module: unknown-module)
                ranks.add(head.get(0) == null ? NONE : fileRank(lic, text));
            }
            // The widest of a module's own licence and the modules it uses, through others: a fixed point.
            boolean changed = true;
            while (changed) {
                changed = false;
                nameRank.clear();
                for (int i = 0; i < files.size(); i++) {
                    String n = heads.get(i).get(0);
                    if (n != null) nameRank.merge(n, ranks.get(i), Math::max);
                }
                for (int i = 0; i < files.size(); i++) {
                    int r = ranks.get(i);
                    for (String u : heads.get(i).subList(1, heads.get(i).size())) {
                        Integer ur = nameRank.get(u);
                        if (ur != null && ur > r) r = ur;
                    }
                    if (r != ranks.get(i)) {
                        ranks.set(i, r);
                        changed = true;
                    }
                }
            }
            for (int i = 0; i < files.size(); i++) fileRank.put(files.get(i), ranks.get(i));
        }

        /**
         * 2c: the rank of a pack from its licence and the {@code uses} lines of its {@code pack.def} text (null: none);
         * none when the text is not shown public (0.93, ruling 2).
         */
        int packRank(String licence, String packText) {
            int r = fileRank(rankOfLicence(table, licence), packText);   // 0.93, ruling 2
            Integer core = nameRank.get(ModelModule.CORE);
            if (core != null && core > r) r = core;
            List<String> h = heads(packText);
            for (String u : h.subList(1, h.size())) {
                Integer ur = nameRank.get(u);
                if (ur != null && ur > r) r = ur;
            }
            return r;
        }
    }
}
