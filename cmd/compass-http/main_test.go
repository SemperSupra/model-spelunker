package main

import (
 "context"
 "encoding/json"
 "fmt"
 "net/http"
 "net/http/httptest"
 "os"
 "path/filepath"
 "runtime"
 "strings"
 "testing"
 "time"
)
func fixtureService(t *testing.T)(*service,string,string){
 t.Helper()
 dir:=t.TempDir()
 tokenFile:=filepath.Join(dir,"token")
 snapshotFile:=filepath.Join(dir,"snapshot.json")
 if err:=os.WriteFile(tokenFile,[]byte(strings.Repeat("A",64)+"\n"),0600);err!=nil{t.Fatal(err)}
 if err:=os.WriteFile(snapshotFile,[]byte(`{"schema":"test","observed_at":"synthetic"}`),0600);err!=nil{t.Fatal(err)}
 fake:=func(_ context.Context,raw []byte)([]byte,error){
  var req rpcRequest
  if err:=json.Unmarshal(raw,&req);err!=nil{return nil,err}
  switch req.Method{
  case "initialize","ping","tools/list":
   return []byte(fmt.Sprintf(`{"jsonrpc":"2.0","id":%s,"result":{"tools":[]}}`,req.ID)),nil
  case "tools/call":
   return []byte(fmt.Sprintf(`{"jsonrpc":"2.0","id":%s,"result":{"content":[{"type":"text","text":"[{\"model_id\":\"fake\"}]"}]}}`,req.ID)),nil
  default:return nil,fmt.Errorf("unexpected method")
  }
 }
 return &service{tokenFile:tokenFile,snapshotFile:snapshotFile,execute:fake,slots:make(chan struct{},8)},tokenFile,snapshotFile
}
func call(t *testing.T,s *service,method,path,body,auth string)*httptest.ResponseRecorder {
 t.Helper()
 req:=httptest.NewRequest(method,path,strings.NewReader(body))
 if auth!=""{req.Header.Set("Authorization",auth)}
 w:=httptest.NewRecorder()
 s.handler().ServeHTTP(w,req)
 return w
}
func TestLivenessNotModelReady(t *testing.T){
 s,_,_:=fixtureService(t)
 w:=call(t,s,"GET","/healthz","","")
 if w.Code!=200||!strings.Contains(w.Body.String(),`"backend_ready":"UNKNOWN"`){t.Fatalf("false readiness: %d %s",w.Code,w.Body)}
}
func TestReadOnlyAuthenticationAndNoSecretLeak(t *testing.T){
 s,_,_:=fixtureService(t)
 for _,p:=range []string{"/v1/snapshot","/v1/venue/example","/v1/recommend","/mcp"}{
  method:="GET";if p=="/v1/recommend"||p=="/mcp"{method="POST"}
  w:=call(t,s,method,p,`{}`,"")
  if w.Code!=401||strings.Contains(w.Body.String(),strings.Repeat("A",64)){t.Fatalf("%s %d %s",p,w.Code,w.Body)}
 }
 wrong:=call(t,s,"GET","/v1/snapshot","","Bearer "+strings.Repeat("B",64))
 if wrong.Code!=401{t.Fatalf("wrong token permitted: %d",wrong.Code)}
}
func TestPersistedExternalStateAndRotation(t *testing.T){
 s,tokenFile,snapshotFile:=fixtureService(t)
 token:="Bearer "+strings.Repeat("A",64)
 a:=call(t,s,"GET","/v1/snapshot","",token)
 if a.Code!=200||!strings.Contains(a.Body.String(),"synthetic"){t.Fatalf("missing external snapshot %d %s",a.Code,a.Body)}
 // Runtime replacement: new server instance sees the same external state.
 second:=&service{tokenFile:tokenFile,snapshotFile:snapshotFile,execute:s.execute,slots:make(chan struct{},8)}
 b:=call(t,second,"GET","/v1/snapshot","",token)
 if b.Code!=200||a.Body.String()!=b.Body.String(){t.Fatal("external state lost across instance recreation")}
 if err:=os.WriteFile(tokenFile,[]byte(strings.Repeat("C",64)),0600);err!=nil{t.Fatal(err)}
 if x:=call(t,second,"GET","/v1/snapshot","",token);x.Code!=401{t.Fatal("stale token accepted after external rotation")}
 if x:=call(t,second,"GET","/v1/snapshot","","Bearer "+strings.Repeat("C",64));x.Code!=200{t.Fatal("fresh token rejected")}
}
func TestTokenFilePermissionsFailClosed(t *testing.T){
 if runtime.GOOS=="windows"{t.Skip("POSIX host file mode enforced on TrueNAS/Linux runtime; Win32 ACL semantics differ")}
 s,tokenFile,_:=fixtureService(t)
 if err:=os.Chmod(tokenFile,0644);err!=nil{t.Fatal(err)}
 if _,err:=tokenFromFile(tokenFile);err==nil{t.Fatal("world-readable secret accepted")}
 if w:=call(t,s,"GET","/v1/snapshot","","Bearer "+strings.Repeat("A",64));w.Code!=401{t.Fatal("insecure secret authenticated")}
}
func TestMCPWhitelistAndBoundedInput(t *testing.T){
 s,_,_:=fixtureService(t)
 auth:="Bearer "+strings.Repeat("A",64)
 valid:=`{"jsonrpc":"2.0","id":1,"method":"tools/list"}`
 if w:=call(t,s,"POST","/mcp",valid,auth);w.Code!=200||!strings.Contains(w.Body.String(),"tools"){t.Fatalf("valid MCP refused: %d %s",w.Code,w.Body)}
 bad:=`{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"execute_shell","arguments":{}}}`
 if w:=call(t,s,"POST","/mcp",bad,auth);w.Code!=400{t.Fatalf("arbitrary tool call permitted: %d",w.Code)}
 for _,payload:=range []string{`{"jsonrpc":"1.0","id":3,"method":"tools/list"}`,
  `{"jsonrpc":"2.0","id":3,"method":"unknown"}`,
  strings.Repeat("x",maxRequest+1)} {
  if w:=call(t,s,"POST","/mcp",payload,auth);w.Code!=400{t.Fatalf("invalid MCP admitted: %d",w.Code)}
 }
 if w:=call(t,s,"POST","/mcp",`{"jsonrpc":"2.0","method":"notifications/initialized"}`,auth);w.Code!=202{t.Fatal("notification not acknowledged without reply",w.Code)}
}
func TestRecommendationIsExplicitlyUnqualified(t *testing.T){
 s,_,_:=fixtureService(t)
 auth:="Bearer "+strings.Repeat("A",64)
 w:=call(t,s,"POST","/v1/recommend",`{"task_family":"code_refactor","only_sovereign_local":true}`,auth)
 if w.Code!=200||!strings.Contains(w.Body.String(),`"qualification":"UNKNOWN"`)||!strings.Contains(w.Body.String(),`"automatic_admission":false`){t.Fatalf("fabricated admission: %d %s",w.Code,w.Body)}
 if w:=call(t,s,"POST","/v1/recommend",`{"task_family":"../garbage"}`,auth);w.Code!=400{t.Fatal("unsafe family accepted",w.Code)}
 if w:=call(t,s,"POST","/v1/recommend",`{"task_family":"valid","cloud_auth_token":"secret"}`,auth);w.Code!=400{t.Fatal("unknown secret property accepted",w.Code)}
}
func TestBoundedConcurrency(t *testing.T){
 s,_,_:=fixtureService(t)
 for i:=0;i<cap(s.slots);i++{s.slots<-struct{}{}}
 w:=call(t,s,"GET","/v1/snapshot","","Bearer "+strings.Repeat("A",64))
 if w.Code!=429{t.Fatalf("unbounded concurrent load: %d",w.Code)}
}
func TestNoExternalSnapshotFailsClosed(t *testing.T){
 s,_,file:=fixtureService(t)
 if err:=os.Remove(file);err!=nil{t.Fatal(err)}
 if w:=call(t,s,"GET","/v1/snapshot","","Bearer "+strings.Repeat("A",64));w.Code!=503{t.Fatal("missing external evidence claimed",w.Code)}
}
func TestRunnerHasAbsoluteBoundAndError(t *testing.T){
 s,_,_:=fixtureService(t)
 s.execute=func(ctx context.Context,_ []byte)([]byte,error){
  select {case <-time.After(10*time.Millisecond):return nil,fmt.Errorf("offline");case <-ctx.Done():return nil,ctx.Err()}
 }
 w:=call(t,s,"POST","/mcp",`{"jsonrpc":"2.0","id":4,"method":"ping"}`,"Bearer "+strings.Repeat("A",64))
 if w.Code!=503{t.Fatal("backend failure incorrectly successful",w.Code)}
}
func TestMethodRestriction(t *testing.T){
 s,_,_:=fixtureService(t)
 w:=call(t,s,http.MethodPut,"/healthz","","")
 if w.Code!=405{t.Fatal(w.Code)}
}

