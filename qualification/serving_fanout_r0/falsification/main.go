// Finite-state synthetic reliability oracle. Not a deployed queue or authorization service.
package main

import (
 "encoding/json"
 "errors"
 "fmt"
 "os"
)

type state struct {
 Durable bool
 Acked bool
 Authorized bool
 Qualified bool
 Generation int
 Lease int
 EffectSeen bool
 Effects int
 Committed bool
}
type node struct{ State state; Trace []string }
type report struct {
 EvidenceClass string `json:"evidence_class"`
 Bound int `json:"bound"`
 VerifiedStates int `json:"verified_states"`
 VerifiedTransitions int `json:"verified_transitions"`
 SafeResult string `json:"safe_result"`
 UnsafeResult string `json:"unsafe_result"`
 UnsafeCounterexample []string `json:"unsafe_counterexample"`
 Assumptions []string `json:"assumptions"`
}
var operations=[]string{"admit","start","effect","commit","crash","revoke","restore","drift","wrong_tenant"}

func initial() state {return state{Authorized:true,Qualified:true,Generation:1}}

// step is a reference model of one job, not the implementation of a scheduling service.
// Durable models a persisted acknowledgment log. EffectSeen models a persistent
// idempotency key at the actual side-effect boundary (not only at the agent).
func step(s state, op string, downstreamDedupe bool) state {
 switch op {
 case "admit":
  if s.Authorized&&s.Qualified&&!s.Durable {s.Durable=true;s.Acked=true}
 case "start":
  if s.Durable&&s.Authorized&&s.Qualified&&!s.Committed {s.Lease=s.Generation}
 case "effect":
  if s.Durable&&s.Authorized&&s.Qualified&&!s.Committed&&s.Lease==s.Generation {
   if !s.EffectSeen || !downstreamDedupe {s.Effects++}
   s.EffectSeen=true
  }
 case "commit":
  if s.Durable&&s.Authorized&&s.Qualified&&s.Lease==s.Generation&&s.EffectSeen {
   s.Committed=true;s.Lease=0
  }
 case "crash":
  s.Generation++;s.Lease=0
 case "revoke":
  s.Authorized=false;s.Lease=0
 case "restore":
  // Explicit synthetic authority action; never inferred from a health check.
  s.Authorized=true;s.Qualified=true;s.Lease=0
 case "drift":
  s.Qualified=false;s.Lease=0
 case "wrong_tenant":
  // Scoped handles cannot act on a job belonging to another tenant.
 }
 return s
}
func invariant(s state) error {
 if s.Acked&&!s.Durable {return errors.New("acknowledged job lacks durable record")}
 if s.Effects>1 {return errors.New("duplicate consequential effect")}
 if s.Effects>0&&!s.Durable {return errors.New("effect without durable admitted record")}
 if s.EffectSeen&&s.Effects==0 {return errors.New("effect key without actual effect")}
 if s.Committed&&(!s.Durable||!s.EffectSeen) {return errors.New("completion without durable effect")}
 if s.Lease!=0&&(s.Lease!=s.Generation||!s.Authorized||!s.Qualified) {
  return errors.New("stale lease or invalid authorization/identity")
 }
 return nil
}
// boundedCheck explores every reachable state/transition up to 'depth'; state merging
// is sound here because the transition relation and checked invariants are Markovian.
func boundedCheck(depth int, dedupe bool) (int,int,[]string,error) {
 if depth<1||depth>12 {return 0,0,nil,errors.New("depth outside bounded model")}
 frontier:=[]node{{State:initial()}}
 visited:=map[state]bool{initial():true}
 transitions:=0
 for d:=0;d<depth;d++ {
  next:=[]node{}
  for _,n:=range frontier {
   for _,op:=range operations {
    transitions++
    stateAfter:=step(n.State,op,dedupe)
    trace:=append(append([]string(nil),n.Trace...),op)
    if err:=invariant(stateAfter);err!=nil {return len(visited),transitions,trace,fmt.Errorf("counterexample %v: %w",trace,err)}
    if !visited[stateAfter] {visited[stateAfter]=true;next=append(next,node{State:stateAfter,Trace:trace})}
   }
  }
  frontier=next
  if len(frontier)==0 {break}
 }
 return len(visited),transitions,nil,nil
}
func main(){
 const bound=9
 safeStates,safeTransitions,_,safeErr:=boundedCheck(bound,true)
 if safeErr!=nil {fmt.Fprintln(os.Stderr,safeErr);os.Exit(1)}
 _,_,unsafeTrace,unsafeErr:=boundedCheck(bound,false)
 if unsafeErr==nil {fmt.Fprintln(os.Stderr,"expected unsafe duplicate-effect counterexample missing");os.Exit(1)}
 r:=report{
  EvidenceClass:"SYNTHETIC_FINITE_STATE_NOT_PRODUCTION",Bound:bound,
  VerifiedStates:safeStates,VerifiedTransitions:safeTransitions,
  SafeResult:"NO_COUNTEREXAMPLE_WITHIN_BOUND",
  UnsafeResult:"COUNTEREXAMPLE_FOUND",
  UnsafeCounterexample:unsafeTrace,
  Assumptions:[]string{
   "Durable append precedes acknowledgment and survives worker crash",
   "The actual side-effect destination enforces a persistent tenant-scoped idempotency key",
   "Authority and exact model identity are checked at admission and execution",
   "Lease generations are fenced and stale leases are rejected",
   "No storage corruption, network partition, Byzantine actor, or concurrent unrelated job is modeled",
  },
 }
 e:=json.NewEncoder(os.Stdout);e.SetIndent("","  ")
 if err:=e.Encode(r);err!=nil {fmt.Fprintln(os.Stderr,err);os.Exit(1)}
}
