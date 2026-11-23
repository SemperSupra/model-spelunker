package recovery

import (
 "bufio"
 "bytes"
 "context"
 "encoding/json"
 "errors"
 "fmt"
 "io"
 "net/http"
 "net/http/httptest"
 "os"
 "os/exec"
 "path/filepath"
 "strings"
 "sync"
 "testing"
 "time"

 intent "example.com/sempersupra/hmrc-intent-r7"
)

func request()Request{
 return Request{ID:ID,Scope:Scope,SourceDigest:Digest([]byte(Source)),
  PayloadDigest:Digest([]byte(Payload))}
}
func post(client *http.Client,url string,v Request,idem string)(Receipt,int,error){
 b,_:=json.Marshal(v)
 r,e:=http.NewRequestWithContext(context.Background(),"POST",url+"/v1/tool",bytes.NewReader(b))
 if e!=nil{return Receipt{},0,e}
 r.Header.Set("X-Idempotency-Key",idem)
 r.Header.Set("Content-Type","application/json")
 resp,e:=client.Do(r)
 if e!=nil{return Receipt{},0,e}
 defer resp.Body.Close()
 var receipt Receipt
 if resp.StatusCode==http.StatusOK {
  if e=json.NewDecoder(resp.Body).Decode(&receipt);e!=nil{return Receipt{},resp.StatusCode,e}
 }
 return receipt,resp.StatusCode,nil
}
func get(client *http.Client,url string)(Receipt,error){
 resp,e:=client.Get(url+"/v1/tool/SYN_ONLY")
 if e!=nil{return Receipt{},e}
 defer resp.Body.Close()
 if resp.StatusCode!=http.StatusOK{return Receipt{},ErrAbsent}
 var r Receipt
 if e=json.NewDecoder(resp.Body).Decode(&r);e!=nil{return Receipt{},e}
 return r,VerifyExternal(r)
}
func TestChildHTTPProcess(t *testing.T){
 if os.Getenv("HMRC_R8_CHILD")!="http-effect"{return}
 root:=os.Getenv("HMRC_R8_JOURNAL")
 url:=os.Getenv("HMRC_R8_TOOL_URL")
 j,e:=intent.Open(root);if e!=nil{t.Fatal(e)}
 if e=j.Prepare([]byte(Source),[]byte(Payload));e!=nil{t.Fatal(e)}
 if e=j.Begin();e!=nil{t.Fatal(e)}
 client:=&http.Client{Timeout:4*time.Second}
 receipt,status,e:=post(client,url,request(),ID)
 if e!=nil||status!=http.StatusOK||VerifyExternal(receipt)!=nil{
  t.Fatalf("remote synthetic effect failed %v status %d receipt %+v",e,status,receipt)
 }
 fmt.Println("REMOTE_EFFECT_DURABLE_NO_LOCAL_ACK")
 var one [1]byte
 _,_ = os.Stdin.Read(one[:]) // parent sends SIGKILL
}
func startAndKillClient(t *testing.T,journalRoot,toolURL string){
 t.Helper()
 cmd:=exec.Command(os.Args[0],"-test.run=^TestChildHTTPProcess$")
 cmd.Env=append(os.Environ(),"HMRC_R8_CHILD=http-effect",
  "HMRC_R8_JOURNAL="+journalRoot,"HMRC_R8_TOOL_URL="+toolURL)
 stdin,e:=cmd.StdinPipe();if e!=nil{t.Fatal(e)}
 output,e:=cmd.StdoutPipe();if e!=nil{t.Fatal(e)}
 cmd.Stderr=os.Stderr
 if e=cmd.Start();e!=nil{t.Fatal(e)}
 line,e:=bufio.NewReader(output).ReadString('\n')
 if e!=nil||strings.TrimSpace(line)!="REMOTE_EFFECT_DURABLE_NO_LOCAL_ACK"{
  cmd.Process.Kill();cmd.Wait()
  t.Fatalf("child failed to reach durable remote effect: %q %v",line,e)
 }
 if e=cmd.Process.Kill();e!=nil{t.Fatal(e)}
 _=cmd.Wait()
 _=stdin.Close()
}
func TestActualClientSIGKILLAfterHTTPExternalEffect(t *testing.T){
 root:=t.TempDir()
 journalRoot:=filepath.Join(root,"intent")
 ledgerRoot:=filepath.Join(root,"tool")
 backend,e:=NewServer(ledgerRoot,false);if e!=nil{t.Fatal(e)}
 srv:=httptest.NewServer(backend)
 startAndKillClient(t,journalRoot,srv.URL)
 srv.Close() // fake HTTP server restarts, persisted ledger must survive.
 fresh,e:=NewServer(ledgerRoot,false);if e!=nil{t.Fatal(e)}
 srv2:=httptest.NewServer(fresh)
 defer srv2.Close()
 if j,e:=intent.Open(journalRoot);!errors.Is(e,intent.ErrLease){
  if j!=nil{j.Close()}
  t.Fatalf("crashed client lease was implicitly stolen: %v",e)
 }
 // In real deployment this reconciliation must be authorized by a fenced
 // owner outside memory/model. Here external approval is a TEST CONDITION.
 if e:=os.Remove(filepath.Join(journalRoot,"writer.lease"));e!=nil{t.Fatal(e)}
 j,e:=intent.Open(journalRoot);if e!=nil{t.Fatal(e)}
 defer j.Close()
 state,e:=j.Recover()
 if !errors.Is(e,intent.ErrHold)||state.State!=intent.Dispatching{
  t.Fatalf("uncertain side effect incorrectly resumed: %+v %v",state,e)
 }
 if e=j.Acknowledge(true);!errors.Is(e,intent.ErrHold){
  t.Fatalf("missing local witness auto acknowledged %v",e)
 }
 external,e:=get(srv2.Client(),srv2.URL)
 if e!=nil||VerifyExternal(external)!=nil||external.AppliedCount!=1{
  t.Fatalf("external durable receipt missing or altered %+v %v",external,e)
 }
 if external.SourceDigest!=state.SourceDigest||external.PayloadDigest!=state.PayloadDigest{
  t.Fatal("external witness mismatches committed intent")
 }
 // Only after strict exact remote readback is it safe for the TEST controller
 // to materialize the local matched witness and ACK without repeating POST.
 if e=j.WriteSyntheticWitness();e!=nil{t.Fatal(e)}
 if e=j.Acknowledge(true);e!=nil{t.Fatal(e)}
 ended,e:=j.Recover()
 if e!=nil||ended.State!=intent.Acked||ended.Generation!=3{
  t.Fatalf("no exact recovered ACK %+v %v",ended,e)
 }
 duplicate,status,e:=post(srv2.Client(),srv2.URL,request(),ID)
 if e!=nil||status!=http.StatusOK||VerifyExternal(duplicate)!=nil||duplicate.AppliedCount!=1{
  t.Fatalf("server replay duplicated durable effect status=%d %+v %v",status,duplicate,e)
 }
 stored,e:=fresh.Inspect()
 if e!=nil||stored.AppliedCount!=1{t.Fatalf("durable server idempotency failed %+v %v",stored,e)}
}
func TestLostHTTPResponseCannotProveNoSideEffect(t *testing.T){
 root:=t.TempDir()
 backend,e:=NewServer(root,true);if e!=nil{t.Fatal(e)}
 srv:=httptest.NewServer(backend);defer srv.Close()
 client:=&http.Client{Timeout:4*time.Second,Transport:&http.Transport{DisableKeepAlives:true}}
 _,_,_=post(client,srv.URL,request(),ID)
 receipt,e:=backend.Inspect()
 if e!=nil||VerifyExternal(receipt)!=nil||receipt.AppliedCount!=1{
  t.Fatalf("unknown response wrongly inferred no side effect %+v %v",receipt,e)
 }
 // Repeating an idempotent request is safe *only because the tool server*,
 // not the inference engine or memory, owns this exact deduplication key.
 r,status,e:=post(srv.Client(),srv.URL,request(),ID)
 if e!=nil||status!=200||VerifyExternal(r)!=nil||r.AppliedCount!=1{
  t.Fatalf("network uncertain replay broke backend fence %+v %d %v",r,status,e)
 }
}
func TestTwentyFourConcurrentIdenticalPOSTsAreIdempotent(t *testing.T){
 backend,e:=NewServer(t.TempDir(),false);if e!=nil{t.Fatal(e)}
 srv:=httptest.NewServer(backend);defer srv.Close()
 var wg sync.WaitGroup
 failures:=make(chan error,24)
 for i:=0;i<24;i++{
  wg.Add(1)
  go func(){
   defer wg.Done()
   r,status,e:=post(srv.Client(),srv.URL,request(),ID)
   if e!=nil||status!=200||VerifyExternal(r)!=nil{
    failures<-fmt.Errorf("synthetic HTTP contender bypass: %d %+v %v",status,r,e)
   }
  }()
 }
 wg.Wait();close(failures)
 for e:=range failures{t.Error(e)}
 receipt,e:=backend.Inspect()
 if e!=nil||receipt.AppliedCount!=1{t.Fatalf("non-idempotent apply %+v %v",receipt,e)}
 wrong:=request();wrong.PayloadDigest=Digest([]byte("rogue"))
 if _,status,e:=post(srv.Client(),srv.URL,wrong,ID);e!=nil||status!=403{
  t.Fatalf("cross-payload replay admitted %d %v",status,e)
 }
 if _,status,e:=post(srv.Client(),srv.URL,request(),"OTHER");e!=nil||status!=403{
  t.Fatalf("wrong operation ID admitted %d %v",status,e)
 }
}
func TestCorruptExternalWitnessAndUnreachableToolFailClosed(t *testing.T){
 root:=t.TempDir()
 backend,e:=NewServer(root,false);if e!=nil{t.Fatal(e)}
 srv:=httptest.NewServer(backend)
 _,status,e:=post(srv.Client(),srv.URL,request(),ID)
 if e!=nil||status!=200{t.Fatalf("setup %v %d",e,status)}
 srv.Close()
 if _,e=get(&http.Client{Timeout:200*time.Millisecond},srv.URL);e==nil{
  t.Fatal("unreachable remote tool accepted an absent receipt")
 }
 path:=filepath.Join(root,"synthetic-receipt.json")
 raw,e:=os.ReadFile(path);if e!=nil{t.Fatal(e)}
 tampered:=bytes.Replace(raw,[]byte("synthetic-atlas"),[]byte("foreign-scope"),1)
 if bytes.Equal(tampered,raw){t.Fatal("tamper did not alter ledger")}
 if e=os.WriteFile(path,tampered,0600);e!=nil{t.Fatal(e)}
 fresh,e:=NewServer(root,false);if e!=nil{t.Fatal(e)}
 if _,e=fresh.Inspect();!errors.Is(e,ErrInvalid){
  t.Fatalf("forged durable ledger looked valid %v",e)
 }
 s:=httptest.NewServer(fresh);defer s.Close()
 resp,e:=s.Client().Get(s.URL+"/v1/tool/SYN_ONLY")
 if e!=nil{t.Fatal(e)}
 defer resp.Body.Close()
 _,_ = io.Copy(io.Discard,resp.Body)
 if resp.StatusCode!=http.StatusConflict{t.Fatalf("corrupted ledger publicly returned %d",resp.StatusCode)}
}
