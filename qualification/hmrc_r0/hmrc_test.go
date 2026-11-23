package hmrc

import (
    "errors"
    "fmt"
    "math/rand"
    "os"
    "path/filepath"
    "strings"
    "sync"
    "testing"
)

func fixture() Snapshot {
    digest := "sha256:"+strings.Repeat("a",64)
    return Snapshot{
        Schema:"hmrc-r0",Generation:1,Scope:"synthetic-atlas",
        EffectiveCapacity:1000,
        Units:[]Unit{
            {ID:"governing",Scope:"synthetic-atlas",Kind:"protected",Tokens:150,Sequence:1},
            {ID:"task",Scope:"synthetic-atlas",Kind:"active",Tokens:220,Sequence:2},
            {ID:"log-1",Scope:"synthetic-atlas",Kind:"historical",Tokens:180,SourceID:"SYN_A",SourceDigest:digest,Verified:true,Sequence:3},
            {ID:"log-2",Scope:"synthetic-atlas",Kind:"historical",Tokens:160,SourceID:"SYN_B",SourceDigest:digest,Verified:true,Sequence:4},
            {ID:"log-3",Scope:"synthetic-atlas",Kind:"historical",Tokens:140,SourceID:"SYN_C",SourceDigest:digest,Verified:true,Sequence:5},
        },
    }
}
func demand() Forecast { return Forecast{NextTurnTokens:60,ReserveTokens:60} }

func TestPredictiveCompactionKeepsProtectedAndActive(t *testing.T) {
    s:=fixture()
    d,err:=Propose(s,demand())
    if err!=nil {t.Fatal(err)}
    if !d.Compact || d.BeforeTokens!=850 || d.ProjectedTokens!=970 ||
       d.AfterProjectedTokens!=630 || len(d.RemoveIDs)!=2 ||
       d.RemoveIDs[0]!="log-1" || d.RemoveIDs[1]!="log-2" {
        t.Fatalf("unexpected plan: %+v",d)
    }
    if d.InvalidatedPrefixTokens!=480 || d.EngineCacheAdvice!="engine-owns-physical-kv" {
        t.Fatalf("incorrect cache advisory %+v",d)
    }
    m,err:=NewManager(filepath.Join(t.TempDir(),"checkpoint.json"),s)
    if err!=nil {t.Fatal(err)}
    after,err:=m.Apply(d)
    if err!=nil {t.Fatal(err)}
    if after.Generation!=2 || len(after.Units)!=3 || len(after.Evicted)!=2 {
        t.Fatalf("wrong recovered working set %+v",after)
    }
    for _,u:=range after.Units {
        if u.Kind=="protected" && u.ID!="governing" {t.Fatal("protected source changed")}
    }
    for _,e:=range after.Evicted {
        if e.SourceID=="" || e.SourceDigest=="" || e.AtGeneration!=2 {t.Fatal("untraceable eviction")}
    }
}

func TestRecoveryPreservesExactReceipts(t *testing.T) {
    path:=filepath.Join(t.TempDir(),"state.json")
    m,err:=NewManager(path,fixture())
    if err!=nil {t.Fatal(err)}
    p,err:=Propose(m.Read(),demand())
    if err!=nil {t.Fatal(err)}
    a,err:=m.Apply(p)
    if err!=nil {t.Fatal(err)}
    r,err:=Recover(path)
    if err!=nil {t.Fatal(err)}
    b:=r.Read()
    if a.Generation!=b.Generation || len(a.Units)!=len(b.Units) ||
        len(a.Evicted)!=len(b.Evicted) {t.Fatalf("recovery mismatch: %+v %+v",a,b)}
    if _,err:=r.Apply(p); !errors.Is(err,ErrStale) {t.Fatalf("replayed stale operation: %v",err)}
}

