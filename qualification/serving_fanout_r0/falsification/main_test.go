package main

import (
 "strings"
 "testing"
)
func TestSafeBoundedAllReachableStates(t *testing.T){
 states,transitions,trace,err:=boundedCheck(9,true)
 if err!=nil {t.Fatalf("safe counterexample %v: %v",trace,err)}
 if states<10||transitions<50 {t.Fatalf("insufficient model exploration: %d states %d transitions",states,transitions)}
}
func TestUnsafeMissingDestinationIdempotency(t *testing.T){
 _,_,trace,err:=boundedCheck(9,false)
 if err==nil {t.Fatal("unsafe destination unexpectedly accepted")}
 path:=strings.Join(trace," ")
 if !strings.Contains(path,"crash")||strings.Count(path,"effect")<2 {
  t.Fatalf("expected crash-between-effect-and-commit counterexample, got %v: %v",trace,err)
 }
}
func TestStaleLeaseCannotEffectAfterCrash(t *testing.T){
 s:=step(initial(),"admit",true)
 s=step(s,"start",true)
 old:=s.Lease
 s=step(s,"crash",true)
 if s.Lease!=0||old==s.Generation {t.Fatalf("stale lease not fenced: %+v",s)}
 s=step(s,"effect",true)
 if s.Effects!=0 {t.Fatalf("effect after crash without reacquire: %+v",s)}
}
func TestRevokedAndDriftAdmissionFailClosed(t *testing.T){
 for _,op:=range []string{"revoke","drift"} {
  s:=step(initial(),op,true)
  s=step(s,"admit",true)
  if s.Durable||s.Acked{t.Fatalf("%s admitted: %+v",op,s)}
 }
}
func TestTenantAndEffectIdempotence(t *testing.T){
 s:=step(initial(),"admit",true)
 s=step(s,"start",true)
 old:=s
 s=step(s,"wrong_tenant",true)
 if s!=old{t.Fatalf("wrong tenant altered job: %+v",s)}
 s=step(s,"effect",true)
 s=step(s,"crash",true)
 s=step(s,"start",true)
 s=step(s,"effect",true)
 if s.Effects!=1{t.Fatalf("effect duplicated: %+v",s)}
 s=step(s,"commit",true)
 if !s.Committed{t.Fatalf("effect not committed: %+v",s)}
}
func TestRejectInvalidBounds(t *testing.T){
 for _,n:=range []int{0,-1,13}{
  if _,_,_,err:=boundedCheck(n,true);err==nil{t.Fatalf("accepted depth %d",n)}
 }
}
