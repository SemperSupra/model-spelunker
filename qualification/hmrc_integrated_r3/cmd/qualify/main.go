// A single disposable, public-source native integration run (issue #306).
// Measured model residency from Ollama, source-backed checkpoint/compaction
// from HMRC, then separately model-backed memory reconstruction.
// The 1000-token policy cap is SYNTHETIC and is NOT the real model limit.
package main

import (
  "context"
  "crypto/sha256"
  "encoding/hex"
  "encoding/json"
  "errors"
  "flag"
  "fmt"
  "os"
  "reflect"
  "strings"

  evidence "example.com/sempersupra/hmrc-evidence-r2"
  join "example.com/sempersupra/hmrc-join-r0"
  hmrc "example.com/sempersupra/hmrc-r0"
  telemetry "example.com/sempersupra/hmrc-telemetry-r0"
)

const modelID="qwen3:1.7b"
const pinnedModelDigest="8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7"
const syntheticCapacity=1000

type doc struct {
 ID string `json:"id"`
 Project string `json:"project"`
 Authority string `json:"authority"`
 Text string `json:"text"`
}

type fixture struct {
 Schema string `json:"schema"`
 Corpus []doc `json:"corpus"`
}

type receipt struct {
 Schema string `json:"schema"`
 NativeModelTelemetry bool `json:"native_model_telemetry"`
 PinnedModelIdentity bool `json:"pinned_model_identity"`
 Model string `json:"model"`
 RuntimeContextTokens int `json:"runtime_context_tokens"`
 PolicyContextCap int `json:"policy_context_cap_synthetic"`
 BeforeGeneration uint64 `json:"before_generation"`
 AfterGeneration uint64 `json:"after_generation"`
 Compacted bool `json:"compacted"`
 ProtectedSurvived bool `json:"protected_survived"`
 EvictedSourceIDs []string `json:"evicted_source_ids"`
 SourceSHA256 []string `json:"evicted_source_sha256"`
 RecoveryVerified bool `json:"recovery_verified"`
 NativeModelInferenceExecuted bool `json:"native_model_inference_executed"`
 PhysicalKVCacheQualified bool `json:"physical_kv_cache_qualified"`
 FullAgentTaskQualified bool `json:"full_agent_task_qualified"`
}

func sha(b []byte) string {
 d:=sha256.Sum256(b)
 return "sha256:"+hex.EncodeToString(d[:])
}

func loadState(path string) (hmrc.Snapshot,evidence.Catalog,error) {
 raw,err:=os.ReadFile(path)
 if err!=nil{return hmrc.Snapshot{},evidence.Catalog{},err}
 var f fixture
 if err=json.Unmarshal(raw,&f);err!=nil{return hmrc.Snapshot{},evidence.Catalog{},err}
 if f.Schema!="synthetic-dle-cpe-memory-v1" || len(f.Corpus)!=8 {
   return hmrc.Snapshot{},evidence.Catalog{},errors.New("invalid public synthetic fixture")
 }
 items:=make(map[string]doc)
 sources:=evidence.Catalog{}
 for _,d:=range f.Corpus {
  if d.ID=="" || items[d.ID].ID!="" {return hmrc.Snapshot{},evidence.Catalog{},errors.New("duplicate source")}
  items[d.ID]=d
  if d.Project=="atlas" {
   sources.Records=append(sources.Records,evidence.Source{ID:d.ID,Scope:"atlas",Status:d.Authority,Bytes:[]byte(d.Text)})
  }
 }
 ids:=[]string{"SYN_ATLAS_DLE_R8_HOLD","SYN_ATLAS_DLE_R8_NEXT","SYN_ATLAS_CPE_R5_BLUE","SYN_ATLAS_SKILL_R2_OPAV"}
 sizes:=[]int{150,180,160,140}
 s:=hmrc.Snapshot{Schema:"hmrc-r0",Scope:"atlas",Generation:1,EffectiveCapacity:syntheticCapacity}
 s.Units=append(s.Units,hmrc.Unit{
   ID:"protected",Scope:"atlas",Kind:"protected",Tokens:sizes[0],
   SourceID:ids[0],SourceDigest:sha([]byte(items[ids[0]].Text)),Verified:true,Sequence:1,
 })
 s.Units=append(s.Units,hmrc.Unit{ID:"active",Scope:"atlas",Kind:"active",Tokens:220,Sequence:2})
 for i:=1;i<len(ids);i++ {
   d,ok:=items[ids[i]]
   if !ok || d.Project!="atlas" {return hmrc.Snapshot{},evidence.Catalog{},errors.New("missing Atlas source")}
   s.Units=append(s.Units,hmrc.Unit{
      ID:fmt.Sprintf("history-%d",i),Scope:"atlas",Kind:"historical",Tokens:sizes[i],
      SourceID:ids[i],SourceDigest:sha([]byte(d.Text)),Verified:true,Sequence:uint64(i+2),
   })
 }
 if items[ids[0]].Authority!="accepted" {return hmrc.Snapshot{},evidence.Catalog{},errors.New("unaccepted protected authority")}
 if err=evidence.Verify(s,sources);err!=nil{return hmrc.Snapshot{},evidence.Catalog{},err}
 return s,sources,nil
}

