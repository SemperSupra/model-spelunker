package main

import (
    "context"
    "errors"
    "flag"
    "fmt"
    "net"
    "net/http"
    "os"
    "path/filepath"
    "strings"
    "time"

    "github.com/modelcontextprotocol/go-sdk/mcp"
)

func main(){
    transport:=flag.String("transport","stdio","stdio or http")
    mode:=flag.String("mode","fixture","fixture or observer")
    repo:=flag.String("repo","o/r","single pinned repository")
    issue:=flag.Int("issue",7,"single pinned issue")
    fixture:=flag.String("fixture","testdata/observed.json","original public-safe fixture JSON")
    bin:=flag.String("observer-bin","","qualified observer executable; no arbitrary shell")
    checkout:=flag.String("checkout","","pinned local checkout for existing observer")
    addr:=flag.String("addr","127.0.0.1:8787","loopback-only listening address")
    reconcileBin:=flag.String("reconcile-bin","","existing qualified Go reconciler binary, optional")
    reconcileBinSHA:=flag.String("reconcile-bin-sha256","","exact qualified reconciler executable sha256")
    candidateFile:=flag.String("candidates","","preselected private candidate file")
    dleFile:=flag.String("dle","","independently sourced pinned local DLE snapshot")
    dleSHA:=flag.String("dle-sha256","","exact DLE source file sha256; not GitHub attestation")
    bootstrapPath:=flag.String("bootstrap-json","","exact preselected public-safe DLE advisory projection JSON")
    bootstrapDigest:=flag.String("bootstrap-json-sha256","","sha256 of the preselected advisory projection")
    bootstrapAuthority:=flag.String("bootstrap-authority","","expected fixed project DLE URL")
    bootstrapRevision:=flag.String("bootstrap-revision","","expected exact source revision")
    bootstrapSourceSHA:=flag.String("bootstrap-dle-sha256","","expected independently selected DLE snapshot sha256")
    flag.Parse()
    if !repoPattern.MatchString(*repo)||strings.Contains(*repo,"..")||*issue<1 {fail(errors.New("invalid repository or issue"))}
    var p Provider
    switch *mode {
    case "fixture":
        value,err:=loadFixture(*fixture);if err!=nil{fail(err)}
        if err=validate(value,*repo,*issue);err!=nil{fail(err)}
        p=fixtureProvider{value}
    case "observer":
        if *bin==""||*checkout==""{fail(errors.New("explicit observer executable and checkout required"))}
        p=observerProvider{bin:*bin,repo:*repo,issue:*issue,checkout:*checkout}
    default:fail(errors.New("unsupported provider mode"))
    }
    var engine ReconcileEngine
    configured:=[]string{*reconcileBin,*reconcileBinSHA,*candidateFile,*dleFile,*dleSHA}
    n:=0
    for _,value:=range configured {if value!="" {n++}}
    if n!=0 && n!=len(configured){fail(errors.New("partial DLE reconciler configuration is forbidden"))}
    if n==len(configured){
        if !validHex(*reconcileBinSHA)||!validHex(*dleSHA) {
            fail(errors.New("invalid pinned reconcile executable or authority digest"))
        }
        for _,file:=range []string{*reconcileBin,*candidateFile,*dleFile}{
            if !filepath.IsAbs(file){fail(errors.New("absolute pinned DLE paths required"))}
        }
        engine=externalReconciler{binary:*reconcileBin,binarySHA256:*reconcileBinSHA,
            authorityFile:*dleFile,candidateFile:*candidateFile,authoritySHA256:*dleSHA}
    }
    var bootstrap *bootstrapReader
    bootstrapSettings:=[]string{*bootstrapPath,*bootstrapDigest,*bootstrapAuthority,*bootstrapRevision,*bootstrapSourceSHA}
    bootstrapCount:=0
    for _,value:=range bootstrapSettings {if value!=""{bootstrapCount++}}
    if bootstrapCount!=0 && bootstrapCount!=len(bootstrapSettings){fail(errors.New("partial bootstrap projection admission forbidden"))}
    if bootstrapCount==len(bootstrapSettings){
        if *bootstrapAuthority!=fmt.Sprintf("https://github.com/%s/issues/%d",*repo,*issue){fail(errors.New("bootstrap belongs to another MCP workset"))}
        var err error
        bootstrap,err=newBootstrapReader(*bootstrapPath,*bootstrapDigest,*bootstrapAuthority,*bootstrapRevision,*bootstrapSourceSHA)
        if err!=nil{fail(err)}
    }
    switch *transport {
    case "stdio":
        if err:=newServerWithBootstrap(p,*repo,*issue,engine,bootstrap).Run(context.Background(),&mcp.StdioTransport{});err!=nil{fail(err)}
    case "http":
        host,_,err:=net.SplitHostPort(*addr);if err!=nil{fail(err)}
        ip:=net.ParseIP(host)
        if ip==nil||!ip.IsLoopback(){fail(errors.New("HTTP pilot only permits an explicit loopback IP"))}
        token:=os.Getenv("DLE_MCP_BEARER_TOKEN")
        if len(token)<24{fail(errors.New("ephemeral bearer token with at least 24 characters required"))}
        srv:=&http.Server{Addr:*addr,Handler:newHTTPHandlerWithBootstrap(p,*repo,*issue,token,engine,bootstrap),
            ReadHeaderTimeout:5*time.Second,ReadTimeout:15*time.Second,WriteTimeout:30*time.Second}
        if err:=srv.ListenAndServe();err!=nil{fail(err)}
    default:fail(errors.New("unsupported transport"))
    }
}
func fail(err error){fmt.Fprintln(os.Stderr,"DLE MCP RDT&E:",err);os.Exit(1)}
