package main

import (
 "context"
 "crypto/sha256"
 "encoding/hex"
 "encoding/json"
 "net/http"
 "net/http/httptest"
 "os"
 "path/filepath"
 "strings"
 "testing"
 "time"

 "github.com/modelcontextprotocol/go-sdk/mcp"
)

type mockSummaryProvider struct{
 result ReconcileSummary
 err error
}
func (p mockSummaryProvider) Reconcile(context.Context)(ReconcileSummary,error){return p.result,p.err}
func sampleSummary() ReconcileSummary{
 return ReconcileSummary{
  Schema:"dle-mcp-reconcile-summary-v0",Status:"CANDIDATE_RECONCILIATION_ONLY",
  Authority:"https://example.invalid/o/r/issues/7",Revision:"frozen-revision",
  AuthoritySHA256:strings.Repeat("a",64),CandidateSHA256:strings.Repeat("b",64),
  ExecutableSHA256:strings.Repeat("c",64),
  Counts:map[string]int{"agreement":1,"unknown":2},
  EvidenceGrade:candidateGrade,GitHubVerified:false,MutationPerformed:false,
 }
}
func TestConditionalReconciliationToolReadOnly(t *testing.T){
 fixture,err:=loadFixture("testdata/observed.json");if err!=nil{t.Fatal(err)}
 engine:=mockSummaryProvider{result:sampleSummary()}
 server:=httptest.NewServer(newHTTPHandlerWithReconciler(fixtureProvider{fixture},"o/r",7,sampleToken,engine))
 defer server.Close()
 ctx,cancel:=context.WithTimeout(context.Background(),15*time.Second);defer cancel()
 client:=mcp.NewClient(&mcp.Implementation{Name:"reconciliation-client",Version:"v0"},nil)
 sess,err:=client.Connect(ctx,&mcp.StreamableClientTransport{
  Endpoint:server.URL+"/mcp",HTTPClient:&http.Client{Transport:bearerTransport{base:http.DefaultTransport}},
 },nil)
 if err!=nil{t.Fatal(err)};defer sess.Close()
 list,err:=sess.ListTools(ctx,nil);if err!=nil{t.Fatal(err)}
 names:=map[string]bool{}
 for _,item:=range list.Tools {names[item.Name]=true}
 if len(names)!=3||!names["dle_observe"]||!names["dle_discover"]||!names["dle_reconcile"] {
  t.Fatalf("bad conditional read-only tool registration: %v",names)
 }
 result,err:=sess.CallTool(ctx,&mcp.CallToolParams{Name:"dle_reconcile",Arguments:map[string]any{}})
 if err!=nil||result.IsError{t.Fatalf("tool failed %v: %+v",err,result)}
 raw,err:=json.Marshal(result.StructuredContent);if err!=nil{t.Fatal(err)}
 var got ReconcileSummary
 if err=json.Unmarshal(raw,&got);err!=nil{t.Fatal(err)}
 if got.Status!="CANDIDATE_RECONCILIATION_ONLY"||got.GitHubVerified||got.MutationPerformed||
 got.Counts["agreement"]!=1||got.Counts["unknown"]!=2 {t.Fatalf("trust error: %+v",got)}
 if strings.Contains(string(raw),"private transcript")||strings.Contains(string(raw),"accepted statement text"){
  t.Fatal("candidate or source body in summary")
 }
}
func TestUnconfiguredReconcilerIsAbsent(t *testing.T){
 fixture,err:=loadFixture("testdata/observed.json");if err!=nil{t.Fatal(err)}
 server:=httptest.NewServer(newHTTPHandler(fixtureProvider{fixture},"o/r",7,sampleToken));defer server.Close()
 ctx,cancel:=context.WithTimeout(context.Background(),10*time.Second);defer cancel()
 client:=mcp.NewClient(&mcp.Implementation{Name:"no-reconciler",Version:"v0"},nil)
 sess,err:=client.Connect(ctx,&mcp.StreamableClientTransport{
  Endpoint:server.URL+"/mcp",HTTPClient:&http.Client{Transport:bearerTransport{base:http.DefaultTransport}},
 },nil)
 if err!=nil{t.Fatal(err)};defer sess.Close()
 list,err:=sess.ListTools(ctx,nil);if err!=nil{t.Fatal(err)}
 if len(list.Tools)!=2{t.Fatalf("unconfigured reconcile tool was exposed: %+v",list.Tools)}
}
func TestReconcileSummaryTrustGuards(t *testing.T){
 s:=sampleSummary()
 if err:=validateReconcileSummary(s);err!=nil{t.Fatal(err)}
 negative:=[]func(*ReconcileSummary){
  func(x *ReconcileSummary){x.GitHubVerified=true},
  func(x *ReconcileSummary){x.MutationPerformed=true},
  func(x *ReconcileSummary){x.Status="ACCEPTED"},
  func(x *ReconcileSummary){x.EvidenceGrade="github_verified"},
  func(x *ReconcileSummary){x.AuthoritySHA256="short"},
  func(x *ReconcileSummary){x.Counts["merge_approved"]=1},
 }
 for i,mutate:=range negative{
  clone:=sampleSummary()
  mutate(&clone)
  if err:=validateReconcileSummary(clone);err==nil{t.Fatalf("negative %d was accepted",i)}
 }
}
func TestReconcilerRejectsStalePinsBeforeExecution(t *testing.T){
 dir:=t.TempDir()
 authority:=filepath.Join(dir,"authority.json")
 candidate:=filepath.Join(dir,"candidate.json")
 binary:=filepath.Join(dir,"reconciler")
 if err:=os.WriteFile(authority,[]byte("private local snapshot"),0600);err!=nil{t.Fatal(err)}
 if err:=os.WriteFile(candidate,[]byte("selected candidate"),0600);err!=nil{t.Fatal(err)}
 if err:=os.WriteFile(binary,[]byte("fake-binary-not-executed"),0700);err!=nil{t.Fatal(err)}
 sum:=func(b []byte)string{v:=sha256.Sum256(b);return hex.EncodeToString(v[:])}
 e:=externalReconciler{binary:binary,binarySHA256:sum([]byte("fake-binary-not-executed")),
  authorityFile:authority,candidateFile:candidate,authoritySHA256:strings.Repeat("0",64)}
 if _,err:=e.Reconcile(context.Background());err==nil {t.Fatal("stale source pin accepted")}
 e.authoritySHA256=sum([]byte("private local snapshot"))
 e.binarySHA256=strings.Repeat("0",64)
 if _,err:=e.Reconcile(context.Background());err==nil {t.Fatal("stale executable pin accepted")}
 e.binarySHA256=sum([]byte("fake-binary-not-executed"))
 link:=filepath.Join(dir,"source-link.json")
 if err:=os.Symlink(authority,link);err!=nil{t.Skip("symlinks unsupported")}
 e.authorityFile=link
 if _,err:=e.Reconcile(context.Background());err==nil {t.Fatal("source symlink accepted")}
}
