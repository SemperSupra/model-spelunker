package main

// Source-labeled live-evidence qualification gate. It is an offline reviewer
// aid, never an authorization or a production scheduling implementation.
import (
 "bytes"
 "encoding/json"
 "errors"
 "fmt"
 "io"
 "os"
)

type liveClaim struct {
 Schema string `json:"schema"`
 EvidenceClass string `json:"evidence_class"`
 SourceSHA string `json:"source_sha"`
 ArtifactSHA256 string `json:"artifact_sha256"`
 ModelDigest string `json:"runtime_model_sha256"`
 TaskClasses int `json:"distinct_task_classes"`
 AttemptedTasks int `json:"attempted_tasks"`
 VerifiedTasks int `json:"independently_verified_tasks"`
 HostReplications int `json:"independent_host_reps"`
 RepsPerCondition int `json:"reps_per_condition"`
 IndependentTaskOracle bool `json:"independent_task_oracle"`
 PhysicalHostAdmitted bool `json:"physical_host_admitted"`
 ModelArtifactAdmitted bool `json:"full_model_artifact_admitted"`
 StreamingTTFTObserved bool `json:"streaming_ttft_observed"`
 MeasuredMemoryPressure bool `json:"measured_memory_pressure"`
 TenantIdentityVerified bool `json:"tenant_identity_verified"`
 BackendBypassClosed bool `json:"backend_bypass_closed"`
 AdmissionViolations int `json:"admission_invariant_violations"`
}
type liveGate struct {
 Decision string `json:"decision"`
 Reasons []string `json:"reasons"`
 AutomaticPromotion string `json:"automatic_promotion"`
 OriginAuthentication string `json:"origin_authentication"`
}

func lowerHex(s string,n int)bool{
 if len(s)!=n{return false}
 for _,r:=range s {if r>='0'&&r<='9'||r>='a'&&r<='f'{continue};return false}
 return true
}
func decodeLive(b []byte)(liveClaim,error){
 if len(b)==0||len(b)>1<<20{return liveClaim{},errors.New("live summary must be 1..1048576 bytes")}
 var c liveClaim
 d:=json.NewDecoder(bytes.NewReader(b));d.DisallowUnknownFields()
 if err:=d.Decode(&c);err!=nil{return liveClaim{},err}
 var trailing any
 if err:=d.Decode(&trailing);err!=io.EOF{return liveClaim{},errors.New("trailing JSON or second document")}
 return c,nil
}
func screenLive(c liveClaim)(liveGate,error){
 if c.Schema!="serving-fanout-g2-screen/v1" || !lowerHex(c.SourceSHA,40) ||
  !lowerHex(c.ArtifactSHA256,64) || !lowerHex(c.ModelDigest,64) {
  return liveGate{},errors.New("unsupported schema or source/artifact/model digest")
 }
 if c.EvidenceClass!="PUBLIC_CPU_DIRECT_INFERENCE" &&
  c.EvidenceClass!="PUBLIC_CPU_CONFIGURED_AGENT" &&
  c.EvidenceClass!="SEPARATELY_ADMITTED_SOVEREIGN_HIL" {
  return liveGate{},fmt.Errorf("unknown evidence class %q",c.EvidenceClass)
 }
 if c.AttemptedTasks<0||c.VerifiedTasks<0||c.VerifiedTasks>c.AttemptedTasks||
  c.TaskClasses<0||c.HostReplications<0||c.RepsPerCondition<0||c.AdmissionViolations<0{
  return liveGate{},errors.New("impossible counters")
 }
 if c.VerifiedTasks>0&&!c.IndependentTaskOracle{
  return liveGate{},errors.New("reported task success has no independent task oracle")
 }
 r:=liveGate{AutomaticPromotion:"NEVER",OriginAuthentication:"NOT_PERFORMED_ON_SUMMARY_METADATA"}
 if c.AdmissionViolations>0{
  r.Decision="REJECT_ADMISSION_INVARIANT"
  r.Reasons=[]string{"recorded_queue_or_tenant_capacity_counterexample"}
  return r,nil
 }
 if c.AttemptedTasks>c.VerifiedTasks{
  r.Decision="REJECT_TASK_QUALITY"
  r.Reasons=[]string{"independent_task_oracle_rejected_attempted_work"}
  return r,nil
 }
 reasons:=[]string{}
 if c.EvidenceClass!="SEPARATELY_ADMITTED_SOVEREIGN_HIL"||!c.PhysicalHostAdmitted{
  reasons=append(reasons,"no_admitted_sovereign_host_measurements")
 }
 if c.AttemptedTasks==0||!c.IndependentTaskOracle {
  reasons=append(reasons,"validated_task_goodput_unknown")
 }
 if c.TaskClasses<2 {reasons=append(reasons,"task_class_coverage_insufficient")}
 if c.HostReplications<3||c.RepsPerCondition<10 {
  reasons=append(reasons,"independent_replications_insufficient")
 }
 if !c.StreamingTTFTObserved {reasons=append(reasons,"true_streaming_ttft_unknown")}
 if !c.MeasuredMemoryPressure {reasons=append(reasons,"physical_pressure_unknown")}
 if !c.ModelArtifactAdmitted {reasons=append(reasons,"model_artifact_unadmitted")}
 if !c.TenantIdentityVerified||!c.BackendBypassClosed {
  reasons=append(reasons,"tenant_identity_or_backend_bypass_unknown")
 }
 if len(reasons)>0 {
  r.Decision="INSUFFICIENT_EVIDENCE"
  r.Reasons=reasons
 }else{
  // Metadata alone cannot authenticate artifact bytes, nor authorize release.
  r.Decision="ELIGIBLE_FOR_INDEPENDENT_REVIEW_ONLY"
  r.Reasons=[]string{"source_authentication_and_governed_reliability_review_required"}
 }
 return r,nil
}
func readLive(path string)(liveClaim,error){
 data,err:=os.ReadFile(path);if err!=nil{return liveClaim{},err}
 return decodeLive(data)
}
