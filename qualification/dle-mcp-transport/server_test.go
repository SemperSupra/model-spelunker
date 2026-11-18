package main

import (
    "context"
    "encoding/json"
    "errors"
    "io"
    "net/http"
    "net/http/httptest"
    "os"
    "os/exec"
    "path/filepath"
    "reflect"
    "strings"
    "testing"
    "time"

    "github.com/modelcontextprotocol/go-sdk/mcp"
)

const sampleToken="synthetic-unit-test-only-token-1234567890"

type bearerTransport struct{ base http.RoundTripper }
func (t bearerTransport) RoundTrip(req *http.Request)(*http.Response,error){
    clone:=req.Clone(req.Context())
    clone.Header.Set("Authorization","Bearer "+sampleToken)
    return t.base.RoundTrip(clone)
}
type brokenProvider struct{}
func (brokenProvider) Observe(context.Context)(Observation,error){return Observation{},errors.New("untrusted observer unavailable")}

func callTools(t *testing.T,session *mcp.ClientSession) map[string]json.RawMessage{
    t.Helper()
    ctx,cancel:=context.WithTimeout(context.Background(),20*time.Second);defer cancel()
    list,err:=session.ListTools(ctx,nil)
    if err!=nil{t.Fatal(err)}
    if len(list.Tools)!=2{t.Fatalf("unexpected tool count %d",len(list.Tools))}
    names:=map[string]bool{}
    for _,v:=range list.Tools{names[v.Name]=true}
    if !names["dle_discover"]||!names["dle_observe"]{t.Fatalf("missing discovered tools: %v",names)}
    result:=map[string]json.RawMessage{}
    for _,name:=range []string{"dle_discover","dle_observe"}{
        got,err:=session.CallTool(ctx,&mcp.CallToolParams{Name:name,Arguments:map[string]any{}})
        if err!=nil||got.IsError{t.Fatalf("%s call failed: %v, %+v",name,err,got)}
        b,err:=json.Marshal(got.StructuredContent);if err!=nil{t.Fatal(err)}
        result[name]=b
    }
    return result
}

func TestExactStdioAndHTTPParity(t *testing.T){
    fixture,err:=loadFixture("testdata/observed.json");if err!=nil{t.Fatal(err)}
    if err:=validate(fixture,"o/r",7);err!=nil{t.Fatal(err)}
    ctx,cancel:=context.WithTimeout(context.Background(),90*time.Second);defer cancel()
    binary:=filepath.Join(t.TempDir(),"dle-mcp-test")
    build:=exec.CommandContext(ctx,"go","build","-o",binary,".")
    if out,err:=build.CombinedOutput();err!=nil{t.Fatalf("build stdio provider: %v: %s",err,out)}
    client:=mcp.NewClient(&mcp.Implementation{Name:"transport-conformance",Version:"v0.0.1"},nil)
    cmd:=exec.CommandContext(ctx,binary,"--transport=stdio","--mode=fixture","--repo=o/r","--issue=7","--fixture=testdata/observed.json")
    stdio,err:=client.Connect(ctx,&mcp.CommandTransport{Command:cmd},nil);if err!=nil{t.Fatal(err)}
    defer stdio.Close()
    fromStdio:=callTools(t,stdio)

    httpSrv:=httptest.NewServer(newHTTPHandler(fixtureProvider{fixture},"o/r",7,sampleToken))
    defer httpSrv.Close()
    apiClient:=mcp.NewClient(&mcp.Implementation{Name:"transport-conformance",Version:"v0.0.1"},nil)
    transport:=&mcp.StreamableClientTransport{
        Endpoint:httpSrv.URL+"/mcp",
        HTTPClient:&http.Client{Transport:bearerTransport{base:http.DefaultTransport}},
    }
    remote,err:=apiClient.Connect(ctx,transport,nil);if err!=nil{t.Fatal(err)}
    defer remote.Close()
    fromHTTP:=callTools(t,remote)
    if !reflect.DeepEqual(fromStdio,fromHTTP){
        t.Fatalf("transport changed semantics: stdio=%v http=%v",fromStdio,fromHTTP)
    }
    for _,v:=range fromHTTP{
        if strings.Contains(string(v),"ghp_")||strings.Contains(string(v),"private_token")||strings.Contains(string(v),"# Mission"){
            t.Fatal("unbounded source or simulated secret leaked")
        }
    }
}

func TestHTTPDeniesMissingOrIncorrectBearer(t *testing.T){
    fixture,err:=loadFixture("testdata/observed.json");if err!=nil{t.Fatal(err)}
    srv:=httptest.NewServer(newHTTPHandler(fixtureProvider{fixture},"o/r",7,sampleToken))
    defer srv.Close()
    for _,header:=range []string{"","Bearer incorrect","Basic example"}{
        req,err:=http.NewRequest("POST",srv.URL+"/mcp",strings.NewReader(`{"jsonrpc":"2.0","method":"tools/list","id":1}`))
        if err!=nil{t.Fatal(err)}
        req.Header.Set("Content-Type","application/json")
        if header!=""{req.Header.Set("Authorization",header)}
        res,err:=http.DefaultClient.Do(req);if err!=nil{t.Fatal(err)}
        io.Copy(io.Discard,res.Body);res.Body.Close()
        if res.StatusCode!=401{t.Fatalf("bad bearer accepted: %q status=%d",header,res.StatusCode)}
    }
}
func TestFailClosedSourceAndNoWriteTools(t *testing.T){
    fixture,err:=loadFixture("testdata/observed.json");if err!=nil{t.Fatal(err)}
    fixture.GitHubVerified=true
    if err:=validate(fixture,"o/r",7);err==nil{t.Fatal("self-attested source accepted")}
    fixture.GitHubVerified=false
    fixture.MutationPerformed=true
    if err:=validate(fixture,"o/r",7);err==nil{t.Fatal("mutating source accepted")}
    fixture.MutationPerformed=false
    fixture.Repository="wrong/repo"
    if err:=validate(fixture,"o/r",7);err==nil{t.Fatal("wrong source accepted")}
    if _,err:=brokenProvider{}.Observe(context.Background());err==nil{t.Fatal("error suppressed")}
    if _,err:=os.Stat("testdata/observed.json");err!=nil{t.Fatal(err)}
}
