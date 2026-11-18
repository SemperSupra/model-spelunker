package main

import (
 "context"
 "encoding/json"
 "errors"
 "strings"
 "testing"
)
const testCommit="0123456789abcdef0123456789abcdef01234567"
const testRemote="abcdef0123456789abcdef0123456789abcdef01"
func goodRunner(_ context.Context,name string,args ...string)([]byte,error){
 if name=="git" && len(args)==5 && args[0]=="-C" && args[1]=="/tmp/fixture" && args[2]=="rev-parse" && args[3]=="--verify" && args[4]=="HEAD^{commit}"{return []byte(testCommit+"\n"),nil}
 if name!="gh"||len(args)!=4||args[0]!="api"||args[1]!="--method"||args[2]!="GET"{return nil,errors.New("non-GET or unsupported command")}
 switch args[3]{
 case "repos/o/r":return []byte(`{"full_name":"o/r","default_branch":"main"}`),nil
 case "repos/o/r/git/ref/heads/main":return []byte(`{"ref":"refs/heads/main","object":{"sha":"`+testRemote+`"}}`),nil
 case "repos/o/r/issues/7":return []byte(`{"id":42,"node_id":"N","number":7,"state":"open","updated_at":"2026-11-18T00:00:00Z","body":"# Mission","comments":2}`),nil
 }
 return nil,errors.New("unexpected endpoint")
}
func TestReadOnlyObservation(t *testing.T){
 got,err:=observe(context.Background(),goodRunner,"o/r",7,"/tmp/fixture")
 if err!=nil{t.Fatal(err)}
 if got.Repository!="o/r"||got.LocalCommit!=testCommit||got.RemoteDefaultCommit!=testRemote||got.IssueBodySHA256==""||got.GitHubVerified||got.MutationPerformed{t.Fatalf("bad source receipt: %+v",got)}
 if got.Coverage!="issue_body_and_counts_not_comments_or_semantic_acceptance"{t.Fatal("coverage overstated")}
 encoded,err:=json.Marshal(got);if err!=nil{t.Fatal(err)}
 if strings.Contains(string(encoded),"# Mission"){t.Fatal("raw body escaped into receipt")}
}
func TestFailClosedInputsAndEvidence(t *testing.T){
 for _,repo:=range []string{"","o/r/other","../r","o/..","o/r?x=1","o/r\nbad"}{
  if validRepo(repo){t.Fatalf("invalid repository accepted: %q",repo)}
 }
 for _,v:=range []struct{repo string;issue int;path string}{{"o/r",0,"/tmp/fixture"},{"o/r",7,""},{"../r",7,"/tmp/fixture"}}{
  if _,err:=observe(context.Background(),goodRunner,v.repo,v.issue,v.path);err==nil{t.Fatalf("accepted invalid input: %+v",v)}
 }
 bad:=func(ctx context.Context,name string,args ...string)([]byte,error){
  b,err:=goodRunner(ctx,name,args...)
  if name=="gh"&&len(args)==4&&args[3]=="repos/o/r/issues/7"{return []byte(`{"id":42,"number":7,"state":"open","body":"x","comments":0}`),nil}
  return b,err
 }
 if _,err:=observe(context.Background(),bad,"o/r",7,"/tmp/fixture");err==nil{t.Fatal("accepted missing GitHub issue identity")}
 deny:=func(context.Context,string,...string)([]byte,error){return nil,errors.New("denied")}
 if _,err:=observe(context.Background(),deny,"o/r",7,"/tmp/fixture");err==nil{t.Fatal("suppressed observation failure")}
}
