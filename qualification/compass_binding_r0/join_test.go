package compassbinding
import ("strings";"testing";"time")
const shaA="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
const shaB="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
func fixture() Input {
 a:=Artifact{Kind:"content-manifest",Digest:"sha256:"+shaA}
 o:=Observed{Alias:"not-an-identity",ObservationEvidenceRef:"synthetic-observation-r0",Artifact:a,FileSHA256:shaA,Installed:true,Loaded:true,InUse:true,Runtime:"ollama",RuntimeVersion:"0.test",ConfigDigest:shaA,HostProfileDigest:shaA,Harness:"goose",HarnessVersion:"1.test",ToolProfileDigest:shaA,TaskClass:"bugfix",ProcessGeneration:"g1",AttestedGeneration:"g1"}
 return Input{Mode:"direct",Observed:o,Registry:&Registry{Artifact:a,FileSHA256:shaA,Status:"privately_adopted",EvidenceRef:"synthetic-registry-r0"},Interview:&Interview{Artifact:a,Runtime:o.Runtime,RuntimeVersion:o.RuntimeVersion,ConfigDigest:o.ConfigDigest,HostProfileDigest:o.HostProfileDigest,Harness:o.Harness,HarnessVersion:o.HarnessVersion,ToolProfileDigest:o.ToolProfileDigest,TaskClass:o.TaskClass,Outcome:"PASS",EvidenceRef:"synthetic-interview-r0",ExpiresAt:"2030-01-01T00:00:00Z"}}
}
func TestDirectDoesNotRequireAgentDispatch(t *testing.T){d:=Evaluate(fixture(),time.Date(2026,11,23,0,0,0,0,time.UTC));if !d.Eligible||d.Admission!="NOT_REQUIRED_FOR_DIRECT_MODEL_ACCESS"{t.Fatalf("unexpected: %+v",d)}}
func TestFailClosedMutations(t *testing.T){
 now:=time.Date(2026,11,23,0,0,0,0,time.UTC)
 tests:=[]struct{name string;mutate func(*Input);identity,qualification string}{
 {"alias_same_bytes_differ",func(x *Input){x.Observed.FileSHA256=shaB},"DIGEST_MISMATCH","QUALIFIED"},
 {"wrong_identity_kind",func(x *Input){x.Registry.Artifact.Kind="oci"},"DIGEST_MISMATCH","QUALIFIED"},
 {"wrong_model_digest",func(x *Input){x.Observed.Artifact.Digest="sha256:"+shaB},"DIGEST_MISMATCH","MISMATCH"},
 {"missing_registry",func(x *Input){x.Registry=nil},"UNREGISTERED","QUALIFIED"},
 {"different_quant_template_config",func(x *Input){x.Observed.ConfigDigest=shaB},"VERIFIED_MATCH","MISMATCH"},
 {"different_harness",func(x *Input){x.Observed.Harness="opencode"},"VERIFIED_MATCH","MISMATCH"},
 {"stale_interview",func(x *Input){x.Interview.ExpiresAt="2020-01-01T00:00:00Z"},"VERIFIED_MATCH","STALE"},
 {"negative_interview",func(x *Input){x.Interview.Outcome="FAIL"},"VERIFIED_MATCH","NOT_QUALIFIED"},
 {"restarted_process",func(x *Input){x.Observed.ProcessGeneration="g2"},"UNKNOWN","QUALIFIED"},
 {"untrusted_hash_shape",func(x *Input){x.Observed.FileSHA256="not-a-sha"},"UNKNOWN","QUALIFIED"},
 {"not_approved",func(x *Input){x.Registry.Status="candidate"},"VERIFIED_MATCH","QUALIFIED"},
 {"missing_qual",func(x *Input){x.Interview=nil},"VERIFIED_MATCH","UNQUALIFIED"},
 {"uninstalled",func(x *Input){x.Observed.Installed=false},"UNKNOWN","QUALIFIED"},
 {"inconsistent_usage",func(x *Input){x.Observed.Loaded=false},"VERIFIED_MATCH","QUALIFIED"},
 {"missing_join_dimension",func(x *Input){x.Observed.ToolProfileDigest=""},"VERIFIED_MATCH","MISMATCH"},
 {"missing_observation_evidence",func(x *Input){x.Observed.ObservationEvidenceRef=""},"UNKNOWN","QUALIFIED"},
 {"missing_registry_evidence",func(x *Input){x.Registry.EvidenceRef=""},"UNKNOWN","QUALIFIED"},
 {"missing_interview_evidence",func(x *Input){x.Interview.EvidenceRef=""},"VERIFIED_MATCH","MISMATCH"},
 {"malformed_config_digest",func(x *Input){x.Observed.ConfigDigest="garbage";x.Interview.ConfigDigest="garbage"},"VERIFIED_MATCH","MISMATCH"},
 }
 for _,tt:=range tests {t.Run(tt.name,func(t *testing.T){in:=fixture();tt.mutate(&in);d:=Evaluate(in,now);if d.Eligible||d.Identity!=tt.identity||d.Qualification!=tt.qualification{t.Fatalf("not fail-closed: %+v",d)}})}
}
func TestManagedNeedsSeparateAdmission(t *testing.T){in:=fixture();in.Mode="managed";d:=Evaluate(in,time.Date(2026,11,23,0,0,0,0,time.UTC));if d.Eligible||d.Admission!="NOT_GRANTED"{t.Fatal(d)};yes:=true;in.Admission=&yes;if d=Evaluate(in,time.Date(2026,11,23,0,0,0,0,time.UTC));!d.Eligible||d.Admission!="GRANTED"{t.Fatal(d)}}
func TestUnknownModeAndNoImplicitFallback(t *testing.T){in:=fixture();in.Mode="unexpected";d:=Evaluate(in,time.Now());if d.Eligible||d.Admission!="INVALID_MODE"{t.Fatal(d)}}
func TestOpaqueAliasNoAuthority(t *testing.T){in:=fixture();in.Observed.Alias=strings.Repeat("approved",20);in.Registry=nil;d:=Evaluate(in,time.Date(2026,11,23,0,0,0,0,time.UTC));if d.Eligible{t.Fatal(d)}}
