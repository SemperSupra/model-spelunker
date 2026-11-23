package catalog

import(
 "bytes"
 "context"
 "encoding/base64"
 "encoding/json"
 "errors"
 "io"
 "net/http"
 "os"
 "strings"
 "testing"
)
type roundTrip func(*http.Request)(*http.Response,error)
func(f roundTrip)RoundTrip(r *http.Request)(*http.Response,error){return f(r)}
func fixture(t *testing.T)[]byte{
 t.Helper()
 b,err:=os.ReadFile("../fixtures/memory_dle_cpe_synthetic_v1.json")
 if err!=nil{t.Fatal(err)}
 return b
}
func makeClient(body []byte,override func(map[string]any))(*http.Client,*int){
 reqCount:=new(int)
 return &http.Client{Transport:roundTrip(func(req *http.Request)(*http.Response,error){
  *reqCount += 1
  if req.Method!="GET"||req.URL.Scheme!="https"||req.URL.Host!="api.github.com"||
    req.URL.Query().Get("ref")!=Commit||req.URL.Path!="/repos/"+Repo+"/contents/"+Path{
    return nil,errors.New("unexpected or mutable destination")
  }
  data:=map[string]any{"type":"file","path":Path,"sha":GitBlob,"encoding":"base64",
    "content":base64.StdEncoding.EncodeToString(body)}
  if override!=nil{override(data)}
  raw,_:=json.Marshal(data)
  return &http.Response{StatusCode:200,Body:io.NopCloser(bytes.NewReader(raw)),
    Header:make(http.Header),Request:req},nil
 })},reqCount
}
func TestValidSourceAndFixedOrigin(t *testing.T){
 b:=fixture(t)
 if len(b)==0||len(b)>MaxSource{t.Fatalf("public source size outside admitted bounds %d",len(b))}
 result,err:=VerifyLocal(PublicPin(),b)
 if err!=nil||!result.PublicSyntheticOnly||result.ProductionDLEAuthenticated||
   len(result.BodySHA256)!=71||result.BlobSHA1!=GitBlob{
  t.Fatalf("local verified fixture failed %+v %v",result,err)
 }
 client,count:=makeClient(b,nil)
 received,err:=LoadPublic(context.Background(),client,PublicPin())
 if err!=nil||*count!=1||received!=result{t.Fatalf("exact API source binding failed %+v %v",received,err)}
}
func TestRejectWrongPinAndMutation(t *testing.T){
 b:=fixture(t)
 variants:=[]Pin{
   {Repo:"other/project",Path:Path,Commit:Commit,Blob:GitBlob},
   {Repo:Repo,Path:"../../private",Commit:Commit,Blob:GitBlob},
   {Repo:Repo,Path:Path,Commit:strings.Repeat("0",40),Blob:GitBlob},
   {Repo:Repo,Path:Path,Commit:Commit,Blob:strings.Repeat("0",40)},
 }
 for _,p:=range variants{
  if _,err:=VerifyLocal(p,b);!errors.Is(err,ErrPin){t.Fatalf("wrong pin accepted %+v %v",p,err)}
 }
 replaced:=bytes.Replace(b,[]byte("release"),[]byte("deploy"),1)
 if bytes.Equal(replaced,b){t.Fatal("mutation test did not alter source")}
 if _,err:=VerifyLocal(PublicPin(),replaced);!errors.Is(err,ErrPin){t.Fatal("tampered bytes accepted")}
}
func TestRejectSpoofedMetadataAndSource(t *testing.T){
 b:=fixture(t)
 attacks:=[]func(map[string]any){
  func(m map[string]any){m["path"]="public/../private"},
  func(m map[string]any){m["sha"]=strings.Repeat("f",40)},
  func(m map[string]any){m["content"]=base64.StdEncoding.EncodeToString([]byte("hijacked"))},
  func(m map[string]any){m["encoding"]="utf-8"},
  func(m map[string]any){m["type"]="dir"},
 }
 for i,attack:=range attacks{
  client,_:=makeClient(b,attack)
  if _,err:=LoadPublic(context.Background(),client,PublicPin());err==nil{
   t.Fatalf("attack %d accepted",i)
  }
 }
}
func TestNoRedirectOrExternalSourceLeak(t *testing.T){
 client:=&http.Client{Transport:roundTrip(func(req *http.Request)(*http.Response,error){
  return &http.Response{StatusCode:302,Header:http.Header{
   "Location":[]string{"https://169.254.169.254/latest"}},
   Body:io.NopCloser(strings.NewReader("")),Request:req},nil
 })}
 if _,err:=LoadPublic(context.Background(),client,PublicPin());!errors.Is(err,ErrResponse){
  t.Fatalf("redirect response was admitted %v",err)
 }
}
func TestRejectOversizedBody(t *testing.T){
 client:=&http.Client{Transport:roundTrip(func(req *http.Request)(*http.Response,error){
  return &http.Response{StatusCode:200,Body:io.NopCloser(strings.NewReader(strings.Repeat("x",MaxResponse+1))),
  Header:make(http.Header),Request:req},nil
 })}
 if _,err:=LoadPublic(context.Background(),client,PublicPin());!errors.Is(err,ErrResponse){t.Fatal("oversized source accepted")}
}
