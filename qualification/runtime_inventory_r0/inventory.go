// Package inventory is an offline-only, synthetic Ollama listing reconciler.
// It never queries an endpoint, validates actual model bytes, or grants authority.
package inventory

import (
 "bytes"
 "encoding/json"
 "errors"
 "fmt"
 "io"
 "sort"
 "strings"
 "time"
 "unicode"
)

const MaxInputBytes = 2 << 20
const MaxModels = 1024

type Input struct {
 Tags []byte
 Running []byte
 TagsAt time.Time
 RunningAt time.Time
 Now time.Time
 MaxAge time.Duration
}
type Entry struct {
 Alias string `json:"alias"`
 Presence string `json:"presence"`
 Activity string `json:"activity"`
 RegisteredIdentity string `json:"registered_identity"`
 Approval string `json:"approval"`
 SourceDigestKind string `json:"source_digest_kind"`
 TagManifestDigest string `json:"tag_manifest_digest,omitempty"`
 RunningManifestDigest string `json:"running_manifest_digest,omitempty"`
}
type Report struct {
 Kind string `json:"kind"`
 ObservedTagsAt string `json:"observed_tags_at"`
 ObservedRunningAt string `json:"observed_running_at"`
 Entries []Entry `json:"entries"`
}

// checkValue checks every JSON object for duplicate names, including nested
// values. Strict duplicate denial prevents ambiguous parser precedence.
func checkValue(d *json.Decoder, depth int) error {
 if depth>32 {return errors.New("maximum JSON nesting exceeded")}
 tok,err:=d.Token();if err!=nil{return err}
 dl,ok:=tok.(json.Delim);if !ok{return nil}
 switch dl {
 case '{':
  seen:=map[string]bool{}
  for d.More() {
   keyTok,err:=d.Token();if err!=nil{return err}
   key,ok:=keyTok.(string);if !ok{return errors.New("invalid JSON object key")}
   if seen[key] {return fmt.Errorf("duplicate JSON key: %q",key)}
   seen[key]=true
   if err:=checkValue(d,depth+1);err!=nil{return err}
  }
  end,err:=d.Token();if err!=nil{return err}
  if end!=json.Delim('}') {return errors.New("invalid object close")}
 case '[':
  for d.More(){if err:=checkValue(d,depth+1);err!=nil{return err}}
  end,err:=d.Token();if err!=nil{return err}
  if end!=json.Delim(']'){return errors.New("invalid array close")}
 default: return errors.New("unexpected JSON delimiter")
 }
 return nil
}
// rejectFieldVariants prevents case-folded aliases of recognized wire fields.
// Unknown extension fields remain permitted; authoritative fields are exact.
func rejectFieldVariants(fields map[string]json.RawMessage, names ...string) error {
 for key:=range fields {
  for _,name:=range names {
   if key!=name && strings.EqualFold(key,name) {return errors.New("noncanonical recognized JSON field")}
  }
 }
 return nil
}

