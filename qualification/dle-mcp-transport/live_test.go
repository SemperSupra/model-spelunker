package main

import (
 "context"
 "encoding/json"
 "net/http"
 "net/http/httptest"
 "os"
 "strconv"
 "testing"
 "time"

 "github.com/modelcontextprotocol/go-sdk/mcp"
)

// This test is opt-in and runs ONLY with public-source read-only GitHub
// authority and a separately built/pinned observer executable.
// No project DLE semantic acceptance is implied.
func TestLivePublicGitHubObserverThroughMCP(t *testing.T){
 bin:=os.Getenv("DLE_OBSERVER_BIN")
 if bin==""{t.Skip("native source observer not supplied")}
 repo:=os.Getenv("DLE_OBSERVER_REPO")
 checkout:=os.Getenv("DLE_OBSERVER_CHECKOUT")
 issue,err:=strconv.Atoi(os.Getenv("DLE_OBSERVER_ISSUE"))
 if err!=nil||repo==""||checkout==""{t.Fatal("missing pinned public source input")}
 provider:=observerProvider{bin:bin,repo:repo,issue:issue,checkout:checkout}
 ctx,cancel:=context.WithTimeout(context.Background(),45*time.Second);defer cancel()
 expected,err:=provider.Observe(ctx);if err!=nil{t.Fatal(err)}
 if err:=validate(expected,repo,issue);err!=nil{t.Fatal(err)}
 web:=httptest.NewServer(newHTTPHandler(provider,repo,issue,sampleToken));defer web.Close()
 client:=mcp.NewClient(&mcp.Implementation{Name:"public-source-conformance",Version:"0.1.0"},nil)
 session,err:=client.Connect(ctx,&mcp.StreamableClientTransport{
  Endpoint:web.URL+"/mcp",
  HTTPClient:&http.Client{Transport:bearerTransport{base:http.DefaultTransport}},
 },nil)
 if err!=nil{t.Fatal(err)}
 defer session.Close()
 got,err:=session.CallTool(ctx,&mcp.CallToolParams{Name:"dle_observe",Arguments:map[string]any{}})
 if err!=nil||got.IsError{t.Fatalf("source tool failed %v",err)}
 b,err:=json.Marshal(got.StructuredContent);if err!=nil{t.Fatal(err)}
 var decoded Result
 if err=json.Unmarshal(b,&decoded);err!=nil{t.Fatal(err)}
 if decoded.Status!="OBSERVED_SOURCE_ONLY"||decoded.Observation.Repository!=repo||
     decoded.Observation.IssueNumber!=issue||decoded.Observation.IssueBodySHA256!=expected.IssueBodySHA256||
     decoded.Observation.GitHubVerified||decoded.MutationPerformed{
     t.Fatalf("source scope/grade mismatch: %+v",decoded)
 }
}
