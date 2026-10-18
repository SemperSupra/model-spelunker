// Read-only FID query of a source-known stripped Windows DLL.
// Usage -postScript QuerySourceKnownFid.java source-known-windows
// Deliberately prints one line per candidate; no automatic function renaming.
import ghidra.app.script.GhidraScript;
import ghidra.feature.fid.db.FidQueryService;
import ghidra.feature.fid.db.FunctionRecord;
import ghidra.feature.fid.service.FidMatch;
import ghidra.feature.fid.service.FidSearchResult;
import ghidra.feature.fid.service.FidService;
import java.util.List;

public class QuerySourceKnownFid extends GhidraScript {
    @Override
    public void run() throws Exception {
        if (currentProgram == null) throw new IllegalArgumentException("no target program");
        String[] args = getScriptArgs();
        if (args.length != 1 || !args[0].matches("[A-Za-z0-9_-]{3,60}"))
            throw new IllegalArgumentException("one expected family argument");
        String family = args[0];
        FidService service = new FidService();
        int scanned = 0, recognized = 0, decoy = 0, ambiguous = 0;
        try (FidQueryService query = service.openFidQueryService(currentProgram.getLanguage(), false)) {
            List<FidSearchResult> rows = service.processProgram(
                currentProgram, query, service.getDefaultScoreThreshold(), monitor);
            for (FidSearchResult row : rows) {
                if (monitor.isCancelled()) throw new IllegalStateException("cancelled");
                scanned++;
                String matchName = null;
                float best = -1.0f;
                int ties = 0;
                if (row.matches == null) continue;
                for (FidMatch match : row.matches) {
                    if (match.getLibraryRecord() == null ||
                        !family.equals(match.getLibraryRecord().getLibraryFamilyName())) continue;
                    FunctionRecord record = match.getFunctionRecord();
                    if (record == null) continue;
                    float score = match.getOverallScore();
                    if (score > best) {
                        matchName = record.getName();
                        best = score;
                        ties = 1;
                    } else if (score == best) {
                        ties++;
                    }
                }
                if (matchName == null) continue;
                if (ties > 1) ambiguous++;
                recognized++;
                if ("re_lib_unrelated".equals(matchName)) decoy++;
                println("RE_FID_MATCH=" + row.function.getEntryPoint() + "," +
                        matchName + "," + best + "," + ties);
            }
        }
        println("RE_FID_TARGET_SCANNED=" + scanned);
        println("RE_FID_TARGET_MATCHES=" + recognized);
        println("RE_FID_TARGET_AMBIGUOUS=" + ambiguous);
        println("RE_FID_TARGET_DECOY=" + decoy);
        // Do not fail for zero matches. The independent evaluator decides acceptance.
    }
}
