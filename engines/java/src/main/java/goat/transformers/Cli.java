package goat.transformers;

import java.io.IOException;
import java.io.PrintStream;
import java.nio.file.Path;
import java.nio.file.Paths;

/**
 * {@code convert --from X --to Y --packs DIR} reads stdin, writes stdout; {@code --set <key>=<value>}, repeatable,
 * supplies a model key the source does not carry.
 * {@code list-formats --packs DIR} prints one {@code <format> <version> <wire>} line per pack.
 * Both take {@code --models DIR} (default {@code <packs>/../model}), {@code --max-distribution public|controlled}
 * (default {@code controlled}), {@code --max-items <n>} (the limit on list items of one decode, default 100,000) and
 * {@code --packs-only a,b}: load only the named packs of the directory, with the
 * model modules they need, instead of every pack.
 * Exit codes: 0 ok, 1 engine error, 2 usage.
 */
public final class Cli {
    private Cli() {}

    public static void main(String[] args) throws IOException {
        System.exit(run(args, System.out, System.err));
    }

    static int run(String[] args, PrintStream out, PrintStream err) throws IOException {
        if (args.length == 0) return usage(err);
        String cmd = args[0];
        String from = null, to = null, packs = null, models = null;
        java.util.List<String> only = null;
        Distribution limit = Distribution.CONTROLLED;
        long maxItems = -1;
        java.util.LinkedHashMap<String, String> context = null;
        for (int i = 1; i < args.length; i++) {
            String a = args[i];
            if (i + 1 >= args.length) return usage(err);
            switch (a) {
                case "--from": from = args[++i]; break;
                case "--to": to = args[++i]; break;
                case "--packs": packs = args[++i]; break;
                case "--models": models = args[++i]; break;
                case "--packs-only": {
                    if (only == null) only = new java.util.ArrayList<>();
                    for (String name : args[++i].split(",", -1)) {
                        if (name.isEmpty()) return usage(err);
                        only.add(name);
                    }
                    break;
                }
                case "--set": {
                    String kv = args[++i];
                    int eq = kv.indexOf('=');
                    if (eq < 1) return usage(err);
                    if (context == null) context = new java.util.LinkedHashMap<>();
                    context.put(kv.substring(0, eq), kv.substring(eq + 1));
                    break;
                }
                case "--max-items": {
                    String n = args[++i];
                    if (!Transform.UNSIGNED.matcher(n).matches() || n.replaceFirst("^0+(?=.)", "").length() > 18) return usage(err);
                    maxItems = Long.parseLong(n);
                    break;
                }
                case "--max-distribution":
                    limit = Distribution.byToken(args[++i]);
                    if (limit == null) return usage(err);
                    break;
                default: return usage(err);
            }
        }
        if (packs == null) return usage(err);
        Path dir = Paths.get(packs);
        try {
            Path modelsDir = models == null ? Engine.defaultModelsDir(dir) : Paths.get(models);
            Engine engine = only == null ? Engine.load(dir, modelsDir, limit) : Engine.loadOnly(dir, modelsDir, limit, only);
            if (maxItems >= 0) engine.setMaxItems(maxItems);
            switch (cmd) {
                case "list-formats":
                    for (Pack p : engine.packs()) out.println(p.format + " " + p.version + " " + p.wire.name().toLowerCase());
                    out.flush();
                    return 0;
                case "convert":
                    if (from == null || to == null) return usage(err);
                    byte[] in = System.in.readAllBytes();
                    out.write(engine.convert(from, to, new String(in, java.nio.charset.StandardCharsets.UTF_8), context)
                            .getBytes(java.nio.charset.StandardCharsets.UTF_8));
                    out.flush();
                    return 0;
                default:
                    return usage(err);
            }
        } catch (GtException ex) {
            err.println("error: " + ex.getMessage());
            return 1;
        }
    }

    private static int usage(PrintStream err) {
        err.println("usage: convert --from FORMAT --to FORMAT --packs DIR [--set KEY=VALUE]...   (stdin -> stdout)");
        err.println("       list-formats --packs DIR");
        err.println("options: --models DIR (default <packs>/../model)  --max-distribution public|controlled (default controlled)");
        err.println("         --packs-only NAME[,NAME...]  load only the named packs, with the model modules they need");
        err.println("         --max-items N  the limit on list items of one decode (default 100000)");
        return 2;
    }
}
