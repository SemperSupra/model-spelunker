// Source-known Ghidra FID reference creation — explicit admitted research only.
// Usage: -process ref_dispatcher.so -postScript BuildSourceKnownFid.java /tmp/out.fidb
// Must run on a SAVED project DomainFile, after complete analysis.
import ghidra.app.script.GhidraScript;
import ghidra.feature.fid.db.FidDB;
import ghidra.feature.fid.db.FidFile;
import ghidra.feature.fid.db.FidFileManager;
import ghidra.feature.fid.service.FidPopulateResult;
import ghidra.feature.fid.service.FidService;
import ghidra.framework.model.DomainFile;
import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.List;

public class BuildSourceKnownFid extends GhidraScript {
    @Override
    protected void run() throws Exception {
        if (currentProgram == null) throw new IllegalArgumentException("missing reference program");
        String[] args = getScriptArgs();
        if (args.length != 1) throw new IllegalArgumentException("provide output .fidb path");
        Path out = Paths.get(args[0]).toAbsolutePath().normalize();
        if (!Files.isDirectory(out.getParent()) || Files.exists(out) || !out.toString().endsWith(".fidb")) {
            throw new IllegalArgumentException("invalid output target");
        }
        DomainFile df = currentProgram.getDomainFile();
        if (df == null) throw new IllegalStateException("reference must be saved into Ghidra project");
        FidFileManager manager = FidFileManager.getInstance();
        manager.createNewFidDatabase(out.toFile());
        FidFile file = manager.addUserFidFile(out.toFile());
        if (file == null) throw new IllegalStateException("could not attach FID");
        FidService service = new FidService();
        try (FidDB db = file.getFidDB(true)) {
            FidPopulateResult result = service.createNewLibraryFromPrograms(
                db, "source-known-dispatcher", "v0", "clang-O1", List.of(df),
                null, currentProgram.getLanguageID(), null, null, monitor);
            if (result == null) throw new IllegalStateException("FID population returned null");
            println("RE_FID_ATTEMPTED=" + result.getTotalAttempted());
            println("RE_FID_ADDED=" + result.getTotalAdded());
            if (result.getTotalAdded() <= 0) throw new IllegalStateException("no source-known FID functions included");
            db.saveDatabase("source-known-re-reference", monitor);
        }
        if (!Files.isRegularFile(out) || Files.size(out) <= 0) {
            throw new IllegalStateException("FID database missing or empty");
        }
        println("RE_FID_DATABASE_CREATED=" + out.getFileName().toString());
    }
}
