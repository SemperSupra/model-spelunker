// Package join composes an independently admitted harness context projection
// with read-only native inference-server telemetry. It returns advisory plans,
// never performs tool, memory, model, routing, or KV cache actions.
package join

import (
    "errors"
    "fmt"

    hmrc "example.com/sempersupra/hmrc-r0"
    telemetry "example.com/sempersupra/hmrc-telemetry-r0"
)

var ErrUnbound=errors.New("model/runtime evidence unavailable, ambiguous or mismatched")

type Binding struct {
    Engine string
    ModelID string
    ExactArtifactDigest string
    ApprovedContextLimit int
}

type Advice struct {
    Schema string
    Binding Binding
    ReportedRuntimeContextTokens int
    BoundedContextTokens int
    RequiresHarnessApproval bool
    PhysicalKVCacheOwner string
    Plan hmrc.Decision
}

// Advise fails closed on UNKNOWN, mismatched or duplicate model residency.
// Both runtime capacity and separately approved budget bound the harness plan.
// It does not infer token occupancy from KV utilization, nor declare model
// execution authority. The caller must independently ensure telemetry freshness.
func Advise(s hmrc.Snapshot, f hmrc.Forecast, o telemetry.Observation, b Binding) (Advice,error) {
    if b.Engine!="ollama" || o.Schema!="hmrc-telemetry-r0" ||
        o.Engine!=b.Engine || o.SourcePath!="/api/ps" ||
        b.ModelID=="" || b.ExactArtifactDigest=="" ||
        b.ApprovedContextLimit<=0 || s.EffectiveCapacity<=0 {
        return Advice{},ErrUnbound
    }
    var selected *telemetry.Model
    for i:=range o.Models {
        model:=&o.Models[i]
        if model.Name==b.ModelID {
            if selected!=nil {return Advice{},ErrUnbound}
            selected=model
        }
    }
    if selected==nil || selected.Digest!=b.ExactArtifactDigest ||
        selected.ReportedContextTokens==nil || *selected.ReportedContextTokens<=0 {
        return Advice{},ErrUnbound
    }
    effective:=s.EffectiveCapacity
    if effective>b.ApprovedContextLimit {effective=b.ApprovedContextLimit}
    if effective>*selected.ReportedContextTokens {effective=*selected.ReportedContextTokens}
    s.EffectiveCapacity=effective
    plan,err:=hmrc.Propose(s,f)
    if err!=nil {return Advice{},fmt.Errorf("source-scoped policy: %w",err)}
    return Advice{
        Schema:"hmrc-join-r0",Binding:b,
        ReportedRuntimeContextTokens:*selected.ReportedContextTokens,
        BoundedContextTokens:effective,
        RequiresHarnessApproval:plan.Compact,
        PhysicalKVCacheOwner:"serving-engine",
        Plan:plan,
    },nil
}
