package main

// A non-deployable OAuth protected-resource contract. It uses the official
// MCP Go SDK bearer/scope/expiration middleware, not a bespoke authentication
// stack. Production issuer/audience/signature and revocation verification must
// be separately qualified and supplied as an auth.TokenVerifier.
//
// This adapter never stores GitHub tokens, changes GitHub or promotes a DLE
// candidate. The existing DLE and Agent Dispatch ownership is unchanged.

import (
 "errors"
 "net/http"
 "net/url"
 "strconv"
 "strings"

 "github.com/modelcontextprotocol/go-sdk/auth"
 "github.com/modelcontextprotocol/go-sdk/mcp"
)

const readScope = "dle.read"
const reconcileScope = "dle.reconcile"

type sourceClientGrant struct {
 Subject string
 ClientID string
}
type sourceAuthConfig struct {
 Verifier auth.TokenVerifier
 Workset string
 ResourceMetadataURL string
 // Explicit operator-selected grant pairs; no implicit client admission.
 AllowedCallers []sourceClientGrant
}

// The verifier MUST cryptographically establish these facts; no chat-supplied
// value is accepted as a token claim by this source-bound access check.
func sourceIdentity(info *auth.TokenInfo,workset string,grants []sourceClientGrant)error{
 if info==nil||info.UserID==""||info.Extra==nil||workset==""||len(grants)==0{
  return errors.New("missing verified identity or approved client grant")
 }
 client,_:=info.Extra["client_id"].(string)
 bound,_:=info.Extra["workset_ref"].(string)
 if client==""||bound!=workset{
  return errors.New("token is not bound to the selected workset/client")
 }
 for _,grant:=range grants{
  if grant.Subject==info.UserID&&grant.ClientID==client{
   return nil
  }
 }
 return errors.New("ungranted subject/client")
}

// newOAuthContractHandler is ONLY for synthetic authentication admission tests.
// It is deliberately not wired to the HTTP CLI listener. Do not expose it
// publicly until an independent issuer/audience/JWKS/token-revocation
// verifier, OAuth metadata, operator grants, and tenant isolation qualify.
// When the optional reconciler is active, both scopes are required for this
// entire endpoint, avoiding read-only clients seeing higher-authority tools.
func newOAuthContractHandler(provider Provider,repo string,issue int,engine ReconcileEngine,c sourceAuthConfig)(http.Handler,error){
 if c.Verifier==nil||!repoPattern.MatchString(repo)||strings.Contains(repo,"..")||
    issue<1||issue>1000000000||c.Workset!=repo+"#"+strconv.Itoa(issue) {
  return nil,errors.New("invalid pinned source or token verifier")
 }
 if len(c.AllowedCallers)==0{return nil,errors.New("explicit caller grant required")}
 for _,grant:=range c.AllowedCallers{
  if grant.Subject==""||grant.ClientID==""{
   return nil,errors.New("empty operator-approved caller grant")
  }
 }
 meta,err:=url.Parse(c.ResourceMetadataURL)
 if err!=nil||meta.Scheme!="https"||meta.Host==""||meta.User!=nil||meta.Fragment!=""{
  return nil,errors.New("invalid HTTPS OAuth resource metadata locator")
 }
 scopes:=[]string{readScope}
 if engine!=nil {scopes=append(scopes,reconcileScope)}
 mcpHandler:=mcp.NewStreamableHTTPHandler(func(*http.Request)*mcp.Server{
  return newServerWithReconciler(provider,repo,issue,engine)
 },&mcp.StreamableHTTPOptions{Stateless:true,JSONResponse:true})
 inner:=http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){
  if err:=sourceIdentity(auth.TokenInfoFromContext(r.Context()),c.Workset,c.AllowedCallers);err!=nil{
   http.Error(w,"workset not authorized",http.StatusForbidden)
   return
  }
  mcpHandler.ServeHTTP(w,r)
 })
 return auth.RequireBearerToken(c.Verifier,&auth.RequireBearerTokenOptions{
  ResourceMetadataURL:c.ResourceMetadataURL,
  Scopes:scopes,
 })(inner),nil
}
