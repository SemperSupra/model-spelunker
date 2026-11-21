package main

// Optional adapter to the EXISTING offline Go DLE reconciler.
// This code neither parses DLE semantics nor decides acceptance. It freezes
// selected local input and executable bytes, invokes the qualified binary,
// validates its structured receipt, and returns a minimized candidate summary.
// It provides no GitHub authorization and must not claim remote attestation.

import (
 "context"
 "crypto/sha256"
 "encoding/hex"
 "encoding/json"
 "errors"
 "io"
 "os"
 "os/exec"
 "path/filepath"
 "strings"
 "time"
)

const maxDLEInput = 16<<20
const maxReconcileBinary = 128<<20
const maxReconcileResult = 2<<20
const candidateGrade = "local_pinned_input_only"

type ReconcileSummary struct {
 Schema string `json:"schema"`
 Status string `json:"status"`
 Authority string `json:"authority"`
 Revision string `json:"revision"`
 AuthoritySHA256 string `json:"authority_sha256"`
 CandidateSHA256 string `json:"candidate_sha256"`
 ExecutableSHA256 string `json:"executable_sha256"`
 Counts map[string]int `json:"counts"`
 EvidenceGrade string `json:"evidence_grade"`
 GitHubVerified bool `json:"github_verified"`
 MutationPerformed bool `json:"mutation_performed"`
}
type ReconcileEngine interface { Reconcile(context.Context)(ReconcileSummary,error) }
type externalReconciler struct {
 binary string
 binarySHA256 string
 authorityFile string
 candidateFile string
 authoritySHA256 string
}

// A local file pin verifies supplied bytes only. It does not prove the file
// originated in the current authoritative GitHub issue.
func hashHex(b []byte)string{sum:=sha256.Sum256(b);return hex.EncodeToString(sum[:])}
func validHex(s string)bool{
 if len(s)!=64 {return false}
 _,err:=hex.DecodeString(s)
 return err==nil && strings.ToLower(s)==s
}
func readRegular(path string,max int64)([]byte,error){
 if !filepath.IsAbs(path){return nil,errors.New("absolute pinned file path required")}
 st,err:=os.Lstat(path)
 if err!=nil{return nil,err}
 if !st.Mode().IsRegular()||st.Size()<0||st.Size()>max{return nil,errors.New("unsafe or oversized pinned input")}
 f,err:=os.Open(path);if err!=nil{return nil,err};defer f.Close()
 b,err:=io.ReadAll(io.LimitReader(f,max+1))
 if err!=nil||int64(len(b))>max{return nil,errors.New("pinned input unreadable or exceeds bound")}
 return b,nil
}
func writeFrozen(path string,b []byte,mode os.FileMode)error{
 f,err:=os.OpenFile(path,os.O_WRONLY|os.O_CREATE|os.O_EXCL,mode)
 if err!=nil{return err}
 if _,err=f.Write(b);err!=nil{f.Close();return err}
 if err=f.Sync();err!=nil{f.Close();return err}
 return f.Close()
}
func limitedJSON(path string,max int64,out any)error{
 raw,err:=readRegular(path,max)
 if err!=nil{return err}
 if err=json.Unmarshal(raw,out);err!=nil{return errors.New("invalid reconciler JSON result")}
 return nil
}
func validateReconcileSummary(s ReconcileSummary)error{
 if s.Schema!="dle-mcp-reconcile-summary-v0"||s.Status!="CANDIDATE_RECONCILIATION_ONLY"||
   s.GitHubVerified||s.MutationPerformed||s.EvidenceGrade!=candidateGrade||
   s.Authority==""||s.Revision==""||!validHex(s.AuthoritySHA256)||
   !validHex(s.CandidateSHA256)||!validHex(s.ExecutableSHA256) {
   return errors.New("untrusted reconciliation summary or semantic overclaim")
 }
 allowed:=map[string]bool{"agreement":true,"conflict":true,"unknown":true,"dle_only":true,"chat_only":true,"superseded":true}
 for k,n:=range s.Counts {if !allowed[k]||n<0{return errors.New("unexpected reconciliation disposition")}}
 return nil
}

