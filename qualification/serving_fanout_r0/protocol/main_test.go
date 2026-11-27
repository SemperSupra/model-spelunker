package main

import (
 "encoding/json"
 "testing"
)
func sample() Fixture {return Fixture{Schema:"serving-fanout-r0/v1",Slots:2,ReservedInteractive:1,Tasks:[]Task{
 {ID:"b1",Tenant:"tenantA",Kind:"batch",Arrival:0,Service:50,Context:4000},
 {ID:"b2",Tenant:"tenantA",Kind:"batch",Arrival:0,Service:50,Context:4000},
 {ID:"i1",Tenant:"tenantB",Kind:"interactive",Arrival:1,Service:1,Context:4000},
 {ID:"i2",Tenant:"tenantC",Kind:"interactive",Arrival:2,Service:1,Context:4000},
}}}
func TestReservedProtectsInteractiveAgainstLongBatch(t *testing.T){
 f:=sample();fifo,err:=simulate(f,"fifo");if err!=nil{t.Fatal(err)}
 res,err:=simulate(f,"reserved");if err!=nil{t.Fatal(err)}
 if res.Interactive.P95QueueWait!=0 {t.Fatalf("reserved interactive wait: %d",res.Interactive.P95QueueWait)}
 if fifo.Interactive.P95QueueWait<=res.Interactive.P95QueueWait{t.Fatalf("no distinction: fifo %d reserved %d",fifo.Interactive.P95QueueWait,res.Interactive.P95QueueWait)}
 if len(res.Observations)!=len(f.Tasks)||res.Batch.Count!=2{t.Fatal("lost acknowledged synthetic work")}
}
func TestDeterminismAndEvidenceLabel(t *testing.T){
 f:=sample();a,e:=simulate(f,"reserved");if e!=nil{t.Fatal(e)}
 b,e:=simulate(f,"reserved");if e!=nil{t.Fatal(e)}
 x,_:=json.Marshal(a);y,_:=json.Marshal(b)
 if string(x)!=string(y){t.Fatal("nondeterministic receipts")}
 if a.EvidenceClass!="SYNTHETIC_SIMULATION_NOT_HARDWARE"{t.Fatal("fake HIL claim")}
}
func TestRejectsInvalidAndDuplicates(t *testing.T){
 f:=sample();f.Tasks[2].ID="b1";if _,e:=simulate(f,"fifo");e==nil{t.Fatal("duplicate accepted")}
 f=sample();f.Tasks[2].Kind="security_superuser";if _,e:=simulate(f,"fifo");e==nil{t.Fatal("unknown class accepted")}
 f=sample();f.ReservedInteractive=2;if _,e:=simulate(f,"reserved");e==nil{t.Fatal("invalid resource reservation accepted")}
 f=sample();if _,e:=simulate(f,"random");e==nil{t.Fatal("unknown policy accepted")}
}
