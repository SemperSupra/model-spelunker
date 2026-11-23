// Package claims is a *deterministic* fail-closed memory claim admission oracle.
// Its external pinned catalog is trusted by the caller; a SHA-256 digest alone
// does not authenticate GitHub or confer permission. Never execute tools here.
package claims

import (
 "bytes"
 "crypto/sha256"
 "encoding/hex"
 "encoding/json"
 "errors"
 "io"
 "strings"
 "unicode/utf8"
)

var ErrInvalid=errors.New("invalid claim or unsupported authority boundary")
var ErrTampered=errors.New("source ID/digest/status/scope mismatch with pinned catalog")

// CatalogEntry must come from an independently authenticated owner source.
// Status is fixed at catalog admission; mutable memory cannot change it.
type CatalogEntry struct {
 ID string
 Scope string
 Revision uint64
 Status string // accepted, advisory, superseded
 Digest string // sha256:<hex>
}
type Evidence struct { ID string; Body []byte }
type Fact struct {
 Schema string `json:"schema"`
 Subject string `json:"subject"`
 Predicate string `json:"predicate"`
 Value string `json:"value"`
}
type Query struct { Scope, Subject, Predicate, IntendedUse string }
type Answer struct {
 State string `json:"state"` // SUPPORTED / ABSTAIN / AMBIGUOUS
 Value string `json:"value,omitempty"`
 SourceID string `json:"source_id,omitempty"`
 SourceDigest string `json:"source_digest,omitempty"`
 Status string `json:"status,omitempty"`
}

func Digest(body []byte) string {
 h:=sha256.Sum256(body)
 return "sha256:"+hex.EncodeToString(h[:])
}
func safeText(s string) bool {
 if !utf8.ValidString(s)||len(s)==0||len(s)>256||s!=strings.TrimSpace(s){return false}
 for _,r:=range s {if r<32||r==127{return false}}
 return true
}
func validEntry(e CatalogEntry) bool {
 if !safeText(e.ID)||!safeText(e.Scope)||e.Revision==0||len(e.Digest)!=71||
  !strings.HasPrefix(e.Digest,"sha256:") {return false}
 if _,err:=hex.DecodeString(e.Digest[7:]);err!=nil{return false}
 return e.Status=="accepted"||e.Status=="advisory"||e.Status=="superseded"
}
func decodeFact(body []byte) (Fact,error) {
 var f Fact
 if len(body)==0||len(body)>4096{return f,ErrInvalid}
 d:=json.NewDecoder(bytes.NewReader(body))
 d.DisallowUnknownFields()
 if err:=d.Decode(&f);err!=nil{return f,ErrInvalid}
 var trailing any
 if err:=d.Decode(&trailing);err!=io.EOF{return f,ErrInvalid}
 if f.Schema!="hmrc-fact-v1"||!safeText(f.Subject)||!safeText(f.Predicate)||
  !safeText(f.Value) {return f,ErrInvalid}
 // The immutable catalog authenticates bytes, but different JSON parsers
 // must not assign conflicting meaning to duplicate keys or encodings.
 // Require a single canonical typed representation at ingestion.
 canonical,err:=json.Marshal(f)
 if err!=nil||!bytes.Equal(canonical,body){return f,ErrInvalid}
 return f,nil
}
// Decide is read-only; it enforces exact source-byte identity AND an already
// pinned catalog scope/status. It does not infer evidence from lexical overlap.
// SUPPORTED means a source-grounded *fact string*, never permission to act.
// Missing/ambiguous claims fail closed; catalog conflict/tamper is an error.
func Decide(catalog []CatalogEntry,found []Evidence,q Query) (Answer,error) {
 abstain:=Answer{State:"ABSTAIN"}
 if !safeText(q.Scope)||!safeText(q.Subject)||!safeText(q.Predicate)||
  q.IntendedUse!="answer" {return abstain,ErrInvalid}
 allowed:=make(map[string]CatalogEntry,len(catalog))
 for _,e:=range catalog {
  if !validEntry(e){return abstain,ErrInvalid}
  if _,ok:=allowed[e.ID];ok{return abstain,ErrInvalid}
  allowed[e.ID]=e
 }
 seen:=make(map[string]bool,len(found))
 answer:=abstain
 for _,e:=range found {
  if !safeText(e.ID)||seen[e.ID]{return abstain,ErrTampered}
  seen[e.ID]=true
  ref,ok:=allowed[e.ID]
  if !ok||Digest(e.Body)!=ref.Digest{return abstain,ErrTampered}
  // Even correctly hashed foreign or superseded sources cannot answer.
  if ref.Scope!=q.Scope||ref.Status=="superseded"{continue}
  fact,err:=decodeFact(e.Body)
  if err!=nil{return abstain,ErrInvalid}
  if fact.Subject!=q.Subject||fact.Predicate!=q.Predicate{continue}
  // An accepted and an advisory claim for the same key are ambiguous;
  // a model or retrieved rank cannot silently choose the source.
  if answer.State=="SUPPORTED"{return Answer{State:"AMBIGUOUS"},nil}
  answer=Answer{State:"SUPPORTED",Value:fact.Value,SourceID:ref.ID,
    SourceDigest:ref.Digest,Status:ref.Status}
 }
 return answer,nil
}
