// Independent synthetic-receipt verifier/reducer; does not implement the simulator.
package main

import (
 "bytes"
 "encoding/hex"
 "encoding/json"
 "errors"
 "flag"
 "fmt"
 "io"
 "math"
 "os"
 "sort"
)

type observation struct {
 ID string `json:"id"`
 Kind string `json:"kind"`
 Arrival int `json:"arrival_tick"`
 Started int `json:"started_tick"`
 Finished int `json:"finished_tick"`
 Wait int `json:"queue_wait_ticks"`
}
type stats struct {
 Count int `json:"count"`
 P95QueueWait int `json:"p95_queue_wait_ticks"`
 Makespan int `json:"makespan_ticks"`
}
type receipt struct {
 Schema string `json:"schema"`
 EvidenceClass string `json:"evidence_class"`
 Policy string `json:"policy"`
 FixtureSHA256 string `json:"fixture_sha256"`
 Slots int `json:"slots"`
 ReservedInteractive int `json:"reserved_interactive"`
 Interactive stats `json:"interactive"`
 Batch stats `json:"batch"`
 Observations []observation `json:"observations"`
}
type comparison struct {
 EvidenceClass string `json:"evidence_class"`
 BaselinePolicy string `json:"baseline_policy"`
 CandidatePolicy string `json:"candidate_policy"`
 FixtureSHA256 string `json:"fixture_sha256"`
 MatchedTaskIDs int `json:"matched_task_ids"`
 InteractiveSamples int `json:"interactive_samples"`
 BaselineInteractiveP95Wait int `json:"baseline_interactive_p95_wait_ticks"`
 CandidateInteractiveP95Wait int `json:"candidate_interactive_p95_wait_ticks"`
 InteractiveP95WaitReduction int `json:"interactive_p95_wait_reduction_ticks"`
 BaselineBatchMakespan int `json:"baseline_batch_makespan_ticks"`
 CandidateBatchMakespan int `json:"candidate_batch_makespan_ticks"`
 BatchMakespanDifference int `json:"batch_makespan_difference_ticks"`
 Uncertainty string `json:"uncertainty"`
 VerificationScope string `json:"verification_scope"`
 Promotion string `json:"promotion"`
}

