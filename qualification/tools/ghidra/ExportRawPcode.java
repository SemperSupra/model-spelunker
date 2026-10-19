// Bounded read-only raw instruction p-code evidence, synthetic public RE controls.
// This is SLEIGH-lifted *raw instruction p-code*, NOT decompiler HighFunction p-code.
// Called as an independent -postScript after normal headless analysis.
// No project mutation, binary execution, external network, or source/oracle exposure.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.pcode.PcodeOp;
import ghidra.program.model.pcode.Varnode;
import java.io.BufferedWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.Map;
import java.util.TreeMap;

public class ExportRawPcode extends GhidraScript {
    private static final int MAX_FUNCTIONS = 256;
    private static final int MAX_INSTRUCTIONS_PER_FUNCTION = 1024;
    private static final int MAX_SAMPLED_OPS_PER_FUNCTION = 256;
    private static final int MAX_GLOBAL_PCODE_OPS = 20000;
    private static final int MAX_INPUTS_PER_OP = 8;
    private static final int MAX_VARNODE_TEXT = 120;

    private static String quote(String text) {
        if (text == null) return "null";
        StringBuilder out = new StringBuilder("\"");
        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);
            if (c == '\\') out.append("\\\\");
            else if (c == '"') out.append("\\\"");
            else if (c == '\n') out.append("\\n");
            else if (c == '\r') out.append("\\r");
            else if (c == '\t') out.append("\\t");
            else if (c < 0x20) out.append(String.format("\\u%04x", (int)c));
            else out.append(c);
        }
        out.append('"');
        return out.toString();
    }

    private static String varnode(Varnode node) {
        if (node == null) return null;
        String value = node.toString();
        return value.length() > MAX_VARNODE_TEXT
            ? value.substring(0, MAX_VARNODE_TEXT) : value;
    }

    @Override
    public void run() throws Exception {
        if (currentProgram == null) throw new IllegalArgumentException("program required");
        String[] args = getScriptArgs();
        if (args.length != 1) throw new IllegalArgumentException("one output path required");
        Path output = Paths.get(args[0]).toAbsolutePath().normalize();
        if (!Files.isDirectory(output.getParent()) || Files.exists(output)) {
            throw new IllegalArgumentException("output parent missing or output exists");
        }
        int globalOps = 0;
        int functionCount = 0;
        try (BufferedWriter w = Files.newBufferedWriter(output, StandardCharsets.UTF_8,
                StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE)) {
            w.write("{\"schema_version\":1,\"pcode_level\":\"raw_instruction\","
                + "\"program_name\":" + quote(currentProgram.getName())
                + ",\"language\":" + quote(currentProgram.getLanguageID().toString())
                + ",\"functions\":[");
            boolean firstFunction = true;
            for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
                if (monitor.isCancelled()) throw new IllegalStateException("cancelled");
                if (++functionCount > MAX_FUNCTIONS) {
                    throw new IllegalStateException("function limit exceeded");
                }
                if (!firstFunction) w.write(",");
                firstFunction = false;
                w.write("{\"entry\":" + quote(f.getEntryPoint().toString())
                    + ",\"name\":" + quote(f.getName()));
                TreeMap<String, Integer> histogram = new TreeMap<>();
                StringBuilder samples = new StringBuilder();
                int instructions = 0;
                int ops = 0;
                int sampled = 0;
                InstructionIterator iter =
                    currentProgram.getListing().getInstructions(f.getBody(), true);
                while (iter.hasNext()) {
                    if (monitor.isCancelled()) throw new IllegalStateException("cancelled");
                    if (++instructions > MAX_INSTRUCTIONS_PER_FUNCTION) {
                        throw new IllegalStateException("instruction limit exceeded");
                    }
                    Instruction insn = iter.next();
                    for (PcodeOp op : insn.getPcode(false)) {
                        if (++globalOps > MAX_GLOBAL_PCODE_OPS) {
                            throw new IllegalStateException("global pcode op limit exceeded");
                        }
                        ops++;
                        String mnemonic = op.getMnemonic();
                        histogram.put(mnemonic, histogram.getOrDefault(mnemonic, 0) + 1);
                        if (sampled >= MAX_SAMPLED_OPS_PER_FUNCTION) continue;
                        if (sampled++ > 0) samples.append(",");
                        samples.append("{\"instruction\":" + quote(insn.getAddress().toString())
                            + ",\"opcode\":" + quote(mnemonic)
                            + ",\"output\":" + quote(varnode(op.getOutput()))
                            + ",\"inputs\":[");
                        int numInputs = op.getNumInputs();
                        if (numInputs > MAX_INPUTS_PER_OP) {
                            throw new IllegalStateException("varnode input limit exceeded");
                        }
                        for (int i = 0; i < numInputs; i++) {
                            if (i != 0) samples.append(",");
                            samples.append(quote(varnode(op.getInput(i))));
                        }
                        samples.append("]}");
                    }
                }
                w.write(",\"instruction_count\":" + instructions
                    + ",\"pcode_total\":" + ops
                    + ",\"sampled\":" + sampled
                    + ",\"truncated\":" + (sampled < ops)
                    + ",\"histogram\":{");
                boolean firstKey = true;
                for (Map.Entry<String, Integer> count : histogram.entrySet()) {
                    if (!firstKey) w.write(",");
                    firstKey = false;
                    w.write(quote(count.getKey()) + ":" + count.getValue());
                }
                w.write("},\"ops\":[" + samples + "]}");
            }
            w.write("],\"function_limit\":" + MAX_FUNCTIONS
                + ",\"global_pcode_total\":" + globalOps + "}\n");
        }
    }
}
