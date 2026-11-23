package main

import (
 "encoding/json"
 "fmt"
 "net/http"
 "net/http/httptest"
 "strings"
 "sync/atomic"
 "testing"
)
func fake(t *testing.T,empty bool)(*httptest.Server,*atomic.Int64){
 t.Helper()
 count:=&atomic.Int64{}
 s:=httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){
  w.Header().Set("Content-Type","application/json")
  switch r.URL.Path{
  case "/api/tags":
   fmt.Fprintf(w,`{"models":[{"name":"qwen3:1.7b","digest":"%s"}]}`, "8f68893c685c"+strings.Repeat("a",52))
  case "/api/generate":
   var req map[string]any
   if err:=json.NewDecoder(r.Body).Decode(&req);err!=nil{http.Error(w,"invalid request",400);return}
   if req["think"]!=false||req["stream"]!=false {http.Error(w,"unsafe shape",400);return}
   options,ok:=req["options"].(map[string]any)
   if !ok||options["num_ctx"]!=float64(2048){http.Error(w,"unexpected context",400);return}
   count.Add(1)
   if empty{fmt.Fprint(w,`{"done":true,"eval_count":0,"prompt_eval_count":8}`);return}
   fmt.Fprint(w,`{"response":"test","done":true,"total_duration":10000000,"load_duration":0,"prompt_eval_count":40,"prompt_eval_duration":5000000,"eval_count":8,"eval_duration":5000000}`)
  default:http.NotFound(w,r)
  }
 }))
 return s,count
}
func TestDirectExploratoryReceipts(t *testing.T){
 s,count:=fake(t,false);defer s.Close()
 r,err:=execute(s.URL,"qwen3:1.7b","8f68893c685c",316)
 if err!=nil{t.Fatal(err)}
 if len(r.Conditions)!=21||count.Load()!=85 {t.Fatalf("unexpected conditions/calls: %d / %d",len(r.Conditions),count.Load())}
 if r.TTFT!="NOT_OBSERVABLE_NONSTREAMING_API"||r.AgentTaskValidity!="NOT_TESTED_DIRECT_COMPLETION_ONLY"||r.ExactFoundryIdentity!="UNKNOWN" {
  t.Fatal("unsupported inferred assurance claim")
 }
 cohorts:=map[int]bool{}
 for _,c:=range r.Conditions{
  if len(c.Samples)!=4||c.P95RequestMS<0 {t.Fatalf("invalid condition %+v",c)}
  if c.Strategy=="prime1_then_fan3" && (c.MaxConcurrentRequests!=3||c.PrefixPattern!="shared"){t.Fatalf("invalid prime fanout declaration %+v",c)}
  if cohorts[c.Cohort]{t.Fatalf("cache cohort repeated across conditions: %+v",c)}
  cohorts[c.Cohort]=true
 }
 b,_:=json.Marshal(r)
 if strings.Contains(string(b),"Synthetic workload,") {t.Fatal("raw prompts must not be emitted in receipt")}
}
func TestHostAndModelFailClosed(t *testing.T){
 for _,url:=range []string{"https://127.0.0.1:11434","http://example.com:11434","http://127.0.0.1:11434/evil","http://x:y@127.0.0.1:11434"}{
  if err:=loopbackOnly(url);err==nil{t.Fatalf("bad host accepted: %s",url)}
 }
 s,_:=fake(t,false);defer s.Close()
 _,err:=execute(s.URL,"qwen3:1.7b","deadbeef",316)
 if err==nil{t.Fatal("wrong model prefix accepted")}
}
func TestMissingModelCountersRejected(t *testing.T){
 s,_:=fake(t,true);defer s.Close()
 if _,err:=execute(s.URL,"qwen3:1.7b","8f68893c685c",316);err==nil {
  t.Fatal("empty model output silently accepted")
 }
}

func TestPromptCohortIsolationAndLexicalParity(t *testing.T){
 a:=prompt(0,"shared",3161)
 b:=prompt(1,"shared",3161)
 c:=prompt(0,"distinct",3161)
 d:=prompt(0,"shared",3162)
 if a==b||a==c||a==d{t.Fatal("unexpected prompt reuse")}
 // Shared prompts must differ only in a short terminal request field.
 if !strings.HasPrefix(a,"Synthetic cohort 00003161. amber cobalt"){
  t.Fatalf("shared prompt prefix malformed: %s",a[:80])
 }
 if len(a)-len(c)>80||len(c)-len(a)>80{t.Fatal("prefix treatment changes payload size materially")}
}
func TestRedirectCannotEscapeLoopback(t *testing.T){
 s:=httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){
  http.Redirect(w,r,"https://example.org/private",http.StatusFound)
 }))
 defer s.Close()
 if _,err:=execute(s.URL,"qwen3:1.7b","8f68893c685c",316);err==nil{
  t.Fatal("outbound redirect followed despite loopback-only policy")
 }
}

func TestPrimeOneThenFanThreeActuallyRunsFourRequests(t *testing.T){
 s,n:=fake(t,false);defer s.Close()
 c,err:=runPrimed(&http.Client{},s.URL,"qwen3:1.7b",4455,2)
 if err!=nil{t.Fatal(err)}
 if c.Strategy!="prime1_then_fan3"||c.MaxConcurrentRequests!=3||len(c.Samples)!=4||n.Load()!=4{
  t.Fatalf("wrong primed branch %+v calls=%d",c,n.Load())
 }
}
