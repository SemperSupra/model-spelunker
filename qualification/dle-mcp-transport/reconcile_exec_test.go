package main

import (
 "context"
 "crypto/sha256"
 "encoding/hex"
 "os"
 "os/exec"
 "path/filepath"
 "strings"
 "testing"
 "time"
)

func TestActualExternalReconcilerProcessBoundary(t *testing.T){
 dir:=t.TempDir()
 binary:=filepath.Join(dir,"synthetic-qualified-reconciler")
 ctx,cancel:=context.WithTimeout(context.Background(),70*time.Second);defer cancel()
 cmd:=exec.CommandContext(ctx,"go","build","-o",binary,"./testdata/synthetic_reconciler")
 if out,err:=cmd.CombinedOutput();err!=nil{t.Fatalf("synthetic executable build failure: %v %s",err,out)}
 digest:=func(b []byte)string{h:=sha256.Sum256(b);return hex.EncodeToString(h[:])}
 binBytes,err:=os.ReadFile(binary);if err!=nil{t.Fatal(err)}
 authority:=filepath.Join(dir,"authority.json")
 candidate:=filepath.Join(dir,"candidate.json")
 source:=[]byte(`{"source":"https://example.invalid/o/r/issues/7","revision":"exact-pinned-synthetic"}`)
 if err:=os.WriteFile(authority,source,0600);err!=nil{t.Fatal(err)}
 e:=externalReconciler{binary:binary,binarySHA256:digest(binBytes),
  authorityFile:authority,candidateFile:candidate,authoritySHA256:digest(source)}
 for _,tc:=range []struct{mode string;allow bool}{
  {"normal",true},{"false-promotion",false},{"wrong-source",false},{"unknown-kind",false},
 }{
  if err:=os.WriteFile(candidate,[]byte(`{"mode":"`+tc.mode+`"}`),0600);err!=nil{t.Fatal(err)}
  receipt,err:=e.Reconcile(ctx)
  if tc.allow {
   if err!=nil{t.Fatalf("%s rejected: %v",tc.mode,err)}
   if receipt.Counts["unknown"]!=1||receipt.GitHubVerified||receipt.MutationPerformed||
   receipt.AuthoritySHA256!=digest(source)||receipt.ExecutableSHA256!=digest(binBytes)||
   receipt.EvidenceGrade!="local_pinned_input_only"{
    t.Fatalf("%s trust boundary incorrect: %+v",tc.mode,receipt)
   }
  }else if err==nil{
   t.Fatalf("%s unsafe reconciler output admitted",tc.mode)
  }
 }
 // The selected source file was not changed by a well-behaved fixture binary.
 if after,err:=os.ReadFile(authority);err!=nil||string(after)!=string(source){
  t.Fatal("frozen source mutated")
 }
 // No test task should accept a transposed private source identifier.
 e.authoritySHA256=strings.Repeat("e",64)
 if _,err:=e.Reconcile(ctx);err==nil{t.Fatal("changed source pin admitted")}
}
