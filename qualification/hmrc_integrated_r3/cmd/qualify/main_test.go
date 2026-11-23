package main

import (
    "errors"
    "os"
    "path/filepath"
    "strings"
    "testing"

    evidence "example.com/sempersupra/hmrc-evidence-r2"
    join "example.com/sempersupra/hmrc-join-r0"
    telemetry "example.com/sempersupra/hmrc-telemetry-r0"
)

func testSource(t *testing.T)(string,error){
    t.Helper()
    return "../../../fixtures/memory_dle_cpe_synthetic_v1.json",nil
}
func mockObservation() telemetry.Observation {
    n:=32768
    return telemetry.Observation{
        Schema:"hmrc-telemetry-r0",Engine:"ollama",SourcePath:"/api/ps",
        Models:[]telemetry.Model{{
            Name:modelID,Digest:"sha256:"+pinnedModelDigest,
            ReportedContextTokens:&n,
        }},
    }
}
func TestNativeJoinSimulatedTelemetryAndExactRecovery(t *testing.T) {
    p,_:=testSource(t)
    s,c,err:=loadState(p)
    if err!=nil {t.Fatal(err)}
    r,err:=run(s,c,mockObservation(),filepath.Join(t.TempDir(),"state.json"))
    if err!=nil {t.Fatal(err)}
    if r.RuntimeContextTokens!=32768 || r.PolicyContextCap!=1000 ||
       !r.Compacted || !r.RecoveryVerified || !r.ProtectedSurvived ||
       len(r.EvictedSourceIDs)!=2 || r.AfterGeneration!=2 ||
       r.NativeModelInferenceExecuted || r.PhysicalKVCacheQualified ||
       r.FullAgentTaskQualified {
        t.Fatalf("invalid integrated receipt %+v",r)
    }
}
func TestWrongModelDigestFailClosed(t *testing.T) {
    p,_:=testSource(t)
    s,c,err:=loadState(p)
    if err!=nil {t.Fatal(err)}
    o:=mockObservation();o.Models[0].Digest="sha256:"+strings.Repeat("f",64)
    if _,err:=run(s,c,o,filepath.Join(t.TempDir(),"state.json"));!errors.Is(err,join.ErrUnbound) {
        t.Fatalf("model identity drift accepted: %v",err)
    }
}
func TestUnknownRuntimeContextFailClosed(t *testing.T) {
    p,_:=testSource(t)
    s,c,_:=loadState(p)
    o:=mockObservation();o.Models[0].ReportedContextTokens=nil
    if _,err:=run(s,c,o,filepath.Join(t.TempDir(),"state.json"));!errors.Is(err,join.ErrUnbound) {
        t.Fatalf("unknown capacity accepted: %v",err)
    }
}
func TestDifferentRuntimeBudgetCannotBeAppliedBlindly(t *testing.T) {
    p,_:=testSource(t)
    s,c,_:=loadState(p)
    o:=mockObservation();n:=800;o.Models[0].ReportedContextTokens=&n
    if _,err:=run(s,c,o,filepath.Join(t.TempDir(),"state.json"));err==nil {
        t.Fatal("cross-generation effective-capacity mismatch silently applied")
    }
}
func TestSourceByteTamperPreventsCompaction(t *testing.T) {
    p,_:=testSource(t)
    s,c,_:=loadState(p)
    for i:=range c.Records {
        if c.Records[i].ID=="SYN_ATLAS_CPE_R5_BLUE" {
            c.Records[i].Bytes=[]byte("forged accepted source text")
        }
    }
    if _,err:=run(s,c,mockObservation(),filepath.Join(t.TempDir(),"state.json"));!errors.Is(err,evidence.ErrEvidence) {
        t.Fatalf("unverified source was evicted: %v",err)
    }
}
func TestAdvisoryCannotReplaceProtectedInstruction(t *testing.T) {
    p,_:=testSource(t)
    s,c,_:=loadState(p)
    for i:=range c.Records {
        if c.Records[i].ID=="SYN_ATLAS_DLE_R8_HOLD" {c.Records[i].Status="advisory"}
    }
    if _,err:=run(s,c,mockObservation(),filepath.Join(t.TempDir(),"state.json"));!errors.Is(err,evidence.ErrEvidence) {
        t.Fatalf("unaccepted owner source became protected: %v",err)
    }
}
func TestConcurrentExclusiveLeaseFailClosed(t *testing.T) {
    p,_:=testSource(t)
    s,c,_:=loadState(p)
    state:=filepath.Join(t.TempDir(),"state.json")
    f,err:=os.OpenFile(state+".lease",os.O_CREATE|os.O_EXCL|os.O_WRONLY,0600)
    if err!=nil {t.Fatal(err)}
    f.Close()
    if _,err:=run(s,c,mockObservation(),state);!errors.Is(err,evidence.ErrBusy){
        t.Fatalf("parallel owner bypassed custody: %v",err)
    }
}
func TestCannotReplayCompletedCompaction(t *testing.T) {
    p,_:=testSource(t)
    s,c,_:=loadState(p)
    state:=filepath.Join(t.TempDir(),"state.json")
    if _,err:=run(s,c,mockObservation(),state);err!=nil {t.Fatal(err)}
    if _,err:=run(s,c,mockObservation(),state);err==nil {t.Fatal("session replay was accepted")}
}
