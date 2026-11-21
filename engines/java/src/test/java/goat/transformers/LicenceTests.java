package goat.transformers;

import static goat.transformers.TestRunner.check;
import static goat.transformers.TestRunner.eq;
import static goat.transformers.TestRunner.throwsCode;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** The loaders under a licence profile (spec Version 0.29), on the fixtures of the tool vectors and on files of their own. */
final class LicenceTests {
    private LicenceTests() {}

    static void run(Path packsDir) {
        Path fixtures = packsDir.resolve("conformance").resolve("tool-fixtures");
        Path a = fixtures.resolve("licences-a");
        if (!Files.isDirectory(a)) {
            check("licences: fixtures", false, "no directory " + a);
            return;
        }
        Path aPacks = a.resolve("packs"), aModels = a.resolve("model");

        Engine none = Engine.load(aPacks, aModels, Distribution.CONTROLLED, null);
        eq("licences: no profile loads every pack", 11, none.packs().size());
        eq("licences: no profile reads no licence", 0, none.licences().size());

        Engine open = Engine.load(aPacks, aModels, Distribution.CONTROLLED, "open");
        eq("licences: open loads the open packs", "[lic-aa, lic-plain]", formats(open).toString());
        eq("licences: open loads the open modules", "[core]", modules(open).toString());
        eq("licences: open records the licences", "[plain lic-plain Apache-2.0 open, zz-first-by-format lic-aa Apache-2.0 open]",
                rows(open).toString());

        Engine copyleft = Engine.load(aPacks, aModels, Distribution.CONTROLLED, "open+copyleft");
        eq("licences: open+copyleft", "[lic-aa, lic-copyleft, lic-plain, lic-uses-sa]", formats(copyleft).toString());
        eq("licences: open+copyleft modules", "[core, sa]", modules(copyleft).toString());

        Engine every = Engine.load(aPacks, aModels, Distribution.CONTROLLED, "everything");
        eq("licences: everything leaves out the controlled licence", 10, every.packs().size());
        eq("licences: everything modules", "[book, core, derived, sa]", modules(every).toString());

        throwsCode("licences: a profile name not one of the three", GtException.Code.BAD_LICENCE,
                () -> Engine.load(aPacks, aModels, Distribution.CONTROLLED, "Open"));
        throwsCode("licences: an unknown profile, before anything is read", GtException.Code.BAD_LICENCE,
                () -> Engine.load(Path.of("/nonexistent-goat-packs"), Path.of("/nonexistent-goat-model"), Distribution.CONTROLLED, "commercial"));

        Engine only = Engine.loadOnly(aPacks, aModels, Distribution.CONTROLLED, List.of("nc", "plain"), "open");
        eq("licences: loadOnly skips a pack outside the profile", "[lic-plain]", formats(only).toString());
        Engine derived = Engine.loadOnly(aPacks, aModels, Distribution.CONTROLLED, List.of("uses-derived"), "everything");
        eq("licences: loadOnly loads the modules used, through others", "[book, core, derived]", modules(derived).toString());
        eq("licences: loadOnly records the pack's profile", "[uses-derived lic-uses-derived Apache-2.0 everything]", rows(derived).toString());
        throwsCode("licences: loadOnly checks the name first", GtException.Code.UNKNOWN_FORMAT,
                () -> Engine.loadOnly(aPacks, aModels, Distribution.CONTROLLED, List.of("no-such-pack"), "open"));

        Path badTable = fixtures.resolve("licences-bad-table");
        throwsCode("licences: a bad table with a profile", GtException.Code.BAD_LICENCE,
                () -> Engine.load(badTable.resolve("packs"), badTable.resolve("model"), Distribution.CONTROLLED, "everything"));
        eq("licences: a bad table without a profile is not read", 1,
                Engine.load(badTable.resolve("packs"), badTable.resolve("model"), Distribution.CONTROLLED, null).packs().size());
        Path core = fixtures.resolve("licences-core-copyleft");
        eq("licences: a copyleft core holds no pack in open", 0,
                Engine.load(core.resolve("packs"), core.resolve("model"), Distribution.CONTROLLED, "open").packs().size());
        eq("licences: a broken pack outside the profile is skipped unread", "[lic-plain]",
                formats(Engine.load(core.resolve("packs"), core.resolve("model"), Distribution.CONTROLLED, "open+copyleft")).toString());

        lineForms();
    }