func (e externalReconciler) Reconcile(ctx context.Context)(ReconcileSummary,error){
 var none ReconcileSummary
 if !validHex(e.authoritySHA256)||!validHex(e.binarySHA256){return none,errors.New("exact binary and authority pins required")}
 auth,err:=readRegular(e.authorityFile,maxDLEInput)
 if err!=nil{return none,err}
 candidates,err:=readRegular(e.candidateFile,maxDLEInput)
 if err!=nil{return none,err}
 binary,err:=readRegular(e.binary,maxReconcileBinary)
 if err!=nil{return none,err}
 if hashHex(auth)!=e.authoritySHA256||hashHex(binary)!=e.binarySHA256 {
  return none,errors.New("pinned source or executable changed")
 }
 root,err:=os.MkdirTemp("","dle-mcp-bounded-*")
 if err!=nil{return none,err}
 defer os.RemoveAll(root)
 if err=os.Chmod(root,0700);err!=nil{return none,err}
 frozenBinary:=filepath.Join(root,"reconcile")
 frozenAuthority:=filepath.Join(root,"dle.json")
 frozenCandidate:=filepath.Join(root,"candidates.json")
 out:=filepath.Join(root,"out")
 for _,v:=range []struct{path string;bytes []byte;mode os.FileMode}{{frozenBinary,binary,0500},{frozenAuthority,auth,0600},{frozenCandidate,candidates,0600}}{
  if err=writeFrozen(v.path,v.bytes,v.mode);err!=nil{return none,err}
 }
 if err=os.Mkdir(out,0700);err!=nil{return none,err}
 ctx,cancel:=context.WithTimeout(ctx,20*time.Second);defer cancel()
 cmd:=exec.CommandContext(ctx,frozenBinary,"--candidates",frozenCandidate,"--dle",frozenAuthority,"--dle-sha256",e.authoritySHA256,"--out",out)
 cmd.Env=[]string{"PATH="+os.Getenv("PATH")}
 if err=cmd.Run();err!=nil{return none,errors.New("qualified offline reconciler failed")}
 var result struct{
  Schema string `json:"schema"`
  Authority string `json:"authority"`
  Revision string `json:"revision"`
  AuthoritySHA256 string `json:"authority_sha256"`
  CandidateSHA256 string `json:"candidate_sha256"`
  Differences []struct{ID string `json:"id"`; Disposition string `json:"disposition"`} `json:"differences"`
  Counts map[string]int `json:"counts"`
  MutationPerformed bool `json:"mutation_performed"`
 }
 if err=limitedJSON(filepath.Join(out,"reconciliation.json"),maxReconcileResult,&result);err!=nil{return none,err}
 var contextOut struct {
  Schema string `json:"schema"`
  Authority string `json:"authority"`
  Revision string `json:"revision"`
  SHA256 string `json:"sha256"`
  GitHubVerified bool `json:"github_verified"`
  Accepted []struct{Status string `json:"status"`} `json:"accepted"`
 }
 if err=limitedJSON(filepath.Join(out,"context.json"),maxReconcileResult,&contextOut);err!=nil{return none,err}
 if result.Schema!="dle-reconciliation-v1"||result.Authority==""||result.Revision==""||
  result.AuthoritySHA256!=e.authoritySHA256||result.CandidateSHA256!=hashHex(candidates)||
  result.MutationPerformed||contextOut.Schema!="dle-context-v1"||contextOut.GitHubVerified||
  contextOut.Authority!=result.Authority||contextOut.Revision!=result.Revision||
  contextOut.SHA256!=result.AuthoritySHA256 {return none,errors.New("reconciler output has incorrect authority, pin or trust grade")}
 for _,item:=range contextOut.Accepted {if item.Status!="accepted"{return none,errors.New("unaccepted claim promoted into context")}}
 counts:=map[string]int{}
 for k,v:=range result.Counts {counts[k]=v}
 tally:=map[string]int{}
 for _,d:=range result.Differences{tally[d.Disposition]++}
 // A difference of unknown type or uncounted difference is a failed proof.
 if len(tally)!=len(counts) {return none,errors.New("reconciler counts disagree with difference list")}
 for k,n:=range counts {if tally[k]!=n{return none,errors.New("reconciler difference count mismatch")}}
 summary:=ReconcileSummary{Schema:"dle-mcp-reconcile-summary-v0",
  Status:"CANDIDATE_RECONCILIATION_ONLY",Authority:result.Authority,Revision:result.Revision,
  AuthoritySHA256:result.AuthoritySHA256,CandidateSHA256:result.CandidateSHA256,
  ExecutableSHA256:e.binarySHA256,Counts:counts,EvidenceGrade:candidateGrade,
  GitHubVerified:false,MutationPerformed:false}
 if err=validateReconcileSummary(summary);err!=nil{return none,err}
 // Avoid leaking the private candidate text or accepted claim bodies through
 // generic tool responses. Other authorized interfaces may serve projections.
 return summary,nil
}

