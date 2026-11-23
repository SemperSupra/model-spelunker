// Package catalog probes an explicitly allowlisted, immutable PUBLIC synthetic
// GitHub source fixture through source-pinned Git blob identity, not arbitrary
// retrieval. This is a public-source bootstrap reference, NOT the owner's
// private DLE trust anchor, a signature verifier or a service credential.
// Never expose this read path as model-controlled remote URL fetch.
package catalog

import (
 "context"
 "crypto/sha1"
 "crypto/sha256"
 "encoding/base64"
 "encoding/hex"
 "encoding/json"
 "errors"
 "io"
 "net/http"
 "net/url"
 "strconv"
 "time"
)
const (
 Repo="SemperSupra/model-spelunker"
 Path="qualification/fixtures/memory_dle_cpe_synthetic_v1.json"
 Commit="b627c86b149b9eb259441e885ad3ab079251da81"
 GitBlob="4f39a993bf9e8b32a4d8c244769c2dccd70e21b2"
 MaxResponse=100000
 MaxSource=20000
)
var ErrPin=errors.New("pinned source identity or allowed origin mismatch")
var ErrResponse=errors.New("source response invalid, ambiguous or oversized")
var ErrUnavailable=errors.New("public GitHub Contents API unavailable (no trust verdict)")
type Result struct {
 Schema string `json:"schema"`
 Repository string `json:"repository"`
 Commit string `json:"commit"`
 Path string `json:"path"`
 BlobSHA1 string `json:"git_blob_sha1"`
 BodySHA256 string `json:"source_sha256"`
 FetchMethod string `json:"fetch_method,omitempty"`
 ByteCount int `json:"source_bytes"`
 PublicSyntheticOnly bool `json:"public_synthetic_only"`
 ProductionDLEAuthenticated bool `json:"production_dle_authenticated"`
}
type Pin struct {
 Repo string
 Path string
 Commit string
 Blob string
}
func PublicPin()Pin{return Pin{Repo:Repo,Path:Path,Commit:Commit,Blob:GitBlob}}
func validatePin(p Pin)error {
 if p.Repo!=Repo||p.Path!=Path||p.Commit!=Commit||p.Blob!=GitBlob{
  return ErrPin
 }
 for _,h:=range []string{p.Commit,p.Blob}{
  if len(h)!=40{return ErrPin}
  if _,err:=hex.DecodeString(h);err!=nil{return ErrPin}
 }
 return nil
}
func GitSHA1(b []byte)string {
 hash:=sha1.New()
 hash.Write([]byte("blob "+strconv.Itoa(len(b))))
 hash.Write([]byte{0})
 hash.Write(b)
 return hex.EncodeToString(hash.Sum(nil))
}
func sourceMetadata(b []byte)error {
 if len(b)==0||len(b)>MaxSource{return ErrResponse}
 var v struct {
  Schema string `json:"schema"`
  AuthorityContract struct {
   NoPrivateContent bool `json:"no_private_content"`
  } `json:"authority_contract"`
 }
 if err:=json.Unmarshal(b,&v);err!=nil{return ErrResponse}
 if v.Schema!="synthetic-dle-cpe-memory-v1"||!v.AuthorityContract.NoPrivateContent{
  return ErrResponse
 }
 return nil
}
// VerifyLocal receives bytes from an external source and verifies exact pinned
// Git blob, schema and public-only constraints. SHA256 is recorded for downstream
// use, but caller authentication/authorization is a separate missing control.
func VerifyLocal(p Pin,b []byte)(Result,error){
 if err:=validatePin(p);err!=nil{return Result{},err}
 if GitSHA1(b)!=p.Blob{return Result{},ErrPin}
 if err:=sourceMetadata(b);err!=nil{return Result{},err}
 h:=sha256.Sum256(b)
 return Result{Schema:"hmrc-public-pinned-catalog-r6",
  Repository:p.Repo,Commit:p.Commit,Path:p.Path,BlobSHA1:p.Blob,
  BodySHA256:"sha256:"+hex.EncodeToString(h[:]),ByteCount:len(b),
  PublicSyntheticOnly:true,ProductionDLEAuthenticated:false},nil
}
// LoadPublic always queries the fixed approved public GitHub API source. HTTP
// clients may be test doubles, but callers cannot choose a host, repo or path.
func LoadPublic(ctx context.Context, client *http.Client,p Pin)(Result,error){
 if err:=validatePin(p);err!=nil{return Result{},err}
 u:=url.URL{Scheme:"https",Host:"api.github.com",
  Path:"/repos/"+Repo+"/contents/"+Path,
  RawQuery:"ref="+Commit}
 if client==nil{client=&http.Client{Timeout:15*time.Second}}
 bounded:=*client
 bounded.CheckRedirect=func(*http.Request,[]*http.Request)error{
  return http.ErrUseLastResponse
 }
 req,err:=http.NewRequestWithContext(ctx,http.MethodGet,u.String(),nil)
 if err!=nil{return Result{},err}
 req.Header.Set("Accept","application/vnd.github+json")
 req.Header.Set("User-Agent","semper-supra-hmrc-public-catalog-r6")
 resp,err:=bounded.Do(req)
 if err!=nil{return Result{},err}
 defer resp.Body.Close()
 if resp.StatusCode==http.StatusForbidden||resp.StatusCode==http.StatusTooManyRequests||resp.StatusCode>=500{
  return Result{},ErrUnavailable
 }
 if resp.StatusCode!=http.StatusOK{return Result{},ErrResponse}
 raw,err:=io.ReadAll(io.LimitReader(resp.Body,MaxResponse+1))
 if err!=nil||len(raw)>MaxResponse{return Result{},ErrResponse}
 var data struct {
  Type string `json:"type"`
  Path string `json:"path"`
  SHA string `json:"sha"`
  Encoding string `json:"encoding"`
  Content string `json:"content"`
 }
 if err:=json.Unmarshal(raw,&data);err!=nil{return Result{},ErrResponse}
 if data.Type!="file"||data.Path!=p.Path||data.SHA!=p.Blob||
    data.Encoding!="base64"{return Result{},ErrResponse}
 decoded,err:=base64.StdEncoding.DecodeString(data.Content)
 if err!=nil||len(decoded)>MaxSource{return Result{},ErrResponse}
 result,err:=VerifyLocal(p,decoded)
 if err!=nil{return Result{},err}
 result.FetchMethod="github-contents-api"
 return result,nil
}


