package main

import (
    "context"
    "errors"
    "flag"
    "fmt"
    "net"
    "net/http"
    "os"
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
    switch *transport {
    case "stdio":
        if err:=newServer(p,*repo,*issue).Run(context.Background(),&mcp.StdioTransport{});err!=nil{fail(err)}
    case "http":
        host,_,err:=net.SplitHostPort(*addr);if err!=nil{fail(err)}
        ip:=net.ParseIP(host)
        if ip==nil||!ip.IsLoopback(){fail(errors.New("HTTP pilot only permits an explicit loopback IP"))}
        token:=os.Getenv("DLE_MCP_BEARER_TOKEN")
        if len(token)<24{fail(errors.New("ephemeral bearer token with at least 24 characters required"))}
        srv:=&http.Server{Addr:*addr,Handler:newHTTPHandler(p,*repo,*issue,token),
            ReadHeaderTimeout:5*time.Second,ReadTimeout:15*time.Second,WriteTimeout:30*time.Second}
        if err:=srv.ListenAndServe();err!=nil{fail(err)}
    default:fail(errors.New("unsupported transport"))
    }
}
func fail(err error){fmt.Fprintln(os.Stderr,"DLE MCP RDT&E:",err);os.Exit(1)}
