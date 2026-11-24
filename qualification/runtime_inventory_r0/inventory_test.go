package inventory

import (
 "encoding/json"
 "strings"
 "testing"
 "time"
)
const sampleDigest="abcdef0123456789"
func inp(tags,running string) Input{
 now:=time.Date(2026,11,23,7,0,0,0,time.UTC)
 return Input{Tags:[]byte(tags),Running:[]byte(running),Now:now,TagsAt:now,RunningAt:now,MaxAge:time.Minute}
}
func TestIndependentPresenceAndUnknownProvenance(t *testing.T){
 in:=inp(`{"models":[{"name":"alpha:latest","digest":"d1"},{"name":"beta:latest","digest":"d2"}]}`,`{"models":[{"model":"beta:latest","digest":"d2"},{"name":"unlisted:7b","digest":"d3"}]}`)
 out,err:=Reconcile(in);if err!=nil{t.Fatal(err)}
 want:=[]struct{alias,presence string}{
 {"alpha:latest","PRESENT_NOT_LOADED"},
 {"beta:latest","LOADED_ACTIVITY_UNKNOWN"},
 {"unlisted:7b","RUNNING_BUT_UNLISTED"},
 }
 if len(out.Entries)!=len(want){t.Fatal(out)}
 for i,w:=range want {
  e:=out.Entries[i]
  if e.Alias!=w.alias||e.Presence!=w.presence||e.Activity!="UNKNOWN"||e.RegisteredIdentity!="UNVERIFIED"||e.Approval!="UNKNOWN"{t.Fatalf("unsafe attribution: %+v",e)}
  if e.SourceDigestKind!="ollama_provider_report_not_oci_or_content_manifest"{t.Fatal("provider digest confused with OCI",e)}
 }
 b,err:=json.Marshal(out);if err!=nil||strings.Contains(string(b),"PRIVATE"){t.Fatal(err)}
}
func TestAliasDigestDriftIsNotProvenance(t *testing.T){
 in:=inp(`{"models":[{"model":"same:tag","digest":"source-manifest-A"}]}`,`{"models":[{"name":"same:tag","digest":"source-manifest-B"}]}`)
 out,err:=Reconcile(in);if err!=nil||len(out.Entries)!=1||out.Entries[0].Presence!="ALIAS_DIGEST_DRIFT"{t.Fatalf("alias drift not caught: %+v %v",out,err)}
}
func TestEmptySourceIsValidNoModels(t *testing.T){out,err:=Reconcile(inp(`{"models":[]}`,`{"models":[]}`));if err!=nil||out.Entries==nil||len(out.Entries)!=0{t.Fatalf("%+v %v",out,err)}}
func TestBadAndStaleInputsRefused(t *testing.T){
 base:=inp(`{"models":[{"name":"good:1"}]}`,`{"models":[]}`)
 tests:=[]struct{name string;change func(*Input)}{
  {"duplicate_nested_name",func(x *Input){x.Tags=[]byte(`{"models":[{"name":"good:1","name":"evil:2"}]}`)}},
  {"duplicate_top_level",func(x *Input){x.Tags=[]byte(`{"models":[],"models":[]}`)}},
  {"name_model_disagree",func(x *Input){x.Tags=[]byte(`{"models":[{"name":"good","model":"evil"}]}`)}},
  {"newline_alias",func(x *Input){x.Tags=[]byte("{\"models\":[{\"name\":\"good\\nevil\"}]}")}},
  {"duplicate_alias",func(x *Input){x.Tags=[]byte(`{"models":[{"name":"good:1"},{"name":"good:1"}]}`)}},
  {"missing_models",func(x *Input){x.Tags=[]byte(`{}`)}},
  {"null_models",func(x *Input){x.Tags=[]byte(`{"models":null}`)}},
  {"wrong_shape",func(x *Input){x.Tags=[]byte(`{"models":{}}`)}},
  {"trailing_data",func(x *Input){x.Tags=[]byte(`{"models":[]}true`)}},
  {"oversized",func(x *Input){x.Tags=[]byte(strings.Repeat(" ",MaxInputBytes+1))}},
  {"nested_over_depth",func(x *Input){x.Tags=[]byte(strings.Repeat("[",34)+`0`+strings.Repeat("]",34))}},
  {"tags_too_old",func(x *Input){x.TagsAt=x.TagsAt.Add(-time.Hour)}},
  {"running_future",func(x *Input){x.RunningAt=x.RunningAt.Add(time.Second)}},
  {"running_missing",func(x *Input){x.Running=nil}},
  {"unsafe_provider_digest",func(x *Input){x.Tags=[]byte(`{"models":[{"name":"good:1","digest":"bad\nvalue"}]}`)}},
 }
 for _,tc:=range tests {t.Run(tc.name,func(t *testing.T){x:=base;tc.change(&x);_,err:=Reconcile(x);if err==nil{t.Fatal("unsafe input accepted")}})}
}


func TestCanonicalFieldSpelling(t *testing.T) {
 cases := []struct{name, raw string}{
  {"root_collision", `{"models":[],"MODELS":[{"name":"unexpected"}]}`},
  {"name_collision", `{"models":[{"name":"expected","NAME":"unexpected"}]}`},
  {"digest_collision", `{"models":[{"name":"expected","digest":"good","DIGEST":"unexpected"}]}`},
  {"model_collision", `{"models":[{"model":"expected","MODEL":"unexpected"}]}`},
  {"root_variant_only", `{"MODELS":[]}`},
  {"name_variant_only", `{"models":[{"NAME":"unexpected"}]}`},
  {"unicode_fold", `{"models":[{"name":"expected","digeſt":"unexpected"}]}`},
 }
 for _,tc:=range cases {
  t.Run(tc.name,func(t *testing.T){
   if _,err:=Reconcile(inp(tc.raw,`{"models":[]}`));err==nil{t.Fatal("ambiguous recognized field accepted")}
   if _,err:=Reconcile(inp(`{"models":[]}`,tc.raw));err==nil{t.Fatal("ambiguous recognized field accepted in running list")}
  })
 }
}
func TestCanonicalFieldsRetainForwardCompatibility(t *testing.T) {
 out,err:=Reconcile(inp(`{"models":[{"model":"alpha:latest","future_field":{"NAME":"ignored"},"digest":"provider-digest"}],"future_metadata":true}`,`{"models":[]}`))
 if err!=nil||len(out.Entries)!=1||out.Entries[0].Alias!="alpha:latest"||out.Entries[0].TagManifestDigest!="provider-digest"||out.Entries[0].Activity!="UNKNOWN"||out.Entries[0].RegisteredIdentity!="UNVERIFIED"{t.Fatalf("unexpected result: %+v %v",out,err)}
}
