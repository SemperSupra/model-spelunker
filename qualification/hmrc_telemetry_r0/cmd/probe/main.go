// Command probe performs one read-only native Ollama telemetry check. Public
// qualification must use the exact admitted loopback model fixture.
package main

import (
    "context"
    "encoding/json"
    "fmt"
    "os"
    "time"

    telemetry "example.com/sempersupra/hmrc-telemetry-r0"
)

func main() {
    ctx,cancel:=context.WithTimeout(context.Background(),10*time.Second)
    defer cancel()
    result,err:=telemetry.Probe(ctx,nil,telemetry.Config{
        Engine:"ollama",BaseURL:"http://127.0.0.1:11434",
    })
    if err!=nil {fmt.Fprintln(os.Stderr,err);os.Exit(2)}
    if len(result.Models)==0 {fmt.Fprintln(os.Stderr,"UNKNOWN: no loaded native model");os.Exit(3)}
    matched:=false
    for _,m:=range result.Models {
        if m.Name=="qwen3:1.7b" && m.ReportedContextTokens!=nil && *m.ReportedContextTokens>0 {
            matched=true
        }
    }
    if !matched {fmt.Fprintln(os.Stderr,"UNKNOWN: admitted pinned model/context not observed");os.Exit(4)}
    if err:=json.NewEncoder(os.Stdout).Encode(result);err!=nil {
        fmt.Fprintln(os.Stderr,err);os.Exit(5)
    }
}
