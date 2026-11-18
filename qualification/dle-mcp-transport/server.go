// Package main provides a deliberately read-only MCP transport adapter.
//
// This experiment does not own project DLE state. It exposes *only* an
// explicitly selected public-safe source observer, or an invented fixture.
// A future privately qualified adapter must supply the existing Go DLE
// reconciler instead of reimplementing its semantics here.
package main

import (
    "context"
    "crypto/subtle"
    "encoding/json"
    "errors"
    "fmt"
    "net/http"
    "os"
    "os/exec"
    "regexp"
    "strings"
    "time"

    "github.com/modelcontextprotocol/go-sdk/mcp"
)

const observationSchema = "dle-gh-source-observation-v0"
var repoPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$`)

type Observation struct {
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

type Provider interface {
    Observe(context.Context) (Observation,error)
}

type fixtureProvider struct{ value Observation }
func (p fixtureProvider) Observe(context.Context)(Observation,error){return p.value,nil}

// observerProvider composes the already-existing public GitHub observation
// executable. All target arguments are pinned at server startup, NOT
// selected by a chat client; no shell, GitHub mutations or auth duplication.
type observerProvider struct {
    bin, repo, checkout string
    issue int
}
func (p observerProvider) Observe(ctx context.Context)(Observation,error){
    var o Observation
    ctx,cancel:=context.WithTimeout(ctx,20*time.Second);defer cancel()
    cmd:=exec.CommandContext(ctx,p.bin,"--repo",p.repo,"--issue",fmt.Sprint(p.issue),"--checkout",p.checkout)
    b,err:=cmd.Output()
    if err!=nil{return o,errors.New("pinned source observation failed")}
    if len(b)>1<<20{return o,errors.New("observation exceeds bound")}
    if err=json.Unmarshal(b,&o);err!=nil{return o,errors.New("invalid observation encoding")}
    return o,validate(o,p.repo,p.issue)
}

func validate(o Observation,repo string,issue int)error{
    if !repoPattern.MatchString(repo)||strings.Contains(repo,"..")||issue<1||issue>1000000000{
        return errors.New("invalid pinned workset")
    }
    if o.Schema!=observationSchema||o.Repository!=repo||o.IssueNumber!=issue||o.MutationPerformed||o.GitHubVerified{
        return errors.New("wrong source, invalid schema or overclaimed authority")
    }
    if o.IssueID<=0||o.IssueNodeID==""||len(o.IssueBodySHA256)!=64||
       o.EvidenceGrade!="github_api_response_only"||
       o.Coverage!="issue_body_and_counts_not_comments_or_semantic_acceptance" {
        return errors.New("incomplete bounded source receipt")
    }
    return nil
}

type noInput struct{}
type Discovery struct {
    Schema string `json:"schema"`
    Repository string `json:"repository"`
    IssueNumber int `json:"issue_number"`
    Tools []string `json:"tools"`
    Scope string `json:"scope"`
    ReadOnly bool `json:"read_only"`
    SemanticAuthority string `json:"semantic_authority"`
    MutationPerformed bool `json:"mutation_performed"`
}
type Result struct {
    Schema string `json:"schema"`
    Status string `json:"status"`
    Observation Observation `json:"observation"`
    Authority string `json:"authority"`
    MutationPerformed bool `json:"mutation_performed"`
}

func newServer(provider Provider,repo string,issue int)*mcp.Server{
    s:=mcp.NewServer(&mcp.Implementation{Name:"dle-source-observer-rdte",Version:"0.1.0"},nil)
    mcp.AddTool(s,&mcp.Tool{Name:"dle_discover",Description:"Discover the single selected source and read-only capabilities. This does not grant DLE authority."},
      func(ctx context.Context,_ *mcp.CallToolRequest,_ noInput)(*mcp.CallToolResult,Discovery,error){
        return nil,Discovery{Schema:"dle-mcp-discovery-v0",Repository:repo,IssueNumber:issue,
            Tools:[]string{"dle_discover","dle_observe"},Scope:"one_pinned_source_only",
            ReadOnly:true,SemanticAuthority:"UNKNOWN_REQUIRES_PROJECT_DLE",MutationPerformed:false},nil
      })
    mcp.AddTool(s,&mcp.Tool{Name:"dle_observe",Description:"Observe the pinned source using the existing read-only GitHub observer; source evidence only, no semantic acceptance."},
      func(ctx context.Context,_ *mcp.CallToolRequest,_ noInput)(*mcp.CallToolResult,Result,error){
        o,err:=provider.Observe(ctx)
        if err!=nil{return nil,Result{},err}
        if err=validate(o,repo,issue);err!=nil{return nil,Result{},err}
        return nil,Result{Schema:"dle-mcp-observe-v0",Status:"OBSERVED_SOURCE_ONLY",
            Observation:o,Authority:"UNKNOWN_UNTIL_INDEPENDENT_DLE_RECONCILIATION",MutationPerformed:false},nil
      })
    return s
}

// Bearer validation is a synthetic ingress test, not a production OAuth
// authorization server. A real remote deployment requires an independently
// qualified OAuth/OIDC resource server and per-client authority binding.
func protected(next http.Handler,token string)http.Handler{
    return http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){
        given:=strings.TrimPrefix(r.Header.Get("Authorization"),"Bearer ")
        if token==""||given==r.Header.Get("Authorization")||subtle.ConstantTimeCompare([]byte(given),[]byte(token))!=1 {
            w.Header().Set("WWW-Authenticate","Bearer")
            http.Error(w,"unauthorized",http.StatusUnauthorized)
            return
        }
        next.ServeHTTP(w,r)
    })
}
func newHTTPHandler(provider Provider,repo string,issue int,token string)http.Handler{
    mux:=http.NewServeMux()
    mcpHandler:=mcp.NewStreamableHTTPHandler(func(*http.Request)*mcp.Server{
        return newServer(provider,repo,issue)
    },&mcp.StreamableHTTPOptions{Stateless:true,JSONResponse:true})
    mux.Handle("/mcp",protected(mcpHandler,token))
    return mux
}
func loadFixture(path string)(Observation,error){
    var o Observation
    if path==""{return o,errors.New("fixture required")}
    f,err:=os.Open(path);if err!=nil{return o,err};defer f.Close()
    if st,err:=f.Stat();err!=nil||st.Size()>1<<20{return o,errors.New("invalid fixture size")}
    dec:=json.NewDecoder(f);dec.DisallowUnknownFields()
    if err=dec.Decode(&o);err!=nil{return o,err}
    return o,nil
}
