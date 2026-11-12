// Conditioning Controller: one-durable-ledger, one-ComfyUI-worker dispatcher.
// There is NO arbitrary workflow execution or GPU placement scheduler here.
// State lives on a Foundry-managed mount; the process/container is disposable.
package main

import (
 "bytes"
 "context"
 "crypto/rand"
 "crypto/sha256"
 "crypto/subtle"
 "encoding/hex"
 "encoding/json"
 "errors"
 "fmt"
 "html/template"
 "io"
 "log"
 "net/http"
 "net/url"
 "os"
 "path/filepath"
 "regexp"
 "strconv"
 "strings"
 "sync"
 "syscall"
 "time"
)

const maxBody=8192
var requestID=reMust("^[a-zA-Z0-9._-]{8,80}$")
var slug=reMust("^[a-f0-9]{32}$")
func reMust(s string)*regexp.Regexp{return regexp.MustCompile(s)}
type JobInput struct{
 Workflow string `json:"workflow"`
 Seed int64 `json:"seed"`
 Variant string `json:"variant"`
 Size int `json:"size"`
}
type Job struct{
 ID string `json:"id"`
 Request JobInput `json:"request"`
 State string `json:"state"`
 Submitted string `json:"submitted_utc"`
 NativePromptID string `json:"native_prompt_id,omitempty"`
 ImageSHA256 string `json:"image_sha256,omitempty"`
 Reason string `json:"reason,omitempty"`
}
type Batch struct{
 Digest string `json:"digest"`
 JobIDs []string `json:"job_ids"`
}
type Ledger struct{
 Schema string `json:"schema"`
 Jobs map[string]*Job `json:"jobs"`
 Order []string `json:"order"`
 Batches map[string]Batch `json:"batches"`
}
type BatchRequest struct{
 RequestID string `json:"request_id"`
 Jobs []JobInput `json:"jobs"`
}
type Server struct{
 mu sync.Mutex
 ledger Ledger
 dir,origin,comfy string
 token []byte
 client *http.Client
 lock *os.File
}
func freshID() (string,error){
 b:=make([]byte,16)
 if _,err:=rand.Read(b);err!=nil{return "",err}
 return hex.EncodeToString(b),nil
}
func New(dir,origin,comfy string,token []byte)(*Server,error){
 if len(token)<32||len(token)>256{return nil,errors.New("TOKEN_MINIMUM_32_BYTES_REQUIRED")}
 if origin==""||(!strings.HasPrefix(origin,"http://127.0.0.1:")&&!strings.HasPrefix(origin,"https://")){
  return nil,errors.New("PINNED_HTTPS_OR_LOCAL_ORIGIN_REQUIRED")
 }
 if !strings.HasPrefix(comfy,"http://") {return nil,errors.New("INTERNAL_WORKER_HTTP_REQUIRED")}
 u,err:=url.Parse(comfy)
 if err!=nil||u.User!=nil||u.RawQuery!=""||u.Fragment!=""||u.Path!=""||u.Hostname()==""{return nil,errors.New("INVALID_COMFY_ENDPOINT")}
 if err=os.MkdirAll(dir,0700);err!=nil{return nil,err}
 f,err:=os.OpenFile(filepath.Join(dir,"controller.lock"),os.O_CREATE|os.O_RDWR,0600)
 if err!=nil{return nil,err}
 if err=syscall.Flock(int(f.Fd()),syscall.LOCK_EX|syscall.LOCK_NB);err!=nil{f.Close();return nil,errors.New("SINGLE_CONTROLLER_LEASE_HELD")}
 s:=&Server{dir:dir,origin:origin,comfy:comfy,token:bytes.Clone(token),lock:f,
 client:&http.Client{Timeout:10*time.Second},ledger:Ledger{Schema:"conditioning-ledger/v1",Jobs:map[string]*Job{},Batches:map[string]Batch{}}}
 raw,err:=os.ReadFile(filepath.Join(dir,"ledger.json"))
 if err==nil {
  d:=json.NewDecoder(bytes.NewReader(raw));d.DisallowUnknownFields()
  if d.Decode(&s.ledger)!=nil||s.ledger.Schema!="conditioning-ledger/v1"||s.ledger.Jobs==nil||s.ledger.Batches==nil{
   s.Close();return nil,errors.New("LEDGER_UNTRUSTED")
  }
  // An interrupted job is UNKNOWN, never silently requeued (duplicate GPU work).
  changed:=false
  for _,j:=range s.ledger.Jobs {
   if j.State=="RUNNING"||j.State=="CANCEL_REQUESTED"{j.State="UNKNOWN_NEEDS_RECONCILIATION";j.Reason="CONTROLLER_RESTART";changed=true}
  }
  if changed {if err=s.save();err!=nil{s.Close();return nil,err}}
 } else if !os.IsNotExist(err){s.Close();return nil,err}
 return s,nil
}
func(s *Server)Close(){if s.lock!=nil{syscall.Flock(int(s.lock.Fd()),syscall.LOCK_UN);s.lock.Close();s.lock=nil}}
func(s *Server)save()error {
 data,err:=json.MarshalIndent(s.ledger,"","  ")
 if err!=nil{return err}
 tmp,err:=os.CreateTemp(s.dir,".ledger-")
 if err!=nil{return err}
 defer os.Remove(tmp.Name())
 if err=tmp.Chmod(0600);err!=nil{tmp.Close();return err}
 if _,err=tmp.Write(data);err!=nil{tmp.Close();return err}
 if err=tmp.Sync();err!=nil{tmp.Close();return err}
 if err=tmp.Close();err!=nil{return err}
 if err=os.Rename(tmp.Name(),filepath.Join(s.dir,"ledger.json"));err!=nil{return err}
 d,err:=os.Open(s.dir);if err!=nil{return err};defer d.Close()
 return d.Sync()
}
func valid(j JobInput)bool{
 return j.Workflow=="toy-cnn-v1"&&j.Seed>=0&&j.Seed<=2147483647&&
  (j.Variant=="base"||j.Variant=="modified")&&j.Size>=32&&j.Size<=128&&j.Size%16==0
}
func(s *Server)submit(batch BatchRequest)([]string,bool,error){
 if !requestID.MatchString(batch.RequestID)||len(batch.Jobs)<1||len(batch.Jobs)>16{return nil,false,errors.New("INVALID_BOUNDED_BATCH")}
 for _,j:=range batch.Jobs {if !valid(j){return nil,false,errors.New("WORKFLOW_NOT_ALLOWLISTED")}}
 canonical,_:=json.Marshal(batch.Jobs)
 digest:=sha256.Sum256(canonical)
 want:=hex.EncodeToString(digest[:])
 s.mu.Lock();defer s.mu.Unlock()
 if old,exists:=s.ledger.Batches[batch.RequestID];exists {
  if old.Digest!=want{return nil,false,errors.New("IDEMPOTENCY_KEY_CONFLICT")}
  return append([]string(nil),old.JobIDs...),true,nil
 }
 ids:=make([]string,0,len(batch.Jobs))
 for _,req:=range batch.Jobs{
  id,err:=freshID();if err!=nil{return nil,false,err}
  ids=append(ids,id)
  s.ledger.Jobs[id]=&Job{ID:id,Request:req,State:"QUEUED",Submitted:time.Now().UTC().Format(time.RFC3339Nano)}
  s.ledger.Order=append(s.ledger.Order,id)
 }
 s.ledger.Batches[batch.RequestID]=Batch{Digest:want,JobIDs:ids}
 if err:=s.save();err!=nil{return nil,false,err}
 return ids,false,nil
}
func jsonOut(w http.ResponseWriter,status int,x any){
 w.Header().Set("Content-Type","application/json; charset=utf-8")
 w.WriteHeader(status);_ = json.NewEncoder(w).Encode(x)
}
func fail(w http.ResponseWriter,status int,reason string){jsonOut(w,status,map[string]any{"status":"HOLD","reason":reason})}
func(s *Server)authenticated(r *http.Request) (bool,bool){
 a:=r.Header.Get("Authorization")
 if strings.HasPrefix(a,"Bearer "){return subtle.ConstantTimeCompare([]byte(strings.TrimPrefix(a,"Bearer ")),s.token)==1,false}
 user,pass,ok:=r.BasicAuth()
 return ok&&user=="operator"&&subtle.ConstantTimeCompare([]byte(pass),s.token)==1,true
}
func(s *Server)ServeHTTP(w http.ResponseWriter,r *http.Request){
 w.Header().Set("Cache-Control","no-store")
 w.Header().Set("X-Content-Type-Options","nosniff")
 w.Header().Set("Referrer-Policy","no-referrer")
 w.Header().Set("Content-Security-Policy","default-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
 if r.URL.Path=="/healthz"{jsonOut(w,200,map[string]string{"status":"controller-alive-not-worker-admission"});return}
 ok,basic:=s.authenticated(r)
 if !ok {w.Header().Set("WWW-Authenticate",`Basic realm="Conditioning Lab"`);fail(w,401,"AUTHENTICATION_REQUIRED");return}
 switch {
 case r.URL.Path=="/"&&r.Method=="GET":
  s.ui(w,r)
 case r.URL.Path=="/ui/submit"&&r.Method=="POST":
  if !basic||!s.validCSRF(r){fail(w,403,"UI_ORIGIN_OR_CSRF_DENIED");return}
  if err:=r.ParseForm();err!=nil{fail(w,400,"INVALID_FORM");return}
  seed,err:=strconv.ParseInt(r.PostFormValue("seed"),10,64)
  if err!=nil {fail(w,400,"INVALID_SEED");return}
  key,err:=freshID();if err!=nil{fail(w,503,"RANDOMNESS_UNAVAILABLE");return}
  ids,_,err:=s.submit(BatchRequest{RequestID:key,Jobs:[]JobInput{{
   Workflow:"toy-cnn-v1",Seed:seed,Variant:r.PostFormValue("variant"),Size:64,
  }}})
  if err!=nil{fail(w,400,"INVALID_BOUNDED_JOB");return}
  http.Redirect(w,r,"/api/v1/jobs/"+ids[0],http.StatusSeeOther)
 case r.URL.Path=="/api/v1/capabilities"&&r.Method=="GET":
  jsonOut(w,200,map[string]any{"schema":"conditioning-capabilities/v1",
   "allowed_workflows":[]string{"toy-cnn-v1"},"max_batch":16,
   "production_generator_admitted":false,"model_acquisition":"MODEL_ARTIFACT_FOUNDRY_APPROVED_DIGEST_ONLY",
   "methods":[]string{"POST /api/v1/batches","GET /api/v1/jobs","GET /api/v1/jobs/{id}","GET /api/v1/jobs/{id}/image","POST /api/v1/jobs/{id}/cancel"},
   "workflow_schema":map[string]any{"workflow":"toy-cnn-v1","seed":"integer 0..2147483647","variant":[]string{"base","modified"},"size":"multiple of 16, 32..128"}})
 case r.URL.Path=="/api/v1/batches"&&r.Method=="POST":
  r.Body=http.MaxBytesReader(w,r.Body,maxBody)
  var b BatchRequest
  d:=json.NewDecoder(r.Body);d.DisallowUnknownFields()
  if d.Decode(&b)!=nil||d.Decode(new(any))!=io.EOF{fail(w,400,"INVALID_REQUEST_JSON");return}
  ids,replay,err:=s.submit(b)
  if err!=nil{
   if err.Error()=="IDEMPOTENCY_KEY_CONFLICT"{fail(w,409,err.Error())}else{fail(w,400,err.Error())}
   return
  }
  jsonOut(w,202,map[string]any{"status":"QUEUED_OR_EXISTING","job_ids":ids,"idempotent_replay":replay})
 case r.URL.Path=="/api/v1/jobs"&&r.Method=="GET":
  s.mu.Lock();rows:=make([]Job,0,len(s.ledger.Order))
  for _,id:=range s.ledger.Order{if j:=s.ledger.Jobs[id];j!=nil{rows=append(rows,*j)}}
  s.mu.Unlock();jsonOut(w,200,map[string]any{"jobs":rows})
 case strings.HasPrefix(r.URL.Path,"/api/v1/jobs/"):
  s.jobRoute(w,r)
 default:fail(w,404,"NOT_FOUND")
 }
}
func(s *Server)jobRoute(w http.ResponseWriter,r *http.Request){
 path:=strings.TrimPrefix(r.URL.Path,"/api/v1/jobs/")
 parts:=strings.Split(path,"/")
 if len(parts)>2||!slug.MatchString(parts[0]){fail(w,404,"JOB_NOT_FOUND");return}
 id:=parts[0]
 s.mu.Lock();j:=s.ledger.Jobs[id]
 var snapshot Job;if j!=nil{snapshot=*j}
 s.mu.Unlock()
 if j==nil{fail(w,404,"JOB_NOT_FOUND");return}
 if len(parts)==1&&r.Method=="GET"{jsonOut(w,200,snapshot);return}
 if len(parts)==2&&parts[1]=="image"&&r.Method=="GET"{
  if snapshot.ImageSHA256==""{fail(w,409,"IMAGE_NOT_AVAILABLE");return}
  raw,err:=os.ReadFile(filepath.Join(s.dir,"results",id+".png"))
  sum:=sha256.Sum256(raw)
  if err!=nil||hex.EncodeToString(sum[:])!=snapshot.ImageSHA256{fail(w,503,"RESULT_FILE_INTEGRITY_HOLD");return}
  w.Header().Set("Content-Type","image/png");w.Write(raw);return
 }
 if len(parts)==2&&parts[1]=="cancel"&&r.Method=="POST"{
  s.mu.Lock();defer s.mu.Unlock()
  if j=s.ledger.Jobs[id];j==nil{fail(w,404,"JOB_NOT_FOUND");return}
  if j.State=="QUEUED"{j.State="CANCELLED"}else if j.State=="RUNNING"{j.State="CANCEL_REQUESTED"}
  if err:=s.save();err!=nil{fail(w,503,"LEDGER_PERSIST_FAILED");return}
  jsonOut(w,200,map[string]string{"state":j.State});return
 }
 fail(w,404,"NOT_FOUND")
}
var home=template.Must(template.New("home").Parse(`<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Conditioning Lab Job Queue</title></head>
<body><main><h1>Conditioning Lab</h1>
<p>This is a synthetic model qualification queue. Production image-generation models are not admitted.</p>
<h2>Submit a toy-model job</h2><form method="post" action="/ui/submit">
<input type="hidden" name="csrf" value="{{.Token}}">
<p><label for="seed">Random seed</label> <input id="seed" name="seed" type="number" value="31" min="0" max="2147483647" required></p>
<fieldset><legend>Model treatment</legend>
<label><input type="radio" name="variant" value="base" checked> Original toy model</label>
<label><input type="radio" name="variant" value="modified"> Modified toy model</label></fieldset>
<button type="submit">Queue toy image</button></form>
<p><a href="/api/v1/jobs">View jobs and statuses (JSON)</a></p>
<p><a href="/api/v1/capabilities">API and agent capabilities (JSON)</a></p>
</main></body></html>`))
func(s *Server)ui(w http.ResponseWriter,r *http.Request){
 b:=make([]byte,24);if _,err:=rand.Read(b);err!=nil{fail(w,503,"RANDOMNESS_UNAVAILABLE");return}
 csrf:=hex.EncodeToString(b)
 http.SetCookie(w,&http.Cookie{Name:"conditioning_csrf",Value:csrf,Path:"/ui/",HttpOnly:true,
  Secure:strings.HasPrefix(s.origin,"https://"),SameSite:http.SameSiteStrictMode,MaxAge:900})
 w.Header().Set("Content-Type","text/html; charset=utf-8")
 _=home.Execute(w,map[string]string{"Token":csrf})
}
func(s *Server)validCSRF(r *http.Request)bool{
 if r.Header.Get("Origin")!=s.origin{return false}
 c,err:=r.Cookie("conditioning_csrf")
 if err!=nil{return false}
 token:=r.PostFormValue("csrf")
 return len(token)==48&&subtle.ConstantTimeCompare([]byte(token),[]byte(c.Value))==1
}
func(s *Server)workerReady()bool{
 ctx,cancel:=context.WithTimeout(context.Background(),2*time.Second);defer cancel()
 req,_:=http.NewRequestWithContext(ctx,"GET",s.comfy+"/system_stats",nil)
 resp,err:=s.client.Do(req);if err!=nil{return false};defer resp.Body.Close()
 return resp.StatusCode==200
}
func(s *Server)runLoop(ctx context.Context){
 t:=time.NewTicker(350*time.Millisecond);defer t.Stop()
 for {select{case<-ctx.Done():return;case<-t.C:
  if !s.workerReady(){continue}
  s.mu.Lock()
  var item *Job
  for _,id:=range s.ledger.Order{j:=s.ledger.Jobs[id];if j!=nil&&j.State=="QUEUED"{j.State="RUNNING";item=j;break}}
  if item==nil{s.mu.Unlock();continue}
  if err:=s.save();err!=nil{item.State="UNKNOWN_NEEDS_RECONCILIATION";s.mu.Unlock();continue}
  snapshot:=*item;s.mu.Unlock()
  image,pid,err:=s.execute(snapshot.Request)
  s.mu.Lock();target:=s.ledger.Jobs[snapshot.ID]
  if target!=nil{
   target.NativePromptID=pid
   if err!=nil{
    target.State="UNKNOWN_NEEDS_RECONCILIATION";target.Reason="WORKER_OUTPUT_OR_ACK_AMBIGUOUS"
   }else{
    digest,writeErr:=s.saveImage(snapshot.ID,image)
    if writeErr!=nil{target.State="UNKNOWN_NEEDS_RECONCILIATION";target.Reason="OUTPUT_DURABILITY_UNKNOWN"
    }else{
     target.ImageSHA256=digest
     if target.State=="CANCEL_REQUESTED"{target.State="COMPLETED_AFTER_CANCEL_REQUEST"
     }else{target.State="COMPLETED"}
    }
   }
   if e:=s.save();e!=nil{log.Printf("ledger postflight integrity HOLD: %s",e)}
  }
  s.mu.Unlock()
 }}
}
func(s *Server)saveImage(id string,buf []byte)(string,error){
 if len(buf)<28||!bytes.Equal(buf[:8],[]byte{137,80,78,71,13,10,26,10})||len(buf)>8*1024*1024{return "",errors.New("PNG_BOUNDED")}
 dir:=filepath.Join(s.dir,"results")
 if err:=os.MkdirAll(dir,0700);err!=nil{return "",err}
 file,err:=os.CreateTemp(dir,".image-")
 if err!=nil{return "",err};defer os.Remove(file.Name())
 if err=file.Chmod(0600);err!=nil{file.Close();return "",err}
 if _,err=file.Write(buf);err!=nil{file.Close();return "",err}
 if err=file.Sync();err!=nil{file.Close();return "",err}
 if err=file.Close();err!=nil{return "",err}
 if err=os.Rename(file.Name(),filepath.Join(dir,id+".png"));err!=nil{return "",err}
 d,err:=os.Open(dir);if err!=nil{return "",err};defer d.Close()
 if err=d.Sync();err!=nil{return "",err}
 sum:=sha256.Sum256(buf);return hex.EncodeToString(sum[:]),nil
}
func(s *Server)execute(job JobInput)([]byte,string,error){
 graph:=map[string]any{
  "1":map[string]any{"class_type":"TinyTorchConditionerFixture","inputs":map[string]any{
   "seed":job.Seed,"variant":job.Variant,"size":job.Size}},
  "2":map[string]any{"class_type":"SaveImage","inputs":map[string]any{"images":[]any{"1",0},"filename_prefix":"controller-toy"}},
 }
 payload,_:=json.Marshal(map[string]any{"prompt":graph,"client_id":"conditioning-controller"})
 req,_:=http.NewRequest("POST",s.comfy+"/prompt",bytes.NewReader(payload));req.Header.Set("Content-Type","application/json")
 resp,err:=s.client.Do(req);if err!=nil{return nil,"",err};defer resp.Body.Close()
 if resp.StatusCode!=200{return nil,"",errors.New("NATIVE_QUEUE_REJECTED")}
 var accepted struct{PromptID string `json:"prompt_id"`}
 if err=json.NewDecoder(io.LimitReader(resp.Body,4096)).Decode(&accepted);err!=nil{return nil,"",err}
 if len(accepted.PromptID)<8||len(accepted.PromptID)>128{return nil,"",errors.New("NO_NATIVE_PROMPT_ID")}
 pid:=accepted.PromptID
 deadline:=time.Now().Add(90*time.Second)
 for time.Now().Before(deadline){
  time.Sleep(500*time.Millisecond)
  result,err:=s.client.Get(s.comfy+"/history/"+url.PathEscape(pid))
  if err!=nil{return nil,pid,err}
  if result.StatusCode!=200{result.Body.Close();return nil,pid,errors.New("HISTORY_FAILURE")}
  var parsed map[string]struct{
   Status struct{StatusStr string `json:"status_str"`} `json:"status"`
   Outputs map[string]struct{Images []struct{
    Filename string `json:"filename"`
    Subfolder string `json:"subfolder"`
    Type string `json:"type"`
   } `json:"images"`} `json:"outputs"`
  }
  er:=json.NewDecoder(io.LimitReader(result.Body,256*1024)).Decode(&parsed);result.Body.Close()
  if er!=nil{return nil,pid,er}
  record,ok:=parsed[pid];if !ok{continue}
  if record.Status.StatusStr=="error"{return nil,pid,errors.New("NATIVE_WORKFLOW_ERROR")}
  images:=record.Outputs["2"].Images
  if len(images)!=1{return nil,pid,errors.New("OUTPUT_IMAGE_CARDINALITY")}
  f:=images[0];if len(f.Filename)>128||f.Type!="output"{return nil,pid,errors.New("OUTPUT_PATH_NOT_ALLOWED")}
  q:=url.Values{"filename":[]string{f.Filename},"subfolder":[]string{f.Subfolder},"type":[]string{"output"}}
  imgResp,er:=s.client.Get(s.comfy+"/view?"+q.Encode());if er!=nil{return nil,pid,er}
  if imgResp.StatusCode!=200{imgResp.Body.Close();return nil,pid,errors.New("IMAGE_NOT_FOUND")}
  png,er:=io.ReadAll(io.LimitReader(imgResp.Body,8*1024*1024+1));imgResp.Body.Close()
  if er!=nil||len(png)>8*1024*1024{return nil,pid,errors.New("IMAGE_OVERSIZED")}
  return png,pid,nil
 }
 return nil,pid,errors.New("NATIVE_HISTORY_TIMEOUT")
}
func main(){
 secretPath:=os.Getenv("CONTROLLER_TOKEN_FILE")
 if secretPath==""{log.Fatal("CONTROLLER_TOKEN_FILE_REQUIRED")}
 secret,err:=os.ReadFile(secretPath);if err!=nil{log.Fatal("TOKEN_FILE_UNREADABLE")}
 secret=bytes.TrimSpace(secret)
 dir:=os.Getenv("CONTROLLER_STATE_DIR");if dir==""{log.Fatal("CONTROLLER_STATE_DIR_REQUIRED")}
 origin:=os.Getenv("CONTROLLER_UI_ORIGIN");comfy:=os.Getenv("CONTROLLER_COMFY_URL")
 if comfy==""{comfy="http://127.0.0.1:8188"}
 bind:=os.Getenv("CONTROLLER_BIND");if bind==""{bind="127.0.0.1:8090"}
 s,err:=New(dir,origin,comfy,secret);if err!=nil{log.Fatal(err)};defer s.Close()
 ctx,cancel:=context.WithCancel(context.Background());defer cancel()
 go s.runLoop(ctx)
 server:=&http.Server{Addr:bind,Handler:s,ReadHeaderTimeout:5*time.Second,
  ReadTimeout:15*time.Second,WriteTimeout:15*time.Second,IdleTimeout:30*time.Second}
 log.Printf("conditioning controller listening on %s (internal only)",bind)
 if err:=server.ListenAndServe();err!=nil&&err!=http.ErrServerClosed{log.Fatal(err)}
}
