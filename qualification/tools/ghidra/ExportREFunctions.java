// Read-only Ghidra headless evidence export for source-known RE qualification.
// UNQUALIFIED: must be exercised against a pinned Ghidra runtime and oracle.
// Called via: -postScript ExportREFunctions.java /absolute/approved/output.json
// Never executes the imported target binary or mutates the Ghidra project.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.Function;
import java.io.BufferedWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.Set;

public class ExportREFunctions extends GhidraScript {
    private static final int MAX_FUNCTIONS = 256;
    private static final int MAX_DECOMP_CHARS = 8000;

    private static String quote(String text) {
        StringBuilder sb = new StringBuilder("\"");
        if (text == null) return "null";
        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);
            if (c == '\\') sb.append("\\\\");
            else if (c == '"') sb.append("\\\"");
            else if (c == '\n') sb.append("\\n");
            else if (c == '\r') sb.append("\\r");
            else if (c == '\t') sb.append("\\t");
            else if (c < 0x20) sb.append(String.format("\\u%04x", (int)c));
            else sb.append(c);
        }
        sb.append('"');
        return sb.toString();
    }

    @Override
    public void run() throws Exception {
        if (currentProgram == null) throw new IllegalArgumentException("program required");
        String[] args = getScriptArgs();
        if (args.length != 1) throw new IllegalArgumentException("one output path required");
        Path output = Paths.get(args[0]).toAbsolutePath().normalize();
        if (!Files.isDirectory(output.getParent()) || Files.exists(output)) {
            throw new IllegalArgumentException("output directory absent or output exists");
        }
        DecompInterface decomp = new DecompInterface();
        try {
            if (!decomp.openProgram(currentProgram)) throw new IllegalStateException("decompiler refused program");
            try (BufferedWriter writer = Files.newBufferedWriter(output, StandardCharsets.UTF_8,
                    StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE)) {
                writer.write("{\"schema_version\":1,\"program_name\":" + quote(currentProgram.getName())
                    + ",\"language\":" + quote(currentProgram.getLanguageID().toString())
                    + ",\"functions\":[");
                boolean first = true;
                int count = 0;
                for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
                    if (monitor.isCancelled() || count >= MAX_FUNCTIONS) break;
                    DecompileResults result = decomp.decompileFunction(f, 20, monitor);
                    String pseudo = result != null && result.decompileCompleted()
                        && result.getDecompiledFunction() != null
                        ? result.getDecompiledFunction().getC() : null;
                    if (pseudo != null && pseudo.length() > MAX_DECOMP_CHARS) {
                        pseudo = pseudo.substring(0, MAX_DECOMP_CHARS);
                    }
                    if (!first) writer.write(",");
                    first = false;
                    writer.write("{\"entry\":" + quote(f.getEntryPoint().toString())
                        + ",\"name\":" + quote(f.getName())
                        + ",\"size\":" + f.getBody().getNumAddresses()
                        + ",\"decompilation\":" + quote(pseudo)
                        + ",\"callees\":[");
                    boolean firstCallee = true;
                    Set<Function> callees = f.getCalledFunctions(monitor);
                    for (Function callee : callees) {
                        if (!firstCallee) writer.write(",");
                        firstCallee = false;
                        writer.write(quote(callee.getEntryPoint().toString()));
                    }
                    writer.write("]}");
                    count++;
                }
                writer.write("],\"function_limit\":" + MAX_FUNCTIONS + "}\n");
            }
        } finally {
            decomp.dispose();
        }
    }
}
