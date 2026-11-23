package claims

import "testing"

// A source hash proves bytes were retained, not that all parsers assign the
// same meaning to those bytes. Canonicalization is an independent admission
// requirement, including when a malicious document was pinned by mistake.
func TestCanonicalJSONRejectsParserDifferentials(t *testing.T) {
 bad := []string{
  `{"schema":"hmrc-fact-v1","subject":"release","predicate":"state","value":"HOLD","value":"GO"}`,
  `{"value":"HOLD","schema":"hmrc-fact-v1","subject":"release","predicate":"state"}`,
  `{ "schema":"hmrc-fact-v1","subject":"release","predicate":"state","value":"HOLD"}`,
  `{"schema":"hmrc-fact-v1","subject":"release","predicate":"state","value":"HOLD"}  `,
  `{"schema":"hmrc-fact-v1","subject":"release","predicate":"state","value":"HOLD","extra":"fake"}`,
  `{"schema":"hmrc-fact-v1","subject":"release","predicate":"state","value":"HOLD"}{"schema":"hmrc-fact-v1"}`,
 }
 query:=Query{Scope:"atlas",Subject:"release",Predicate:"state",IntendedUse:"answer"}
 for i,body:=range bad {
  bytes:=[]byte(body)
  c:=CatalogEntry{ID:"pinned",Scope:"atlas",Status:"accepted",Revision:1,Digest:Digest(bytes)}
  a,err:=Decide([]CatalogEntry{c},[]Evidence{{ID:"pinned",Body:bytes}},query)
  if err!=ErrInvalid||a.State!="ABSTAIN"{
   t.Fatalf("parser differential #%d accepted despite immutable digest: %+v err=%v",i,a,err)
  }
 }
}
func TestCanonicalSignedValidFactStillAccepted(t *testing.T) {
 c,e:=entry("ONE","atlas","accepted","สัญญาณสีน้ำเงิน","meaning","blaues Signal",5)
 a,err:=Decide([]CatalogEntry{c},[]Evidence{e},
  Query{Scope:"atlas",Subject:"สัญญาณสีน้ำเงิน",Predicate:"meaning",IntendedUse:"answer"})
 if err!=nil||a.State!="SUPPORTED"||a.SourceID!="ONE"{
  t.Fatalf("canonical public source regressed: %+v err=%v",a,err)
 }
}
