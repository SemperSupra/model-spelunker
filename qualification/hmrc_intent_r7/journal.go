// Package intent is an experimental source-bound, single-host synthetic
// side-effect intent journal. It NEVER authorizes tools from model memory.
// Every uncertain dispatch remains HOLD until an external controller validates
// a matching durable tool receipt. No network/distributed exactly-once claim.
package intent

import (
 "crypto/sha256"
 "encoding/hex"
 "encoding/json"
 "errors"
 "fmt"
 "os"
 "path/filepath"
 "strings"
 "sync"
)

var ErrLease=errors.New("journal writer lease busy")
var ErrHold=errors.New("uncertain tool side-effect; external reconciliation required")
var ErrInvalid=errors.New("invalid or tampered journal/evidence")
var ErrState=errors.New("invalid state transition")
const (
 Prepared="PREPARED"
 Dispatching="DISPATCHING"
 Acked="ACKED"
)
type Record struct {
 Schema string
 ID string
 Scope string
 SourceDigest string
 PayloadDigest string
 State string
 Generation uint64
}
type Witness struct {
 Schema string
 ID string
 Scope string
 SourceDigest string
 PayloadDigest string
 ReceiptDigest string
}
type Journal struct {
 mu sync.Mutex
 root string
 lease *os.File
 closed bool
}
func sha(b []byte)string{h:=sha256.Sum256(b);return "sha256:"+hex.EncodeToString(h[:])}
func validDigest(v string)bool{
 if len(v)!=71||!strings.HasPrefix(v,"sha256:"){return false}
 _,err:=hex.DecodeString(v[7:])
 return err==nil
}
func valid(r Record)bool{
 return r.Schema=="hmrc-intent-r7"&&r.ID=="SYN_ONLY"&&r.Scope=="synthetic-atlas"&&
  validDigest(r.SourceDigest)&&validDigest(r.PayloadDigest)&&r.Generation>0&&
  (r.State==Prepared||r.State==Dispatching||r.State==Acked)
}
func atomic(root,path string,payload []byte)error{
 f,err:=os.CreateTemp(root,".intent-pending-")
 if err!=nil{return err}
 tmp:=f.Name()
 defer os.Remove(tmp)
 if err=f.Chmod(0600);err!=nil{f.Close();return err}
 if _,err=f.Write(payload);err!=nil{f.Close();return err}
 if err=f.Sync();err!=nil{f.Close();return err}
 if err=f.Close();err!=nil{return err}
 if err=os.Rename(tmp,path);err!=nil{return err}
 d,err:=os.Open(root);if err!=nil{return err}
 defer d.Close()
 return d.Sync()
}
func Open(root string)(*Journal,error){
 if err:=os.MkdirAll(root,0700);err!=nil{return nil,err}
 p:=filepath.Join(root,"writer.lease")
 f,err:=os.OpenFile(p,os.O_WRONLY|os.O_CREATE|os.O_EXCL,0600)
 if err!=nil{
  if errors.Is(err,os.ErrExist){return nil,ErrLease}
  return nil,err
 }
 if _,err=f.WriteString("single-owner; stale leases must be externally reconciled");err!=nil{
  f.Close();os.Remove(p);return nil,err
 }
 if err=f.Sync();err!=nil{f.Close();os.Remove(p);return nil,err}
 return &Journal{root:root,lease:f},nil
}
func (j *Journal) Close()error{
 j.mu.Lock();defer j.mu.Unlock()
 if j.closed{return ErrState}
 j.closed=true
 stat,err:=j.lease.Stat();if err!=nil{j.lease.Close();return err}
 p:=filepath.Join(j.root,"writer.lease")
 current,err:=os.Lstat(p);if err!=nil{j.lease.Close();return err}
 if !os.SameFile(stat,current){j.lease.Close();return ErrLease}
 if err=j.lease.Close();err!=nil{return err}
 return os.Remove(p)
}
func (j *Journal) path()string{return filepath.Join(j.root,"intent.json")}
func (j *Journal) witnessPath()string{return filepath.Join(j.root,"tool-witness.json")}
func (j *Journal) read() (Record,error){
 b,err:=os.ReadFile(j.path());if err!=nil{return Record{},err}
 var r Record
 if err=json.Unmarshal(b,&r);err!=nil||!valid(r){return Record{},ErrInvalid}
 canonical,err:=json.Marshal(r);if err!=nil{return Record{},err}
 if string(b)!=string(canonical){return Record{},ErrInvalid}
 return r,nil
}
func (j *Journal) put(r Record)error{
 if !valid(r){return ErrInvalid}
 b,err:=json.Marshal(r);if err!=nil{return err}
 return atomic(j.root,j.path(),b)
}
func (j *Journal) Prepare(source,payload []byte)error{
 j.mu.Lock();defer j.mu.Unlock()
 if j.closed{return ErrState}
 if len(source)==0||len(payload)==0||len(source)>4096||len(payload)>4096{return ErrInvalid}
 if _,err:=os.Lstat(j.path());err==nil{return ErrState}else if !errors.Is(err,os.ErrNotExist){return err}
 return j.put(Record{Schema:"hmrc-intent-r7",ID:"SYN_ONLY",Scope:"synthetic-atlas",
   SourceDigest:sha(source),PayloadDigest:sha(payload),State:Prepared,Generation:1})
}
func (j *Journal) Begin()error{
 j.mu.Lock();defer j.mu.Unlock()
 if j.closed{return ErrState}
 r,err:=j.read();if err!=nil{return err}
 if r.State!=Prepared{return ErrState}
 r.State=Dispatching;r.Generation++
 return j.put(r)
}
// WriteSyntheticWitness is a deliberately synthetic file-backed tool. It may
// only be called after durable DISPATCHING. The remote target's idempotence
// would be a distinct capability in real integrations, not assumed here.
func (j *Journal) WriteSyntheticWitness()error{
 j.mu.Lock();defer j.mu.Unlock()
 if j.closed{return ErrState}
 r,err:=j.read();if err!=nil{return err}
 if r.State!=Dispatching{return ErrState}
 p:=j.witnessPath()
 if _,err:=os.Lstat(p);err==nil{return ErrHold}else if !errors.Is(err,os.ErrNotExist){return err}
 w:=Witness{Schema:"hmrc-synthetic-tool-witness-r7",ID:r.ID,Scope:r.Scope,
  SourceDigest:r.SourceDigest,PayloadDigest:r.PayloadDigest,
  ReceiptDigest:sha([]byte(r.ID+"|"+r.SourceDigest+"|"+r.PayloadDigest))}
 b,_:=json.Marshal(w)
 // Atomic durable synthetic witness, never a real external side effect.
 return atomic(j.root,p,b)
}
func (j *Journal) evidence(r Record)error{
 b,err:=os.ReadFile(j.witnessPath())
 if err!=nil{return ErrHold}
 var w Witness
 if err=json.Unmarshal(b,&w);err!=nil{return ErrHold}
 canonical,err:=json.Marshal(w)
 if err!=nil||string(b)!=string(canonical){return ErrHold}
 if w.Schema!="hmrc-synthetic-tool-witness-r7"||w.ID!=r.ID||
  w.Scope!=r.Scope||w.SourceDigest!=r.SourceDigest||w.PayloadDigest!=r.PayloadDigest||
  w.ReceiptDigest!=sha([]byte(r.ID+"|"+r.SourceDigest+"|"+r.PayloadDigest)){return ErrHold}
 return nil
}
// Acknowledge requires a durable witness. The controller must independently
// authorize a process-restart reconciliation; this bool is a test-double
// authority input, NEVER a memory/model-derived production permission.
func (j *Journal) Acknowledge(externalReconciliationApproved bool)error{
 j.mu.Lock();defer j.mu.Unlock()
 if j.closed{return ErrState}
 r,err:=j.read();if err!=nil{return err}
 if r.State==Acked{return ErrState}
 if r.State!=Dispatching{return ErrState}
 if !externalReconciliationApproved{return ErrHold}
 if err=j.evidence(r);err!=nil{return err}
 r.State=Acked;r.Generation++
 return j.put(r)
}
func (j *Journal) Recover() (Record,error){
 j.mu.Lock();defer j.mu.Unlock()
 if j.closed{return Record{},ErrState}
 r,err:=j.read();if err!=nil{return Record{},err}
 if r.State==Dispatching{return r,ErrHold}
 return r,nil
}
func (j *Journal) Inspect() (Record,error){
 j.mu.Lock();defer j.mu.Unlock()
 if j.closed{return Record{},ErrState}
 return j.read()
}
func (j *Journal) WitnessCount()(int,error){
 j.mu.Lock();defer j.mu.Unlock()
 if j.closed{return 0,ErrState}
 _,err:=os.Lstat(j.witnessPath())
 if errors.Is(err,os.ErrNotExist){return 0,nil}
 if err!=nil{return 0,err}
 return 1,nil
}
func (j *Journal) AssertNoDuplicate()error{
 n,err:=j.WitnessCount();if err!=nil{return err}
 if n>1{return fmt.Errorf("synthetic witness duplicate")}
 return nil
}
