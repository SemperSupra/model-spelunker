package main
import (
 "bytes"
 "encoding/json"
 "testing"
 claims "example.com/sempersupra/hmrc-claim-r5"
)
func TestSourceBoundReadOnlyCLI(t *testing.T){
 body:=[]byte("{\"schema\":\"hmrc-fact-v1\",\"subject\":\"node\",\"predicate\":\"status\",\"value\":\"HOLD\"}")
 input,_:=json.Marshal(Request{
  Catalog:[]claims.CatalogEntry{{ID:"SOURCE",Scope:"atlas",Status:"accepted",Revision:1,Digest:claims.Digest(body)}},
  Found:[]claims.Evidence{{ID:"SOURCE",Body:body}},
  Query:claims.Query{Scope:"atlas",Subject:"node",Predicate:"status",IntendedUse:"answer"},
 })
 var output bytes.Buffer
 if err:=dispatch(&output,bytes.NewReader(input));err!=nil{t.Fatal(err)}
 var got Response
 if err:=json.Unmarshal(output.Bytes(),&got);err!=nil{t.Fatal(err)}
 if got.State!="SUPPORTED"||got.Value!="HOLD"||got.SourceID!="SOURCE"{t.Fatalf("source claim mismatch %+v",got)}
}
func TestUnknownAndTamperedFailClosed(t *testing.T){
 for _,str:=range []string{"{bad",`{"catalog":[],"found":[],"query":{"Scope":"atlas","Subject":"unknown","Predicate":"status","IntendedUse":"answer"}}`} {
  var o bytes.Buffer
  if err:=dispatch(&o,bytes.NewBufferString(str));err!=nil{t.Fatal(err)}
  var reply Response
  if err:=json.Unmarshal(o.Bytes(),&reply);err!=nil{t.Fatal(err)}
  if reply.State!="ERROR" && reply.State!="ABSTAIN"{t.Fatalf("unknown became source authority %+v",reply)}
 }
}
