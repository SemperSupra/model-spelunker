package main

// Optional, read-only projection of an already prepared PUBLIC-SYNTHETIC
// dle-bootstrap-advisory-v1. The authoritative reconciler/source receiver and
// source-to-bootstrap conversion live elsewhere. This adapter never mints
// authority, queries GitHub, publishes memory or declassifies information.
import (
 "bytes"
 "crypto/sha256"
 "encoding/hex"
 "encoding/json"
 "errors"
 "fmt"
 "io"
 "os"
 "path/filepath"
 "strings"
)

const maxBootstrapBytes = 6 << 10

type bootstrapClaim struct {
 ID string `json:"id"`
 Text string `json:"text"`
 Source string `json:"source"`
}
type BootstrapView struct {
 Schema string `json:"schema"`
 Authority string `json:"authority"`
 Revision string `json:"revision"`
 AuthoritySHA256 string `json:"authority_sha256"`
 ProjectionFileSHA256 string `json:"projection_file_sha256"`
 GitHubVerified bool `json:"github_verified"`
 AdvisoryOnly bool `json:"advisory_only"`
 Mission string `json:"mission"`
 NextAction string `json:"next_action"`
 Constraints []string `json:"constraints"`
 Unknowns []string `json:"unknowns"`
 Accepted []bootstrapClaim `json:"accepted"`
}
type bootstrapReader struct {
 file string
 digest string
 authority string
 revision string
 authoritySHA string
}

// Reject duplicate keys at any depth. A valid hash of ambiguously decoded JSON
// is not evidence that caller and verifier interpreted identical fields.
func uniqueJSON(raw []byte) error {
 dec:=json.NewDecoder(bytes.NewReader(raw))
 var scan func()error
 scan=func()error {
  tok,e:=dec.Token();if e!=nil{return e}
  open,ok:=tok.(json.Delim)
  if !ok{return nil}
  switch open {
  case '{':
   seen:=map[string]bool{}
   for dec.More(){
    keyTok,e:=dec.Token();if e!=nil{return e}
    key,ok:=keyTok.(string);if !ok{return errors.New("invalid key")}
    if seen[key]{return errors.New("duplicate bootstrap key")}
    seen[key]=true
    if e=scan();e!=nil{return e}
   }
   end,e:=dec.Token();if e!=nil{return e};if end!=json.Delim('}') {return errors.New("unclosed object")}
  case '[':
   for dec.More(){if e:=scan();e!=nil{return e}}
   end,e:=dec.Token();if e!=nil{return e};if end!=json.Delim(']'){return errors.New("unclosed array")}
  default:return errors.New("unexpected JSON delimiter")
  }
  return nil
 }
 if e:=scan();e!=nil{return e}
 if _,e:=dec.Token();e!=io.EOF {
  if e==nil{return errors.New("trailing JSON document")}
  return e
 }
 return nil
}

func (b bootstrapReader) Read() (BootstrapView,error) {
 var out BootstrapView
 if !validHex(b.digest)||!validHex(b.authoritySHA)||b.authority==""||b.revision=="" {
  return out,errors.New("bootstrap binding incomplete")
 }
 if !filepath.IsAbs(b.file){return out,errors.New("absolute bootstrap file required")}
 info,e:=os.Lstat(b.file)
 if e!=nil{return out,e}
 if !info.Mode().IsRegular()||info.Size()<1||info.Size()>maxBootstrapBytes {
  return out,errors.New("bootstrap file is unsafe or oversized")
 }
 f,e:=os.Open(b.file);if e!=nil{return out,e};defer f.Close()
 raw,e:=io.ReadAll(io.LimitReader(f,maxBootstrapBytes+1))
 if e!=nil||len(raw)>maxBootstrapBytes{return out,errors.New("bootstrap read exceeds limit")}
 sum:=sha256.Sum256(raw)
 if hex.EncodeToString(sum[:])!=b.digest{return out,errors.New("bootstrap artifact changed")}
 if e=uniqueJSON(raw);e!=nil{return out,errors.New("ambiguous bootstrap JSON")}
 decoder:=json.NewDecoder(bytes.NewReader(raw));decoder.DisallowUnknownFields()
 if e=decoder.Decode(&out);e!=nil{return out,errors.New("invalid bootstrap schema")}
 if out.Schema!="dle-bootstrap-advisory-v1"||out.Authority!=b.authority||
    out.Revision!=b.revision||out.AuthoritySHA256!=b.authoritySHA||
    out.GitHubVerified||!out.AdvisoryOnly||
    len(out.ProjectionFileSHA256)!=64||out.Mission==""||out.NextAction=="" {
  return BootstrapView{},errors.New("bootstrap source/authority assertion invalid")
 }
 for _,h:=range []string{out.ProjectionFileSHA256}{
  if _,e=hex.DecodeString(h);e!=nil{return BootstrapView{},errors.New("bad projection provenance")}
 }
 if len(out.Accepted)>16||len(out.Constraints)>24||len(out.Unknowns)>24 {
  return BootstrapView{},errors.New("bootstrap claims exceed bound")
 }
 seen:=map[string]bool{}
 for _,claim:=range out.Accepted{
  if claim.ID==""||claim.Text==""||claim.Source==""||seen[claim.ID]{
   return BootstrapView{},errors.New("invalid bootstrap accepted claim")
  }
  seen[claim.ID]=true
 }
 // This is intentionally an existing advisory projection. A separately
 // approved public A-D release decision must precede selecting this file.
 return out,nil
}

func newBootstrapReader(file,hash,authority,revision,sourceSHA string)(*bootstrapReader,error){
 b:=bootstrapReader{file:file,digest:strings.ToLower(hash),
  authority:authority,revision:revision,authoritySHA:strings.ToLower(sourceSHA)}
 if _,e:=b.Read();e!=nil{return nil,fmt.Errorf("bootstrap admission: %w",e)}
 return &b,nil
}