func parseList(raw []byte)([]record,error){
 if len(raw)==0||len(raw)>MaxInputBytes{return nil,errors.New("missing or oversized JSON observation")}
 scanner:=json.NewDecoder(bytes.NewReader(raw))
 if err:=checkValue(scanner,0);err!=nil{return nil,fmt.Errorf("untrusted JSON: %w",err)}
 if _,err:=scanner.Token();err!=io.EOF{return nil,errors.New("trailing JSON data")}
 var root map[string]json.RawMessage
 if err:=json.Unmarshal(raw,&root);err!=nil{return nil,err}
 if err:=rejectFieldVariants(root,"models");err!=nil{return nil,err}
 // Empty models are valid; missing/null models are not observations.
 models,present:=root["models"]
 if !present||bytes.Equal(bytes.TrimSpace(models),[]byte("null")){return nil,errors.New("models array missing")}
 var entries []json.RawMessage
 if err:=json.Unmarshal(models,&entries);err!=nil{return nil,err}
 if entries==nil{return nil,errors.New("models must be an array")}
 if len(entries)>MaxModels{return nil,errors.New("too many model entries")}
 out:=make([]record,0,len(entries))
 for _,entry:=range entries {
  var fields map[string]json.RawMessage
  if err:=json.Unmarshal(entry,&fields);err!=nil{return nil,err}
  if fields==nil{return nil,errors.New("model entry must be an object")}
  if err:=rejectFieldVariants(fields,"name","model","digest");err!=nil{return nil,err}
  var m record
  for _,field:=range []struct{name string; target *string}{{"name",&m.Name},{"model",&m.Model},{"digest",&m.Digest}} {
   if v,ok:=fields[field.name];ok {
    if err:=json.Unmarshal(v,field.target);err!=nil{return nil,err}
   }
  }
  if _,err:=canonicalAlias(m);err!=nil{return nil,err}
  if err:=validateReportedDigest(m.Digest);err!=nil{return nil,err}
  out=append(out,m)
 }
 return out,nil
}
type record struct {
 Name string `json:"name"`
 Model string `json:"model"`
 Digest string `json:"digest"`
}
func canonicalAlias(m record)(string,error){
 name:=m.Model
 if name==""{name=m.Name}
 if name==""||len(name)>256||strings.TrimSpace(name)!=name {return "",errors.New("empty/oversized/unsafe model alias")}
 for _,r:=range name {if unicode.IsControl(r){return "",errors.New("control character in alias")}}
 if m.Model!=""&&m.Name!=""&&m.Model!=m.Name{return "",errors.New("name and model aliases disagree")}
 return name,nil
}
func validateReportedDigest(s string)error {
 if s==""{return nil}
 if len(s)>100{return errors.New("oversized provider digest")}
 for _,r:=range s{if unicode.IsControl(r)||unicode.IsSpace(r){return errors.New("unsafe provider digest")}}
 return nil // provider metadata only, never a provenance proof
}
func fresh(now,at time.Time,maxAge time.Duration)bool {
 return !now.IsZero()&&!at.IsZero()&&maxAge>0&&!at.After(now)&&now.Sub(at)<=maxAge
}
// Reconcile treats /api/tags as advertised presence and /api/ps as loaded
// state. Neither listing can prove actively serving requests, GPU residency,
// exact weight bytes, provenance/MAF registration, or Foundry approval.
func Reconcile(in Input)(Report,error){
 out:=Report{Kind:"synthetic_ollama_listing",Entries:[]Entry{}}
 if !fresh(in.Now,in.TagsAt,in.MaxAge)||!fresh(in.Now,in.RunningAt,in.MaxAge){
  return out,errors.New("missing, future, or stale observation timestamp")
 }
 tags,err:=parseList(in.Tags);if err!=nil{return out,fmt.Errorf("tags: %w",err)}
 running,err:=parseList(in.Running);if err!=nil{return out,fmt.Errorf("running: %w",err)}
 if len(tags)+len(running)>2*MaxModels{return out,errors.New("too many entries")}
 registry:=map[string]record{}
 active:=map[string]record{}
 for _,m:=range tags {
  id,_:=canonicalAlias(m)
  if _,ok:=registry[id];ok{return out,fmt.Errorf("duplicate tag alias: %q",id)}
  registry[id]=m
 }
 for _,m:=range running {
  id,_:=canonicalAlias(m)
  if _,ok:=active[id];ok{return out,fmt.Errorf("duplicate running alias: %q",id)}
  active[id]=m
 }
 keys:=make([]string,0,len(registry)+len(active))
 seen:=map[string]bool{}
 for id:=range registry {seen[id]=true;keys=append(keys,id)}
 for id:=range active {if !seen[id]{keys=append(keys,id)}}
 sort.Strings(keys)
 for _,id:=range keys{
  tag,t:=registry[id];run,r:=active[id]
  e:=Entry{Alias:id,Presence:"UNKNOWN",Activity:"UNKNOWN",RegisteredIdentity:"UNVERIFIED",Approval:"UNKNOWN",SourceDigestKind:"ollama_provider_report_not_oci_or_content_manifest"}
  if t {e.TagManifestDigest=tag.Digest}
  if r {e.RunningManifestDigest=run.Digest}
  switch {
  case t&&r&&tag.Digest!=""&&run.Digest!=""&&tag.Digest!=run.Digest:
   e.Presence="ALIAS_DIGEST_DRIFT"
  case t&&r:e.Presence="LOADED_ACTIVITY_UNKNOWN"
  case t:e.Presence="PRESENT_NOT_LOADED"
  case r:e.Presence="RUNNING_BUT_UNLISTED"
  }
  out.Entries=append(out.Entries,e)
 }
 out.ObservedTagsAt=in.TagsAt.UTC().Format(time.RFC3339Nano)
 out.ObservedRunningAt=in.RunningAt.UTC().Format(time.RFC3339Nano)
 return out,nil
}
