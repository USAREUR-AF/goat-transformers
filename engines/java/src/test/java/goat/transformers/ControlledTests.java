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
import java.util.TreeMap;

/**
 * Spec Version 0.93 (a controlled pack is in no licence profile) in the library: the shown-public test of ruling 1,
 * the limit a profile sets (rulings 5 and 6, each sentence), and a controlled inner pack (Version 0.34) under every
 * profile. Every tree is written to a temporary directory.
 */
final class ControlledTests {
    private ControlledTests() {}

    private static final List<String> PROFILES = Engine.PROFILES;
    private static final String SRC = "source \"goat-transformers spec/engine-spec.md, Version 0.93 (test fixture)\"\n";
    private static final String CORE = "module core\nversion 0.93.0\ndistribution public\n" + SRC + "key lat float - \"k\"\n";
    private static final String T = "module t\nversion 0.93.0\ndistribution public\n" + SRC
            + "key w int - \"k\"\nkey x int - \"k\"\nkey y int - \"k\"\n";
    private static final String CTL = "module ctl\nversion 0.93.0\ndistribution controlled\n" + SRC + "key q int - \"k\"\n";
    private static final String OUTER = "format t-outer\nversion 0.93.0\ndistribution public\n" + SRC
            + "uses t\nwire bits\nlayout sequential\nbit_order msb\nfield t.w 8 uint\ninner t-inner\n";
    /** (a) an inner pack that is not shown public. */
    private static final String INNER_CONTROLLED = "format t-inner\nversion 0.93.0\ndistribution controlled\n" + SRC
            + "uses t\nwire bits\nword_bytes 1\nbit_order lsb\nfield t.x 0:0:8 uint\n";
    /** (b) an inner pack shown public that uses a module that is not. */
    private static final String INNER_USES_CTL = "format t-inner\nversion 0.93.0\ndistribution public\n" + SRC
            + "uses t\nuses ctl\nwire bits\nword_bytes 1\nbit_order lsb\nfield t.x 0:0:8 uint\nfield ctl.q 0:8:8 uint\n";
    private static final String PUB = "format t-pub\nversion 0.93.0\ndistribution public\n" + SRC + "wire json\nfield lat pos.lat float\n";
    private static final String PUB_NC = "format t-pub-nc\nversion 0.93.0\ndistribution public\n" + SRC + "wire json\nfield lat pos.lat float\n";
    private static final String CTL_PACK = "format t-ctl\nversion 0.93.0\ndistribution controlled\n" + SRC + "wire json\nfield lat pos.lat float\n";
    // REUSE-IgnoreStart: the quoted licence lines below are data
    private static final String NC_REUSE = "version = 1\n[[annotations]]\npath = \"**\"\nSPDX-License-Identifier = \"CC-BY-NC-4.0\"\n";
    // REUSE-IgnoreEnd
    private static final String TABLE = "[licences.\"Apache-2.0\"]\ncommercial = \"yes\"\nshare_alike = false\nfield_of_use = []\n"
            + "distribution = \"public\"\n\n[licences.\"CC-BY-NC-4.0\"]\ncommercial = \"no\"\nshare_alike = false\n"
            + "field_of_use = []\ndistribution = \"public\"\n";

    static void run() {
        shownPublic();
        Path dir = null;
        try {
            dir = Files.createTempDirectory("goat-controlled");
            limitTests(dir.resolve("limit"));
            innerTests(dir.resolve("inner"));
        } catch (IOException ex) {
            check("0.93: temporary trees", false, ex.toString());
        } finally {
            if (dir != null) deleteTree(dir);
        }
    }

