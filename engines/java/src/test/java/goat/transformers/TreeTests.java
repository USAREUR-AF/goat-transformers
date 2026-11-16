package goat.transformers;

import static goat.transformers.TestRunner.check;
import static goat.transformers.TestRunner.eq;
import static goat.transformers.TestRunner.throwsCode;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

/** {@link Tree}: the named packs and only the model modules they need. */
final class TreeTests {
    private TreeTests() {}

    private static List<String> modules(Engine e) {
        List<String> out = new ArrayList<>();
        for (ModelModule m : e.modules()) out.add(m.name);
        java.util.Collections.sort(out);
        return out;
    }

    static void run(Path packsDir) {
        Path root = packsDir.resolve("..");
        Engine e = Tree.load(root, List.of("cot-xml", "geojson"));
        eq("tree: two packs need core only", modules(e).toString(), "[core]");
        eq("tree: two packs loaded", String.valueOf(e.packs().size()), "2");
        String cot = "<event version=\"2.0\" uid=\"J-01334\" type=\"a-f-G-U-C\" time=\"2021-02-27T20:00:00.000Z\" how=\"m-g\">"
                + "<point lat=\"30.0090027\" lon=\"-85.9578182\" hae=\"-42.6\" ce=\"45.3\" le=\"99.5\"/></event>";
        eq("tree: convert", e.convert("cot-xml", "geojson", cot),
                "{\"type\":\"Feature\",\"geometry\":{\"type\":\"Point\",\"coordinates\":[-85.9578182,30.0090027,-42.6]},"
                + "\"properties\":{\"type\":\"a-f-G-U-C\",\"time_ms\":1614456000000,\"how\":\"m-g\",\"ce\":45.3,\"le\":99.5},\"id\":\"J-01334\"}");
        // asterix-cat062 uses cat062, and cat062 uses track
        Engine a = Tree.load(root, List.of("asterix-cat062"));
        eq("tree: uses through a module", modules(a).toString(), "[cat062, core, track]");
        Tree.loadInto(a, root, List.of("canonical-track-v2"));
        check("tree: a second load adds a pack", a.packs().size() == 2 && modules(a).size() == 3, modules(a).toString());
        throwsCode("tree: a pack the tree does not hold", GtException.Code.UNKNOWN_FORMAT, () -> Tree.load(root, List.of("no-such-format")));
    }
}
