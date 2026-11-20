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
 "strings"
 "testing"
 "time"

 "github.com/modelcontextprotocol/go-sdk/mcp"
)

// Integration only when a *different* independently pinned source tree's
// existing bootstrap consumer has been explicitly supplied by the CI job.
// Never pull an unpinned remote script, private DLE or arbitrary local path.
func TestBootstrapFromPinnedPublicDLEConsumer(t *testing.T){
 script:=os.Getenv("PINNED_DLE_CONSUMER")
 if script=="" {t.Skip("separate pinned public consumer source not supplied")}
 if !filepath.IsAbs(script){t.Fatal("consumer must be an absolute pinned local source")}
 root:=t.TempDir()
 source:=filepath.Join(root,"context.json")
 bootstrap:=filepath.Join(root,"bootstrap.json")
 const authority="https://github.com/o/r/issues/7"
 const revision="synthetic-source-sha-9"
 sourceDigest:=strings.Repeat("a",64)
 raw:=map[string]any{
  "schema":"dle-context-v1","authority":authority,"revision":revision,
  "sha256":sourceDigest,"github_verified":false,
  "mission":"Synthetic test DLE mission","next_action":"Inspect fixture and run verifier",
  "constraints":[]string{"No real external effects","Public synthetic source only"},
  "unknowns":[]string{"Real current private GitHub authority is unverified"},
  "accepted":[]map[string]string{
   {"id":"claim1","text":"Only synthetic data may be used","source":authority,"status":"accepted"},
  },
 }
 b,err:=json.Marshal(raw);if err!=nil{t.Fatal(err)}
 if err=os.WriteFile(source,b,0600);err!=nil{t.Fatal(err)}
 cmd:=exec.Command("python3",script,
  "--context",source,"--authority",authority,"--revision",revision,"--sha256",sourceDigest)
 data,err:=cmd.Output()
 if err!=nil{t.Fatalf("pinned consumer failed: %v",err)}
 if err=os.WriteFile(bootstrap,data,0600);err!=nil{t.Fatal(err)}
 h:=sha256.Sum256(data)
 reader,err:=newBootstrapReader(bootstrap,hex.EncodeToString(h[:]),authority,revision,sourceDigest)
 if err!=nil{t.Fatalf("Go adapter rejected published synthetic consumer output: %v",err)}
 direct,err:=reader.Read();if err!=nil{t.Fatal(err)}
 if direct.GitHubVerified||!direct.AdvisoryOnly{t.Fatal("consumer improperly asserted source authority")}
 fixture,err:=loadFixture("testdata/observed.json");if err!=nil{t.Fatal(err)}
 server:=httptest.NewServer(newHTTPHandlerWithBootstrap(fixtureProvider{fixture},"o/r",7,sampleToken,nil,reader))
 defer server.Close()
 ctx,cancel:=context.WithTimeout(context.Background(),20*time.Second);defer cancel()
 cli:=mcp.NewClient(&mcp.Implementation{Name:"consumer-integration",Version:"0.1"},nil)
 session,err:=cli.Connect(ctx,&mcp.StreamableClientTransport{
  Endpoint:server.URL+"/mcp",
  HTTPClient:&http.Client{Transport:bearerTransport{base:http.DefaultTransport}},
 },nil)
 if err!=nil{t.Fatal(err)}
 defer session.Close()
 result,err:=session.CallTool(ctx,&mcp.CallToolParams{Name:"dle_bootstrap",Arguments:map[string]any{}})
 if err!=nil||result.IsError{t.Fatalf("MCP bootstrap read failed: %v",err)}
 encoded,err:=json.Marshal(result.StructuredContent);if err!=nil{t.Fatal(err)}
 var overMCP BootstrapView
 if err=json.Unmarshal(encoded,&overMCP);err!=nil{t.Fatal(err)}
 if !reflect.DeepEqual(direct,overMCP){t.Fatal("native CLI consumer and selected MCP resource yielded different bootstrap content")}
 // The existing on-host source cannot be considered authenticated just because
 // both tools agree; confirm both preserve false-attestation semantics.
 if overMCP.GitHubVerified||!overMCP.AdvisoryOnly {t.Fatal("MCP transport upgraded provisional output")}
}
