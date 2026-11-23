package intent

import(
 "bytes"
 "errors"
 "fmt"
 "os"
 "os/exec"
 "path/filepath"
 "strings"
 "sync"
 "testing"
)
const src="synthetic source authorizes no real tool or deployment"
const payload="synthetic add-one counter receipt, no external target"
func helper(t *testing.T){
 phase:=os.Getenv("HMRC_R7_CHILD_PHASE")
 if phase==""{return}
 j,err:=Open(os.Getenv("HMRC_R7_CHILD_ROOT"));if err!=nil{t.Fatal(err)}
 if err=j.Prepare([]byte(src),[]byte(payload));err!=nil{t.Fatal(err)}
 if phase=="prepared"{fmt.Println("READY:"+phase)}
 if phase!="prepared"{
  if err=j.Begin();err!=nil{t.Fatal(err)}
  if phase=="dispatching"{fmt.Println("READY:"+phase)}
 }
 if phase=="effect"||phase=="acked"{
  if err=j.WriteSyntheticWitness();err!=nil{t.Fatal(err)}
  if phase=="effect"{fmt.Println("READY:"+phase)}
 }
 if phase=="acked"{
  if err=j.Acknowledge(true);err!=nil{t.Fatal(err)}
  fmt.Println("READY:"+phase)
 }
 // Parent SIGKILL leaves an O_EXCL stale lease; never Close.
 var one [1]byte
 _,_ = os.Stdin.Read(one[:])
}
func TestHelperProcess(t *testing.T){helper(t)}
func startPhase(t *testing.T,root,phase string){
 t.Helper()
 c:=exec.Command(os.Args[0],"-test.run=^TestHelperProcess$")
 c.Env=append(os.Environ(),"HMRC_R7_CHILD_PHASE="+phase,"HMRC_R7_CHILD_ROOT="+root)
 r,w,err:=os.Pipe();if err!=nil{t.Fatal(err)}
 c.Stdin=r
 out,err:=c.StdoutPipe();if err!=nil{t.Fatal(err)}
 c.Stderr=os.Stderr
 if err=c.Start();err!=nil{t.Fatal(err)}
 r.Close()
 var line []byte
 buf:=make([]byte,1)
 for len(line)<64{
  n,e:=out.Read(buf)
  if n==1 {line=append(line,buf[0]);if buf[0]==10{break}}
  if e!=nil{t.Fatalf("child failed before durable phase %s: %q %v",phase,line,e)}
 }
 if strings.TrimSpace(string(line))!="READY:"+phase{
  c.Process.Kill();c.Wait();t.Fatalf("child phase not reached: %s %q",phase,line)
 }
 if err:=c.Process.Kill();err!=nil{t.Fatal(err)}
 _=c.Wait()
 _=w.Close()
}
func manualReleaseForTest(t *testing.T,root string){
 t.Helper()
 // External authorization is simulated only AFTER parent proves child exit
 // and this test's exact synthetic scope. Library has no such auto-takeover.
 if err:=os.Remove(filepath.Join(root,"writer.lease"));err!=nil{t.Fatal(err)}
}
func TestActualSIGKILLAtFourDurabilityBoundaries(t *testing.T){
 for _,phase:=range []string{"prepared","dispatching","effect","acked"}{
  t.Run(phase,func(t *testing.T){
   root:=t.TempDir()
   startPhase(t,root,phase)
   if j,err:=Open(root);!errors.Is(err,ErrLease){
    if j!=nil{j.Close()}
    t.Fatalf("SIGKILL stale owner lease auto-stolen: %v",err)
   }
   manualReleaseForTest(t,root)
   j,err:=Open(root);if err!=nil{t.Fatal(err)}
   defer j.Close()
   record,err:=j.Inspect();if err!=nil{t.Fatal(err)}
   expected:=map[string]string{"prepared":Prepared,"dispatching":Dispatching,
       "effect":Dispatching,"acked":Acked}[phase]
   if record.State!=expected{t.Fatalf("lost exact phase %+v",record)}
   n,err:=j.WitnessCount();if err!=nil{t.Fatal(err)}
   want:=0;if phase=="effect"||phase=="acked"{want=1}
   if n!=want{t.Fatalf("synthetic durable witness count=%d want %d",n,want)}
   recovered,e:=j.Recover()
   if phase=="dispatching"||phase=="effect" {
    if !errors.Is(e,ErrHold)||recovered.Generation!=2{t.Fatalf("uncertain state acted on %v %+v",e,recovered)}
    if err:=j.Acknowledge(false);!errors.Is(err,ErrHold){t.Fatalf("unauthorized ack: %v",err)}
    if phase=="dispatching"{
     if err:=j.Acknowledge(true);!errors.Is(err,ErrHold){t.Fatalf("missing witness treated as completed: %v",err)}
    }else{
     // Authoritative external evidence check is explicit; no second effect.
     if err:=j.WriteSyntheticWitness();!errors.Is(err,ErrHold){t.Fatalf("duplicate effect allowed: %v",err)}
     if err:=j.Acknowledge(true);err!=nil{t.Fatal(err)}
     result,err:=j.Recover()
     if err!=nil||result.State!=Acked||result.Generation!=3{t.Fatalf("external reconciliation lost %+v %v",result,err)}
    }
   }else if e!=nil{t.Fatalf("safe phase not recoverable %v",e)}
  })
 }
}
func TestForgedWitnessAndUnknownScopeNeverResume(t *testing.T){
 root:=t.TempDir()
 j,err:=Open(root);if err!=nil{t.Fatal(err)}
 defer j.Close()
 if err:=j.Prepare([]byte(src),[]byte(payload));err!=nil{t.Fatal(err)}
 if err:=j.Begin();err!=nil{t.Fatal(err)}
 path:=j.witnessPath()
 spoof:=[]byte(`{"Schema":"hmrc-synthetic-tool-witness-r7","ID":"SYN_ONLY","Scope":"foreign-project"}`)
 if err:=os.WriteFile(path,spoof,0600);err!=nil{t.Fatal(err)}
 if err:=j.Acknowledge(true);!errors.Is(err,ErrHold){t.Fatalf("forged source witness accepted %v",err)}
 if err:=os.WriteFile(path,[]byte("{invalid"),0600);err!=nil{t.Fatal(err)}
 if err:=j.Acknowledge(true);!errors.Is(err,ErrHold){t.Fatalf("corrupt witness accepted %v",err)}
 if err:=j.WriteSyntheticWitness();!errors.Is(err,ErrHold){t.Fatalf("duplicate external effect despite forged witness %v",err)}
}
func TestNoConcurrentWritersAndNoImplicitReplay(t *testing.T){
 root:=t.TempDir()
 j,err:=Open(root);if err!=nil{t.Fatal(err)}
 defer j.Close()
 var wg sync.WaitGroup
 problems:=make(chan error,16)
 for i:=0;i<16;i++{
  wg.Add(1)
  go func(){
   defer wg.Done()
   c,err:=Open(root)
   if c!=nil{c.Close()}
   if !errors.Is(err,ErrLease){problems<-fmt.Errorf("unleased writer: %v",err)}
  }()
 }
 wg.Wait();close(problems)
 for err:=range problems{t.Error(err)}
 if err:=j.Prepare([]byte(src),[]byte(payload));err!=nil{t.Fatal(err)}
 if err:=j.Prepare([]byte(src),[]byte(payload));!errors.Is(err,ErrState){t.Fatalf("replayed prepare %v",err)}
 if err:=j.Begin();err!=nil{t.Fatal(err)}
 if err:=j.Begin();!errors.Is(err,ErrState){t.Fatalf("replayed dispatch %v",err)}
 if _,err:=j.Recover();!errors.Is(err,ErrHold){t.Fatalf("unfinished dispatch auto-completed %v",err)}
}
func TestCorruptedJournalFailsClosed(t *testing.T){
 root:=t.TempDir()
 j,err:=Open(root);if err!=nil{t.Fatal(err)}
 defer j.Close()
 if err:=j.Prepare([]byte(src),[]byte(payload));err!=nil{t.Fatal(err)}
 canonical,err:=os.ReadFile(j.path());if err!=nil{t.Fatal(err)}
 tampered:=bytes.Replace(canonical,[]byte("synthetic-atlas"),[]byte("synthetic-other"),1)
 if bytes.Equal(canonical,tampered){t.Fatal("negative tamper was unchanged")}
 if err:=os.WriteFile(j.path(),tampered,0600);err!=nil{t.Fatal(err)}
 if _,err:=j.Recover();!errors.Is(err,ErrInvalid){t.Fatalf("tampered restart accepted %v",err)}
}
