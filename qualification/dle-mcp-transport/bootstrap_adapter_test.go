package main

import (
 "bytes"
 "context"
 "crypto/sha256"
 "encoding/hex"
 "encoding/json"
 "fmt"
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

const syntheticSource="https://github.com/o/r/issues/7"
const syntheticRevision="issue-sha256-synthetic-rev-4"
const syntheticDLEHash="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

func bootstrapFixture()BootstrapView {
 return BootstrapView{
  Schema:"dle-bootstrap-advisory-v1",
  Authority:syntheticSource,
  Revision:syntheticRevision,
  AuthoritySHA256:syntheticDLEHash,
  ProjectionFileSHA256:strings.Repeat("b",64),
  GitHubVerified:false,AdvisoryOnly:true,
  Mission:"Repair public synthetic workcell fixture",
  NextAction:"Read the immutable task and run verifier",
  Constraints:[]string{"No external release","Public synthetic inputs only"},
  Unknowns:[]string{"Live GitHub source not independently authenticated"},
  Accepted:[]bootstrapClaim{{ID:"decision-01",Text:"Use bounded evidence",Source:syntheticSource}},
 }
}

func writeBootstrap(t *testing.T)(bootstrapReader,string){
 t.Helper()
 body,err:=json.Marshal(bootstrapFixture());if err!=nil{t.Fatal(err)}
 path:=filepath.Join(t.TempDir(),"bootstrap.json")
 if err=os.WriteFile(path,body,0600);err!=nil{t.Fatal(err)}
 digest:=sha256.Sum256(body)
 hash:=hex.EncodeToString(digest[:])
 reader,err:=newBootstrapReader(path,hash,syntheticSource,syntheticRevision,syntheticDLEHash)
 if err!=nil{t.Fatal(err)}
 return *reader,path
}

func TestBootstrapDefaultAbsentAndAdmission(t *testing.T){
 fixture,err:=loadFixture("testdata/observed.json");if err!=nil{t.Fatal(err)}
 client:=mcp.NewClient(&mcp.Implementation{Name:"default-no-bootstrap",Version:"0.1"},nil)
 ctx,cancel:=context.WithTimeout(context.Background(),10*time.Second);defer cancel()
 srv:=httptest.NewServer(newHTTPHandler(fixtureProvider{fixture},"o/r",7,sampleToken));defer srv.Close()
 session,err:=client.Connect(ctx,&mcp.StreamableClientTransport{
  Endpoint:srv.URL+"/mcp",
  HTTPClient:&http.Client{Transport:bearerTransport{base:http.DefaultTransport}},
 },nil)
 if err!=nil{t.Fatal(err)};defer session.Close()
 tools,err:=session.ListTools(ctx,nil);if err!=nil{t.Fatal(err)}
 if len(tools.Tools)!=2{t.Fatalf("bootstrap was exposed without admission: %d",len(tools.Tools))}
}

func TestBootstrapStdioAndHTTPExactParity(t *testing.T){
 fixture,err:=loadFixture("testdata/observed.json");if err!=nil{t.Fatal(err)}
 reader,path:=writeBootstrap(t)
 ctx,cancel:=context.WithTimeout(context.Background(),90*time.Second);defer cancel()
 binary:=filepath.Join(t.TempDir(),"dle-mcp-bootstrap")
 build:=exec.CommandContext(ctx,"go","build","-o",binary,".")
 if out,err:=build.CombinedOutput();err!=nil{t.Fatalf("build test server: %v; %s",err,out)}
 options:=[]string{
  "--repo=o/r","--issue=7","--bootstrap-json="+path,
  "--bootstrap-json-sha256="+reader.digest,
  "--bootstrap-authority="+reader.authority,
  "--bootstrap-revision="+reader.revision,
  "--bootstrap-dle-sha256="+reader.authoritySHA,
 }
 client:=mcp.NewClient(&mcp.Implementation{Name:"bootstrap-stdio-test",Version:"0.1"},nil)
 command:=exec.CommandContext(ctx,binary,append([]string{"--transport=stdio","--mode=fixture","--fixture=testdata/observed.json"},options...)...)
 stdio,err:=client.Connect(ctx,&mcp.CommandTransport{Command:command},nil)
 if err!=nil{t.Fatal(err)};defer stdio.Close()
 server:=httptest.NewServer(newHTTPHandlerWithBootstrap(fixtureProvider{fixture},"o/r",7,sampleToken,nil,&reader))
 defer server.Close()
 networkClient:=mcp.NewClient(&mcp.Implementation{Name:"bootstrap-http-test",Version:"0.1"},nil)
 remote,err:=networkClient.Connect(ctx,&mcp.StreamableClientTransport{
  Endpoint:server.URL+"/mcp",
  HTTPClient:&http.Client{Transport:bearerTransport{base:http.DefaultTransport}},
 },nil)
 if err!=nil{t.Fatal(err)};defer remote.Close()

 for _,session:=range []*mcp.ClientSession{stdio,remote} {
  listing,err:=session.ListTools(ctx,nil);if err!=nil{t.Fatal(err)}
  if len(listing.Tools)!=3 {t.Fatalf("expected 3 tools with admitted bootstrap, got %d",len(listing.Tools))}
  names:=map[string]bool{}
  for _,tool:=range listing.Tools{names[tool.Name]=true}
  if !names["dle_discover"]||!names["dle_observe"]||!names["dle_bootstrap"]||names["dle_reconcile"]{
   t.Fatalf("unexpected bootstrap tool visibility: %+v",names)
  }
 }
 invoke:=func(session *mcp.ClientSession)json.RawMessage{
  t.Helper()
  got,err:=session.CallTool(ctx,&mcp.CallToolParams{Name:"dle_bootstrap",Arguments:map[string]any{}})
  if err!=nil||got.IsError{t.Fatalf("bootstrap call: %v, %+v",err,got)}
  b,err:=json.Marshal(got.StructuredContent);if err!=nil{t.Fatal(err)}
  return b
 }
 a,b:=invoke(stdio),invoke(remote)
 if !reflect.DeepEqual(a,b){t.Fatalf("stdio/HTTP content changed: stdio=%s http=%s",a,b)}
 var parsed BootstrapView
 if err=json.Unmarshal(a,&parsed);err!=nil{t.Fatal(err)}
 if parsed.GitHubVerified||!parsed.AdvisoryOnly||parsed.AuthoritySHA256!=syntheticDLEHash{
  t.Fatal("invalid source or authority claim in bootstrap")
 }
 if bytes.Contains(a,[]byte("ghp_"))||bytes.Contains(a,[]byte("PRIVATE_DLE")){t.Fatal("sensitive marker leaked")}
 // Change bytes after creating the valid reader; each call must rehash and deny.
 if err=os.WriteFile(path,[]byte("{}"),0600);err!=nil{t.Fatal(err)}
 for _,session:=range []*mcp.ClientSession{stdio,remote}{
  got,err:=session.CallTool(ctx,&mcp.CallToolParams{Name:"dle_bootstrap",Arguments:map[string]any{}})
  if err==nil && got!=nil && !got.IsError{t.Fatal("stale bootstrap was served after file mutation")}
 }
}

func TestBootstrapRefusesSourceAndSchemaDrift(t *testing.T){
 good,path:=writeBootstrap(t)
 for _,bad:=range []bootstrapReader{
  {file:path,digest:strings.Repeat("0",64),authority:good.authority,revision:good.revision,authoritySHA:good.authoritySHA},
  {file:path,digest:good.digest,authority:"wrong/repo",revision:good.revision,authoritySHA:good.authoritySHA},
  {file:path,digest:good.digest,authority:good.authority,revision:"stale",authoritySHA:good.authoritySHA},
  {file:path,digest:good.digest,authority:good.authority,revision:good.revision,authoritySHA:strings.Repeat("c",64)},
 } {
  if _,err:=bad.Read();err==nil{t.Fatalf("wrong source binding was accepted: %+v",bad)}
 }
 copy:=bootstrapFixture()
 copy.GitHubVerified=true
 body,_:=json.Marshal(copy)
 if err:=os.WriteFile(path,body,0600);err!=nil{t.Fatal(err)}
 hash:=sha256.Sum256(body)
 if _,err:=newBootstrapReader(path,hex.EncodeToString(hash[:]),syntheticSource,syntheticRevision,syntheticDLEHash);err==nil{
  t.Fatal("self-verified bootstrap accepted")
 }
}

func TestBootstrapRefusesDuplicateKeysAndSymlink(t *testing.T){
 reader,path:=writeBootstrap(t)
 original,err:=os.ReadFile(path);if err!=nil{t.Fatal(err)}
 // Duplicate top-level and nested JSON keys must fail even when pinned to the byte hash.
 for _,raw:=range [][]byte{
  []byte(strings.Replace(string(original),`"github_verified":false`,`"github_verified":false,"github_verified":true`,1)),
  []byte(strings.Replace(string(original),`"id":"decision-01"`,`"id":"decision-01","id":"different"`,1)),
 } {
  if bytes.Equal(raw,original){t.Fatal("duplicate-key negative fixture did not mutate")}
  hash:=sha256.Sum256(raw)
  if err=os.WriteFile(path,raw,0600);err!=nil{t.Fatal(err)}
  _,err:=newBootstrapReader(path,hex.EncodeToString(hash[:]),reader.authority,reader.revision,reader.authoritySHA)
  if err==nil{t.Fatal("ambiguous JSON object accepted")}
 }
 os.Remove(path)
 target:=filepath.Join(t.TempDir(),"real-bootstrap.json")
 if err=os.WriteFile(target,original,0600);err!=nil{t.Fatal(err)}
 if err=os.Symlink(target,path);err!=nil{t.Skipf("symlink unavailable: %v",err)}
 hash:=sha256.Sum256(original)
 if _,err=newBootstrapReader(path,hex.EncodeToString(hash[:]),reader.authority,reader.revision,reader.authoritySHA);err==nil{
  t.Fatal("symlink bootstrap admitted")
 }
}

func TestBootstrapPartialCLIAdmissionMustFail(t *testing.T){
 // Zero configuration must be legal; an incomplete authority binding must not.
 cmd:=exec.Command("go","run",".","--repo=o/r","--issue=7","--bootstrap-json=/tmp/incomplete.json")
 out,err:=cmd.CombinedOutput()
 if err==nil || !strings.Contains(string(out),"partial bootstrap projection admission forbidden"){
  t.Fatalf("partial config did not deny: error=%v output=%s",err,out)
 }
}

func ExampleBootstrapView(){
 view:=bootstrapFixture()
 fmt.Println(view.Schema,view.GitHubVerified,view.AdvisoryOnly)
 // Output: dle-bootstrap-advisory-v1 false true
}
