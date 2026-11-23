// Package recovery qualifies an actual HTTP loopback synthetic tool whose
// durable idempotency ledger can be reconciled after a client crash. It is a
// TEST DOUBLE, not a real authorized external action, auth service or
// distributed exactly-once implementation.
package recovery

import (
 "bytes"
 "crypto/sha256"
 "encoding/hex"
 "encoding/json"
 "errors"
 "io"
 "net/http"
 "os"
 "path/filepath"
 "sync"
)

const Source="R8 public synthetic source, no real authority"
const Payload="R8 synthetic tool increment, no external target"
const ID="SYN_ONLY"
const Scope="synthetic-atlas"
var ErrInvalid=errors.New("invalid source-bound synthetic tool receipt")
var ErrAbsent=errors.New("synthetic external tool receipt absent")
func Digest(b []byte)string{
 h:=sha256.Sum256(b)
 return "sha256:"+hex.EncodeToString(h[:])
}
type Request struct{
 ID string
 Scope string
 SourceDigest string
 PayloadDigest string
}
type Receipt struct {
 Schema string
 ID string
 Scope string
 SourceDigest string
 PayloadDigest string
 ReceiptDigest string
 AppliedCount int
}
func ValidRequest(req Request) bool {
 return req.ID==ID&&req.Scope==Scope&&req.SourceDigest==Digest([]byte(Source))&&
  req.PayloadDigest==Digest([]byte(Payload))
}
func ReceiptFor(req Request)Receipt{
 return Receipt{Schema:"hmrc-r8-synthetic-http-tool",ID:req.ID,Scope:req.Scope,
  SourceDigest:req.SourceDigest,PayloadDigest:req.PayloadDigest,
  ReceiptDigest:Digest([]byte(req.ID+"|"+req.SourceDigest+"|"+req.PayloadDigest)),
  AppliedCount:1}
}
func validReceipt(r Receipt)bool{
 return r==ReceiptFor(Request{ID:ID,Scope:Scope,SourceDigest:Digest([]byte(Source)),
  PayloadDigest:Digest([]byte(Payload))})
}
func atomicWrite(root,path string,b []byte)error{
 f,e:=os.CreateTemp(root,".http-tool-r8-")
 if e!=nil{return e}
 tmp:=f.Name();defer os.Remove(tmp)
 if e=f.Chmod(0600);e!=nil{f.Close();return e}
 if _,e=f.Write(b);e!=nil{f.Close();return e}
 if e=f.Sync();e!=nil{f.Close();return e}
 if e=f.Close();e!=nil{return e}
 if e=os.Rename(tmp,path);e!=nil{return e}
 d,e:=os.Open(root);if e!=nil{return e}
 defer d.Close()
 return d.Sync()
}
type Server struct {
 mu sync.Mutex
 Root string
 DropResponseAfterPersist bool
}
func NewServer(root string,drop bool)(*Server,error){
 if e:=os.MkdirAll(root,0700);e!=nil{return nil,e}
 return &Server{Root:root,DropResponseAfterPersist:drop},nil
}
func (s *Server) path()string{return filepath.Join(s.Root,"synthetic-receipt.json")}
func (s *Server) read()(Receipt,error){
 b,e:=os.ReadFile(s.path())
 if errors.Is(e,os.ErrNotExist){return Receipt{},ErrAbsent}
 if e!=nil{return Receipt{},e}
 var r Receipt
 if e=json.Unmarshal(b,&r);e!=nil{return Receipt{},ErrInvalid}
 canonical,_:=json.Marshal(r)
 if !bytes.Equal(b,canonical)||!validReceipt(r){return Receipt{},ErrInvalid}
 return r,nil
}
func (s *Server) Inspect()(Receipt,error){
 s.mu.Lock();defer s.mu.Unlock()
 return s.read()
}
func (s *Server) ServeHTTP(w http.ResponseWriter,r *http.Request){
 // This test-only tool is served on an in-process loopback httptest.Server,
 // never on a public listener or arbitrary remote URL.
 w.Header().Set("Content-Type","application/json")
 if r.Method=="GET"&&r.URL.Path=="/v1/tool/SYN_ONLY"{
  receipt,e:=s.Inspect()
  if errors.Is(e,ErrAbsent){http.Error(w,"missing",http.StatusNotFound);return}
  if e!=nil{http.Error(w,"invalid witness",http.StatusConflict);return}
  _=json.NewEncoder(w).Encode(receipt)
  return
 }
 if r.Method!="POST"||r.URL.Path!="/v1/tool"{
  http.Error(w,"not admitted",http.StatusNotFound);return
 }
 if r.Header.Get("X-Idempotency-Key")!=ID{
  http.Error(w,"unknown idempotency key",http.StatusForbidden);return
 }
 d:=json.NewDecoder(io.LimitReader(r.Body,4096))
 d.DisallowUnknownFields()
 var req Request
 if d.Decode(&req)!=nil||!ValidRequest(req){
  http.Error(w,"source/payload mismatch",http.StatusForbidden);return
 }
 var tail any
 if d.Decode(&tail)!=io.EOF{http.Error(w,"trailing data",http.StatusBadRequest);return}
 s.mu.Lock()
 receipt,e:=s.read()
 if errors.Is(e,ErrAbsent){
  receipt=ReceiptFor(req)
  b,_:=json.Marshal(receipt)
  e=atomicWrite(s.Root,s.path(),b)
  if e==nil&&s.DropResponseAfterPersist{
   s.DropResponseAfterPersist=false
   // Deliberately lose the client response AFTER durable synthetic effect.
   // This is the classic uncertain HTTP outcome and must never trigger
   // blind "try again" from a memory-aware harness.
   h,ok:=w.(http.Hijacker)
   if ok {
    conn,_,err:=h.Hijack()
    if err==nil {conn.Close();s.mu.Unlock();return}
   }
  }
 }
 s.mu.Unlock()
 if e!=nil{http.Error(w,"unsafe ledger state",http.StatusConflict);return}
 _=json.NewEncoder(w).Encode(receipt)
}
// A real caller must verify the server's identity and authorization separately.
// This function checks the synthetic exact source and payload witness only.
func VerifyExternal(r Receipt)error{
 if !validReceipt(r){return ErrInvalid}
 return nil
}
