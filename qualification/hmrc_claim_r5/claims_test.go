package claims

import (
 "fmt"
 "math/rand"
 "strings"
 "testing"
)
func entry(id,scope,status,subject,predicate,value string,revision uint64) (CatalogEntry,Evidence){
 b:=[]byte(fmt.Sprintf("{%q:%q,%q:%q,%q:%q,%q:%q}",
 "schema","hmrc-fact-v1","subject",subject,"predicate",predicate,"value",value))
 e:=CatalogEntry{ID:id,Scope:scope,Status:status,Revision:revision,Digest:Digest(b)}
 return e,Evidence{ID:id,Body:b}
}
func run(q Query,c []CatalogEntry,e []Evidence)(Answer,error){return Decide(c,e,q)}
func TestThreeLanguagesAndExactGrounding(t *testing.T){
 cases:=[]struct{subject,pred,value string}{
  {"blue-signal","meaning","English blue signal"},
  {"blaues Signal","meaning","Deutsches blaues Signal"},
  {"สัญญาณสีน้ำเงิน","ความหมาย","สัญญาณสีน้ำเงิน"},
 }
 for _,tc:=range cases{
  c,e:=entry("SYN_ID","atlas","accepted",tc.subject,tc.pred,tc.value,5)
  a,err:=run(Query{"atlas",tc.subject,tc.pred,"answer"},[]CatalogEntry{c},[]Evidence{e})
  if err!=nil||a.State!="SUPPORTED"||a.Value!=tc.value||a.SourceDigest!=c.Digest{
   t.Fatalf("multilingual exact source claim: %+v %v",a,err)
  }
  absent,err:=run(Query{"atlas","red-signal",tc.pred,"answer"},[]CatalogEntry{c},[]Evidence{e})
  if err!=nil||absent.State!="ABSTAIN"{t.Fatal("near-negative must abstain")}
 }
}
func TestNoEvidenceAndScope(t *testing.T){
 c,e:=entry("SYN_1","vega","accepted","blue","state","HOLD",1)
 for _,q:=range []Query{{"atlas","blue","state","answer"},{"atlas","lamp","state","answer"}}{
  a,err:=run(q,[]CatalogEntry{c},[]Evidence{e})
  if err!=nil||a.State!="ABSTAIN"||a.Value!=""{t.Fatalf("leaked foreign value: %+v %v",a,err)}
 }
}
func TestSupersededNeverGranted(t *testing.T){
 c,e:=entry("SYN_OLD","atlas","superseded","release","admission","APPROVED",7)
 a,err:=run(Query{"atlas","release","admission","answer"},[]CatalogEntry{c},[]Evidence{e})
 if err!=nil||a.State!="ABSTAIN"{t.Fatalf("stale authority: %+v %v",a,err)}
}
func TestTwoAcceptedCurrentAmbiguous(t *testing.T){
 c1,e1:=entry("ONE","atlas","accepted","release","state","HOLD",8)
 c2,e2:=entry("TWO","atlas","accepted","release","state","GO",9)
 a,err:=run(Query{"atlas","release","state","answer"},[]CatalogEntry{c1,c2},[]Evidence{e1,e2})
 if err!=nil||a.State!="AMBIGUOUS"||a.SourceID!=""{t.Fatalf("conflict promoted: %+v %v",a,err)}
}
func TestExactBytesAndMetadataTamperingDenied(t *testing.T){
 c,e:=entry("ONE","atlas","accepted","release","state","HOLD",8)
 damaged:=e;damaged.Body=[]byte(strings.Replace(string(e.Body),"HOLD","GO",1))
 _,err:=run(Query{"atlas","release","state","answer"},[]CatalogEntry{c},[]Evidence{damaged})
 if err!=ErrTampered{t.Fatalf("same ID content tamper: %v",err)}
 c.Digest=Digest(damaged.Body)
 // Attacker can forge a digest if caller accepts untrusted catalog.
 // This is a documented trust assumption, not a certified signature.
 a,err:=run(Query{"atlas","release","state","answer"},[]CatalogEntry{c},[]Evidence{damaged})
 if err!=nil||a.Value!="GO"{t.Fatal("trust assumption changed; test needs reassessment")}
}
func TestNoModelOrMemoryMayGrantExecution(t *testing.T){
 c,e:=entry("ONE","atlas","accepted","release","state","HOLD",8)
 for _,use:=range []string{"execute","deploy","tool","publish",""}{
  if _,err:=run(Query{"atlas","release","state",use},[]CatalogEntry{c},[]Evidence{e});err!=ErrInvalid{
   t.Fatalf("%q self-authorized: %v",use,err)
  }
 }
}
func TestUnknownClaimAndDuplicateReject(t *testing.T){
 c,e:=entry("ONE","atlas","accepted","subject","predicate","value",1)
 if _,err:=run(Query{"atlas","subject","predicate","answer"},[]CatalogEntry{c,c},[]Evidence{e});err!=ErrInvalid{
  t.Fatal("duplicate catalog")
 }
 if _,err:=run(Query{"atlas","subject","predicate","answer"},[]CatalogEntry{c},[]Evidence{e,e});err!=ErrTampered{
  t.Fatal("duplicate recalled evidence")
 }
 spoof:=Evidence{ID:"FAKE",Body:e.Body}
 if _,err:=run(Query{"atlas","subject","predicate","answer"},[]CatalogEntry{c},[]Evidence{spoof});err!=ErrTampered{
  t.Fatal("untrusted memory")
 }
}
func TestFuzzedNearMissAbstainAndMutation(t *testing.T){
 for _,seed:=range []int64{11,29,47,71,107}{
  randv:=rand.New(rand.NewSource(seed))
  c,e:=entry(fmt.Sprintf("SOURCE-%d",seed),"atlas","accepted","subject","predicate",fmt.Sprintf("val-%d",seed),1)
  for i:=0;i<400;i++{
   q:=Query{"atlas",fmt.Sprintf("subject-%03d",randv.Intn(120)),"predicate","answer"}
   a,err:=run(q,[]CatalogEntry{c},[]Evidence{e})
   if err!=nil||a.State!="ABSTAIN"{t.Fatalf("near miss seed=%d rep=%d %+v %v",seed,i,a,err)}
  }
 }
}
func BenchmarkSourceGrounded100(b *testing.B){
 c,e:=entry("ONE","atlas","accepted","fact","state","HOLD",1)
 q:=Query{"atlas","fact","state","answer"}
 b.ResetTimer()
 for i:=0;i<b.N;i++{if a,err:=run(q,[]CatalogEntry{c},[]Evidence{e});err!=nil||a.State!="SUPPORTED"{b.Fatal(err)}}
}
