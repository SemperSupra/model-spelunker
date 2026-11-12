package main

import (
 "bytes"
 "context"
 "encoding/base64"
 "encoding/json"
 "fmt"
 "image"
 "image/color"
 "image/png"
 "io"
 "net/http"
 "net/http/httptest"
 "net/url"
 "os"
 "path/filepath"
 "regexp"
 "strings"
 "testing"
 "time"
)
var fixtureToken=[]byte(strings.Repeat("k",40))
func newTest(t *testing.T)(*Server,string){
 t.Helper()
 dir:=t.TempDir()
 s,err:=New(dir,"http://127.0.0.1:8090","http://127.0.0.1:8188",fixtureToken)
 if err!=nil{t.Fatal(err)}
 t.Cleanup(s.Close)
 return s,dir
}
func fixtureJob()JobInput{return JobInput{Workflow:"toy-cnn-v1",Variant:"base",Seed:31,Size:64}}
func post(t *testing.T,s *Server,path,auth string,body any)(int,map[string]any){
 t.Helper()
 b,_:=json.Marshal(body)
 req:=httptest.NewRequest("POST",path,bytes.NewReader(b))
 req.Header.Set("Authorization",auth)
 rec:=httptest.NewRecorder();s.ServeHTTP(rec,req)
 out:=map[string]any{}
 _=json.Unmarshal(rec.Body.Bytes(),&out)
 return rec.Code,out
}
func TestValidationAndReplay(t *testing.T){
 s,_:=newTest(t)
 b:=BatchRequest{RequestID:"first-batch-key",Jobs:[]JobInput{fixtureJob(),fixtureJob()}}
 ids,replay,err:=s.submit(b)
 if err!=nil||replay||len(ids)!=2{t.Fatalf("%v %v %v",ids,replay,err)}
 twice,wasReplay,err:=s.submit(b)
 if err!=nil||!wasReplay||strings.Join(ids,",")!=strings.Join(twice,","){t.Fatal("idempotent replay drift")}
 b.Jobs[0].Seed=32
 if _,_,err=s.submit(b);err==nil||err.Error()!="IDEMPOTENCY_KEY_CONFLICT"{t.Fatal("mutated payload not refused")}
 if _,_,err=s.submit(BatchRequest{RequestID:"other-key",Jobs:[]JobInput{{Workflow:"arbitrary",Seed:1,Variant:"base",Size:64}}});err==nil{t.Fatal("unapproved graph admitted")}
 if _,_,err=s.submit(BatchRequest{RequestID:"other-key",Jobs:make([]JobInput,17)});err==nil{t.Fatal("unbounded batch admitted")}
}
func TestAuthenticationAndAPIBounds(t *testing.T){
 s,_:=newTest(t)
 if code,_:=post(t,s,"/api/v1/batches","",BatchRequest{});code!=401{t.Fatalf("unauthenticated %d",code)}
 bearer:="Bearer "+string(fixtureToken)
 b:=BatchRequest{RequestID:"batch-id-123",Jobs:[]JobInput{fixtureJob()}}
 code,out:=post(t,s,"/api/v1/batches",bearer,b)
 if code!=202||out["status"]!="QUEUED_OR_EXISTING"{t.Fatalf("failed submit %d %v",code,out)}
 code,out=post(t,s,"/api/v1/batches",bearer,b)
 if code!=202||out["idempotent_replay"]!=true{t.Fatalf("failed replay %d %v",code,out)}
 b.Jobs[0].Seed=999
 code,_=post(t,s,"/api/v1/batches",bearer,b)
 if code!=409{t.Fatalf("expected conflict %d",code)}
 req:=httptest.NewRequest("POST","/api/v1/batches",strings.NewReader(`{"request_id":"batch-bad-key","jobs":[{"workflow":"toy-cnn-v1","seed":31,"variant":"base","size":64,"unapproved_code":"run"}]}`))
 req.Header.Set("Authorization",bearer)
 w:=httptest.NewRecorder();s.ServeHTTP(w,req)
 if w.Code!=400{t.Fatalf("unknown field accepted %d",w.Code)}
 req=httptest.NewRequest("GET","/api/v1/capabilities",nil)
 req.Header.Set("Authorization",bearer)
 w=httptest.NewRecorder();s.ServeHTTP(w,req)
 if w.Code!=200||!strings.Contains(w.Body.String(),"production_generator_admitted":false"){t.Fatalf("capabilities %d %s",w.Code,w.Body.String())}
}
func TestPersistentCrashAmbiguityAndSingleLease(t *testing.T){
 dir:=t.TempDir()
 s,err:=New(dir,"http://127.0.0.1:8090","http://127.0.0.1:8188",fixtureToken)
 if err!=nil{t.Fatal(err)}
 if _,err=New(dir,"http://127.0.0.1:8090","http://127.0.0.1:8188",fixtureToken);err==nil{t.Fatal("multiple controller replicas accepted")}
 ids,_,err:=s.submit(BatchRequest{RequestID:"restart-id",Jobs:[]JobInput{fixtureJob()}})
 if err!=nil{t.Fatal(err)}
 s.mu.Lock()
 s.ledger.Jobs[ids[0]].State="RUNNING"
 if err=s.save();err!=nil{t.Fatal(err)}
 s.mu.Unlock();s.Close()
 recovered,err:=New(dir,"http://127.0.0.1:8090","http://127.0.0.1:8188",fixtureToken)
 if err!=nil{t.Fatal(err)}
 defer recovered.Close()
 if recovered.ledger.Jobs[ids[0]].State!="UNKNOWN_NEEDS_RECONCILIATION"{t.Fatal("running job was blindly retried")}
 if recovered.ledger.Jobs[ids[0]].Reason!="CONTROLLER_RESTART"{t.Fatal("missing reason")}
}
func TestCancelAndNoModelPromotion(t *testing.T){
 s,_:=newTest(t)
 ids,_,err:=s.submit(BatchRequest{RequestID:"cancel-id",Jobs:[]JobInput{fixtureJob()}})
 if err!=nil{t.Fatal(err)}
 path:="/api/v1/jobs/"+ids[0]+"/cancel"
 code,out:=post(t,s,path,"Bearer "+string(fixtureToken),struct{}{})
 if code!=200||out["state"]!="CANCELLED"{t.Fatalf("cancel %v %v",code,out)}
 if s.ledger.Jobs[ids[0]].ImageSHA256!=""{t.Fatal("cancel invented image")}
}
func TestAccessibleBasicFormWithOriginAndCSRF(t *testing.T){
 s,_:=newTest(t)
 basic:="Basic "+base64.StdEncoding.EncodeToString([]byte("operator:"+string(fixtureToken)))
 req:=httptest.NewRequest("GET","/",nil);req.Header.Set("Authorization",basic)
 w:=httptest.NewRecorder();s.ServeHTTP(w,req)
 if w.Code!=200{t.Fatal(w.Code)}
 html:=w.Body.String()
 for _,label:=range []string{`<main>`,`<label for="seed">`,`<fieldset><legend>`,`<button type="submit">`}{
  if !strings.Contains(html,label){t.Fatalf("missing semantic a11y control %q",label)}
 }
 tok:=regexp.MustCompile(`name="csrf" value="([a-f0-9]+)"`).FindStringSubmatch(html)
 if len(tok)!=2{t.Fatal("CSRF hidden token missing")}
 form:=url.Values{"csrf":[]string{tok[1]},"seed":[]string{"31"},"variant":[]string{"base"}}
 makeRequest:=func(origin string)int{
  r:=httptest.NewRequest("POST","/ui/submit",strings.NewReader(form.Encode()))
  r.Header.Set("Authorization",basic);r.Header.Set("Content-Type","application/x-www-form-urlencoded")
  r.Header.Set("Origin",origin)
  r.AddCookie(w.Result().Cookies()[0])
  z:=httptest.NewRecorder();s.ServeHTTP(z,r);return z.Code
 }
 if v:=makeRequest("https://attacker.invalid");v!=403{t.Fatalf("CSRF accepted %d",v)}
 if v:=makeRequest("http://127.0.0.1:8090");v!=303{t.Fatalf("valid UI rejected %d",v)}
}
func TestNativeQueueDispatchAndDurablePNG(t *testing.T){
 imageData:=image.NewRGBA(image.Rect(0,0,64,64))
 for y:=0;y<64;y++{for x:=0;x<64;x++{imageData.Set(x,y,color.RGBA{R:uint8(x*3),G:uint8(y*3),B:42,A:255})}}
 var buf bytes.Buffer
 if err:=png.Encode(&buf,imageData);err!=nil{t.Fatal(err)}
 native:=httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){
  switch {
  case r.URL.Path=="/system_stats":io.WriteString(w,`{"devices":[]}`)
  case r.URL.Path=="/prompt":
   var graph map[string]any
   if err:=json.NewDecoder(r.Body).Decode(&graph);err!=nil{t.Error(err)}
   io.WriteString(w,`{"prompt_id":"native-prompt-123"}`)
  case r.URL.Path=="/history/native-prompt-123":
   io.WriteString(w,`{"native-prompt-123":{"status":{"status_str":"success"},"outputs":{"2":{"images":[{"filename":"fixture.png","type":"output","subfolder":""}]}}}}`)
  case r.URL.Path=="/view":
   w.Header().Set("Content-Type","image/png");w.Write(buf.Bytes())
  default:http.NotFound(w,r)
  }
 }))
 defer native.Close()
 dir:=t.TempDir()
 s,err:=New(dir,"http://127.0.0.1:8090",native.URL,fixtureToken)
 if err!=nil{t.Fatal(err)};defer s.Close()
 ids,_,err:=s.submit(BatchRequest{RequestID:"native-one-id",Jobs:[]JobInput{fixtureJob()}})
 if err!=nil{t.Fatal(err)}
 ctx,cancel:=context.WithCancel(context.Background());defer cancel()
 go s.runLoop(ctx)
 for i:=0;i<80;i++{
  time.Sleep(100*time.Millisecond)
  s.mu.Lock();j:=*s.ledger.Jobs[ids[0]];s.mu.Unlock()
  if j.State=="COMPLETED"{
   if j.ImageSHA256==""||j.NativePromptID!="native-prompt-123"{t.Fatal("native receipt missing")}
   if _,err:=os.Stat(filepath.Join(dir,"results",j.ID+".png"));err!=nil{t.Fatal(err)}
   req:=httptest.NewRequest("GET","/api/v1/jobs/"+j.ID+"/image",nil)
   req.Header.Set("Authorization","Bearer "+string(fixtureToken))
   w:=httptest.NewRecorder();s.ServeHTTP(w,req)
   if w.Code!=200||!bytes.Equal(w.Body.Bytes(),buf.Bytes()){t.Fatalf("image retrieval %d",w.Code)}
   return
  }
  if strings.HasPrefix(j.State,"UNKNOWN"){t.Fatalf("native failed: %v",j)}
 }
 t.Fatal(fmt.Sprintf("native dispatch not completed: %s",ids[0]))
}
