package main

import (
 "os"
 "strings"
 "testing"
)
func fixtures(t *testing.T)(receipt,receipt){
 t.Helper()
 readFixture:=func(name string)receipt {
  b,err:=os.ReadFile("fixtures/"+name+".json");if err!=nil{t.Fatal(err)}
  var r receipt
  if err:=strictDecode(b,&r);err!=nil{t.Fatal(err)}
  return r
 }
 return readFixture("fifo"),readFixture("reserved")
}
func TestPairReductionChecksDataAndDoesNotPromote(t *testing.T){
 b,c:=fixtures(t)
 r,err:=compare(b,c);if err!=nil{t.Fatal(err)}
 if r.InteractiveP95WaitReduction!=49||r.BatchMakespanDifference!=50||r.MatchedTaskIDs!=4{t.Fatalf("unexpected effect: %+v",r)}
 if r.Promotion!="NO_RUNTIME_PROMOTION"||r.Uncertainty!="NOT_ESTIMABLE_SINGLE_SYNTHETIC_FIXTURE"{t.Fatalf("overstated confidence: %+v",r)}
}
func TestRejectsTamperedAggregatesAndTimelines(t *testing.T){
 b,c:=fixtures(t)
 b.Interactive.P95QueueWait++
 if _,err:=compare(b,c);err==nil{t.Fatal("forged aggregate passed")}
 b,c=fixtures(t)
 b.Observations[0].Wait=1
 if _,err:=compare(b,c);err==nil{t.Fatal("wrong wait passed")}
 b,c=fixtures(t)
 c.Slots=1
 if _,err:=compare(b,c);err==nil{t.Fatal("changed resources/overlap passed")}
}
func TestRejectsMissingOrCrossFixture(t *testing.T){
 b,c:=fixtures(t)
 c.FixtureSHA256=strings.Repeat("f",64)
 if _,err:=compare(b,c);err==nil{t.Fatal("cross-fixture passed")}
 b,c=fixtures(t)
 c.Observations=c.Observations[1:]
 if _,err:=compare(b,c);err==nil{t.Fatal("missing job passed")}
 b,c=fixtures(t)
 c.Observations[2].Arrival=0
 c.Observations[2].Wait=1
 c.Interactive=recompute(c.Observations,"interactive")
 if _,err:=compare(b,c);err==nil{t.Fatal("forged matching digest with mismatched task arrival passed")}
}
func TestStrictParsing(t *testing.T){
 b,err:=os.ReadFile("fixtures/fifo.json");if err!=nil{t.Fatal(err)}
 cases:=[][]byte{
  append(append([]byte(nil),b...),[]byte(" {}")...),
  []byte(`{"schema":"x","unexpected_field":"bad"}`),
  make([]byte,1<<20+1),
 }
 for i,data:=range cases{
  var r receipt
  if err:=strictDecode(data,&r);err==nil{t.Fatalf("accepted malformed fixture index %d",i)}
 }
}
func TestNoFalseEvidenceClass(t *testing.T){
 b,c:=fixtures(t)
 b.EvidenceClass="PHYSICAL_HARDWARE_PASS"
 if _,err:=compare(b,c);err==nil{t.Fatal("synthetic promoted as physical")}
}
