package goat.transformers;

import java.io.IOException;
import java.io.InputStream;
import java.io.PrintStream;
import java.io.UncheckedIOException;
import java.math.BigInteger;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.InvalidPathException;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;
import java.util.stream.Stream;

/**
 * The command-line tool of spec Version 0.23 (the command-line contract):
 * {@code convert}, {@code list-formats}, {@code capability}, {@code matrix} and {@code help}.
 * Exit status 0 on success, 1 on a load or call failure (standard error's first line begins with the kind and a
 * colon), 2 on a usage error (every argument is checked before anything is loaded).
 * The default of {@code --packs} is {@code packs}, resolved against the working directory.
 */
public final class Cli {
    private Cli() {}

    static final String DEFAULT_PACKS = "packs";

    private static final Set<String> COMMON = Set.of("--packs", "--models", "--packs-only", "--max-items", "--max-distribution");
    private static final Pattern DIGITS = Pattern.compile("[0-9]+");
    private static final BigInteger LONG_MAX = BigInteger.valueOf(Long.MAX_VALUE);
    private static final Comparator<String> BYTE_ORDER = (a, b) -> Arrays.compareUnsigned(
            a.getBytes(StandardCharsets.UTF_8), b.getBytes(StandardCharsets.UTF_8));

    public static void main(String[] args) throws IOException {
        PrintStream out = new PrintStream(new java.io.FileOutputStream(java.io.FileDescriptor.out), false, "UTF-8");
        PrintStream err = new PrintStream(new java.io.FileOutputStream(java.io.FileDescriptor.err), true, "UTF-8");
        int code = run(args, System.in, out, err);
        out.flush();
        err.flush();
        System.exit(code);
    }

    /** As {@link #run(String[], InputStream, PrintStream, PrintStream)} with standard input. */
    static int run(String[] args, PrintStream out, PrintStream err) throws IOException {
        return run(args, System.in, out, err);
    }

    /** One run of the tool: the arguments after the program name; returns the exit status. */
    static int run(String[] args, InputStream in, PrintStream out, PrintStream err) throws IOException {
        Args a = parse(args);
        if (a.usage != null) {
            err.println("goat-xf-java: " + a.usage);
            usage(err);
            return 2;
        }
        if (a.cmd.equals("help")) {
            usage(out);
            out.flush();
            return 0;
        }
        try {
            Engine engine = load(a);
            byte[] result;
            switch (a.cmd) {
                case "list-formats": {
                    List<Pack> packs = new ArrayList<>(engine.packs());
                    packs.sort((p, q) -> BYTE_ORDER.compare(p.format, q.format));
                    StringBuilder sb = new StringBuilder();
                    for (Pack p : packs) {
                        sb.append(p.format).append('\t').append(p.version).append('\t')
                                .append(p.wire.name().toLowerCase(Locale.ROOT)).append('\n');
                    }
                    result = sb.toString().getBytes(StandardCharsets.UTF_8);
                    break;
                }
                case "capability":
                    result = line(a.from, a.to, engine.capability(a.from, a.to)).getBytes(StandardCharsets.UTF_8);
                    break;
                case "matrix": {
                    List<String> formats = new ArrayList<>();
                    for (Pack p : engine.packs()) formats.add(p.format);
                    formats.sort(BYTE_ORDER);
                    StringBuilder sb = new StringBuilder("from\tto\tgrade\tcarried\tdropped\n");
                    for (String f : formats) {
                        for (String t : formats) sb.append(line(f, t, engine.capability(f, t)));
                    }
                    result = sb.toString().getBytes(StandardCharsets.UTF_8);
                    break;
                }
                case "convert": {
                    engine.modelKeys(a.from);   // unknown-format, --from first, before standard input is read
                    engine.modelKeys(a.to);
                    String text = utf8(in.readAllBytes(), a.from);
                    result = engine.convert(a.from, a.to, text, a.context).getBytes(StandardCharsets.UTF_8);
                    break;
                }
                default:
                    throw new IllegalStateException(a.cmd);
            }
            out.write(result);
            out.flush();
            return 0;
        } catch (GtException ex) {
            err.println(ex.getMessage());
            return 1;
        } catch (UncheckedIOException ex) {
            err.println("io: " + ex.getMessage() + (ex.getCause() == null ? "" : " (" + ex.getCause() + ")"));
            return 1;
        }
    }