    /** The line forms of ruling 1, on files written to a temporary directory. */
    private static void lineForms() {
        Path dir = null;
        try {
            dir = Files.createTempDirectory("goat-licences");
            Path pack = Files.createDirectory(dir.resolve("p"));
            Path reuse = pack.resolve("REUSE.toml");
            // REUSE-IgnoreStart: the quoted licence lines below are data
            write(reuse, "SPDX-License-Identifier: CC0-1.0\r\n  SPDX-License-Identifier =\t\"MIT\"  \r\n");
            eq("licences 1a: a colon line is passed over", "MIT", Licences.packLicence(pack));
            write(reuse, "SPDX-License-Identifier = \"MIT\"\nSPDX-License-Identifier = \"MIT\"\n");
            throwsCode("licences 1a: two licence lines", GtException.Code.BAD_LICENCE, () -> Licences.packLicence(pack));
            write(reuse, "SPDX-License-Identifier = MIT\n");
            throwsCode("licences 1a: an unquoted id", GtException.Code.BAD_LICENCE, () -> Licences.packLicence(pack));
            write(reuse, "﻿SPDX-License-Identifier = \"MIT\"\n");
            throwsCode("licences 1a: a byte-order mark is not removed", GtException.Code.BAD_LICENCE, () -> Licences.packLicence(pack));
            Files.write(reuse, new byte[]{'S', (byte) 0xff, '\n'});
            throwsCode("licences 1a: not UTF-8", GtException.Code.BAD_LICENCE, () -> Licences.packLicence(pack));
            Files.delete(reuse);
            eq("licences 1a: no REUSE.toml is Apache-2.0", "Apache-2.0", Licences.packLicence(pack));
            Files.createDirectory(reuse);
            throwsCode("licences 1a: a directory is bad-licence", GtException.Code.BAD_LICENCE, () -> Licences.packLicence(pack));
            Files.delete(reuse);

            Path def = dir.resolve("m.def");
            Path lic = dir.resolve("m.def.license");
            write(lic, "SPDX-License-Identifier = \"MIT\"\nSPDX-License-Identifier:\t\tCC-BY-SA-4.0\r");
            eq("licences 1b: an = line is passed over, a carriage return at the end removed", "CC-BY-SA-4.0", Licences.moduleLicence(def));
            write(lic, "SPDX-License-Identifier:CC0-1.0\n");
            // REUSE-IgnoreEnd
            throwsCode("licences 1b: no space after the colon", GtException.Code.BAD_LICENCE, () -> Licences.moduleLicence(def));

            Path toml = dir.resolve("licences.toml");
            String row = "[licences.\"X\"]\ncommercial = \"yes\"\nshare_alike\t=\ttrue\nfield_of_use = []\ndistribution = \"public\"\n";
            write(toml, "# t\n\n" + row + "name = \"x\"\nurl=\"u\"\n");
            eq("licences 1c: a share-alike row", Map.of("X", Licences.OPEN_COPYLEFT), Licences.table(toml));
            write(toml, row.replace("[]", "[\"\"]"));
            eq("licences 1c: [\"\"] is a field of use", Map.of("X", Licences.EVERYTHING), Licences.table(toml));
            write(toml, row.replace("public", "controlled"));
            eq("licences 2a: controlled is in no profile", Map.of("X", Licences.NONE), Licences.table(toml));
            for (String[] b : new String[][]{
                    {"a second row", row + row},
                    {"a missing line", row.replace("distribution = \"public\"\n", "")},
                    {"a line twice", row + "commercial = \"yes\"\n"},
                    {"a comment after a value", row.replace("true", "true # x")},
                    {"a line before the first row", "x = 1\n" + row},
                    {"another key", row + "other = 1\n"},
                    {"name twice", row + "name = \"a\"\nname = \"b\"\n"},
                    {"a header with a space", row.replace("[licences.\"X\"]", "[licences. \"X\"]")}}) {
                write(toml, b[1]);
                throwsCode("licences 1c: " + b[0], GtException.Code.BAD_LICENCE, () -> Licences.table(toml));
            }
            eq("licences 1c: no table is Apache-2.0 alone", Map.of("Apache-2.0", Licences.OPEN),
                    Licences.table(dir.resolve("no-such-file")));
            eq("licences: a path through a file is a file that does not exist", Map.of("Apache-2.0", Licences.OPEN),
                    Licences.table(toml.resolve("licences.toml")));
            eq("licences 2b: module and uses lines", List.of("a", "b"),
                    nonNull(Licences.heads("  module a\r\nmodule z\nuses \"q\"\nuses b # c\nuses\tb\n")));
        } catch (IOException ex) {
            check("licences: line forms", false, ex.toString());
        } finally {
            if (dir != null) deleteTree(dir);
        }
    }

    private static List<String> nonNull(List<String> l) {
        List<String> out = new ArrayList<>();
        for (String s : l) if (s != null) out.add(s);
        return out;
    }

    private static void write(Path f, String text) throws IOException {
        Files.write(f, text.getBytes(StandardCharsets.UTF_8));
    }

    private static void deleteTree(Path dir) {
        try (java.util.stream.Stream<Path> s = Files.walk(dir)) {
            List<Path> all = new ArrayList<>();
            s.forEach(all::add);
            java.util.Collections.reverse(all);
            for (Path p : all) Files.deleteIfExists(p);
        } catch (IOException ex) {
            check("licences: temporary directory removed", false, ex.toString());
        }
    }

    private static List<String> formats(Engine e) {
        List<String> out = new ArrayList<>();
        for (Pack p : e.packs()) out.add(p.format);
        return out;
    }

    private static List<String> modules(Engine e) {
        List<String> out = new ArrayList<>();
        for (ModelModule m : e.modules()) out.add(m.name);
        return out;
    }

    private static List<String> rows(Engine e) {
        List<String> out = new ArrayList<>();
        for (Engine.PackLicence r : e.licences()) out.add(r.dir + " " + r.format + " " + r.licence + " " + r.profile);
        return out;
    }
}