    /** Ruling 1: each form of a file that is or is not shown public. */
    private static void shownPublic() {
        String head = "format f\nversion 1.0.0\n";
        String[][] yes = {
                {"the exact line", head + "distribution public\n"},
                {"tabs and spaces between and around", head + " \tdistribution \t public\t \n"},
                {"a carriage return before a line feed", head + "distribution public\r\nwire json\r\n"},
                {"a carriage return at the end", head + "distribution public\r"},
                {"two exact lines", head + "distribution public\ndistribution\tpublic\n"},
                {"a quote elsewhere", head + "source \"distribution controlled\"\ndistribution public\n"},
        };
        for (String[] c : yes) eq("0.93 ruling 1 shown public: " + c[0], true, Licences.shownPublic(c[1]));
        String[][] no = {
                {"controlled", head + "distribution controlled\n"},
                {"no line", head + "wire json\n"},
                {"an empty file", ""},
                {"public beside a doubtful line", head + "distribution public\ndistribution controlled\n"},
                {"\"distribution\" controlled beside public", head + "distribution public\n\"distribution\" controlled\n"},
                {"distri\"bution\" x beside public", head + "distribution public\ndistri\"bution\" x\n"},
                {"distribution\"controlled\" beside public", head + "distribution public\ndistribution\"controlled\"\n"},
                {"distribution # x beside public", head + "distribution public\ndistribution # x\n"},
                {"a comment after public", head + "distribution public # x\n"},
                {"the quoted word", head + "distribution \"public\"\n"},
                {"a carriage return between the words", head + "distribution\rpublic\n"},
                {"a carriage return before the words", head + "\rdistribution public\n"},
                {"two carriage returns before a line feed", head + "distribution public\r\r\n"},
                {"a carriage return inside another line", head + "distribution public\nwire\rjson\n"},
                {"a byte-order mark first", "﻿" + head + "distribution public\n"},
                {"a byte-order mark anywhere", head + "distribution public\nsource \"﻿\"\n"},
                {"a NUL byte", head + "distribution public\n\u0000\n"},
                {"distributions public", head + "distribution public\ndistributions public\n"},
                {"upper case", head + "Distribution public\n"},
                {"not UTF-8 or not readable", null},
        };
        for (String[] c : no) eq("0.93 ruling 1 not shown public: " + c[0], false, Licences.shownPublic(c[1]));
    }