    /** One line of the matrix form, with its line feed. */
    private static String line(String from, String to, Engine.Capability c) {
        return from + '\t' + to + '\t' + c.grade + '\t' + String.join(" ", c.carried) + '\t' + String.join(" ", c.dropped) + '\n';
    }

    /** Standard input as text; bytes that are not UTF-8 are malformed-wire on every wire. */
    private static String utf8(byte[] bytes, String format) {
        try {
            return StandardCharsets.UTF_8.newDecoder()
                    .onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT)
                    .decode(ByteBuffer.wrap(bytes)).toString();
        } catch (CharacterCodingException ex) {
            throw new GtException(GtException.Code.MALFORMED_WIRE, format, null, "standard input is not UTF-8");
        }
    }

    /** The checked arguments of one run, or the reason for a usage error. */
    private static final class Args {
        String usage;
        String cmd;
        String from, to;
        String packs = DEFAULT_PACKS, models;
        List<String> only;
        Long maxItems;
        Distribution limit = Distribution.CONTROLLED;
        LinkedHashMap<String, String> context;
    }

    private static Args fail(Args a, String why) {
        a.usage = why;
        return a;
    }

    private static Args parse(String[] args) {
        Args a = new Args();
        if (args.length == 0) return fail(a, "no subcommand");
        String cmd = args[0];
        if (cmd.equals("help") || cmd.equals("-h") || cmd.equals("--help")) {
            a.cmd = "help";
            return a;
        }
        Set<String> names = new HashSet<>(COMMON);
        switch (cmd) {
            case "convert": names.add("--set"); names.add("--from"); names.add("--to"); break;
            case "capability": names.add("--from"); names.add("--to"); break;
            case "list-formats": case "matrix": break;
            default: return fail(a, "unknown subcommand " + cmd);
        }
        a.cmd = cmd;
        Set<String> seen = new HashSet<>();
        for (int i = 1; i < args.length; i += 2) {
            String name = args[i];
            if (!names.contains(name)) return fail(a, cmd + " takes no option " + name);
            if (i + 1 >= args.length) return fail(a, name + " has no value");
            String value = args[i + 1];
            if (!name.equals("--set") && !seen.add(name)) return fail(a, name + " given twice");
            switch (name) {
                case "--from": a.from = value; break;
                case "--to": a.to = value; break;
                case "--packs": a.packs = value; break;
                case "--models": a.models = value; break;
                case "--packs-only": {
                    a.only = new ArrayList<>();
                    for (String n : value.split(",", -1)) {
                        if (n.isEmpty()) return fail(a, "--packs-only has an empty name");
                        a.only.add(n);
                    }
                    break;
                }
                case "--max-items": {
                    if (!DIGITS.matcher(value).matches()) return fail(a, "--max-items is not a number: " + value);
                    BigInteger n = new BigInteger(value);
                    if (n.compareTo(LONG_MAX) > 0) return fail(a, "--max-items is above 2^63 - 1: " + value);
                    a.maxItems = n.longValue();
                    break;
                }
                case "--max-distribution":
                    a.limit = Distribution.byToken(value);
                    if (a.limit == null) return fail(a, "--max-distribution is neither public nor controlled: " + value);
                    break;
                case "--set": {
                    int eq = value.indexOf('=');
                    if (eq < 1) return fail(a, "--set needs <key>=<value>: " + value);
                    if (a.context == null) a.context = new LinkedHashMap<>();
                    a.context.put(value.substring(0, eq), value.substring(eq + 1));   // last value, first place
                    break;
                }
                default: throw new IllegalStateException(name);
            }
        }
        if ((cmd.equals("convert") || cmd.equals("capability")) && (a.from == null || a.to == null)) {
            return fail(a, cmd + " needs --from and --to");
        }
        return a;
    }

    /**
     * Loading of the contract: every module of {@code --models} (none when it is not a directory), then the packs
     * named by {@code --packs-only} in the order given, or every pack directory of {@code --packs} in byte order.
     */
    private static Engine load(Args a) {
        Engine e = new Engine();
        e.setMaxDistribution(a.limit);
        if (a.maxItems != null) e.setMaxItems(a.maxItems);
        Path models = path(a.models != null ? a.models : a.packs + "/../model");
        if (models != null && Files.isDirectory(models)) {
            for (String[] m : Engine.modelsInLoadOrder(models)) e.loadModel(m[1], m[0]);
        }
        Path packs = path(a.packs);
        List<Path> defs = new ArrayList<>();
        if (a.only != null) {
            // --packs is not listed: each name is looked up in it, so a missing --packs makes the first name unknown-format
            for (String name : a.only) {
                Path def = packs == null ? null : packDef(packs, name);
                if (def == null) {
                    throw new GtException(GtException.Code.UNKNOWN_FORMAT, name, null,
                            "no pack directory " + name + " holding pack.def in " + a.packs);
                }
                loadPack(e, def);   // a name given twice is loaded twice: duplicate-format
            }
            return e;
        }
        if (packs == null || !Files.isDirectory(packs) || !Files.isReadable(packs)) {
            throw new UncheckedIOException(new IOException("cannot read the packs directory " + a.packs));
        }
        List<String> names = new ArrayList<>();
        try (Stream<Path> s = Files.list(packs)) {
            s.forEach(p -> names.add(p.getFileName().toString()));
        } catch (IOException ex) {
            throw new UncheckedIOException("cannot list the packs directory " + a.packs, ex);
        }
        names.sort(BYTE_ORDER);
        for (String n : names) {
            if (n.startsWith(".")) continue;
            Path dir = packs.resolve(n), def = dir.resolve("pack.def");
            if (Files.isDirectory(dir) && Files.isRegularFile(def)) defs.add(def);
        }
        for (Path def : defs) loadPack(e, def);
        return e;
    }

    /** The {@code pack.def} of the subdirectory {@code name}, or null when the name is not one such directory. */
    private static Path packDef(Path packs, String name) {
        if (name.indexOf('/') >= 0 || name.indexOf('\\') >= 0 || name.equals(".") || name.equals("..")) return null;
        try {
            Path dir = packs.resolve(name), def = dir.resolve("pack.def");
            return Files.isDirectory(dir) && Files.isRegularFile(def) ? def : null;
        } catch (InvalidPathException ex) {
            return null;
        }
    }

    private static void loadPack(Engine e, Path def) {
        String text;
        try {
            text = Files.readString(def, StandardCharsets.UTF_8);
        } catch (IOException ex) {
            throw new UncheckedIOException("cannot read " + def, ex);
        }
        e.loadPack(text, def.toString());
    }

    private static Path path(String text) {
        try {
            return Paths.get(text);
        } catch (InvalidPathException ex) {
            return null;
        }
    }

    private static void usage(PrintStream s) {
        s.println("usage: <tool> convert --from FORMAT --to FORMAT [--set KEY=VALUE]... [options]   (stdin -> stdout)");
        s.println("       <tool> list-formats [options]");
        s.println("       <tool> capability --from FORMAT --to FORMAT [options]");
        s.println("       <tool> matrix [options]");
        s.println("       <tool> help");
        s.println("options: --packs DIR                 the packs directory (default: packs, in the working directory)");
        s.println("         --models DIR                the model modules (default: <packs>/../model)");
        s.println("         --packs-only NAME[,NAME...] load only these subdirectories of --packs, in this order");
        s.println("         --max-items N               the limit on list items of one decode (default 100000)");
        s.println("         --max-distribution public|controlled   the distribution limit (default controlled)");
        s.println("exit status: 0 success, 1 load or call failure (stderr begins with the kind), 2 usage error");
    }
}