func strictDecode(data []byte, v *receipt) error {
 if len(data)==0||len(data)>1<<20 {return errors.New("receipt byte length outside 1..1MiB")}
 d:=json.NewDecoder(bytes.NewReader(data));d.DisallowUnknownFields()
 if err:=d.Decode(v);err!=nil{return fmt.Errorf("decode: %w",err)}
 var extra any
 if err:=d.Decode(&extra);err!=io.EOF {return errors.New("trailing JSON document")}
 return nil
}
func recompute(items []observation, kind string) stats {
 waits:=[]int{}; minArrival:=math.MaxInt; maxFinish:=0
 for _,o:=range items {if o.Kind==kind{
  waits=append(waits,o.Wait)
  if o.Arrival<minArrival {minArrival=o.Arrival}
  if o.Finished>maxFinish {maxFinish=o.Finished}
 }}
 if len(waits)==0 {return stats{}}
 sort.Ints(waits);rank:=int(math.Ceil(.95*float64(len(waits))))-1
 return stats{Count:len(waits),P95QueueWait:waits[rank],Makespan:maxFinish-minArrival}
}
func verify(r receipt) error {
 if r.Schema!="serving-fanout-receipt-r0/v1"||r.EvidenceClass!="SYNTHETIC_SIMULATION_NOT_HARDWARE" {
  return errors.New("unsupported provenance/schema")
 }
 if r.Policy!="fifo"&&r.Policy!="reserved" {return errors.New("unknown serving policy")}
 d,err:=hex.DecodeString(r.FixtureSHA256)
 if err!=nil||len(d)!=32 {return errors.New("invalid fixture digest")}
 if r.Slots<1||r.Slots>64||r.ReservedInteractive<0||r.ReservedInteractive>=r.Slots {
  return errors.New("invalid slot/reservation bounds")
 }
 if r.Policy=="reserved"&&r.ReservedInteractive==0 {return errors.New("reservation absent")}
 if len(r.Observations)==0||len(r.Observations)>10000 {return errors.New("invalid observation count")}
 ids:=map[string]bool{}
 type event struct{ tick,delta int }
 events:=[]event{}
 for _,o:=range r.Observations {
  if o.ID==""||ids[o.ID]||o.Kind!="batch"&&o.Kind!="interactive" {return fmt.Errorf("invalid/duplicate observation %q",o.ID)}
  ids[o.ID]=true
  if o.Arrival<0||o.Started<o.Arrival||o.Finished<=o.Started||o.Wait!=o.Started-o.Arrival {
   return fmt.Errorf("invalid chronology for %q",o.ID)
  }
  events=append(events,event{o.Started,1},event{o.Finished,-1})
 }
 sort.Slice(events,func(i,j int)bool{if events[i].tick!=events[j].tick{return events[i].tick<events[j].tick};return events[i].delta<events[j].delta})
 live:=0
 for _,e:=range events{
  live+=e.delta
  if live<0||live>r.Slots {return errors.New("slot capacity violation")}
 }
 if live!=0{return errors.New("unclosed serving events")}
 if (recompute(r.Observations,"interactive")!=r.Interactive)||(recompute(r.Observations,"batch")!=r.Batch){
  return errors.New("declared aggregate differs from per-job observations")
 }
 return nil
}
func compare(base,cand receipt)(comparison,error){
 if err:=verify(base);err!=nil{return comparison{},fmt.Errorf("baseline: %w",err)}
 if err:=verify(cand);err!=nil{return comparison{},fmt.Errorf("candidate: %w",err)}
 if base.Policy==cand.Policy||base.FixtureSHA256!=cand.FixtureSHA256||base.Slots!=cand.Slots{
  return comparison{},errors.New("comparison must use different policies with same fixture digest and capacity")
 }
 if base.Interactive.Count==0||base.Batch.Count==0{return comparison{},errors.New("both workload classes are required")}
 refs:=map[string]observation{}
 for _,o:=range base.Observations{refs[o.ID]=o}
 for _,o:=range cand.Observations{
  b,ok:=refs[o.ID]
  if !ok||b.Kind!=o.Kind||b.Arrival!=o.Arrival {
   return comparison{},errors.New("task identity/arrival mismatch despite matching digest")
  }
  delete(refs,o.ID)
 }
 if len(refs)!=0{return comparison{},errors.New("candidate omitted original tasks")}
 return comparison{
  EvidenceClass:"SYNTHETIC_RECEIPT_REDUCTION_ONLY",
  BaselinePolicy:base.Policy,CandidatePolicy:cand.Policy,FixtureSHA256:base.FixtureSHA256,
  MatchedTaskIDs:len(cand.Observations),InteractiveSamples:base.Interactive.Count,
  BaselineInteractiveP95Wait:base.Interactive.P95QueueWait,
  CandidateInteractiveP95Wait:cand.Interactive.P95QueueWait,
  InteractiveP95WaitReduction:base.Interactive.P95QueueWait-cand.Interactive.P95QueueWait,
  BaselineBatchMakespan:base.Batch.Makespan,CandidateBatchMakespan:cand.Batch.Makespan,
  BatchMakespanDifference:cand.Batch.Makespan-base.Batch.Makespan,
  Uncertainty:"NOT_ESTIMABLE_SINGLE_SYNTHETIC_FIXTURE",
  VerificationScope:"structure_chronology_aggregate_and_digest_equality_only_not_origin_authentication",
  Promotion:"NO_RUNTIME_PROMOTION",
 },nil
}
func read(path string)(receipt,error){
 data,err:=os.ReadFile(path);if err!=nil{return receipt{},err}
 var r receipt;err=strictDecode(data,&r);return r,err
}
func main(){
 baseline:=flag.String("baseline","","path to synthetic FIFO receipt JSON")
 candidate:=flag.String("candidate","","path to synthetic reservation receipt JSON")
 live:=flag.String("live-gate","","optional source-labeled exploratory live evidence screen JSON")
 flag.Parse()
 if *live!=""{
  c,err:=readLive(*live);if err!=nil{fmt.Fprintln(os.Stderr,err);os.Exit(2)}
  r,err:=screenLive(c);if err!=nil{fmt.Fprintln(os.Stderr,err);os.Exit(2)}
  enc:=json.NewEncoder(os.Stdout);enc.SetIndent("","  ")
  if err:=enc.Encode(r);err!=nil{fmt.Fprintln(os.Stderr,err);os.Exit(2)}
  return
 }
 if *baseline==""||*candidate==""{fmt.Fprintln(os.Stderr,"both -baseline and -candidate required");os.Exit(2)}
 a,err:=read(*baseline);if err!=nil{fmt.Fprintln(os.Stderr,err);os.Exit(2)}
 b,err:=read(*candidate);if err!=nil{fmt.Fprintln(os.Stderr,err);os.Exit(2)}
 summary,err:=compare(a,b);if err!=nil{fmt.Fprintln(os.Stderr,err);os.Exit(2)}
 enc:=json.NewEncoder(os.Stdout);enc.SetIndent("","  ")
 if err:=enc.Encode(summary);err!=nil{fmt.Fprintln(os.Stderr,err);os.Exit(2)}
}