func TestBackendRPCResponseIDMustMatchRequest(t *testing.T){
 s,_,_:=fixtureService(t)
 s.execute=func(_ context.Context,_ []byte)([]byte,error){
  return []byte(`{"jsonrpc":"2.0","id":999,"result":{}}`),nil
 }
 w:=call(t,s,"POST","/mcp",`{"jsonrpc":"2.0","id":5,"method":"ping"}`,"Bearer "+strings.Repeat("A",64))
 if w.Code!=503{t.Fatalf("foreign backend reply accepted: %d %s",w.Code,w.Body)}
}
func TestBackendRPCCannotOmitResultAndError(t *testing.T){
 s,_,_:=fixtureService(t)
 s.execute=func(_ context.Context,_ []byte)([]byte,error){
  return []byte(`{"jsonrpc":"2.0","id":1}`),nil
 }
 w:=call(t,s,"POST","/mcp",`{"jsonrpc":"2.0","id":1,"method":"ping"}`,"Bearer "+strings.Repeat("A",64))
 if w.Code!=503{t.Fatalf("incomplete backend reply accepted: %d %s",w.Code,w.Body)}
}
func TestBackendToolErrorFlagCannotBeLaunderedAsRecommendation(t *testing.T){
 s,_,_:=fixtureService(t)
 s.execute=func(_ context.Context,raw []byte)([]byte,error){
  var req rpcRequest
  if err:=json.Unmarshal(raw,&req);err!=nil{return nil,err}
  return []byte(fmt.Sprintf(`{"jsonrpc":"2.0","id":%s,"result":{"isError":true,"content":[{"type":"text","text":"[1]"}]}}`,req.ID)),nil
 }
 w:=call(t,s,"POST","/v1/recommend",`{"task_family":"code_refactor"}`,"Bearer "+strings.Repeat("A",64))
 if w.Code!=422{t.Fatalf("failed backend tool result laundered into success: %d %s",w.Code,w.Body)}
}