func TestRejectOpenToolBoundary(t *testing.T) {
    s:=fixture(); s.OpenToolTransactions=1
    _,err:=Propose(s,demand())
    if !errors.Is(err,ErrBoundary) {t.Fatalf("expected boundary, got %v",err)}
}
func TestRejectInsufficientDurableHistory(t *testing.T) {
    s:=fixture()
    for i:=range s.Units {if s.Units[i].Kind=="historical" {s.Units[i].Verified=false}}
    _,err:=Propose(s,demand())
    if !errors.Is(err,ErrHeadroom) {t.Fatalf("expected no safe eviction: %v",err)}
}
func TestRejectCrossScope(t *testing.T) {
    s:=fixture();s.Units[3].Scope="synthetic-vega"
    _,err:=Propose(s,demand())
    if !errors.Is(err,ErrInvalid) {t.Fatalf("foreign scope accepted: %v",err)}
}
func TestRejectBadEvidenceDigest(t *testing.T) {
    s:=fixture();s.Units[2].SourceDigest="fake"
    _,err:=Propose(s,demand())
    if !errors.Is(err,ErrInvalid) {t.Fatalf("bad digest accepted: %v",err)}
}
func TestRejectUnknownCapacity(t *testing.T) {
    s:=fixture();s.EffectiveCapacity=0
    _,err:=Propose(s,demand())
    if !errors.Is(err,ErrInvalid) {t.Fatalf("unknown capacity: %v",err)}
}
func TestRejectOversizedForecast(t *testing.T) {
    _,err:=Propose(fixture(),Forecast{NextTurnTokens:980,ReserveTokens:40})
    if !errors.Is(err,ErrInvalid) {t.Fatalf("unbounded generation: %v",err)}
}
func TestRejectForgedPolicy(t *testing.T) {
    m,err:=NewManager(filepath.Join(t.TempDir(),"checkpoint.json"),fixture())
    if err!=nil {t.Fatal(err)}
    d,err:=Propose(m.Read(),demand())
    if err!=nil {t.Fatal(err)}
    d.RemoveIDs=[]string{"governing","task"}
    if _,err:=m.Apply(d);!errors.Is(err,ErrUntrustedPlan) {t.Fatalf("forged plan accepted: %v",err)}
}
func TestNoCompactionWhenNoPressure(t *testing.T) {
    s:=fixture();s.EffectiveCapacity=1500
    m,err:=NewManager(filepath.Join(t.TempDir(),"checkpoint.json"),s)
    if err!=nil {t.Fatal(err)}
    p,err:=Propose(s,demand())
    if err!=nil {t.Fatal(err)}
    if p.Compact {t.Fatal("unnecessary cache invalidation")}
    after,err:=m.Apply(p)
    if err!=nil || after.Generation!=1 {t.Fatalf("compacted when no need: %v %+v",err,after)}
}
func TestRollbackOnCheckpointFailure(t *testing.T) {
    m,err:=NewManager(filepath.Join(t.TempDir(),"state.json"),fixture())
    if err!=nil {t.Fatal(err)}
    p,err:=Propose(m.Read(),demand())
    if err!=nil {t.Fatal(err)}
    m.path=t.TempDir() // rename to existing directory fails before state mutation
    if _,err:=m.Apply(p);err==nil {t.Fatal("checkpoint write failure ignored")}
    if m.Read().Generation!=1 || len(m.Read().Units)!=5 {t.Fatal("mutated without durable commit")}
}
func TestRejectCorruptedCheckpoint(t *testing.T) {
    p:=filepath.Join(t.TempDir(),"state.json")
    if err:=os.WriteFile(p,[]byte("{not-json"),0600);err!=nil {t.Fatal(err)}
    if _,err:=Recover(p);err==nil {t.Fatal("corrupt state accepted")}
}
func TestConcurrentCompactionsSingleWinner(t *testing.T) {
    m,err:=NewManager(filepath.Join(t.TempDir(),"state.json"),fixture())
    if err!=nil {t.Fatal(err)}
    p,err:=Propose(m.Read(),demand())
    if err!=nil {t.Fatal(err)}
    var wg sync.WaitGroup
    successes:=make(chan bool,24)
    for i:=0;i<24;i++ {
        wg.Add(1)
        go func() {
            defer wg.Done()
            _,err:=m.Apply(p)
            if err!=nil && !errors.Is(err,ErrStale) {t.Errorf("unexpected concurrent error: %v",err)}
            successes<-err==nil
        }()
    }
    wg.Wait();close(successes)
    wins:=0
    for v:=range successes {if v {wins++}}
    if wins!=1 {t.Fatalf("expected exactly one CAS winner, got %d",wins)}
}

func TestSyntheticPressureCrossover(t *testing.T) {
    // A deterministic no-model screening control: current-token-only trigger
    // versus projected-next-turn trigger across 3 seeds x 20 synthetic turns.
    // Reports threshold misses, not model/task improvement or physical KV hits.
    misses,proposed,blocked:=0,0,0
    for _,seed:=range []int64{11,29,47} {
        rng:=rand.New(rand.NewSource(seed))
        for rep:=0;rep<20;rep++ {
            s:=fixture()
            // 70..90% current context; next request 6..20%, reserve 5%.
            current:=700+rng.Intn(201)
            s.Units[4].Tokens+=current-total(s)
            f:=Forecast{NextTurnTokens:60+rng.Intn(141),ReserveTokens:50}
            predicted:=total(s)+f.NextTurnTokens+f.ReserveTokens
            currentOnlyTrigger:=total(s)>=s.EffectiveCapacity*85/100
            p,err:=Propose(s,f)
            if err!=nil {
                if !errors.Is(err,ErrHeadroom) {t.Fatal(err)}
                blocked++;continue
            }
            if p.Compact {
                proposed++
                for _,id:=range p.RemoveIDs {
                    if id=="governing" || id=="task" {t.Fatal("removed protected or active memory")}
                }
            }
            if predicted>=850 && !currentOnlyTrigger && p.Compact {misses++}
        }
    }
    t.Logf("SYNTHETIC_ONLY crossovers=60 predicted_early_compaction=%d plan_count=%d fail_closed_headroom=%d; no LLM or KV cache measured",misses,proposed,blocked)
    if misses==0 || proposed==0 {t.Fatal("no predictive distinction from current-only baseline")}
}

func BenchmarkPropose(b *testing.B) {
    s:=fixture();f:=demand()
    for i:=0;i<b.N;i++ {
        if _,err:=Propose(s,f);err!=nil {b.Fatal(fmt.Sprint(err))}
    }
}
