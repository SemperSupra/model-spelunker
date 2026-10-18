// Source-known MSVC CRT /MT vs /MD experiment. Read-only query using
// ONLY FID databases bundled with checksum-pinned Ghidra; no custom FID.
// This is an observation stream, NOT automatic naming or source identity proof.
import ghidra.app.script.GhidraScript;
import ghidra.feature.fid.db.FidFile;
import ghidra.feature.fid.db.FidFileManager;
import ghidra.feature.fid.db.FidQueryService;
import ghidra.feature.fid.db.FunctionRecord;
import ghidra.feature.fid.service.FidMatch;
import ghidra.feature.fid.service.FidSearchResult;
import ghidra.feature.fid.service.FidService;
import java.util.List;
import java.util.Locale;

public class QueryBundledCrtFid extends GhidraScript {
    private static String field(String in) {
        if (in == null) return "UNKNOWN";
        return in.replace('|', '_').replace('\n', '_').replace('\r', '_');
    }
    @Override
    public void run() throws Exception {
        if (currentProgram == null) throw new IllegalStateException("program missing");
        String[] args = getScriptArgs();
        if (args.length != 1 || !("static".equals(args[0]) || "dynamic".equals(args[0]))) {
            throw new IllegalArgumentException("expected exact static or dynamic label");
        }
        FidFileManager fm = FidFileManager.getInstance();
        List<FidFile> dbs = fm.getFidFiles();
        int active = 0;
        for (FidFile db : dbs) {
            if (db.isActive() && db.canProcessLanguage(currentProgram.getLanguage())) {
                active++;
                println("RE_SHIPPED_FID_DB=" + field(db.getName()));
            }
        }
        println("RE_FID_VARIANT=" + args[0]);
        println("RE_FID_FUNCTIONS_ANALYZED=" +
                currentProgram.getFunctionManager().getFunctionCount());
        println("RE_SHIPPED_FID_DB_COUNT=" + dbs.size());
        println("RE_SHIPPED_FID_ELIGIBLE_COUNT=" + active);
        int candidateRows = 0, matches = 0, ambiguous = 0, outputLimit = 500;
        FidService service = new FidService();
        try (FidQueryService query = service.openFidQueryService(currentProgram.getLanguage(), false)) {
            List<FidSearchResult> rows = service.processProgram(
                    currentProgram, query, service.getDefaultScoreThreshold(), monitor);
            for (FidSearchResult row : rows) {
                if (monitor.isCancelled()) throw new IllegalStateException("cancelled");
                if (++candidateRows > 4096) throw new IllegalStateException("candidate limit");
                if (row.matches == null || row.matches.isEmpty()) continue;
                FidMatch best = null;
                float bestScore = -1.0f;
                int ties = 0;
                for (FidMatch candidate : row.matches) {
                    if (candidate.getLibraryRecord() == null ||
                        candidate.getFunctionRecord() == null) continue;
                    float score = candidate.getOverallScore();
                    if (score > bestScore) {
                        bestScore = score; best = candidate; ties = 1;
                    } else if (score == bestScore) {
                        ties++;
                    }
                }
                if (best == null) continue;
                matches++;
                if (ties > 1) ambiguous++;
                if (matches > outputLimit) throw new IllegalStateException("match output limit");
                println("RE_SHIPPED_FID_MATCH=" +
                    Long.toHexString(row.function.getEntryPoint().getOffset()).toLowerCase(Locale.ROOT)
                    + "|" + field(best.getFunctionRecord().getName())
                    + "|" + bestScore
                    + "|" + field(best.getLibraryRecord().getLibraryFamilyName())
                    + "|" + field(best.getLibraryRecord().getLibraryVersion())
                    + "|" + field(best.getLibraryRecord().getLibraryVariant())
                    + "|" + ties);
            }
        }
        println("RE_SHIPPED_FID_CANDIDATE_ROWS=" + candidateRows);
        println("RE_SHIPPED_FID_MATCH_COUNT=" + matches);
        println("RE_SHIPPED_FID_AMBIGUOUS_COUNT=" + ambiguous);
    }
}
