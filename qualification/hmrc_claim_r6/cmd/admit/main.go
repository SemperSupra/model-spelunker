// Command admit bridges a model/harness query to the *actual* R5 typed
// source-backed verifier. It is read-only and incapable of tool execution.
// Catalog is explicitly caller-supplied and MUST be independently authenticated
// before any production use; this CLI only runs synthetic public QA fixtures.
package main

import (
  "encoding/json"
  "errors"
  "io"
  "os"

  claims "example.com/sempersupra/hmrc-claim-r5"
)
type Request struct {
  Catalog []claims.CatalogEntry `json:"catalog"`
  Found []claims.Evidence `json:"found"`
  Query claims.Query `json:"query"`
}
type Response struct {
  State string `json:"state"`
  Value string `json:"value,omitempty"`
  SourceID string `json:"source_id,omitempty"`
  SourceDigest string `json:"source_digest,omitempty"`
  Failure string `json:"failure,omitempty"`
}
func dispatch(w io.Writer,rd io.Reader) error {
  d:=json.NewDecoder(io.LimitReader(rd,1<<20))
  d.DisallowUnknownFields()
  var req Request
  if err:=d.Decode(&req);err!=nil {
    return json.NewEncoder(w).Encode(Response{State:"ERROR",Failure:"MALFORMED_REQUEST"})
  }
  var tail any
  if err:=d.Decode(&tail);err!=io.EOF{
    return json.NewEncoder(w).Encode(Response{State:"ERROR",Failure:"TRAILING_OR_OVERSIZED"})
  }
  a,err:=claims.Decide(req.Catalog,req.Found,req.Query)
  if err!=nil {
    failure:="INVALID"
    if errors.Is(err,claims.ErrTampered){failure="TAMPERED"}
    return json.NewEncoder(w).Encode(Response{State:"ERROR",Failure:failure})
  }
  return json.NewEncoder(w).Encode(Response{
    State:a.State,Value:a.Value,SourceID:a.SourceID,SourceDigest:a.SourceDigest,
  })
}
func main(){
  if err:=dispatch(os.Stdout,os.Stdin);err!=nil{os.Exit(2)}
}