func run(s hmrc.Snapshot,cat evidence.Catalog,obs telemetry.Observation,statePath string) (receipt,error) {
 var m *telemetry.Model
 for i:=range obs.Models {
    if obs.Models[i].Name==modelID {
        if m!=nil {return receipt{},join.ErrUnbound}
        m=&obs.Models[i]
    }
 }
 if m==nil || strings.TrimPrefix(m.Digest,"sha256:")!=pinnedModelDigest {
   return receipt{},join.ErrUnbound
 }
 b:=join.Binding{Engine:"ollama",ModelID:modelID,ExactArtifactDigest:m.Digest,ApprovedContextLimit:syntheticCapacity}
 forecast:=hmrc.Forecast{NextTurnTokens:60,ReserveTokens:60}
 advice,err:=join.Advise(s,forecast,obs,b)
 if err!=nil{return receipt{},err}
 if !advice.Plan.Compact || advice.BoundedContextTokens!=syntheticCapacity {
    return receipt{},errors.New("unexpected policy cap or no compaction")
 }
 session,err:=evidence.Open(statePath,cat,&s)
 if err!=nil{return receipt{},err}
 proposed,err:=session.Propose(forecast)
 if err!=nil {session.Close();return receipt{},err}
 if !reflect.DeepEqual(advice.Plan,proposed) {
    session.Close();return receipt{},errors.New("runtime policy and guarded policy disagree")
 }
 after,err:=session.Apply(proposed)
 if err!=nil {session.Close();return receipt{},err}
 if err:=session.Close();err!=nil{return receipt{},err}
 restart,err:=evidence.Open(statePath,cat,nil)
 if err!=nil{return receipt{},err}
 recovered,err:=restart.Read()
 if err!=nil {restart.Close();return receipt{},err}
 if err:=restart.Close();err!=nil{return receipt{},err}
 if recovered.Generation!=after.Generation || recovered.Generation!=s.Generation+1 ||
      !reflect.DeepEqual(recovered.Evicted,after.Evicted) {
    return receipt{},errors.New("recovery evidence mismatch")
 }
 protected:=false
 for _,u:=range recovered.Units {
    if u.ID=="protected" && u.SourceID=="SYN_ATLAS_DLE_R8_HOLD" {protected=true}
 }
 if !protected || len(after.Evicted)!=2 {
    return receipt{},errors.New("protected context lost or unexpected eviction count")
 }
 r:=receipt{
  Schema:"hmrc-r3-native-joined-public",NativeModelTelemetry:true,
  PinnedModelIdentity:true,Model:modelID,
  RuntimeContextTokens:advice.ReportedRuntimeContextTokens,
  PolicyContextCap:syntheticCapacity,BeforeGeneration:s.Generation,
  AfterGeneration:recovered.Generation,Compacted:true,
  ProtectedSurvived:protected,RecoveryVerified:true,
  NativeModelInferenceExecuted:false,PhysicalKVCacheQualified:false,
  FullAgentTaskQualified:false,
 }
 for _,e:=range recovered.Evicted {
    r.EvictedSourceIDs=append(r.EvictedSourceIDs,e.SourceID)
    r.SourceSHA256=append(r.SourceSHA256,e.SourceDigest)
 }
 if !reflect.DeepEqual(r.EvictedSourceIDs,[]string{"SYN_ATLAS_DLE_R8_NEXT","SYN_ATLAS_CPE_R5_BLUE"}) {
    return receipt{},errors.New("incorrect evidence lifecycle targets")
 }
 return r,nil
}

func main(){
 fixturePath:=flag.String("fixture","../fixtures/memory_dle_cpe_synthetic_v1.json","public synthetic source only")
 statePath:=flag.String("state","","disposable externalized state")
 out:=flag.String("out","","receipt")
 flag.Parse()
 if *statePath==""||*out=="" {fmt.Fprintln(os.Stderr,"state/out required");os.Exit(2)}
 s,c,err:=loadState(*fixturePath)
 if err!=nil {fmt.Fprintln(os.Stderr,err);os.Exit(2)}
 obs,err:=telemetry.Probe(context.Background(),nil,telemetry.Config{
    Engine:"ollama",BaseURL:"http://127.0.0.1:11434",
 })
 if err!=nil {fmt.Fprintln(os.Stderr,err);os.Exit(2)}
 receipt,err:=run(s,c,obs,*statePath)
 if err!=nil {fmt.Fprintln(os.Stderr,err);os.Exit(2)}
 f,err:=os.Create(*out)
 if err!=nil {fmt.Fprintln(os.Stderr,err);os.Exit(2)}
 if err:=json.NewEncoder(f).Encode(receipt);err!=nil {f.Close();fmt.Fprintln(os.Stderr,err);os.Exit(2)}
 if err:=f.Close();err!=nil {fmt.Fprintln(os.Stderr,err);os.Exit(2)}
 fmt.Printf("NATIVE_MODEL_CTX=%d, SYNTHETIC_POLICY_CAP=%d, EVICITED_EVIDENCE=%d, RECOVERY_VERIFIED=YES
",
   receipt.RuntimeContextTokens,receipt.PolicyContextCap,len(receipt.EvictedSourceIDs))
 fmt.Println("MODEL_INFERENCE=NOT_RUN_BY_GO; PHYSICAL_KV_CACHE=UNKNOWN; FULL_AGENT_TASK=NOT_RUN")
}
