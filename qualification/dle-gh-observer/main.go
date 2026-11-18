// This read-only experiment composes native Git and the official GitHub CLI.
// It does not authenticate separately, interpret DLE semantics, or mutate GitHub.
package main

import (
 "bytes"
 "context"
 "crypto/sha256"
 "encoding/hex"
 "encoding/json"
 "errors"
 "flag"
 "fmt"
 "os"
 "os/exec"
 "path/filepath"
 "regexp"
 "strconv"
 "strings"
 "time"
)

var component = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$`)
var gitID = regexp.MustCompile(`^(?:[0-9a-f]{40}|[0-9a-f]{64})$`)
const maxResponse = 1<<20

type runner func(context.Context,string,...string)([]byte,error)
type receipt struct {
 Schema string `json:"schema"`
 Repository string `json:"repository"`
 LocalCommit string `json:"local_commit"`
 DefaultBranch string `json:"default_branch"`
 RemoteDefaultCommit string `json:"remote_default_commit"`
 IssueNumber int `json:"issue_number"`
 IssueID int64 `json:"issue_id"`
 IssueNodeID string `json:"issue_node_id"`
 IssueState string `json:"issue_state"`
 IssueUpdatedAt string `json:"issue_updated_at"`
 IssueBodySHA256 string `json:"issue_body_sha256"`
 IssueBodyBytes int `json:"issue_body_bytes"`
 IssueCommentCount int `json:"issue_comment_count"`
 EvidenceGrade string `json:"evidence_grade"`
 Coverage string `json:"coverage"`
 GitHubVerified bool `json:"github_verified"`
 MutationPerformed bool `json:"mutation_performed"`
}
func validRepo(s string) bool {
 p:=strings.Split(s,"/")
 return len(p)==2 && component.MatchString(p[0]) && component.MatchString(p[1]) && p[0]!="." && p[0]!=".." && p[1]!="." && p[1]!=".."
}
func sha(b []byte) string {h:=sha256.Sum256(b);return hex.EncodeToString(h[:])}
func call(ctx context.Context,name string,args ...string)([]byte,error){
 cmd:=exec.CommandContext(ctx,name,args...)
 var stdout bytes.Buffer
 cmd.Stdout=&stdout
 // Do not expose stderr or the inherited environment in receipts.
 if err:=cmd.Run();err!=nil{return nil,fmt.Errorf("%s read-only command failed: %w",name,err)}
 if stdout.Len()>maxResponse{return nil,errors.New("response exceeds observation bound")}
 return stdout.Bytes(),nil
}
func observe(ctx context.Context,run runner,repo string,issue int,checkout string)(receipt,error){
 var out receipt
 if !validRepo(repo)||issue<1||issue>1000000000||checkout==""{return out,errors.New("invalid explicit source locator")}
 local,err:=run(ctx,"git","-C",checkout,"rev-parse","--verify","HEAD^{commit}")
 if err!=nil{return out,err}
 localSHA:=strings.TrimSpace(string(local))
 if !gitID.MatchString(localSHA){return out,errors.New("invalid local commit")}
 repoRaw,err:=run(ctx,"gh","api","--method","GET","repos/"+repo)
 if err!=nil{return out,err}
 var r struct{FullName string `json:"full_name"`;DefaultBranch string `json:"default_branch"`}
 if len(repoRaw)>maxResponse||json.Unmarshal(repoRaw,&r)!=nil||r.FullName!=repo||!component.MatchString(r.DefaultBranch){return out,errors.New("invalid repository response")}
 refRaw,err:=run(ctx,"gh","api","--method","GET","repos/"+repo+"/git/ref/heads/"+r.DefaultBranch)
 if err!=nil{return out,err}
 var ref struct{Ref string `json:"ref"`;Object struct{SHA string `json:"sha"`} `json:"object"`}
 if len(refRaw)>maxResponse||json.Unmarshal(refRaw,&ref)!=nil||ref.Ref!="refs/heads/"+r.DefaultBranch||!gitID.MatchString(ref.Object.SHA){return out,errors.New("invalid branch ref")}
 issueRaw,err:=run(ctx,"gh","api","--method","GET","repos/"+repo+"/issues/"+strconv.Itoa(issue))
 if err!=nil{return out,err}
 var i struct{
  ID int64 `json:"id"`;NodeID string `json:"node_id"`;Number int `json:"number"`;State string `json:"state"`
  UpdatedAt string `json:"updated_at"`;Body *string `json:"body"`;Comments int `json:"comments"`
  PullRequest *json.RawMessage `json:"pull_request"`
 }
 if len(issueRaw)>maxResponse||json.Unmarshal(issueRaw,&i)!=nil||i.Number!=issue||i.ID<=0||i.NodeID==""||(i.State!="open"&&i.State!="closed")||i.UpdatedAt==""||i.Body==nil||i.Comments<0||i.PullRequest!=nil{return out,errors.New("invalid issue response")}
 return receipt{Schema:"dle-gh-source-observation-v0",Repository:repo,LocalCommit:localSHA,DefaultBranch:r.DefaultBranch,RemoteDefaultCommit:ref.Object.SHA,IssueNumber:i.Number,IssueID:i.ID,IssueNodeID:i.NodeID,IssueState:i.State,IssueUpdatedAt:i.UpdatedAt,IssueBodySHA256:sha([]byte(*i.Body)),IssueBodyBytes:len(*i.Body),IssueCommentCount:i.Comments,EvidenceGrade:"github_api_response_only",Coverage:"issue_body_and_counts_not_comments_or_semantic_acceptance",GitHubVerified:false,MutationPerformed:false},nil
}
func main(){
 repo:=flag.String("repo","","explicit OWNER/REPO")
 issue:=flag.Int("issue",0,"issue number to observe")
 checkout:=flag.String("checkout",".","local checkout")
 flag.Parse()
 path,err:=filepath.Abs(*checkout);if err!=nil{fmt.Fprintln(os.Stderr,"invalid checkout");os.Exit(2)}
 ctx,cancel:=context.WithTimeout(context.Background(),30*time.Second);defer cancel()
 result,err:=observe(ctx,call,*repo,*issue,path)
 if err!=nil{fmt.Fprintln(os.Stderr,"observation failed:",err);os.Exit(1)}
 if err=json.NewEncoder(os.Stdout).Encode(result);err!=nil{fmt.Fprintln(os.Stderr,"output failed");os.Exit(1)}
}
