package evidence

import (
    "errors"
    "os"
    "path/filepath"
    "strings"
    "testing"

    hmrc "example.com/sempersupra/hmrc-r0"
)

const scope="synthetic-atlas"
func fixtures() (hmrc.Snapshot,Catalog) {
    srcs:=[]Source{
        {ID:"SYN_OWNER",Scope:scope,Status:"accepted",Bytes:[]byte("no deployment without independent authorization")},
        {ID:"SYN_HISTORY_A",Scope:scope,Status:"accepted",Bytes:[]byte("synthetic accepted result A")},
        {ID:"SYN_HISTORY_B",Scope:scope,Status:"advisory",Bytes:[]byte("synthetic advisory result B")},
        {ID:"SYN_HISTORY_C",Scope:scope,Status:"accepted",Bytes:[]byte("synthetic accepted result C")},
    }
    s:=hmrc.Snapshot{Schema:"hmrc-r0",Scope:scope,Generation:1,EffectiveCapacity:1000}
    s.Units=[]hmrc.Unit{
        {ID:"protected",Scope:scope,Kind:"protected",Tokens:150,SourceID:srcs[0].ID,SourceDigest:digest(srcs[0].Bytes),Verified:true,Sequence:1},
        {ID:"active",Scope:scope,Kind:"active",Tokens:220,Sequence:2},
        {ID:"history-A",Scope:scope,Kind:"historical",Tokens:180,SourceID:srcs[1].ID,SourceDigest:digest(srcs[1].Bytes),Verified:true,Sequence:3},
        {ID:"history-B",Scope:scope,Kind:"historical",Tokens:160,SourceID:srcs[2].ID,SourceDigest:digest(srcs[2].Bytes),Verified:true,Sequence:4},
        {ID:"history-C",Scope:scope,Kind:"historical",Tokens:140,SourceID:srcs[3].ID,SourceDigest:digest(srcs[3].Bytes),Verified:true,Sequence:5},
    }
    return s,Catalog{Records:srcs}
}
func forecast() hmrc.Forecast {return hmrc.Forecast{NextTurnTokens:60,ReserveTokens:60}}
func TestSourceBoundCompactionAndRestart(t *testing.T) {
    s,c:=fixtures()
    path:=filepath.Join(t.TempDir(),"checkpoint.json")
    m,err:=Open(path,c,&s)
    if err!=nil {t.Fatal(err)}
    p,err:=m.Propose(forecast())
    if err!=nil || !p.Compact || len(p.RemoveIDs)!=2 {t.Fatalf("plan=%+v error=%v",p,err)}
    after,err:=m.Apply(p)
    if err!=nil {t.Fatal(err)}
    if after.Generation!=2 || len(after.Evicted)!=2 {t.Fatal("exact evictions lost")}
    if err:=Verify(after,c);err!=nil {t.Fatal(err)}
    if err:=m.Close();err!=nil {t.Fatal(err)}
    // Recovery must reuse existing checkpoint, not caller's stale initial state.
    restored,err:=Open(path,c,&s)
    if err!=nil {t.Fatal(err)}
    snap,err:=restored.Read()
    if err!=nil || snap.Generation!=2 || len(snap.Evicted)!=2 {t.Fatalf("restart lost history: %+v %v",snap,err)}
    if _,err:=restored.Apply(p);!errors.Is(err,hmrc.ErrStale){t.Fatalf("stale replay accepted: %v",err)}
    if err:=restored.Close();err!=nil {t.Fatal(err)}
}
func TestCannotDuplicateSessionAcrossProcessesOrInstances(t *testing.T) {
    s,c:=fixtures()
    path:=filepath.Join(t.TempDir(),"state.json")
    m,err:=Open(path,c,&s)
    if err!=nil {t.Fatal(err)}
    if _,err:=Open(path,c,nil);!errors.Is(err,ErrBusy){t.Fatalf("duplicate session lease accepted: %v",err)}
    if err:=m.Close();err!=nil {t.Fatal(err)}
    restored,err:=Open(path,c,nil)
    if err!=nil {t.Fatal(err)}
    if err:=restored.Close();err!=nil{t.Fatal(err)}
}
func TestCrashStaleLeaseNeedsReconciliation(t *testing.T) {
    s,c:=fixtures()
    path:=filepath.Join(t.TempDir(),"state.json")
    f,err:=os.OpenFile(path+".lease",os.O_CREATE|os.O_EXCL|os.O_WRONLY,0600)
    if err!=nil{t.Fatal(err)}
    f.Close()
    if _,err:=Open(path,c,&s);!errors.Is(err,ErrBusy){t.Fatalf("stale lease bypassed: %v",err)}
}
func TestRejectModelDeclaredVerifiedWithoutActualEvidence(t *testing.T) {
    s,c:=fixtures()
    c.Records[1].Bytes=[]byte("manipulated model text")
    if err:=Verify(s,c);!errors.Is(err,ErrEvidence){t.Fatalf("forged verified flag accepted: %v",err)}
}
func TestRejectSupersededRetrieval(t *testing.T) {
    s,c:=fixtures()
    c.Records[1].Status="superseded"
    if _,err:=Open(filepath.Join(t.TempDir(),"s.json"),c,&s);!errors.Is(err,ErrEvidence){
        t.Fatalf("superseded source accepted: %v",err)
    }
}
func TestRejectForeignScopeMemory(t *testing.T) {
    s,c:=fixtures()
    c.Records[3].Scope="synthetic-vega"
    if err:=Verify(s,c);!errors.Is(err,ErrEvidence){t.Fatalf("cross-scope source accepted: %v",err)}
}
func TestRejectAdvisoryAsProtectedInstruction(t *testing.T) {
    s,c:=fixtures()
    c.Records[0].Status="advisory"
    if err:=Verify(s,c);!errors.Is(err,ErrEvidence){t.Fatalf("advisory promoted to protected: %v",err)}
}
func TestRejectCatalogDuplicateIDs(t *testing.T) {
    s,c:=fixtures()
    c.Records=append(c.Records,c.Records[0])
    if err:=Verify(s,c);!errors.Is(err,ErrEvidence){t.Fatalf("ambiguous source accepted: %v",err)}
}
func TestCatalogNotWritableAfterOpen(t *testing.T) {
    s,c:=fixtures()
    m,err:=Open(filepath.Join(t.TempDir(),"s.json"),c,&s)
    if err!=nil {t.Fatal(err)}
    c.Records[0].Bytes[0]='x'
    c.Records[1].Status="superseded"
    if _,err:=m.Read();err!=nil {t.Fatalf("caller mutated admitted manifest: %v",err)}
    m.Close()
}
func TestRejectTamperedCheckpointOnReopen(t *testing.T) {
    s,c:=fixtures()
    p:=filepath.Join(t.TempDir(),"state.json")
    m,err:=Open(p,c,&s)
    if err!=nil {t.Fatal(err)}
    if err:=m.Close();err!=nil {t.Fatal(err)}
    raw,err:=os.ReadFile(p)
    if err!=nil {t.Fatal(err)}
    corrupted:=strings.Replace(string(raw),digest(c.Records[1].Bytes),"sha256:"+strings.Repeat("f",64),1)
    if corrupted==string(raw){t.Fatal("source digest was not in checkpoint")}
    if err:=os.WriteFile(p,[]byte(corrupted),0600);err!=nil {t.Fatal(err)}
    if _,err:=Open(p,c,nil);!errors.Is(err,ErrEvidence){t.Fatalf("tampered persisted evidence accepted: %v",err)}
}
func TestNoAutoRecoveryFromCorruptCheckpoint(t *testing.T) {
    s,c:=fixtures()
    p:=filepath.Join(t.TempDir(),"s.json")
    m,err:=Open(p,c,&s)
    if err!=nil {t.Fatal(err)}
    m.Close()
    if err:=os.WriteFile(p,[]byte("{corrupt"),0600);err!=nil {t.Fatal(err)}
    if _,err:=Open(p,c,nil);err==nil {t.Fatal("corruption was silently repaired")}
}
func TestNoSourceNoReversibleCompaction(t *testing.T) {
    s,c:=fixtures()
    s.Units[2].Verified=false
    s.Units[3].Verified=false
    s.Units[4].Verified=false
    m,err:=Open(filepath.Join(t.TempDir(),"s.json"),c,&s)
    if err!=nil {t.Fatal(err)}
    _,err=m.Propose(forecast())
    if !errors.Is(err,hmrc.ErrHeadroom){t.Fatalf("unverified eviction not blocked: %v",err)}
    m.Close()
}