    /** Rulings 5 and 6, sentence by sentence. */
    private static void limitTests(Path root) throws IOException {
        Map<String, String> files = new TreeMap<>();
        files.put("licences.toml", TABLE);
        files.put("model/core.def", CORE);
        files.put("packs/pub/pack.def", PUB);
        files.put("packs/pub-nc/pack.def", PUB_NC);
        files.put("packs/pub-nc/REUSE.toml", NC_REUSE);
        Path packs = tree(root.resolve("t"), files).resolve("packs"), models = packs.resolve("../model");
        Map<String, String> withCtl = new TreeMap<>(files);
        withCtl.put("packs/ctl/pack.def", CTL_PACK);
        Path ctlPacks = tree(root.resolve("c"), withCtl).resolve("packs");

        // Ruling 5: with a profile the limit is public, without a message also when the caller asked for controlled.
        Engine asked = Engine.load(packs, models, Distribution.CONTROLLED, "open");
        eq("0.93 ruling 5: a profile sets the limit public, controlled asked", Distribution.PUBLIC, asked.maxDistribution());
        eq("0.93 ruling 5: the load under that limit", "[t-pub]", formats(asked).toString());
        Engine askedOnly = Engine.loadOnly(packs, models, Distribution.CONTROLLED, List.of("pub"), "everything");
        eq("0.93 ruling 5: loadOnly with a profile sets the limit public", Distribution.PUBLIC, askedOnly.maxDistribution());

        // Ruling 5: a file that reads as controlled when it is loaded is distribution-refused and the load fails. This
        // engine reads each file once, so the test hook stands for a file that changed after its profile was read.
        for (String which : new String[]{"core.def", "pub/pack.def"}) {
            for (int loader = 0; loader < 2; loader++) {
                Engine e = new Engine();
                e.profiledTextHook = (source, text) -> source.endsWith(which)
                        ? text.replace("distribution public", "distribution controlled") : text;
                String name = "0.93 ruling 5: " + which + " controlled when loaded, " + (loader == 0 ? "loadAll" : "loadOnly");
                if (loader == 0) {
                    throwsCode(name, GtException.Code.DISTRIBUTION_REFUSED, () -> e.loadAll(packs, models, "open"));
                } else {
                    throwsCode(name, GtException.Code.DISTRIBUTION_REFUSED,
                            () -> e.loadOnly(packs, models, List.of("pub"), "open", false));
                }
                eq(name + ", limit public after", Distribution.PUBLIC, e.maxDistribution());
            }
        }
        {
            // a limit set controlled before the load does not let the changed file through
            Engine e = new Engine();
            e.setMaxDistribution(Distribution.CONTROLLED);
            e.profiledTextHook = (source, text) -> text.replace("distribution public", "distribution controlled");
            throwsCode("0.93 ruling 5: a module controlled when loaded, the limit set controlled before",
                    GtException.Code.DISTRIBUTION_REFUSED, () -> e.loadAll(packs, models, "everything"));
            eq("0.93 ruling 5: nothing loaded past the refusal", 0, e.modules().size());
        }

        // Ruling 6: the limit is the instance's from the load with a profile on: the lower of public and what a
        // caller sets before or after.
        Engine six = new Engine();
        six.setMaxDistribution(Distribution.CONTROLLED);
        six.loadAll(packs, models, "open");
        eq("0.93 ruling 6: the instance's limit after a load with a profile", Distribution.PUBLIC, six.maxDistribution());
        six.setMaxDistribution(Distribution.CONTROLLED);   // no error
        eq("0.93 ruling 6: setting controlled afterwards has no effect", Distribution.PUBLIC, six.maxDistribution());
        // a controlled text loaded directly later is distribution-refused
        throwsCode("0.93 ruling 6: a controlled module loaded directly later", GtException.Code.DISTRIBUTION_REFUSED,
                () -> six.loadModel(CTL, "ctl.def"));
        throwsCode("0.93 ruling 6: a controlled pack loaded directly later", GtException.Code.DISTRIBUTION_REFUSED,
                () -> six.loadPack(CTL_PACK, "ctl/pack.def"));
        // a later load with no profile is bounded by the limit, not by the profile
        Engine later = new Engine();
        later.loadAll(packs, models, "open");
        later.loadPack(PUB_NC.replace("t-pub-nc", "t-later"), "later/pack.def");
        eq("0.93 ruling 6: a later load with no profile loads what open does not hold", "[t-later, t-pub]", formats(later).toString());
        eq("0.93 ruling 6: a later load with no profile leaves the limit", Distribution.PUBLIC, later.maxDistribution());
        Engine laterCtl = new Engine();
        laterCtl.loadAll(packs, models, "open");
        throwsCode("0.93 ruling 6: a later load with no profile is bounded by the limit", GtException.Code.DISTRIBUTION_REFUSED,
                () -> laterCtl.loadPack(CTL_PACK.replace("t-ctl", "t-later"), "later/pack.def"));

        // Ruling 6: a load with a profile on an instance that already holds a controlled module or pack is
        // distribution-refused before anything is read; it refuses with the limit unchanged and leaves no trace.
        Path nowhere = root.resolve("no-such-tree").resolve("packs");
        for (int holds = 0; holds < 2; holds++) {
            String what = holds == 0 ? "module" : "pack";
            for (int loader = 0; loader < 2; loader++) {
                Engine e = new Engine();
                e.loadModel(CORE, "core.def");
                if (holds == 0) e.loadModel(CTL, "ctl.def");
                else e.loadPack(CTL_PACK, "ctl/pack.def");
                int modules = e.modules().size(), loaded = e.packs().size();
                String name = "0.93 ruling 6: a profile on an instance holding a controlled " + what + (loader == 0 ? ", loadAll" : ", loadOnly");
                // the tree does not exist: refused before anything is read
                if (loader == 0) {
                    throwsCode(name, GtException.Code.DISTRIBUTION_REFUSED, () -> e.loadAll(nowhere, nowhere, "open"));
                } else {
                    throwsCode(name, GtException.Code.DISTRIBUTION_REFUSED,
                            () -> e.loadOnly(nowhere, nowhere, List.of("x"), "open", false));
                }
                eq(name + ": limit unchanged", Distribution.CONTROLLED, e.maxDistribution());
                eq(name + ": no module added", modules, e.modules().size());
                eq(name + ": no pack added", loaded, e.packs().size());
                eq(name + ": no licence row", 0, e.licences().size());
                // no trace: the limit can still be set and a controlled pack still loads
                e.loadPack(CTL_PACK.replace("t-ctl", "t-ctl-2"), "ctl2/pack.def");
                check(name + ": a controlled pack still loads after", e.packs().size() == loaded + 1, "packs " + e.packs().size());
                e.setMaxDistribution(Distribution.PUBLIC);
                e.setMaxDistribution(Distribution.CONTROLLED);
                eq(name + ": the limit can still be set", Distribution.CONTROLLED, e.maxDistribution());
            }
        }
        // the order: a profile name that is none of the three is bad-licence first, then the instance check
        {
            Engine e = new Engine();
            e.loadModel(CORE, "core.def");
            e.loadModel(CTL, "ctl.def");
            throwsCode("0.93 ruling 6: a bad name comes before the instance check", GtException.Code.BAD_LICENCE,
                    () -> e.loadAll(packs, models, "Open"));
            throwsCode("0.93 ruling 6: a bad name comes before the instance check, loadOnly", GtException.Code.BAD_LICENCE,
                    () -> e.loadOnly(packs, models, List.of("pub"), "commercial", false));
            eq("0.93 ruling 6: a bad name leaves the limit unchanged", Distribution.CONTROLLED, e.maxDistribution());
            e.loadPack(CTL_PACK, "ctl/pack.def");
            eq("0.93 ruling 6: a bad name leaves no trace", 1, e.packs().size());
            Engine clean = new Engine();
            throwsCode("0.93 ruling 6: a bad name on a clean instance", GtException.Code.BAD_LICENCE,
                    () -> clean.loadAll(nowhere, nowhere, "none"));
            eq("0.93 ruling 6: a bad name on a clean instance, limit unchanged", Distribution.CONTROLLED, clean.maxDistribution());
            clean.loadModel(CTL.replace("module ctl", "module core"), "core.def");
            eq("0.93 ruling 6: a bad name on a clean instance, no trace", 1, clean.modules().size());
        }
        // then the limit is public, and stays so when the load fails later; what it loaded before it failed stays
        {
            Map<String, String> broken = new TreeMap<>(files);
            broken.put("packs/zz-broken/pack.def", PUB.replace("t-pub", "t-broken").replace("wire json", "wire nowire"));
            Path brokenPacks = tree(root.resolve("b"), broken).resolve("packs");
            Engine e = new Engine();
            throwsCode("0.93 ruling 6: a load with a profile that fails later", GtException.Code.UNKNOWN_WIRE,
                    () -> e.loadAll(brokenPacks, models, "everything"));
            eq("0.93 ruling 6: the limit stays public when the load fails later", Distribution.PUBLIC, e.maxDistribution());
            eq("0.93 ruling 6: what it loaded before it failed stays", "[t-pub, t-pub-nc]", formats(e).toString());
            Map<String, String> badTable = new TreeMap<>(files);
            badTable.put("licences.toml", "x = 1\n");
            Path badPacks = tree(root.resolve("l"), badTable).resolve("packs");
            Engine f = new Engine();
            throwsCode("0.93 ruling 6: a bad table after the start", GtException.Code.BAD_LICENCE,
                    () -> f.loadAll(badPacks, badPacks.resolve("../model"), "open"));
            eq("0.93 ruling 6: the limit is public after a bad table", Distribution.PUBLIC, f.maxDistribution());
        }
        // Ruling 2, fail closed: with a profile a module file that 2b gives no name is not loaded, also when shown
        // public, and what uses it is unknown-module; with no profile nothing changes
        for (String bad : new String[]{"module mx # note", "module \"mx\""}) {
            Map<String, String> noName = new TreeMap<>(files);
            noName.put("model/mx.def", bad + "\nversion 0.93.0\ndistribution public\n" + SRC);
            noName.put("packs/uses-mx/pack.def", PUB.replace("t-pub", "t-uses-mx").replace("wire json", "uses mx\nwire json"));
            Path nn = tree(root.resolve("n" + bad.length()), noName).resolve("packs");
            Path nnModels = nn.resolve("../model");
            throwsCode("0.93 ruling 2: " + bad + ", a pack that uses it, open", GtException.Code.UNKNOWN_MODULE,
                    () -> Engine.load(nn, nnModels, Distribution.CONTROLLED, "open"));
            throwsCode("0.93 ruling 2: " + bad + ", a pack that uses it, loadOnly", GtException.Code.UNKNOWN_MODULE,
                    () -> Engine.loadOnly(nn, nnModels, Distribution.CONTROLLED, List.of("uses-mx"), "everything"));
            Engine noPack = Engine.loadOnly(nn, nnModels, Distribution.CONTROLLED, List.of("pub"), "open");
            eq("0.93 ruling 2: " + bad + " is not loaded", "[core]", modules(noPack).toString());
        }
        {
            Map<String, String> noCore = new TreeMap<>(files);
            noCore.put("model/core.def", CORE.replace("module core", "module core # note"));
            Path nc = tree(root.resolve("nocore"), noCore).resolve("packs");
            throwsCode("0.93 ruling 2: a core that 2b gives no name, open", GtException.Code.UNKNOWN_MODULE,
                    () -> Engine.load(nc, nc.resolve("../model"), Distribution.CONTROLLED, "open"));
        }

        // Ruling 7: no profile asked for, nothing changes
        Engine plain = Engine.load(ctlPacks, models, Distribution.CONTROLLED, null);
        eq("0.93 ruling 7: no profile, the limit as asked", Distribution.CONTROLLED, plain.maxDistribution());
        eq("0.93 ruling 7: no profile, a controlled pack loads", "[t-ctl, t-pub, t-pub-nc]", formats(plain).toString());
    }

