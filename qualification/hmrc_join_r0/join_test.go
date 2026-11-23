package join

import (
    "errors"
    "reflect"
    "strings"
    "testing"

    hmrc "example.com/sempersupra/hmrc-r0"
    telemetry "example.com/sempersupra/hmrc-telemetry-r0"
)

func ptr[T any](v T)*T{return &v}
func snapshot() hmrc.Snapshot {
    dig:="sha256:"+strings.Repeat("a",64)
    return hmrc.Snapshot{
        Schema:"hmrc-r0",Generation:4,Scope:"synthetic-atlas",EffectiveCapacity:1000,
        Units:[]hmrc.Unit{
            {ID:"owner",Scope:"synthetic-atlas",Kind:"protected",Tokens:120,Sequence:1},
            {ID:"work",Scope:"synthetic-atlas",Kind:"active",Tokens:130,Sequence:2},
            {ID:"historical-a",Scope:"synthetic-atlas",Kind:"historical",Tokens:180,SourceID:"SYN_A",SourceDigest:dig,Verified:true,Sequence:3},
            {ID:"historical-b",Scope:"synthetic-atlas",Kind:"historical",Tokens:160,SourceID:"SYN_B",SourceDigest:dig,Verified:true,Sequence:4},
        },
    }
}
func observation() telemetry.Observation {
    return telemetry.Observation{
        Schema:"hmrc-telemetry-r0",Engine:"ollama",SourcePath:"/api/ps",
        Endpoint:"http://127.0.0.1:11434",
        Models:[]telemetry.Model{{
            Name:"synthetic-qwen",Digest:"sha256:"+strings.Repeat("f",64),
            ReportedContextTokens:ptr(700),
        }},
    }
}
func binding() Binding{
    return Binding{Engine:"ollama",ModelID:"synthetic-qwen",
        ExactArtifactDigest:"sha256:"+strings.Repeat("f",64),
        ApprovedContextLimit:1000}
}
func forecast()hmrc.Forecast{return hmrc.Forecast{NextTurnTokens:80,ReserveTokens:80}}

func TestCrossLayerForecastAndAuthority(t *testing.T) {
    s:=snapshot()
    direct,err:=hmrc.Propose(s,forecast())
    if err!=nil || direct.Compact {t.Fatalf("without real server bound, no compaction expected: %+v %v",direct,err)}
    a,err:=Advise(s,forecast(),observation(),binding())
    if err!=nil {t.Fatal(err)}
    if !a.Plan.Compact || !a.RequiresHarnessApproval || a.BoundedContextTokens!=700 ||
        a.ReportedRuntimeContextTokens!=700 || a.PhysicalKVCacheOwner!="serving-engine" ||
        a.Plan.AfterProjectedTokens!=410 || len(a.Plan.RemoveIDs)!=2 {
        t.Fatalf("joined result unexpected: %+v",a)
    }
    for _,id:=range a.Plan.RemoveIDs {
        if id=="owner" || id=="work" {t.Fatal("protected/active content evicted")}
    }
    if s.EffectiveCapacity!=1000 || s.Generation!=4 {t.Fatal("advisory join mutated harness state")}
}
func TestRejectWrongDigest(t *testing.T) {
    b:=binding();b.ExactArtifactDigest="sha256:wrong"
    if _,err:=Advise(snapshot(),forecast(),observation(),b);!errors.Is(err,ErrUnbound){t.Fatalf("wrong artifact accepted: %v",err)}
}
func TestRejectAmbiguousModel(t *testing.T) {
    o:=observation();o.Models=append(o.Models,o.Models[0])
    if _,err:=Advise(snapshot(),forecast(),o,binding());!errors.Is(err,ErrUnbound){t.Fatalf("duplicate residency accepted: %v",err)}
}
func TestRejectUnknownContext(t *testing.T) {
    o:=observation();o.Models[0].ReportedContextTokens=nil
    if _,err:=Advise(snapshot(),forecast(),o,binding());!errors.Is(err,ErrUnbound){t.Fatalf("unknown capacity accepted: %v",err)}
}
func TestRejectUnknownModel(t *testing.T) {
    b:=binding();b.ModelID="missing"
    if _,err:=Advise(snapshot(),forecast(),observation(),b);!errors.Is(err,ErrUnbound){t.Fatalf("missing model accepted: %v",err)}
}
func TestRejectWrongSourcePath(t *testing.T) {
    o:=observation();o.SourcePath="/api/generate"
    if _,err:=Advise(snapshot(),forecast(),o,binding());!errors.Is(err,ErrUnbound){t.Fatalf("untrusted source endpoint accepted: %v",err)}
}
func TestRejectNonNativeLlamaBinding(t *testing.T) {
    o:=observation();o.Engine="llama.cpp"
    b:=binding();b.Engine="llama.cpp"
    if _,err:=Advise(snapshot(),forecast(),o,b);!errors.Is(err,ErrUnbound){t.Fatalf("missing model binding accepted: %v",err)}
}
func TestRejectOpenToolTransaction(t *testing.T) {
    s:=snapshot();s.OpenToolTransactions=1
    if _,err:=Advise(s,forecast(),observation(),binding());!errors.Is(err,hmrc.ErrBoundary){t.Fatalf("open tool boundary ignored: %v",err)}
}
func TestRejectTaintedEvidence(t *testing.T) {
    s:=snapshot();s.Units[2].SourceDigest="sha256:fake"
    if _,err:=Advise(s,forecast(),observation(),binding());!errors.Is(err,hmrc.ErrInvalid){t.Fatalf("tainted evidence accepted: %v",err)}
}
func TestCachePressureCannotForceSemanticEviction(t *testing.T) {
    s:=snapshot();s.EffectiveCapacity=2000
    b:=binding();b.ApprovedContextLimit=2000
    o:=observation();o.Models[0].ReportedContextTokens=ptr(2000)
    baseline,err:=Advise(s,forecast(),o,b)
    if err!=nil || baseline.Plan.Compact {t.Fatalf("should have headroom %v %+v",err,baseline)}
    o.KVCachePressure=ptr(0.99)
    o.PromptCacheHitRate=ptr(0.01)
    after,err:=Advise(s,forecast(),o,b)
    if err!=nil || !reflect.DeepEqual(after.Plan,baseline.Plan) {t.Fatal("physical KV telemetry overrode semantic policy")}
}
func TestApprovedLimitIsUpperBound(t *testing.T) {
    b:=binding();b.ApprovedContextLimit=680
    a,err:=Advise(snapshot(),forecast(),observation(),b)
    if err!=nil || a.BoundedContextTokens!=680 {t.Fatalf("approval limit not applied: %+v %v",a,err)}
}
func BenchmarkAdvise(b *testing.B) {
    s,o,c,f:=snapshot(),observation(),binding(),forecast()
    for i:=0;i<b.N;i++ {
        if _,err:=Advise(s,f,o,c);err!=nil {b.Fatal(err)}
    }
}
