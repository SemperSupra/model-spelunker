package main

import (
 "context"
 "encoding/json"
 "io"
 "net/http"
 "net/http/httptest"
 "strings"
 "testing"
 "time"

 "github.com/modelcontextprotocol/go-sdk/mcp"
 "github.com/modelcontextprotocol/go-sdk/oauthex"
)

const syntheticResourceURL = "https://gateway.example.invalid/mcp"

func TestSDKProtectedMetadataAndAuthenticatedMCPComposition(t *testing.T){
 fixture,err:=loadFixture("testdata/observed.json");if err!=nil{t.Fatal(err)}
 config:=syntheticOAuthConfig()
 config.ResourceMetadataURL="https://gateway.example.invalid/.well-known/oauth-protected-resource"
 protected,err:=newOAuthContractHandler(fixtureProvider{fixture},"o/r",7,nil,config)
 if err!=nil{t.Fatal(err)}
 metadata:=&oauthex.ProtectedResourceMetadata{
  Resource:syntheticResourceURL,
  AuthorizationServers:[]string{"https://trusted-issuer.example.invalid"},
  ScopesSupported:[]string{readScope},
 }
 h,err:=oauthDiscoveryRoutes(protected,metadata,syntheticResourceURL)
 if err!=nil{t.Fatal(err)}
 srv:=httptest.NewServer(h);defer srv.Close()
 route:=srv.URL+"/.well-known/oauth-protected-resource"
 request,err:=http.NewRequest("GET",route,nil);if err!=nil{t.Fatal(err)}
 response,err:=http.DefaultClient.Do(request);if err!=nil{t.Fatal(err)}
 var responseMetadata oauthex.ProtectedResourceMetadata
 if err=json.NewDecoder(response.Body).Decode(&responseMetadata);err!=nil{t.Fatal(err)}
 response.Body.Close()
 if response.StatusCode!=200||responseMetadata.Resource!=syntheticResourceURL||
  len(responseMetadata.AuthorizationServers)!=1||
  responseMetadata.AuthorizationServers[0]!="https://trusted-issuer.example.invalid"{
  t.Fatalf("invalid SDK metadata response: %+v status %d",responseMetadata,response.StatusCode)
 }
 if response.Header.Get("Access-Control-Allow-Origin")!="*"{
  t.Fatal("standard SDK public metadata CORS policy changed")
 }
 options,err:=http.NewRequest("OPTIONS",route,nil);if err!=nil{t.Fatal(err)}
 resp,err:=http.DefaultClient.Do(options);if err!=nil{t.Fatal(err)}
 io.Copy(io.Discard,resp.Body);resp.Body.Close()
 if resp.StatusCode!=204{t.Fatalf("metadata OPTIONS %d",resp.StatusCode)}
 post,err:=http.NewRequest("POST",route,strings.NewReader("{}"));if err!=nil{t.Fatal(err)}
 resp,err=http.DefaultClient.Do(post);if err!=nil{t.Fatal(err)}
 io.Copy(io.Discard,resp.Body);resp.Body.Close()
 if resp.StatusCode!=405{t.Fatalf("metadata POST %d",resp.StatusCode)}
 // The tool interface itself still denies anonymous access. Metadata is
 // public and contains no GitHub credentials, source or private DLE content.
 unauth,err:=http.NewRequest("POST",srv.URL+"/mcp",strings.NewReader("{}"));if err!=nil{t.Fatal(err)}
 resp,err=http.DefaultClient.Do(unauth);if err!=nil{t.Fatal(err)}
 io.Copy(io.Discard,resp.Body);resp.Body.Close()
 if resp.StatusCode!=401{t.Fatalf("unprotected MCP endpoint: %d",resp.StatusCode)}
 if !strings.Contains(resp.Header.Get("WWW-Authenticate"),config.ResourceMetadataURL){
  t.Fatal("MCP challenge did not advertise fixed OAuth resource metadata")
 }
 ctx,cancel:=context.WithTimeout(context.Background(),15*time.Second);defer cancel()
 client:=mcp.NewClient(&mcp.Implementation{Name:"metadata-client",Version:"v0"},nil)
 session,err:=client.Connect(ctx,&mcp.StreamableClientTransport{
  Endpoint:srv.URL+"/mcp",
  HTTPClient:&http.Client{Transport:scopedTokenTransport{base:http.DefaultTransport,token:"valid-web"}},
 },nil)
 if err!=nil{t.Fatal(err)}
 defer session.Close()
 tools,err:=session.ListTools(ctx,nil);if err!=nil{t.Fatal(err)}
 if len(tools.Tools)!=2{t.Fatalf("unexpected discovered tool set %d",len(tools.Tools))}
}
func TestOAuthMetadataFailsClosedOnMaliciousReferences(t *testing.T){
 good:=func()*oauthex.ProtectedResourceMetadata{return &oauthex.ProtectedResourceMetadata{
  Resource:syntheticResourceURL,
  AuthorizationServers:[]string{"https://trusted-issuer.example.invalid"},
  ScopesSupported:[]string{readScope},
 }}
 handler:=http.HandlerFunc(func(w http.ResponseWriter,_ *http.Request){w.WriteHeader(204)})
 cases:=[]func(*oauthex.ProtectedResourceMetadata){
  func(m *oauthex.ProtectedResourceMetadata){m.Resource="http://insecure.example.invalid/mcp"},
  func(m *oauthex.ProtectedResourceMetadata){m.Resource="https://other.example.invalid/mcp"},
  func(m *oauthex.ProtectedResourceMetadata){m.AuthorizationServers=[]string{}},
  func(m *oauthex.ProtectedResourceMetadata){m.AuthorizationServers=[]string{"http://insecure.example.invalid"}},
  func(m *oauthex.ProtectedResourceMetadata){m.AuthorizationServers=[]string{"https://a.example.invalid/#token"}},
  func(m *oauthex.ProtectedResourceMetadata){m.AuthorizationServers=[]string{"https://user:pass@issuer.example.invalid"}},
  func(m *oauthex.ProtectedResourceMetadata){m.ScopesSupported=[]string{"other.scope"}},
 }
 for i,f:=range cases{
  m:=good();f(m)
  if _,err:=oauthDiscoveryRoutes(handler,m,syntheticResourceURL);err==nil{
   t.Fatalf("invalid static OAuth discovery metadata %d accepted",i)
  }
 }
 if _,err:=oauthDiscoveryRoutes(handler,good(),"http://gateway.example.invalid/mcp");err==nil{
  t.Fatal("insecure expected resource accepted")
 }
}