    /**
     * A controlled inner pack (Version 0.34) never loads under a profile: (a) an inner pack not shown public, (b) one
     * shown public that uses a module that is not. Only the outer pack loads; decode and encode through the inner
     * line give unknown-format and model_keys of the outer does not fail. (c) With no profile and the limit public,
     * an inner pack in the load is distribution-refused.
     */
    private static void innerTests(Path root) throws IOException {
        String[][] variants = {{"a: not shown public", INNER_CONTROLLED}, {"b: uses a controlled module", INNER_USES_CTL}};
        // an entity for encode, from a load with no profile of the same inner pack shown public
        Path plainPacks = tree(root.resolve("plain"), innerFiles(INNER_CONTROLLED.replace("distribution controlled",
                "distribution public"))).resolve("packs");
        Engine plain = Engine.loadOnly(plainPacks, plainPacks.resolve("../model"), Distribution.CONTROLLED, List.of("outer"), null, true);
        eq("0.93 inner: with no profile both packs load", "[t-inner, t-outer]", formats(plain).toString());
        Entity entity = plain.decode("t-outer", "0907");
        eq("0.93 inner: with no profile the inner line decodes", "7", String.valueOf(entity.get("t.x")));
        for (int v = 0; v < variants.length; v++) {
            String label = variants[v][0];
            Path packs = tree(root.resolve("v" + v), innerFiles(variants[v][1])).resolve("packs");
            Path models = packs.resolve("../model");
            for (String profile : PROFILES) {
                for (int loader = 0; loader < 2; loader++) {
                    String name = "0.93 inner " + label + ", " + profile + (loader == 0 ? ", load" : ", loadOnly with inner packs");
                    Engine e;
                    try {
                        e = loader == 0 ? Engine.load(packs, models, Distribution.CONTROLLED, profile)
                                : Engine.loadOnly(packs, models, Distribution.CONTROLLED, List.of("outer"), profile, true);
                    } catch (RuntimeException ex) {
                        check(name + ": loads", false, ex.toString());
                        continue;
                    }
                    eq(name + ": only the outer pack loads", "[t-outer]", formats(e).toString());
                    throwsCode(name + ": decode through the inner line", GtException.Code.UNKNOWN_FORMAT, () -> e.decode("t-outer", "0907"));
                    throwsCode(name + ": encode through the inner line", GtException.Code.UNKNOWN_FORMAT, () -> e.encode("t-outer", entity));
                    try {
                        eq(name + ": model_keys of the outer", "[t.w]", e.modelKeys("t-outer").toString());
                    } catch (RuntimeException ex) {
                        check(name + ": model_keys of the outer does not fail", false, ex.toString());
                    }
                }
            }
            // (c) no profile, limit public, the inner pack in the load
            throwsCode("0.93 inner " + label + ": no profile, limit public, the inner pack loaded", GtException.Code.DISTRIBUTION_REFUSED,
                    () -> Engine.loadOnly(packs, models, Distribution.PUBLIC, List.of("outer"), null, true));
            throwsCode("0.93 inner " + label + ": no profile, limit public, every pack loaded", GtException.Code.DISTRIBUTION_REFUSED,
                    () -> Engine.load(packs, models, Distribution.PUBLIC, null));
        }
    }

    private static Map<String, String> innerFiles(String inner) {
        Map<String, String> files = new TreeMap<>();
        files.put("model/core.def", CORE);
        files.put("model/t.def", T);
        files.put("model/ctl.def", CTL);
        files.put("packs/outer/pack.def", OUTER);
        files.put("packs/t-inner/pack.def", inner);
        return files;
    }

    private static Path tree(Path root, Map<String, String> files) throws IOException {
        for (Map.Entry<String, String> f : files.entrySet()) {
            Path p = root.resolve(f.getKey());
            Files.createDirectories(p.getParent());
            Files.write(p, f.getValue().getBytes(StandardCharsets.UTF_8));
        }
        Files.createDirectories(root.resolve("packs"));
        Files.createDirectories(root.resolve("model"));
        return root;
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

    private static void deleteTree(Path dir) {
        try (java.util.stream.Stream<Path> s = Files.walk(dir)) {
            List<Path> all = new ArrayList<>();
            s.forEach(all::add);
            java.util.Collections.reverse(all);
            for (Path p : all) Files.deleteIfExists(p);
        } catch (IOException ex) {
            check("0.93: temporary directory removed", false, ex.toString());
        }
    }
}
