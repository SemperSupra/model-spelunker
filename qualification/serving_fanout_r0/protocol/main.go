// Synthetic deterministic contention oracle. NOT a hardware benchmark or production scheduler.
package main

import (
 "crypto/sha256"
 "encoding/hex"
 "encoding/json"
 "errors"
 "flag"
 "fmt"
 "math"
 "os"
 "sort"
)

type Task struct {
 ID string `json:"id"`
 Tenant string `json:"tenant"`
 Kind string `json:"kind"`
 Arrival int `json:"arrival_tick"`
 Service int `json:"service_ticks"`
 Context int `json:"context_tokens"`
 Prefix string `json:"prefix_group"`
}
type Fixture struct {
 Schema string `json:"schema"`
 Slots int `json:"slots"`
 ReservedInteractive int `json:"reserved_interactive"`
 Tasks []Task `json:"tasks"`
}
type Observation struct {
 ID string `json:"id"`
 Kind string `json:"kind"`
 Arrival int `json:"arrival_tick"`
 Started int `json:"started_tick"`
 Finished int `json:"finished_tick"`
 Wait int `json:"queue_wait_ticks"`
}
type Stats struct {
 Count int `json:"count"`
 P95QueueWait int `json:"p95_queue_wait_ticks"`
 Makespan int `json:"makespan_ticks"`
}
type Receipt struct {
 Schema string `json:"schema"`
 EvidenceClass string `json:"evidence_class"`
 Policy string `json:"policy"`
 FixtureSHA256 string `json:"fixture_sha256"`
 Slots int `json:"slots"`
 ReservedInteractive int `json:"reserved_interactive"`
 Interactive Stats `json:"interactive"`
 Batch Stats `json:"batch"`
 Observations []Observation `json:"observations"`
}
func validate(f Fixture) error {
 if f.Schema!="serving-fanout-r0/v1" {return errors.New("unsupported schema")}
 if f.Slots<1 || f.Slots>64 {return errors.New("slots must be 1..64")}
 if f.ReservedInteractive<0 || f.ReservedInteractive>=f.Slots {return errors.New("reserved_interactive must be 0..slots-1")}
 if len(f.Tasks)==0 || len(f.Tasks)>10000 {return errors.New("task count out of bounds")}
 seen:=map[string]bool{}
 for _,t:=range f.Tasks {
  if t.ID=="" || t.Tenant=="" || seen[t.ID] {return fmt.Errorf("missing tenant/id or duplicate id: %q",t.ID)}
  seen[t.ID]=true
  if t.Kind!="interactive" && t.Kind!="batch" {return fmt.Errorf("unknown kind for %q",t.ID)}
  if t.Arrival<0 || t.Service<1 || t.Service>100000 || t.Context<0 {return fmt.Errorf("invalid bounds for %q",t.ID)}
 }
 return nil
}
func summarize(obs []Observation, kind string) Stats {
 waits:=[]int{}; minArrival:=math.MaxInt; maxFinish:=0
 for _,o:=range obs {if o.Kind==kind {waits=append(waits,o.Wait);if o.Arrival<minArrival{minArrival=o.Arrival};if o.Finished>maxFinish{maxFinish=o.Finished}}}
 if len(waits)==0{return Stats{}}
 sort.Ints(waits)
 rank:=int(math.Ceil(.95*float64(len(waits))))-1
 return Stats{Count:len(waits),P95QueueWait:waits[rank],Makespan:maxFinish-minArrival}
}
func simulate(f Fixture, policy string)(Receipt,error){
 if err:=validate(f);err!=nil{return Receipt{},err}
 if policy!="fifo"&&policy!="reserved"{return Receipt{},errors.New("unknown policy")}
 if policy=="reserved" && f.ReservedInteractive==0{return Receipt{},errors.New("reserved policy requires reserved_interactive > 0")}
 b,_:=json.Marshal(f);digest:=sha256.Sum256(b)
 tasks:=append([]Task(nil),f.Tasks...)
 sort.SliceStable(tasks,func(i,j int)bool{if tasks[i].Arrival!=tasks[j].Arrival{return tasks[i].Arrival<tasks[j].Arrival};return tasks[i].ID<tasks[j].ID})
 type active struct{obs Observation; finish int}
 running:=make([]*active,f.Slots);pending:=[]Task{};observations:=[]Observation{}
 t,next:=0,0
 for len(observations)<len(tasks) {
  for s,a:=range running {if a!=nil && a.finish<=t {observations=append(observations,a.obs);running[s]=nil}}
  for next<len(tasks)&&tasks[next].Arrival<=t {pending=append(pending,tasks[next]);next++}
  take:=func(kind string)(Task,bool){
   for i,p:=range pending{if kind==""||p.Kind==kind{pending=append(pending[:i],pending[i+1:]...);return p,true}}
   return Task{},false
  }
  for slot,a:=range running {if a!=nil{continue}
   var job Task;var ok bool
   if policy=="reserved"{
    if slot<f.ReservedInteractive{job,ok=take("interactive")} else {job,ok=take("batch");if !ok{job,ok=take("interactive")}}
   }else{job,ok=take("")}
   if ok {running[slot]=&active{obs:Observation{ID:job.ID,Kind:job.Kind,Arrival:job.Arrival,Started:t,Finished:t+job.Service,Wait:t-job.Arrival},finish:t+job.Service}}
  }
  if len(observations)==len(tasks){break}
  advance:=math.MaxInt
  for _,a:=range running{if a!=nil && a.finish<advance{advance=a.finish}}
  if next<len(tasks)&&tasks[next].Arrival<advance{advance=tasks[next].Arrival}
  if advance==math.MaxInt{return Receipt{},errors.New("deadlock: work remains without progress")}
  if advance<=t{return Receipt{},errors.New("clock did not advance")}
  t=advance
 }
 sort.Slice(observations,func(i,j int)bool{return observations[i].ID<observations[j].ID})
 return Receipt{Schema:"serving-fanout-receipt-r0/v1",EvidenceClass:"SYNTHETIC_SIMULATION_NOT_HARDWARE",Policy:policy,FixtureSHA256:hex.EncodeToString(digest[:]),Slots:f.Slots,ReservedInteractive:f.ReservedInteractive,Interactive:summarize(observations,"interactive"),Batch:summarize(observations,"batch"),Observations:observations},nil
}
func main(){
 file:=flag.String("fixture","", "path to public synthetic JSON fixture")
 policy:=flag.String("policy","fifo","fifo or reserved (synthetic event simulator)")
 flag.Parse()
 if *file==""{fmt.Fprintln(os.Stderr,"-fixture is required");os.Exit(2)}
 b,err:=os.ReadFile(*file);if err!=nil{fmt.Fprintln(os.Stderr,err);os.Exit(2)}
 var f Fixture
 if err=json.Unmarshal(b,&f);err!=nil{fmt.Fprintln(os.Stderr,err);os.Exit(2)}
 r,err:=simulate(f,*policy);if err!=nil{fmt.Fprintln(os.Stderr,err);os.Exit(2)}
 e:=json.NewEncoder(os.Stdout);e.SetIndent("","  ")
 if err=e.Encode(r);err!=nil{fmt.Fprintln(os.Stderr,err);os.Exit(2)}
}
