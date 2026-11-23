// Public-safe, loopback-only direct inference measurement. Not a configured-agent qualification.
package main

import (
 "bytes"
 "encoding/json"
 "errors"
 "flag"
 "fmt"
 "io"
 "math"
 "math/rand"
 "net"
 "net/http"
 "net/url"
 "os"
 "runtime"
 "sort"
 "strings"
 "sync"
 "time"
)
type modelRow struct { Name string `json:"name"`; Digest string `json:"digest"` }
type tagsResponse struct { Models []modelRow `json:"models"` }
type generation struct {
 Response string `json:"response"`
 Done bool `json:"done"`
 TotalDuration int64 `json:"total_duration"`
 LoadDuration int64 `json:"load_duration"`
 PromptEvalCount int `json:"prompt_eval_count"`
 PromptEvalDuration int64 `json:"prompt_eval_duration"`
 EvalCount int `json:"eval_count"`
 EvalDuration int64 `json:"eval_duration"`
}
type sample struct {
 Index int `json:"index"`
 ElapsedMS float64 `json:"elapsed_ms"`
 LoadMS float64 `json:"load_ms"`
 PrefillMS float64 `json:"prefill_ms"`
 DecodeMS float64 `json:"decode_ms"`
 PromptTokens int `json:"prompt_tokens"`
 OutputTokens int `json:"output_tokens"`
}
type condition struct {
 Concurrency int `json:"client_concurrency"`
 PrefixPattern string `json:"prefix_pattern"`
 Strategy string `json:"strategy"`
 MaxConcurrentRequests int `json:"max_inflight"`
 Replicate int `json:"replicate"`
 Cohort int `json:"cohort"`
 WallMS float64 `json:"wall_ms"`
 P95RequestMS float64 `json:"p95_request_ms"`
 Samples []sample `json:"samples"`
}
type output struct {
 EvidenceClass string `json:"evidence_class"`
 Backend string `json:"backend"`
 BackendVersion string `json:"backend_version"`
 ModelTag string `json:"model_tag"`
 RuntimeModelDigest string `json:"runtime_model_digest"`
 ExactFoundryIdentity string `json:"exact_foundry_identity"`
 ArtifactAndLicenseAdmission string `json:"artifact_and_license_admission"`
 Platform string `json:"platform"`
 SourceSHA string `json:"source_sha"`
 StartedUTC string `json:"started_utc"`
 Seed int64 `json:"seed"`
 TTFT string `json:"ttft"`
 KVCacheMetrics string `json:"kv_cache_metrics"`
 AgentTaskValidity string `json:"agent_task_validity"`
 ExperimentalDesign string `json:"experimental_design"`
 Conditions []condition `json:"conditions"`
}
func loopbackOnly(raw string) error {
 u,err:=url.Parse(raw)
 if err!=nil||u.Scheme!="http"||u.Path!=""||u.RawQuery!=""||u.User!=nil||u.Fragment!=""{return errors.New("URL must be uncredentialed loopback HTTP origin")}
 h:=u.Hostname()
 if h=="localhost"{return nil}
 ip:=net.ParseIP(h)
 if ip==nil||!ip.IsLoopback(){return errors.New("non-loopback URL refused")}
 return nil
}
func requestJSON(client *http.Client,method,url string,payload any,dest any) error{
 var rd io.Reader
 if payload!=nil{b,err:=json.Marshal(payload);if err!=nil{return err};rd=bytes.NewReader(b)}
 req,err:=http.NewRequest(method,url,rd);if err!=nil{return err}
 if payload!=nil{req.Header.Set("Content-Type","application/json")}
 resp,err:=client.Do(req);if err!=nil{return err}
 defer resp.Body.Close()
 if resp.StatusCode!=http.StatusOK{return fmt.Errorf("HTTP status %d",resp.StatusCode)}
 dec:=json.NewDecoder(io.LimitReader(resp.Body,2<<20))
 if err=dec.Decode(dest);err!=nil{return err}
 return nil
}
func modelDigest(client *http.Client,base,tag,prefix string)(string,error){
 var response tagsResponse
 if err:=requestJSON(client,"GET",base+"/api/tags",nil,&response);err!=nil{return "",err}
 for _,m:=range response.Models{
  if m.Name!=tag{continue}
  d:=strings.TrimPrefix(m.Digest,"sha256:")
  if len(d)!=64||!strings.HasPrefix(d,prefix){return "",errors.New("live model digest does not match pinned family prefix")}
  for _,r:=range d{if !strings.ContainsRune("0123456789abcdef",r){return "",errors.New("invalid model digest")}}
  return d,nil
 }
 return "",errors.New("required model not installed")
}
func prompt(i int,pattern string,cohort int)string {
 // Same vocabulary and word count in both treatments; rearrange prefix tokens
 // to vary prefix reuse while keeping expected token length approximately matched.
 words:=[]string{"amber","cobalt","cedar","river","field","lunar","pixel","vector","signal","orbit"}
 var out strings.Builder
 fmt.Fprintf(&out,"Synthetic cohort %08d. ",cohort)
 for repeat:=0;repeat<16;repeat++ {
  for j:=0;j<len(words);j++{
   idx:=j
   if pattern=="distinct"{idx=(j+i+1)%len(words)}
   out.WriteString(words[idx]);out.WriteByte(' ')
  }
 }
 fmt.Fprintf(&out,"Request %02d: Write one short sentence about testing software.",i)
 return out.String()
}
func infer(client *http.Client,base,model,pattern string,i,cohort int)(sample,error){
 payload:=map[string]any{
  "model":model,"prompt":prompt(i,pattern,cohort),"stream":false,"think":false,
  "keep_alive":"10m",
  "options":map[string]any{"num_predict":16,"num_ctx":2048,"temperature":0},
 }
 var response generation
 start:=time.Now()
 err:=requestJSON(client,"POST",base+"/api/generate",payload,&response)
 elapsed:=float64(time.Since(start).Microseconds())/1000
 if err!=nil{return sample{},err}
 if !response.Done||response.EvalCount<1||response.PromptEvalCount<1 {
  return sample{},errors.New("API response missing required timing/token counters")
 }
 return sample{
  Index:i,ElapsedMS:elapsed,LoadMS:float64(response.LoadDuration)/1e6,
  PrefillMS:float64(response.PromptEvalDuration)/1e6,
  DecodeMS:float64(response.EvalDuration)/1e6,
  PromptTokens:response.PromptEvalCount,OutputTokens:response.EvalCount,
 },nil
}
func p95(samples []sample)float64{
 xs:=make([]float64,len(samples))
 for i,s:=range samples {xs[i]=s.ElapsedMS}
 sort.Float64s(xs);return xs[int(math.Ceil(.95*float64(len(xs))))-1]
}
func runCondition(client *http.Client,base,model string,concurrency,n int,pattern string,cohort,replicate int)(condition,error){
 if concurrency<1||concurrency>8||n<1||n>32||(pattern!="shared"&&pattern!="distinct"){return condition{},errors.New("invalid bounded condition")}
 jobs:=make(chan int,n);results:=make([]sample,n)
 errorsByJob:=make([]error,n)
 var wg sync.WaitGroup
 for j:=0;j<concurrency;j++{
  wg.Add(1)
  go func(){
   defer wg.Done()
   for i:=range jobs{
    results[i],errorsByJob[i]=infer(client,base,model,pattern,i,cohort)
   }
  }()
 }
 start:=time.Now()
 for i:=0;i<n;i++{jobs<-i}
 close(jobs);wg.Wait()
 for i,err:=range errorsByJob{if err!=nil{return condition{},fmt.Errorf("job %d: %w",i,err)}}
 return condition{Concurrency:concurrency,PrefixPattern:pattern,Strategy:"burst",MaxConcurrentRequests:concurrency,Replicate:replicate,Cohort:cohort,
  WallMS:float64(time.Since(start).Microseconds())/1000,
  P95RequestMS:p95(results),Samples:results},nil
}
// Primed fan-out serially completes one shared-prefix request, then concurrently
// launches the other three. It is a treatment, not server-side KV manipulation.
func runPrimed(client *http.Client,base,model string,cohort,replicate int)(condition,error){
 start:=time.Now()
 result:=make([]sample,4)
 first,err:=infer(client,base,model,"shared",0,cohort)
 if err!=nil{return condition{},fmt.Errorf("prime: %w",err)}
 result[0]=first
 errs:=make([]error,4)
 var wg sync.WaitGroup
 for i:=1;i<4;i++{
  wg.Add(1)
  go func(i int){
   defer wg.Done()
   result[i],errs[i]=infer(client,base,model,"shared",i,cohort)
  }(i)
 }
 wg.Wait()
 for i:=1;i<4;i++{if errs[i]!=nil{return condition{},fmt.Errorf("fan job %d: %w",i,errs[i])}}
 return condition{Concurrency:4,PrefixPattern:"shared",Strategy:"prime1_then_fan3",
  MaxConcurrentRequests:3,Replicate:replicate,Cohort:cohort,
  WallMS:float64(time.Since(start).Microseconds())/1000,
  P95RequestMS:p95(result),Samples:result},nil
}
func execute(base,model,prefix string,seed int64)(output,error){
 if err:=loopbackOnly(base);err!=nil{return output{},err}
 client:=&http.Client{Timeout:120*time.Second,CheckRedirect:func(req *http.Request,via []*http.Request)error{return http.ErrUseLastResponse}}
 full,err:=modelDigest(client,base,model,prefix)
 if err!=nil{return output{},err}
 // Real warm-up does not become a reported benchmark request.
 if _,err:=infer(client,base,model,"shared",999,-1);err!=nil{return output{},fmt.Errorf("warmup: %w",err)}
 type jobSpec struct{concurrency int;pattern string;strategy string}
 jobs:=[]jobSpec{}
 for _,n:=range []int{1,2,4}{
  for _,pattern:=range []string{"shared","distinct"}{
   jobs=append(jobs,jobSpec{n,pattern,"burst"})
  }
 }
 jobs=append(jobs,jobSpec{4,"shared","prime1_then_fan3"})
 rng:=rand.New(rand.NewSource(seed))
 report:=output{EvidenceClass:"LIVE_PUBLIC_CPU_DIRECT_INFERENCE_EXPLORATORY",Backend:"ollama",
  BackendVersion:os.Getenv("OLLAMA_VERSION"),ModelTag:model,
  RuntimeModelDigest:full,ExactFoundryIdentity:"UNKNOWN",ArtifactAndLicenseAdmission:"NOT_ASSESSED_BY_THIS_PROBE",
  Platform:runtime.GOOS+"/"+runtime.GOARCH,
  SourceSHA:os.Getenv("GITHUB_SHA"),StartedUTC:time.Now().UTC().Format(time.RFC3339Nano),Seed:seed,
  TTFT:"NOT_OBSERVABLE_NONSTREAMING_API",KVCacheMetrics:"NOT_OBSERVED",
  AgentTaskValidity:"NOT_TESTED_DIRECT_COMPLETION_ONLY",
  ExperimentalDesign:"3 randomized blocks, 7 policies, unique cohort prefixes, matched token vocabulary; not independent hosts"}
 for replicate:=1;replicate<=3;replicate++ {
  rng.Shuffle(len(jobs),func(i,j int){jobs[i],jobs[j]=jobs[j],jobs[i]})
  matched:=map[int]map[string]float64{}
  primedTokens:=0.0
  for _,job:=range jobs {
   patternID:=0;if job.pattern=="distinct"{patternID=1}
   if job.strategy=="prime1_then_fan3"{patternID=2}
   cohort:=int(seed%1000)*1000+replicate*100+job.concurrency*10+patternID
   var c condition;var err error
   if job.strategy=="prime1_then_fan3"{
    c,err=runPrimed(client,base,model,cohort,replicate)
   }else{
    c,err=runCondition(client,base,model,job.concurrency,4,job.pattern,cohort,replicate)
   }
   if err!=nil{return output{},fmt.Errorf("rep %d concurrency %d prefix %s strategy %s: %w",replicate,job.concurrency,job.pattern,job.strategy,err)}
   var tokens float64
   for _,sample:=range c.Samples{tokens+=float64(sample.PromptTokens)}
   if job.strategy=="burst"{
    if matched[job.concurrency]==nil{matched[job.concurrency]=map[string]float64{}}
    matched[job.concurrency][job.pattern]=tokens/float64(len(c.Samples))
   }else{
    primedTokens=tokens/float64(len(c.Samples))
   }
   report.Conditions=append(report.Conditions,c)
  }
  refTokens:=matched[4]["shared"]
  if primedTokens==0||refTokens==0||math.Abs(primedTokens-refTokens)/math.Max(primedTokens,refTokens)>.15 {
   return output{},fmt.Errorf("rep %d primed vs burst prompt-token parity failed: primed=%g burst=%g",replicate,primedTokens,refTokens)
  }
  for concurrency,pairs:=range matched{
   a,b:=pairs["shared"],pairs["distinct"]
   if a==0||b==0||math.Abs(a-b)/math.Max(a,b)>.15{
    return output{},fmt.Errorf("rep %d concurrency %d prompt-token parity failed: shared=%g distinct=%g",replicate,concurrency,a,b)
   }
  }
 }
 return report,nil
}
func main(){
 base:=flag.String("base","http://127.0.0.1:11434","Ollama loopback origin")
 model:=flag.String("model","qwen3:1.7b","preexisting pinned public model tag")
 prefix:=flag.String("digest-prefix","8f68893c685c","expected installed model digest prefix")
 seed:=flag.Int64("seed",316,"deterministic condition-order seed")
 out:=flag.String("out","","output JSON file; otherwise stdout")
 flag.Parse()
 report,err:=execute(*base,*model,*prefix,*seed)
 if err!=nil{fmt.Fprintln(os.Stderr,err);os.Exit(1)}
 b,err:=json.MarshalIndent(report,"","  ")
 if err!=nil{fmt.Fprintln(os.Stderr,err);os.Exit(1)}
 b=append(b,'\n')
 if *out!=""{err=os.WriteFile(*out,b,0600)}else{_,err=os.Stdout.Write(b)}
 if err!=nil{fmt.Fprintln(os.Stderr,err);os.Exit(1)}
}
