// Read-only FID query of a source-known stripped Windows DLL.
// Usage -postScript QuerySourceKnownFid.java source-known-windows
// Deliberately prints one line per candidate; no automatic function renaming.
import ghidra.app.script.GhidraScript;
import ghidra.feature.fid.db.FidQueryService;
import ghidra.feature.fid.db.FidFile;
import ghidra.feature.fid.db.FidFileManager;
import java.io.File;
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
        if (args.length != 2 || !args[0].matches("[A-Za-z0-9_-]{3,60}"))
            throw new IllegalArgumentException("expected family and exact .fidb path");
        String family = args[0];
        FidFileManager manager = FidFileManager.getInstance();
        File reference = new File(args[1]);
        if (!reference.isFile() || !reference.getName().endsWith(".fidb")) {
            throw new IllegalArgumentException("FID file not found");
        }
        FidFile fidFile = manager.addUserFidFile(reference);
        if (fidFile == null || !fidFile.isActive() ||
            !fidFile.canProcessLanguage(currentProgram.getLanguage())) {
            throw new IllegalStateException("FID database unavailable for target language");
        }
        println("RE_FID_ATTACHED=" + fidFile.getName());
        println("RE_FID_PROGRAM_FUNCTIONS=" +
                currentProgram.getFunctionManager().getFunctionCount());
        println("RE_FID_AVAILABLE_DATABASES=" + manager.getFidFiles().size());
        FidService service = new FidService();
        int candidates = 0, recognized = 0, decoy = 0, ambiguous = 0;
        try (FidQueryService query = service.openFidQueryService(currentProgram.getLanguage(), false)) {
            List<FidSearchResult> rows = service.processProgram(
                currentProgram, query, service.getDefaultScoreThreshold(), monitor);
            for (FidSearchResult row : rows) {
                if (monitor.isCancelled()) throw new IllegalStateException("cancelled");
                candidates++;
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
        println("RE_FID_TARGET_CANDIDATE_ROWS=" + candidates);
        println("RE_FID_TARGET_MATCHES=" + recognized);
        println("RE_FID_TARGET_AMBIGUOUS=" + ambiguous);
        println("RE_FID_TARGET_DECOY=" + decoy);
        // Do not fail for zero matches. The independent evaluator decides acceptance.
    }
}
