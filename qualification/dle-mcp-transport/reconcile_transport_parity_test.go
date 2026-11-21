package main

import (
 "context"
 "crypto/sha256"
 "encoding/hex"
 "encoding/json"
 "net/http"
 "net/http/httptest"
 "os"
 "os/exec"
 "path/filepath"
 "reflect"
 "testing"
 "time"

 "github.com/modelcontextprotocol/go-sdk/mcp"
)

// The same externally configured, synthetic Go reconciliation executable
// must supply identical results to both terminal and web-capable MCP clients.
// This test does NOT prove real private semantic authority or OAuth readiness.
func TestConfiguredReconciliationStdioHTTPParity(t *testing.T){
 ctx,cancel:=context.WithTimeout(context.Background(),95*time.Second);defer cancel()
 root:=t.TempDir()
 reconciler:=filepath.Join(root,"synthetic-reconciler")
 transportBin:=filepath.Join(root,"mcp-server")
 for _,spec:=range []struct{dst,source string}{{reconciler,"./testdata/synthetic_reconciler"},{transportBin,"."}}{
  build:=exec.CommandContext(ctx,"go","build","-o",spec.dst,spec.source)
  if out,err:=build.CombinedOutput();err!=nil{t.Fatalf("build %s failed: %v; %s",spec.source,err,out)}
 }
 read:=func(path string)[]byte{
  data,err:=os.ReadFile(path);if err!=nil{t.Fatal(err)};return data
 }
 sha:=func(b []byte)string{d:=sha256.Sum256(b);return hex.EncodeToString(d[:])}
 authority:=filepath.Join(root,"dle.json")
 candidates:=filepath.Join(root,"candidates.json")
 if err:=os.WriteFile(authority,[]byte(`{"source":"https://example.invalid/o/r/issues/7","revision":"frozen-local"}`),0600);err!=nil{t.Fatal(err)}
 if err:=os.WriteFile(candidates,[]byte(`{"mode":"normal"}`),0600);err!=nil{t.Fatal(err)}
 pin:=sha(read(authority));binpin:=sha(read(reconciler))
 args:=[]string{"--mode=fixture","--transport=stdio","--repo=o/r","--issue=7",
  "--fixture=testdata/observed.json","--reconcile-bin="+reconciler,
  "--reconcile-bin-sha256="+binpin,"--candidates="+candidates,
  "--dle="+authority,"--dle-sha256="+pin}
 cli:=mcp.NewClient(&mcp.Implementation{Name:"agentic-cli-test",Version:"v0"},nil)
 cmd:=exec.CommandContext(ctx,transportBin,args...)
 term,err:=cli.Connect(ctx,&mcp.CommandTransport{Command:cmd},nil)
 if err!=nil{t.Fatal(err)};defer term.Close()
 fixture,err:=loadFixture("testdata/observed.json");if err!=nil{t.Fatal(err)}
 engine:=externalReconciler{binary:reconciler,binarySHA256:binpin,
  authorityFile:authority,candidateFile:candidates,authoritySHA256:pin}
 server:=httptest.NewServer(newHTTPHandlerWithReconciler(fixtureProvider{fixture},"o/r",7,sampleToken,engine))
 defer server.Close()
 web:=mcp.NewClient(&mcp.Implementation{Name:"web-chat-test",Version:"v0"},nil)
 remote,err:=web.Connect(ctx,&mcp.StreamableClientTransport{
  Endpoint:server.URL+"/mcp",
  HTTPClient:&http.Client{Transport:bearerTransport{base:http.DefaultTransport}},
 },nil)
 if err!=nil{t.Fatal(err)};defer remote.Close()
 call:=func(s *mcp.ClientSession) map[string]json.RawMessage{
  list,err:=s.ListTools(ctx,nil);if err!=nil{t.Fatal(err)}
  if len(list.Tools)!=3{t.Fatalf("expected 3 tools, got %d",len(list.Tools))}
  got:=map[string]json.RawMessage{}
  for _,name:=range []string{"dle_discover","dle_observe","dle_reconcile"}{
   result,err:=s.CallTool(ctx,&mcp.CallToolParams{Name:name,Arguments:map[string]any{}})
   if err!=nil||result.IsError{t.Fatalf("%s failed: %v: %+v",name,err,result)}
   b,err:=json.Marshal(result.StructuredContent);if err!=nil{t.Fatal(err)}
   got[name]=b
  }
  return got
 }
 fromCLI,fromHTTP:=call(term),call(remote)
 if !reflect.DeepEqual(fromCLI,fromHTTP){
  t.Fatalf("identical pinned executable+inputs yielded divergent MCP results: cli=%v remote=%v",fromCLI,fromHTTP)
 }
 var reconciled ReconcileSummary
 if err=json.Unmarshal(fromHTTP["dle_reconcile"],&reconciled);err!=nil{t.Fatal(err)}
 if reconciled.Status!="CANDIDATE_RECONCILIATION_ONLY"||
 reconciled.GitHubVerified||reconciled.MutationPerformed||
 reconciled.Counts["unknown"]!=1{t.Fatalf("incorrect candidate grade: %+v",reconciled)}
}
