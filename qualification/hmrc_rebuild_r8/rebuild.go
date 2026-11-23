// Package rebuild is a deterministic context/data projection adapter over
// existing HMRC R0 compaction, R2 source custody and R7 durable tool intent.
// It is NOT a new memory manager, model harness or system prompt author.
// All source content remains data; no retrieved text may gain instruction role.
package rebuild

import (
 "crypto/sha256"
 "encoding/hex"
 "encoding/json"
 "errors"
 "strings"

 hmrc "example.com/sempersupra/hmrc-r0"
 evidence "example.com/sempersupra/hmrc-evidence-r2"
 intent "example.com/sempersupra/hmrc-intent-r7"
)

var ErrInvalid=errors.New("invalid snapshot, source or active transcript")
var ErrHold=errors.New("unresolved tool effect or missing acknowledged checkpoint")
type Segment struct {
 Role string `json:"role"`
 UnitID string `json:"unit_id"`
 SourceID string `json:"source_id"`
 SourceDigest string `json:"source_digest"`
 Content string `json:"content"`
}
type EvictedRef struct {
 UnitID string `json:"unit_id"`
 SourceID string `json:"source_id"`
 Digest string `json:"digest"`
 Generation uint64 `json:"generation"`
}
type Projection struct {
 Schema string `json:"schema"`
 Scope string `json:"scope"`
 Generation uint64 `json:"generation"`
 ToolIntentID string `json:"tool_intent_id"`
 ToolIntentState string `json:"tool_intent_state"`
 ProtectedData []Segment `json:"protected_data"`
 ActiveToolData []Segment `json:"active_tool_data"`
 AdvisoryData []Segment `json:"advisory_data"`
 EvictedSourceRefs []EvictedRef `json:"evicted_source_refs"`
 EngineKVAdvice string `json:"engine_kv_advice"`
 SystemMessageFromMemory bool `json:"system_message_from_memory"`
}
func digest(b []byte) string {
 h:=sha256.Sum256(b)
 return "sha256:"+hex.EncodeToString(h[:])
}
func accepted(c evidence.Catalog, id, scope, hash string, isProtected bool) (evidence.Source,bool) {
 for _,src:=range c.Records{
  if src.ID!=id || src.Scope!=scope || src.Status=="superseded" {continue}
  if isProtected&&src.Status!="accepted"{return evidence.Source{},false}
  if digest(src.Bytes)!=hash{return evidence.Source{},false}
  return src,true
 }
 return evidence.Source{},false
}
// Build is source/transaction read-only. The journal must already own an
// admitted single-writer lease, and its authoritative ACK must have been
// reconciled against an actual tool witness outside this adapter.
// Caller-provided immutable source catalog and active transcript are trust
// inputs needing their own production authentication, not model testimony.
func Build(s hmrc.Snapshot,c evidence.Catalog,j *intent.Journal,activeTranscript []byte)(Projection,error){
 if j==nil||s.Schema!="hmrc-r0"||s.Generation==0||s.Scope==""||
   s.OpenToolTransactions!=0{return Projection{},ErrHold}
 if len(activeTranscript)==0||len(activeTranscript)>4096{return Projection{},ErrInvalid}
 if e:=evidence.Verify(s,c);e!=nil{return Projection{},ErrInvalid}
 tx,e:=j.Recover()
 if e!=nil||tx.State!=intent.Acked||tx.Scope!=s.Scope||tx.Generation<3{
  return Projection{},ErrHold
 }
 p:=Projection{
  Schema:"hmrc-r8-source-bound-data-reconstruction",
  Scope:s.Scope,Generation:s.Generation,ToolIntentID:tx.ID,
  ToolIntentState:tx.State,
  ProtectedData:[]Segment{},ActiveToolData:[]Segment{},
  AdvisoryData:[]Segment{},EvictedSourceRefs:[]EvictedRef{},
  EngineKVAdvice:"engine-owns-physical-kv",SystemMessageFromMemory:false,
 }
 seen:=map[string]bool{}
 ownerMatch:=false
 for _,u:=range s.Units {
  if u.ID==""||seen[u.ID]||u.Scope!=s.Scope||u.Tokens<=0{
   return Projection{},ErrInvalid
  }
  seen[u.ID]=true
  switch u.Kind {
  case "protected":
   src,ok:=accepted(c,u.SourceID,s.Scope,u.SourceDigest,true)
   if !ok{return Projection{},ErrInvalid}
   if u.SourceDigest==tx.SourceDigest{ownerMatch=true}
   p.ProtectedData=append(p.ProtectedData,Segment{
    Role:"protected-source-data",UnitID:u.ID,SourceID:u.SourceID,
    SourceDigest:u.SourceDigest,Content:string(src.Bytes)})
  case "active":
   if u.SourceID!=tx.ID||u.SourceDigest!=digest(activeTranscript){
    return Projection{},ErrInvalid
   }
   p.ActiveToolData=append(p.ActiveToolData,Segment{
    Role:"active-tool-transcript-data",UnitID:u.ID,SourceID:u.SourceID,
    SourceDigest:u.SourceDigest,Content:string(activeTranscript)})
  case "historical":
   // Unverified historical memory is NOT reconstructed as usable context.
   if !u.Verified{continue}
   src,ok:=accepted(c,u.SourceID,s.Scope,u.SourceDigest,false)
   if !ok{return Projection{},ErrInvalid}
   p.AdvisoryData=append(p.AdvisoryData,Segment{
    Role:"untrusted-retrieved-history-data",UnitID:u.ID,SourceID:u.SourceID,
    SourceDigest:u.SourceDigest,Content:string(src.Bytes)})
  default: return Projection{},ErrInvalid
  }
 }
 if !ownerMatch||len(p.ProtectedData)==0||len(p.ActiveToolData)!=1{
  return Projection{},ErrInvalid
 }
 for _,ev:=range s.Evicted{
  if ev.ID==""||seen[ev.ID]||ev.AtGeneration<2||ev.AtGeneration>s.Generation{
   return Projection{},ErrInvalid
  }
  src,ok:=accepted(c,ev.SourceID,s.Scope,ev.SourceDigest,false)
  if !ok||len(src.Bytes)==0{return Projection{},ErrInvalid}
  seen[ev.ID]=true
  p.EvictedSourceRefs=append(p.EvictedSourceRefs,EvictedRef{
    UnitID:ev.ID,SourceID:ev.SourceID,Digest:ev.SourceDigest,Generation:ev.AtGeneration})
 }
 if strings.Contains(strings.Join([]string{p.ProtectedData[0].Role,
     p.ActiveToolData[0].Role}," "), "system"){return Projection{},ErrInvalid}
 return p,nil
}
func Canonical(p Projection)([]byte,error){
 if p.Schema!="hmrc-r8-source-bound-data-reconstruction"||
   p.EngineKVAdvice!="engine-owns-physical-kv"||p.SystemMessageFromMemory{
  return nil,ErrInvalid
 }
 return json.Marshal(p)
}
