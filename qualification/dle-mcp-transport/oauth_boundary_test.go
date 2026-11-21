package main

import (
 "context"
 "encoding/json"
 "errors"
 "io"
 "net/http"
 "net/http/httptest"
 "reflect"
 "strings"
 "testing"
 "time"

 "github.com/modelcontextprotocol/go-sdk/auth"
 "github.com/modelcontextprotocol/go-sdk/mcp"
)

const mockResourceMetadata = "https://identity.example.invalid/.well-known/oauth-protected-resource"
const mockWorkset = "o/r#7"

// This verifier is an ORIGINAL SYNTHETIC TEST DOUBLE. It does not verify
// cryptographic signatures, issuers, audiences, or real OAuth tokens.
func syntheticVerifiedToken(_ context.Context,token string,_ *http.Request)(*auth.TokenInfo,error){
 if token=="invalid"||token=="revoked"||token=="wrong-audience"{
  return nil,auth.ErrInvalidToken
 }
 info:=&auth.TokenInfo{
  Scopes:[]string{readScope},
  UserID:"actor-1",
  Expiration:time.Now().Add(8*time.Minute),
  Extra:map[string]any{"client_id":"synthetic-web","workset_ref":mockWorkset},
 }
 switch token {
 case "valid-web","valid-cli":
   if token=="valid-cli"{info.Extra["client_id"]="synthetic-cli"}
 case "valid-reconcile":
   info.Scopes=append(info.Scopes,reconcileScope)
 case "expired":
   info.Expiration=time.Now().Add(-time.Minute)
 case "missing-expiry":
   info.Expiration=time.Time{}
 case "missing-scope":
   info.Scopes=[]string{"unrelated"}
 case "wrong-workset":
   info.Extra["workset_ref"]="wrong/owner#777"
 case "no-subject":
   info.UserID=""
 case "no-client":
   delete(info.Extra,"client_id")
 case "ungranted-client":
   info.Extra["client_id"]="unapproved-client"
 case "ungranted-subject":
   info.UserID="other-user"
 default:return nil,auth.ErrInvalidToken
 }
 return info,nil
}
type scopedTokenTransport struct {base http.RoundTripper;token string}
func (t scopedTokenTransport) RoundTrip(req *http.Request)(*http.Response,error){
 cp:=req.Clone(req.Context())
 cp.Header.Set("Authorization","Bearer "+t.token)
 return t.base.RoundTrip(cp)
}
func syntheticOAuthConfig()sourceAuthConfig{
 return sourceAuthConfig{
  Verifier:syntheticVerifiedToken,
  Workset:mockWorkset,
  ResourceMetadataURL:mockResourceMetadata,
  AllowedCallers:[]sourceClientGrant{
   {Subject:"actor-1",ClientID:"synthetic-web"},
   {Subject:"actor-1",ClientID:"synthetic-cli"},
  },
 }
}
func TestSDKNativeOAuthDenials(t *testing.T){
 fixture,err:=loadFixture("testdata/observed.json");if err!=nil{t.Fatal(err)}
 handler,err:=newOAuthContractHandler(fixtureProvider{fixture},"o/r",7,nil,syntheticOAuthConfig())
 if err!=nil{t.Fatal(err)}
 srv:=httptest.NewServer(handler);defer srv.Close()
 cases:=[]struct{token string; expected int}{
  {"",401},{"invalid",401},{"revoked",401},{"wrong-audience",401},
  {"expired",401},{"missing-expiry",401},{"missing-scope",403},
  {"wrong-workset",403},{"no-subject",403},{"no-client",403},
  {"ungranted-client",403},{"ungranted-subject",403},
 }
 for _,tc:=range cases{
  req,err:=http.NewRequest("POST",srv.URL,strings.NewReader(`{"jsonrpc":"2.0","method":"tools/list","id":1}`))
  if err!=nil{t.Fatal(err)}
  req.Header.Set("Content-Type","application/json")
  if tc.token!=""{req.Header.Set("Authorization","Bearer "+tc.token)}
  res,err:=http.DefaultClient.Do(req);if err!=nil{t.Fatal(err)}
  io.Copy(io.Discard,res.Body);res.Body.Close()
  if res.StatusCode!=tc.expected{t.Fatalf("%q got HTTP %d want %d",tc.token,res.StatusCode,tc.expected)}
  if tc.expected==401||tc.expected==403{
   if c:=res.Header.Get("WWW-Authenticate");c==""&&tc.expected==401{
    t.Fatalf("%q missing authentication challenge",tc.token)
   }
  }
 }
}
func connectScoped(t *testing.T,url,token string)*mcp.ClientSession{
 t.Helper()
 ctx,cancel:=context.WithTimeout(context.Background(),15*time.Second)
 defer cancel()
 client:=mcp.NewClient(&mcp.Implementation{Name:"scope-test",Version:"v0"},nil)
 sess,err:=client.Connect(ctx,&mcp.StreamableClientTransport{
  Endpoint:url,
  HTTPClient:&http.Client{Transport:scopedTokenTransport{base:http.DefaultTransport,token:token}},
 },nil)
 if err!=nil{t.Fatalf("OAuth synthetic MCP Connect(%s) failed: %v",token,err)}
 return sess
}
func TestSDKScopesAndEquivalentWebCLIResults(t *testing.T){
 fixture,err:=loadFixture("testdata/observed.json");if err!=nil{t.Fatal(err)}
 readHandler,err:=newOAuthContractHandler(fixtureProvider{fixture},"o/r",7,nil,syntheticOAuthConfig())
 if err!=nil{t.Fatal(err)}
 srv:=httptest.NewServer(readHandler);defer srv.Close()
 web:=connectScoped(t,srv.URL,"valid-web");defer web.Close()
 cli:=connectScoped(t,srv.URL,"valid-cli");defer cli.Close()
 get:=func(s *mcp.ClientSession)map[string]json.RawMessage{
  ctx,cancel:=context.WithTimeout(context.Background(),15*time.Second);defer cancel()
  list,err:=s.ListTools(ctx,nil);if err!=nil{t.Fatal(err)}
  if len(list.Tools)!=2{t.Fatalf("read-only endpoint unexpectedly widened tool list: %+v",list.Tools)}
  got:=map[string]json.RawMessage{}
  for _,name:=range []string{"dle_discover","dle_observe"}{
   reply,err:=s.CallTool(ctx,&mcp.CallToolParams{Name:name,Arguments:map[string]any{}})
   if err!=nil||reply.IsError{t.Fatalf("tool %s failed %v",name,err)}
   content,err:=json.Marshal(reply.StructuredContent);if err!=nil{t.Fatal(err)}
   got[name]=content
  }
  return got
 }
 if a,b:=get(web),get(cli);!reflect.DeepEqual(a,b){
  t.Fatalf("equivalent scoped clients diverged: web=%v cli=%v",a,b)
 }
 engine:=mockSummaryProvider{result:sampleSummary()}
 highHandler,err:=newOAuthContractHandler(fixtureProvider{fixture},"o/r",7,engine,syntheticOAuthConfig())
 if err!=nil{t.Fatal(err)}
 highSrv:=httptest.NewServer(highHandler);defer highSrv.Close()
 // A read-only client must not even initialize on a reconcile-enabled endpoint.
 req,err:=http.NewRequest("POST",highSrv.URL,strings.NewReader(`{"jsonrpc":"2.0","method":"initialize","id":1}`))
 if err!=nil{t.Fatal(err)}
 req.Header.Set("Authorization","Bearer valid-web")
 req.Header.Set("Content-Type","application/json")
 response,err:=http.DefaultClient.Do(req);if err!=nil{t.Fatal(err)}
 io.Copy(io.Discard,response.Body);response.Body.Close()
 if response.StatusCode!=403{t.Fatalf("read-only token reached elevated endpoint: %d",response.StatusCode)}
 admin:=connectScoped(t,highSrv.URL,"valid-reconcile");defer admin.Close()
 ctx,cancel:=context.WithTimeout(context.Background(),15*time.Second);defer cancel()
 tools,err:=admin.ListTools(ctx,nil);if err!=nil{t.Fatal(err)}
 if len(tools.Tools)!=3{t.Fatalf("expected elevated read-only tool: %d",len(tools.Tools))}
}
func TestOAuthConfigurationFailsClosed(t *testing.T){
 fixture,err:=loadFixture("testdata/observed.json");if err!=nil{t.Fatal(err)}
 cases:=[]func(*sourceAuthConfig){
  func(c *sourceAuthConfig){c.Verifier=nil},
  func(c *sourceAuthConfig){c.AllowedCallers=nil},
  func(c *sourceAuthConfig){c.AllowedCallers=[]sourceClientGrant{{Subject:"",ClientID:"synthetic-web"}}},
  func(c *sourceAuthConfig){c.Workset="wrong/r#7"},
  func(c *sourceAuthConfig){c.ResourceMetadataURL="http://identity.example.invalid"},
  func(c *sourceAuthConfig){c.ResourceMetadataURL="https://identity.example.invalid/#fragment"},
  func(c *sourceAuthConfig){c.ResourceMetadataURL=""},
 }
 for i,f:=range cases{
  c:=syntheticOAuthConfig();f(&c)
  if _,err:=newOAuthContractHandler(fixtureProvider{fixture},"o/r",7,nil,c);err==nil{
   t.Fatalf("invalid OAuth resource config %d accepted",i)
  }
 }
 if _,err:=newOAuthContractHandler(fixtureProvider{fixture},"o/..",7,nil,syntheticOAuthConfig());err==nil{
  t.Fatal("invalid repo accepted")
 }
 if _,err:=newOAuthContractHandler(fixtureProvider{fixture},"o/r",0,nil,syntheticOAuthConfig());err==nil{
  t.Fatal("invalid issue accepted")
 }
 if !errors.Is(auth.ErrInvalidToken,auth.ErrInvalidToken){t.Fatal("invalid verifier sentinel")}
}
