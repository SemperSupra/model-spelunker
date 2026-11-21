package main

// OAuth resource-discovery composition for synthetic public-safe tests.
// The official MCP SDK owns RFC 9728 metadata serialization. This is NOT an
// authorization server, verified IdP configuration, or internet deployment.

import (
 "errors"
 "net/http"
 "net/url"
 "strings"

 "github.com/modelcontextprotocol/go-sdk/auth"
 "github.com/modelcontextprotocol/go-sdk/oauthex"
)

func httpsLocator(value string)bool{
 u,err:=url.Parse(value)
 return err==nil&&u.Scheme=="https"&&u.Host!=""&&u.User==nil&&u.Fragment==""&&u.RawQuery==""
}

// oauthDiscoveryRoutes serves public OAuth metadata and the separate,
// SDK-authenticated MCP tool endpoint. Only prevalidated issuer URLs are
// admitted; no dynamic user/chat parameter can choose an auth server.
func oauthDiscoveryRoutes(protected http.Handler,metadata *oauthex.ProtectedResourceMetadata,expectedResourceURL string)(http.Handler,error){
 if protected==nil||metadata==nil||!httpsLocator(expectedResourceURL)||
  !httpsLocator(metadata.Resource)||metadata.Resource!=expectedResourceURL||
  !strings.HasSuffix(metadata.Resource,"/mcp")||len(metadata.AuthorizationServers)==0{
  return nil,errors.New("invalid fixed OAuth resource metadata")
 }
 for _,issuer:=range metadata.AuthorizationServers {
  if !httpsLocator(issuer){return nil,errors.New("non-HTTPS or malformed fixed authorization server")}
 }
 foundRead:=false
 for _,scope:=range metadata.ScopesSupported{if scope==readScope{foundRead=true}}
 if !foundRead{return nil,errors.New("DLE resource metadata must advertise read scope")}
 mux:=http.NewServeMux()
 mux.Handle("/.well-known/oauth-protected-resource",auth.ProtectedResourceMetadataHandler(metadata))
 mux.Handle("/mcp",protected)
 return mux,nil
}
