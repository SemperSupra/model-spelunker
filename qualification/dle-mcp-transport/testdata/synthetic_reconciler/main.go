// Synthetic *test double* for the existing private Go DLE reconciler CLI.
// These fixtures deliberately do not prove DLE semantics or GitHub provenance.
package main

import (
 "crypto/sha256"
 "encoding/hex"
 "encoding/json"
 "flag"
 "os"
 "path/filepath"
)
func hash(b []byte)string{h:=sha256.Sum256(b);return hex.EncodeToString(h[:])}
func save(path string,v any){b,e:=json.Marshal(v);if e!=nil{os.Exit(2)};if os.WriteFile(path,b,0600)!=nil{os.Exit(2)}}
func main(){
 c:=flag.String("candidates","","")
 a:=flag.String("dle","","")
 pin:=flag.String("dle-sha256","","")
 out:=flag.String("out","","")
 flag.Parse()
 if *c==""||*a==""||*out==""{os.Exit(2)}
 cb,e:=os.ReadFile(*c);if e!=nil{os.Exit(2)}
 ab,e:=os.ReadFile(*a);if e!=nil{os.Exit(2)}
 if hash(ab)!=*pin{os.Exit(3)}
 var authority struct{Source string `json:"source"`;Revision string `json:"revision"`}
 if json.Unmarshal(ab,&authority)!=nil||authority.Source==""||authority.Revision==""{os.Exit(4)}
 var candidate struct{Mode string `json:"mode"`}
 if json.Unmarshal(cb,&candidate)!=nil{os.Exit(5)}
 if os.MkdirAll(*out,0700)!=nil{os.Exit(6)}
 result:=map[string]any{
  "schema":"dle-reconciliation-v1","authority":authority.Source,
  "revision":authority.Revision,"authority_sha256":hash(ab),
  "candidate_sha256":hash(cb),"counts":map[string]int{"unknown":1},
  "differences":[]map[string]string{{"id":"synthetic-1","disposition":"unknown"}},
  "mutation_performed":false,
 }
 context:=map[string]any{
  "schema":"dle-context-v1","authority":authority.Source,
  "revision":authority.Revision,"sha256":hash(ab),
  "github_verified":false,
  "accepted":[]map[string]string{{"status":"accepted"}},
 }
 if candidate.Mode=="false-promotion"{context["github_verified"]=true}
 if candidate.Mode=="wrong-source"{result["authority_sha256"]=hash(cb)}
 if candidate.Mode=="unknown-kind"{result["counts"]=map[string]int{"approved":1};result["differences"]=[]map[string]string{{"id":"x","disposition":"approved"}}}
 save(filepath.Join(*out,"reconciliation.json"),result)
 save(filepath.Join(*out,"context.json"),context)
}
