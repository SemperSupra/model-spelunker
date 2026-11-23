package crash

import (
  "bufio"
  "crypto/sha256"
  "encoding/hex"
  "errors"
  "fmt"
  "io"
  "os"
  "os/exec"
  "path/filepath"
  "strings"
  "sync"
  "testing"

  evidence "example.com/sempersupra/hmrc-evidence-r2"
  hmrc "example.com/sempersupra/hmrc-r0"
)

func fixture() (hmrc.Snapshot,evidence.Catalog) {
  source:=[]evidence.Source{
    {ID:"SYN_OWNER",Scope:"synthetic-atlas",Status:"accepted",Bytes:[]byte("Synthetic authorized read-only continuity")},
    {ID:"SYN_H1",Scope:"synthetic-atlas",Status:"accepted",Bytes:[]byte("Synthetic past outcome one")},
    {ID:"SYN_H2",Scope:"synthetic-atlas",Status:"advisory",Bytes:[]byte("Synthetic past outcome two")},
    {ID:"SYN_H3",Scope:"synthetic-atlas",Status:"accepted",Bytes:[]byte("Synthetic past outcome three")},
  }
  dig:=func(v []byte)string{h:=sha256.Sum256(v);return "sha256:"+hex.EncodeToString(h[:])}
  s:=hmrc.Snapshot{Schema:"hmrc-r0",Scope:"synthetic-atlas",Generation:1,EffectiveCapacity:1000}
  s.Units=[]hmrc.Unit{
    {ID:"protected",Scope:s.Scope,Kind:"protected",Tokens:150,SourceID:source[0].ID,SourceDigest:dig(source[0].Bytes),Verified:true,Sequence:1},
    {ID:"active",Scope:s.Scope,Kind:"active",Tokens:220,Sequence:2},
    {ID:"past-one",Scope:s.Scope,Kind:"historical",Tokens:180,SourceID:source[1].ID,SourceDigest:dig(source[1].Bytes),Verified:true,Sequence:3},
    {ID:"past-two",Scope:s.Scope,Kind:"historical",Tokens:160,SourceID:source[2].ID,SourceDigest:dig(source[2].Bytes),Verified:true,Sequence:4},
    {ID:"past-three",Scope:s.Scope,Kind:"historical",Tokens:140,SourceID:source[3].ID,SourceDigest:dig(source[3].Bytes),Verified:true,Sequence:5},
  }
  return s,evidence.Catalog{Records:source}
}
func child(path,mode string)error{
  _,catalog:=fixture()
  m,err:=evidence.Open(path,catalog,nil)
  if mode=="probe"{
    if errors.Is(err,evidence.ErrBusy){fmt.Println("BUSY");return nil}
    if m!=nil{m.Close()}
    return fmt.Errorf("competing child unexpectedly entered lease: %v",err)
  }
  if err!=nil{return err}
  if mode=="commit"{
    p,e:=m.Propose(hmrc.Forecast{NextTurnTokens:60,ReserveTokens:60})
    if e!=nil{return e}
    n,e:=m.Apply(p)
    if e!=nil{return e}
    if n.Generation!=2||len(n.Evicted)!=2{return fmt.Errorf("committed unexpected snapshot")}
    fmt.Println("COMMITTED")
  }else if mode=="hold"{
    fmt.Println("LOCKED")
  }else{
    return fmt.Errorf("unknown child role")
  }
  // The parent terminates the child while the kernel still owns an open
  // descriptor. A stale lease remains and the next owner must fail closed.
  var buf [1]byte
  _,_ = os.Stdin.Read(buf[:])
  return m.Close()
}
func TestLeaseHelperProcess(t *testing.T){
 mode:=os.Getenv("HMRC_CHILD_MODE")
 if mode==""{return}
 if err:=child(os.Getenv("HMRC_CHILD_PATH"),mode);err!=nil{t.Fatal(err)}
}
func makeState(t *testing.T)(string,evidence.Catalog){
 t.Helper()
 p:=filepath.Join(t.TempDir(),"state.json")
 s,c:=fixture()
 m,err:=evidence.Open(p,c,&s)
 if err!=nil{t.Fatal(err)}
 if err:=m.Close();err!=nil{t.Fatal(err)}
 return p,c
}
func runChild(t *testing.T,path,mode string)*exec.Cmd{
 t.Helper()
 return &exec.Cmd{Path:os.Args[0],Args:[]string{os.Args[0],"-test.run=^TestLeaseHelperProcess$"},
    Env:append(os.Environ(),"HMRC_CHILD_MODE="+mode,"HMRC_CHILD_PATH="+path)}
}
func startHold(t *testing.T,path,mode string)*exec.Cmd{
 t.Helper()
 c:=runChild(t,path,mode)
 out,err:=c.StdoutPipe()
 if err!=nil{t.Fatal(err)}
 c.Stderr=os.Stderr
 c.Stdin=io.NopCloser(strings.NewReader("")) // overridden below: keep child stdin open with a pipe
 _=c.Stdin
 w,err:=c.StdinPipe()
 if err!=nil{t.Fatal(err)}
 // Prevent stdin EOF until parent has killed the child.
 _=w
 if err:=c.Start();err!=nil{t.Fatal(err)}
 expected:="LOCKED"
 if mode=="commit"{expected="COMMITTED"}
 line,err:=bufio.NewReader(out).ReadString('\n')
 if err!=nil||strings.TrimSpace(line)!=expected{
   c.Process.Kill();c.Wait()
   t.Fatalf("child did not admit expected phase %q: %q (%v)",expected,line,err)
 }
 return c
}
func TestCrashAfterCommitIsDurableAndLeaseStale(t *testing.T){
 p,c:=makeState(t)
 child:=startHold(t,p,"commit")
 // The parent has observed COMMITTED only after fsync+rename+dir-sync.
 if err:=child.Process.Kill();err!=nil{t.Fatal(err)}
 _=child.Wait()
 if _,err:=evidence.Open(p,c,nil);!errors.Is(err,evidence.ErrBusy){
   t.Fatalf("unsafe implicit lock stealing after crash: %v",err)
 }
 // Recovery must not modify the stale lease. The externally authorized
 // coordinator, not this experimental library, reconciles it after confirming
 // both process exit and exact source-backed checkpoint generation.
 raw,err:=os.ReadFile(p)
 if err!=nil{t.Fatal(err)}
 if len(raw)==0{t.Fatal("committed checkpoint disappeared")}
 if err:=os.Remove(p+".lease");err!=nil{t.Fatal(err)}
 m,err:=evidence.Open(p,c,nil)
 if err!=nil{t.Fatal(err)}
 snap,err:=m.Read()
 if err!=nil||snap.Generation!=2||len(snap.Evicted)!=2{t.Fatalf("committed state lost: %+v %v",snap,err)}
 if snap.Units[0].ID!="protected"||snap.Units[1].ID!="active"{t.Fatal("protected or active context displaced")}
 if err:=m.Close();err!=nil{t.Fatal(err)}
}
func TestConcurrentProcessesCannotSplitBrain(t *testing.T){
 p,c:=makeState(t)
 owner:=startHold(t,p,"hold")
 defer func(){owner.Process.Kill();owner.Wait()}()
 var wg sync.WaitGroup
 errs:=make(chan error,12)
 for i:=0;i<12;i++{
  wg.Add(1)
  go func(){
   defer wg.Done()
   child:=runChild(t,p,"probe")
   output,err:=child.CombinedOutput()
   if err!=nil||!strings.Contains(string(output),"BUSY"){errs<-fmt.Errorf("probe bypass or error %v %q",err,output)}
  }()
 }
 wg.Wait();close(errs)
 for e:=range errs{t.Error(e)}
 if _,err:=evidence.Open(p,c,nil);!errors.Is(err,evidence.ErrBusy){
  t.Fatalf("parent bypassed active child lease: %v",err)
 }
}
func TestSymlinkLeaseCannotBypassExclusiveCreation(t *testing.T){
 p,c:=makeState(t)
 target:=filepath.Join(t.TempDir(),"attacker")
 if err:=os.WriteFile(target,[]byte("invalid"),0600);err!=nil{t.Fatal(err)}
 if err:=os.Symlink(target,p+".lease");err!=nil{t.Fatal(err)}
 if _,err:=evidence.Open(p,c,nil);!errors.Is(err,evidence.ErrBusy){
  t.Fatalf("symlink to existing lease did not fail closed: %v",err)
 }
 got,err:=os.ReadFile(target);if err!=nil||string(got)!="invalid"{t.Fatal("external file mutated by lease attempt")}
}