// LoadPinnedRaw is an explicit *second* fixed trusted public Git blob source,
// used only if GitHub Contents API is unavailable (403/429/5xx). It does not
// accept model-provided URLs, credentials, redirects or unpinned content.
func LoadPinnedRaw(ctx context.Context,client *http.Client,p Pin)(Result,error){
 if err:=validatePin(p);err!=nil{return Result{},err}
 u:=url.URL{Scheme:"https",Host:"raw.githubusercontent.com",
  Path:"/"+Repo+"/"+Commit+"/"+Path}
 if client==nil{client=&http.Client{Timeout:15*time.Second}}
 bounded:=*client
 bounded.CheckRedirect=func(*http.Request,[]*http.Request)error{
  return http.ErrUseLastResponse
 }
 req,err:=http.NewRequestWithContext(ctx,http.MethodGet,u.String(),nil)
 if err!=nil{return Result{},err}
 req.Header.Set("User-Agent","semper-supra-hmrc-public-catalog-r6")
 resp,err:=bounded.Do(req)
 if err!=nil{return Result{},err}
 defer resp.Body.Close()
 if resp.StatusCode!=http.StatusOK{return Result{},ErrResponse}
 raw,err:=io.ReadAll(io.LimitReader(resp.Body,MaxSource+1))
 if err!=nil||len(raw)>MaxSource{return Result{},ErrResponse}
 result,err:=VerifyLocal(p,raw)
 if err!=nil{return Result{},err}
 result.FetchMethod="pinned-github-raw"
 return result,nil
}
// FetchPinned chooses Contents API first and falls back only on API
// availability; a 200/mismatched blob or redirect MUST fail without fallback.
func FetchPinned(ctx context.Context,client *http.Client,p Pin)(Result,error){
 result,err:=LoadPublic(ctx,client,p)
 if err==nil{return result,nil}
 if !errors.Is(err,ErrUnavailable){return Result{},err}
 return LoadPinnedRaw(ctx,client,p)
}
