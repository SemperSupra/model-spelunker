package main

import (
 "bytes"
 "encoding/json"
 "strings"
 "testing"
)

func r7Claim()liveClaim{
 return liveClaim{
  Schema:"serving-fanout-g2-screen/v1",
  EvidenceClass:"PUBLIC_CPU_CONFIGURED_AGENT",
  SourceSHA:"184a079bfe92596b8b1541a95d1b07a13da80ca3",
  ArtifactSHA256:"0904c7f87f6e6b2abd2f3124eee2e579d08426a6bbe0b768d0a9532b6a74110e",
  ModelDigest:"8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7",
  TaskClasses:1,AttemptedTasks:24,VerifiedTasks:24,HostReplications:1,
  RepsPerCondition:2,IndependentTaskOracle:true,
 }
}
func TestR7NoPromotionDespite24Of24Passed(t *testing.T){
 c:=r7Claim()
 r,e:=screenLive(c);if e!=nil{t.Fatal(e)}
 if r.Decision!="INSUFFICIENT_EVIDENCE"||r.AutomaticPromotion!="NEVER"{
  t.Fatalf("overpromoted simple single-host task evidence: %+v",r)
 }
 if len(r.Reasons)<4{t.Fatalf("insufficient reasons: %+v",r)}
}
func TestR9TaskFailureBlocksRegardlessOfInfrastructure(t *testing.T){
 c:=r7Claim();c.AttemptedTasks=2;c.VerifiedTasks=0;c.TaskClasses=2
 r,e:=screenLive(c);if e!=nil{t.Fatal(e)}
 if r.Decision!="REJECT_TASK_QUALITY"{t.Fatalf("unsafe conclusion: %+v",r)}
}
func TestR10NativeQueueInvariantFailureCannotBecomeADefault(t *testing.T){
 c:=r7Claim();c.EvidenceClass="PUBLIC_CPU_DIRECT_INFERENCE"
 c.AttemptedTasks=0;c.VerifiedTasks=0;c.IndependentTaskOracle=false
 c.AdmissionViolations=1
 r,e:=screenLive(c);if e!=nil{t.Fatal(e)}
 if r.Decision!="REJECT_ADMISSION_INVARIANT"{t.Fatalf("ignored counterexample: %+v",r)}
}
func TestR13MTLSDoesNotEstablishTenantAuthority(t *testing.T){
 c:=r7Claim();c.EvidenceClass="PUBLIC_CPU_DIRECT_INFERENCE"
 c.AttemptedTasks=0;c.VerifiedTasks=0;c.IndependentTaskOracle=false
 c.HostReplications=2;c.RepsPerCondition=12;c.TaskClasses=0
 c.TenantIdentityVerified=false;c.BackendBypassClosed=false
 r,e:=screenLive(c);if e!=nil{t.Fatal(e)}
 if r.Decision!="INSUFFICIENT_EVIDENCE"||r.AutomaticPromotion!="NEVER"{t.Fatalf("%+v",r)}
}
func TestEvenCompleteSourceLabeledMetadataDoesNotSelfAuthorize(t *testing.T){
 c:=r7Claim()
 c.EvidenceClass="SEPARATELY_ADMITTED_SOVEREIGN_HIL"
 c.PhysicalHostAdmitted=true;c.ModelArtifactAdmitted=true
 c.TaskClasses=4;c.HostReplications=10;c.RepsPerCondition=20
 c.StreamingTTFTObserved=true;c.MeasuredMemoryPressure=true
 c.TenantIdentityVerified=true;c.BackendBypassClosed=true
 r,e:=screenLive(c);if e!=nil{t.Fatal(e)}
 if r.Decision!="ELIGIBLE_FOR_INDEPENDENT_REVIEW_ONLY"||r.AutomaticPromotion!="NEVER"{
  t.Fatalf("metadata attempted unauthorized auto-release: %+v",r)
 }
}
func TestInvalidCountersAndProvenanceFailClosed(t *testing.T){
 cases:=[]func(*liveClaim){
  func(c *liveClaim){c.SourceSHA="short"},
  func(c *liveClaim){c.ModelDigest="wrong"},
  func(c *liveClaim){c.ArtifactSHA256=strings.Repeat("z",64)},
  func(c *liveClaim){c.AttemptedTasks=-1},
  func(c *liveClaim){c.VerifiedTasks=25},
  func(c *liveClaim){c.IndependentTaskOracle=false},
  func(c *liveClaim){c.EvidenceClass="PHYSICAL_SLO_PROVED"},
 }
 for i,modify:=range cases {
  c:=r7Claim();modify(&c)
  if _,err:=screenLive(c);err==nil{t.Fatalf("forged source/quality accepted: %d",i)}
 }
}
func TestStrictJSONAndTrustedInputShape(t *testing.T){
 c:=r7Claim();raw,e:=json.Marshal(c);if e!=nil{t.Fatal(e)}
 roundtrip,e:=decodeLive(raw);if e!=nil{t.Fatal(e)}
 if r,e:=screenLive(roundtrip);e!=nil||r.AutomaticPromotion!="NEVER"{t.Fatalf("unexpected %+v %v",r,e)}
 for i,blob:=range [][]byte{
  append(append([]byte(nil),raw...),[]byte(" {}")...),
  bytes.Replace(raw,[]byte("}"),[]byte(",\"untrusted_production_override\":true}"),1),
  make([]byte,(1<<20)+1),
 }{
  if _,e:=decodeLive(blob);e==nil{t.Fatalf("accepted malformed JSON %d",i)}
 }
}
