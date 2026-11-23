// Command compass-http is a bounded, read-only HTTP/MCP adapter to the existing
// model-compass CLI. It does not perform model inference or own model identities.
// TrueNAS Foundry owns the container lifecycle; external state is read-only here.
package main

import (
 "bytes"
 "context"
 "crypto/subtle"
 "encoding/json"
 "errors"
 "flag"
 "fmt"
 "io"
 "net/http"
 "os"
 "os/exec"
 "path/filepath"
 "regexp"
 "strings"
 "time"
)

const maxRequest = 16 << 10
const maxResponse = 1 << 20
const maxSnapshot = 1 << 20
const maxToken = 4096

var identifier = regexp.MustCompile(`^[a-z0-9][a-z0-9_-]{0,63}$`)
var allowedTools = map[string]bool{"recommend_models":true,"get_venue_catalog":true,"get_sommelier_specials":true}
var allowedMethods = map[string]bool{"initialize":true,"ping":true,"tools/list":true,"tools/call":true,"notifications/initialized":true}

type rpcRequest struct {
 JSONRPC string `json:"jsonrpc"`
 ID json.RawMessage `json:"id,omitempty"`
 Method string `json:"method"`
 Params json.RawMessage `json:"params,omitempty"`
}
type callParams struct {
 Name string `json:"name"`
 Arguments json.RawMessage `json:"arguments"`
}
type runner func(context.Context, []byte) ([]byte,error)
type service struct {
 tokenFile string
 snapshotFile string
 execute runner
 slots chan struct{}
}
type configuration struct {
 listen, tokenFile, snapshotFile, modelBinary string
}
func configFromEnv() configuration {
 env:=func(k,d string)string {v:=os.Getenv(k);if v!="" {return v};return d}
 return configuration{
  listen:env("COMPASS_LISTEN",":8088"),
  tokenFile:env("COMPASS_TOKEN_FILE","/run/secrets/compass_token"),
  snapshotFile:env("COMPASS_SNAPSHOT_FILE","/state/snapshot.json"),
  modelBinary:env("COMPASS_MODEL_BIN","/usr/local/bin/model-compass"),
 }
}
func tokenFromFile(path string)([]byte,error){
 fi,err:=os.Stat(path);if err!=nil{return nil,fmt.Errorf("missing token file: %w",err)}
 if !fi.Mode().IsRegular()||fi.Size()>maxToken {return nil,errors.New("token file invalid")}
 // Do not allow world-readable credentials. On ACL-based platforms configure
 // the secret bind mount for the container service user.
 if fi.Mode().Perm()&0007!=0 {return nil,errors.New("token file must not be world-accessible")}
 b,err:=os.ReadFile(path);if err!=nil{return nil,err}
 b=bytes.TrimSpace(b)
 if len(b)<32||len(b)>maxToken||bytes.IndexByte(b,0)>=0{return nil,errors.New("token length/encoding invalid")}
 return b,nil
}
func (s *service) authorized(r *http.Request) bool {
 token,err:=tokenFromFile(s.tokenFile);if err!=nil{return false}
 auth:=r.Header.Get("Authorization")
 if !strings.HasPrefix(auth,"Bearer ") {return false}
 supplied:=[]byte(strings.TrimPrefix(auth,"Bearer "))
 if len(supplied)!=len(token){return false}
 return subtle.ConstantTimeCompare(supplied,token)==1
}
func writeJSON(w http.ResponseWriter,code int,x interface{}){
 w.Header().Set("Content-Type","application/json")
 w.Header().Set("Cache-Control","no-store")
 w.Header().Set("X-Content-Type-Options","nosniff")
 w.WriteHeader(code)
 _=json.NewEncoder(w).Encode(x)
}
func fail(w http.ResponseWriter,code int,reason string){
 writeJSON(w,code,map[string]interface{}{"status":"ERROR","reason":reason})
}
func safeDecode(r *http.Request,target interface{})error {
 if r.ContentLength>maxRequest{return errors.New("request too large")}
 body,err:=io.ReadAll(io.LimitReader(r.Body,maxRequest+1));if err!=nil{return err}
 if len(body)>maxRequest{return errors.New("request too large")}
 dec:=json.NewDecoder(bytes.NewReader(body));dec.DisallowUnknownFields()
 if err:=dec.Decode(target);err!=nil{return err}
 var extra interface{}
 if err:=dec.Decode(&extra);err!=io.EOF{return errors.New("trailing JSON or multiple documents")}
 return nil
}
func invokeModel(program string)runner{
 return func(ctx context.Context,payload []byte)([]byte,error){
  if len(payload)>maxRequest{return nil,errors.New("input too large")}
  cctx,cancel:=context.WithTimeout(ctx,8*time.Second)
  defer cancel()
  cmd:=exec.CommandContext(cctx,program,"-mcp")
  // No shell, no untrusted argv, and no service credentials in subprocess args.
  cmd.Stdin=bytes.NewReader(append(append([]byte{},payload...), '\n'))
  var stdout bytes.Buffer
  cmd.Stdout=&boundedWriter{buf:&stdout,limit:maxResponse}
  // Avoid reflecting host command errors or leaked stderr into response.
  if err:=cmd.Run();err!=nil{return nil,errors.New("model-compass subprocess unavailable or timed out")}
  out:=bytes.TrimSpace(stdout.Bytes())
  if len(out)==0||len(out)>maxResponse||!json.Valid(out){return nil,errors.New("invalid or oversized model-compass response")}
  return append([]byte(nil),out...),nil
 }
}
type boundedWriter struct {buf *bytes.Buffer;limit int}
func(w *boundedWriter)Write(b []byte)(int,error){
 if w.buf.Len()+len(b)>w.limit{return 0,errors.New("output bound exceeded")}
 return w.buf.Write(b)
}
func validToolCall(req rpcRequest)bool {
 if req.Method!="tools/call"{return true}
 var p callParams
 if err:=json.Unmarshal(req.Params,&p);err!=nil{return false}
 return allowedTools[p.Name]
}
func (s *service) runRPC(ctx context.Context,req rpcRequest)(json.RawMessage,error){
 body,err:=json.Marshal(req);if err!=nil{return nil,err}
 out,err:=s.execute(ctx,body);if err!=nil{return nil,err}
 var response struct {JSONRPC string `json:"jsonrpc"`;ID json.RawMessage `json:"id"`}
 if err:=json.Unmarshal(out,&response);err!=nil||response.JSONRPC!="2.0"{return nil,errors.New("malformed backend RPC response")}
 return json.RawMessage(out),nil
}
func makeCall(id int,name string,args interface{})(rpcRequest,error){
 b,err:=json.Marshal(args)
 if err!=nil{return rpcRequest{},err}
 params,err:=json.Marshal(map[string]interface{}{"name":name,"arguments":json.RawMessage(b)})
 if err!=nil{return rpcRequest{},err}
 return rpcRequest{JSONRPC:"2.0",ID:json.RawMessage(fmt.Sprintf("%d",id)),Method:"tools/call",Params:params},nil
}
func extractToolText(raw json.RawMessage)(json.RawMessage,error){
 var response struct {
  Error *struct{Code int `json:"code"`;Message string `json:"message"`} `json:"error"`
  Result struct{Content []struct{Type string `json:"type"`;Text string `json:"text"`} `json:"content"`} `json:"result"`
 }
 if err:=json.Unmarshal(raw,&response);err!=nil{return nil,err}
 if response.Error!=nil{return nil,errors.New("backend tool rejected request")}
 if len(response.Result.Content)!=1||response.Result.Content[0].Type!="text"{return nil,errors.New("invalid tool content")}
 data:=[]byte(response.Result.Content[0].Text)
 if len(data)>maxResponse||!json.Valid(data){return nil,errors.New("invalid tool JSON")}
 return json.RawMessage(data),nil
}
func (s *service) handler()http.Handler{
 mux:=http.NewServeMux()
 mux.HandleFunc("/healthz",func(w http.ResponseWriter,r *http.Request){
  if r.Method!="GET" {fail(w,405,"method_not_allowed");return}
  writeJSON(w,200,map[string]interface{}{"status":"UP","scope":"adapter_liveness_only","backend_ready":"UNKNOWN"})
 })
 protected:=func(fn http.HandlerFunc)http.HandlerFunc{
  return func(w http.ResponseWriter,r *http.Request){
   if !s.authorized(r){fail(w,401,"authentication_required");return}
   select{case s.slots<-struct{}{}:defer func(){<-s.slots}();default:fail(w,429,"bounded_concurrency_exceeded");return}
   fn(w,r)
  }
 }
 mux.HandleFunc("/v1/snapshot",protected(func(w http.ResponseWriter,r *http.Request){
  if r.Method!="GET"{fail(w,405,"method_not_allowed");return}
  fi,err:=os.Stat(s.snapshotFile)
  if err!=nil||!fi.Mode().IsRegular()||fi.Size()>maxSnapshot{fail(w,503,"external_snapshot_unavailable");return}
  b,err:=os.ReadFile(s.snapshotFile)
  if err!=nil||len(b)>maxSnapshot||!json.Valid(b){fail(w,503,"external_snapshot_invalid");return}
  var data json.RawMessage=b
  writeJSON(w,200,map[string]interface{}{"status":"EXTERNAL_SNAPSHOT_UNVERIFIED","snapshot":data})
 }))
 mux.HandleFunc("/v1/venue/",protected(func(w http.ResponseWriter,r *http.Request){
  if r.Method!="GET"{fail(w,405,"method_not_allowed");return}
  id:=strings.TrimPrefix(r.URL.Path,"/v1/venue/")
  if !identifier.MatchString(id){fail(w,400,"invalid_venue");return}
  req,_:=makeCall(1,"get_venue_catalog",map[string]string{"venue_id":id})
  raw,err:=s.runRPC(r.Context(),req);if err!=nil{fail(w,503,"backend_unavailable");return}
  data,err:=extractToolText(raw);if err!=nil{fail(w,422,"venue_unavailable");return}
  // Static catalog entries are NOT proof of installed weights or actual route.
  writeJSON(w,200,map[string]interface{}{"schema":"compass-advisory/v1","qualification":"UNKNOWN","route_status":"UNVERIFIED_STATIC_CATALOG","catalog":data})
 }))
 mux.HandleFunc("/v1/recommend",protected(func(w http.ResponseWriter,r *http.Request){
  if r.Method!="POST"{fail(w,405,"method_not_allowed");return}
  var p struct {
   TaskFamily string `json:"task_family"`
   EstimatedContextTokens int `json:"estimated_context_tokens"`
   OnlySovereignLocal bool `json:"only_sovereign_local"`
   MaxResults int `json:"max_results"`
  }
  if err:=safeDecode(r,&p);err!=nil{fail(w,400,"invalid_request");return}
  if !identifier.MatchString(p.TaskFamily)||p.EstimatedContextTokens<0||p.EstimatedContextTokens>1_000_000||p.MaxResults<0||p.MaxResults>10{
   fail(w,400,"invalid_request_constraints");return
  }
  req,_:=makeCall(2,"recommend_models",p)
  raw,err:=s.runRPC(r.Context(),req);if err!=nil{fail(w,503,"backend_unavailable");return}
  data,err:=extractToolText(raw);if err!=nil{fail(w,422,"recommendation_unavailable");return}
  writeJSON(w,200,map[string]interface{}{"schema":"compass-advisory/v1","qualification":"UNKNOWN","route_status":"UNVERIFIED_STATIC_CATALOG","automatic_admission":false,"advisory":data})
 }))
 mux.HandleFunc("/mcp",protected(func(w http.ResponseWriter,r *http.Request){
  if r.Method!="POST"{fail(w,405,"method_not_allowed");return}
  var req rpcRequest
  if err:=safeDecode(r,&req);err!=nil||req.JSONRPC!="2.0"||!allowedMethods[req.Method]||!validToolCall(req){
   fail(w,400,"unsupported_or_invalid_rpc");return
  }
  if len(req.ID)==0 {w.WriteHeader(202);return}
  raw,err:=s.runRPC(r.Context(),req);if err!=nil{fail(w,503,"backend_unavailable");return}
  writeJSON(w,200,raw)
 }))
 return mux
}
func main(){
 cfg:=configFromEnv()
 selfCheck:=flag.Bool("self-check",false,"check only the local adapter liveness")
 flag.Parse()
 if *selfCheck{
  c:=http.Client{Timeout:2*time.Second}
  resp,err:=c.Get("http://127.0.0.1:8088/healthz")
  if err!=nil{os.Exit(1)}
  defer resp.Body.Close()
  if resp.StatusCode!=200{os.Exit(1)}
  return
 }
 if !filepath.IsAbs(cfg.tokenFile)||!filepath.IsAbs(cfg.snapshotFile)||!filepath.IsAbs(cfg.modelBinary){
  fmt.Fprintln(os.Stderr,"invalid absolute configuration paths");os.Exit(2)
 }
 if _,err:=tokenFromFile(cfg.tokenFile);err!=nil{
  fmt.Fprintln(os.Stderr,"token file missing or insecure");os.Exit(2)
 }
 s:=&service{tokenFile:cfg.tokenFile,snapshotFile:cfg.snapshotFile,execute:invokeModel(cfg.modelBinary),slots:make(chan struct{},8)}
 srv:=&http.Server{Addr:cfg.listen,Handler:s.handler(),ReadHeaderTimeout:3*time.Second,ReadTimeout:5*time.Second,WriteTimeout:12*time.Second,IdleTimeout:20*time.Second,MaxHeaderBytes:8<<10}
 if err:=srv.ListenAndServe();err!=nil&&!errors.Is(err,http.ErrServerClosed){fmt.Fprintln(os.Stderr,"adapter listener failed");os.Exit(1)}
}
