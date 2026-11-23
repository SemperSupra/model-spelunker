// Package compassbinding joins supplied synthetic artifact and actor evidence.
// It does not call Agent Dispatch, contact models, authorize tools, or own a registry.
package compassbinding

import (
    "fmt"
    "regexp"
    "strings"
    "time"
)

var digestRE = regexp.MustCompile(`^sha256:[0-9a-f]{64}$`)

type Artifact struct {
    Kind string `json:"kind"`
    Digest string `json:"digest"`
}
type Observed struct {
    Alias string `json:"alias"`
    Artifact Artifact `json:"artifact"`
    FileSHA256 string `json:"file_sha256"`
    Installed bool `json:"installed"`
    Loaded bool `json:"loaded"`
    InUse bool `json:"in_use"`
    Runtime string `json:"runtime"`
    RuntimeVersion string `json:"runtime_version"`
    ConfigDigest string `json:"config_digest"`
    HostProfileDigest string `json:"host_profile_digest"`
    Harness string `json:"harness"`
    HarnessVersion string `json:"harness_version"`
    ToolProfileDigest string `json:"tool_profile_digest"`
    TaskClass string `json:"task_class"`
    ProcessGeneration string `json:"process_generation"`
    AttestedGeneration string `json:"attested_generation"`
}
type Registry struct {
    Artifact Artifact `json:"artifact"`
    FileSHA256 string `json:"file_sha256"`
    Status string `json:"status"`
    EvidenceRef string `json:"evidence_ref"`
}
type Interview struct {
    Artifact Artifact `json:"artifact"`
    Runtime string `json:"runtime"`
    RuntimeVersion string `json:"runtime_version"`
    ConfigDigest string `json:"config_digest"`
    HostProfileDigest string `json:"host_profile_digest"`
    Harness string `json:"harness"`
    HarnessVersion string `json:"harness_version"`
    ToolProfileDigest string `json:"tool_profile_digest"`
    TaskClass string `json:"task_class"`
    Outcome string `json:"outcome"`
    ExpiresAt string `json:"expires_at"`
    EvidenceRef string `json:"evidence_ref"`
}
type Input struct {
    Mode string `json:"mode"` // direct or managed; AD optional only in managed mode
    Observed Observed `json:"observed"`
    Registry *Registry `json:"registry"`
    Interview *Interview `json:"interview"`
    Admission *bool `json:"admission"`
}
type Decision struct {
    Presence string `json:"presence"`
    Identity string `json:"identity"`
    Approval string `json:"approval"`
    Qualification string `json:"qualification"`
    Admission string `json:"admission"`
    Eligible bool `json:"eligible"`
    Reasons []string `json:"reasons"`
}
func validArtifact(a Artifact) bool { return (a.Kind=="oci" || a.Kind=="content-manifest") && digestRE.MatchString(a.Digest) }
func sameArtifact(a,b Artifact) bool {return validArtifact(a)&&validArtifact(b)&&a.Kind==b.Kind&&a.Digest==b.Digest}
func validHash(h string) bool {return digestRE.MatchString("sha256:"+h)}
func complete(o Observed,r Interview) bool {
    fields:=[]string{o.Runtime,o.RuntimeVersion,o.ConfigDigest,o.HostProfileDigest,o.Harness,o.HarnessVersion,o.ToolProfileDigest,o.TaskClass,r.Runtime,r.RuntimeVersion,r.ConfigDigest,r.HostProfileDigest,r.Harness,r.HarnessVersion,r.ToolProfileDigest,r.TaskClass}
    for _,s:=range fields {if strings.TrimSpace(s)=="" {return false}}
    return true
}
func sameBinding(o Observed,r Interview) bool {
    return sameArtifact(o.Artifact,r.Artifact)&&o.Runtime==r.Runtime&&o.RuntimeVersion==r.RuntimeVersion&&o.ConfigDigest==r.ConfigDigest&&o.HostProfileDigest==r.HostProfileDigest&&o.Harness==r.Harness&&o.HarnessVersion==r.HarnessVersion&&o.ToolProfileDigest==r.ToolProfileDigest&&o.TaskClass==r.TaskClass
}
// Evaluate is a deterministic projection over supplied evidence, never live attestation.
// Callers must independently authenticate and validate all source evidence.
func Evaluate(in Input,now time.Time) Decision {
    d:=Decision{Presence:"UNKNOWN",Identity:"UNKNOWN",Approval:"UNKNOWN",Qualification:"UNKNOWN",Admission:"NOT_EVALUATED",Reasons:[]string{}}
    fail:=func(s string){d.Reasons=append(d.Reasons,s)}
    o:=in.Observed
    if !o.Installed {d.Presence="CONFIGURED_NOT_PRESENT"} else if o.InUse {d.Presence="OBSERVED_IN_USE"} else if o.Loaded {d.Presence="LOADED_NOT_USED"} else {d.Presence="PRESENT_NOT_LOADED"}
    if o.InUse && !o.Loaded {fail("in_use_without_loaded")}
    if !o.Installed||!validArtifact(o.Artifact)||!validHash(o.FileSHA256)||o.ProcessGeneration==""||o.AttestedGeneration==""||o.ProcessGeneration!=o.AttestedGeneration {
        d.Identity="UNKNOWN";fail("unverified_runtime_or_artifact")
    } else if in.Registry==nil {
        d.Identity="UNREGISTERED";fail("registry_missing")
    } else if !validArtifact(in.Registry.Artifact)||!validHash(in.Registry.FileSHA256) {
        d.Identity="UNKNOWN";fail("registry_identity_invalid")
    } else if !sameArtifact(o.Artifact,in.Registry.Artifact)||o.FileSHA256!=in.Registry.FileSHA256 {
        d.Identity="DIGEST_MISMATCH";fail("bytes_or_representation_differ")
    } else {d.Identity="VERIFIED_MATCH"}
    if in.Registry!=nil {switch in.Registry.Status {case "approved","privately_adopted":d.Approval="APPROVED";default:d.Approval="NOT_APPROVED";fail("artifact_not_approved")}}
    if in.Interview==nil {d.Qualification="UNQUALIFIED";fail("interview_missing")
    } else if !complete(o,*in.Interview)||!sameBinding(o,*in.Interview) {d.Qualification="MISMATCH";fail("interview_binding_mismatch")
    } else if in.Interview.Outcome!="PASS" {d.Qualification="NOT_QUALIFIED";fail("interview_not_pass")
    } else if t,err:=time.Parse(time.RFC3339,in.Interview.ExpiresAt);err!=nil||!now.Before(t) {d.Qualification="STALE";fail("interview_expired")
    } else {d.Qualification="QUALIFIED"}
    switch in.Mode {
    case "direct": d.Admission="NOT_REQUIRED_FOR_DIRECT_MODEL_ACCESS"
    case "managed": if in.Admission!=nil&&*in.Admission {d.Admission="GRANTED"} else {d.Admission="NOT_GRANTED";fail("managed_route_not_admitted")}
    default: d.Admission="INVALID_MODE";fail("mode_invalid")
    }
    d.Eligible=d.Presence!="CONFIGURED_NOT_PRESENT"&&!(o.InUse&&!o.Loaded)&&d.Identity=="VERIFIED_MATCH"&&d.Approval=="APPROVED"&&d.Qualification=="QUALIFIED"&&(d.Admission=="GRANTED"||d.Admission=="NOT_REQUIRED_FOR_DIRECT_MODEL_ACCESS")
    if !d.Eligible&&len(d.Reasons)==0 {fail("requirements_not_satisfied")}
    return d
}
func ValidateDigest(ref Artifact) error {if !validArtifact(ref){return fmt.Errorf("invalid artifact identity kind or digest")};return nil}
