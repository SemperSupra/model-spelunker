// Package telemetry reads native model server observability without changing a
// generation, model, slot or physical KV-cache state. Issue #306 independent R0.
package telemetry

import (
    "context"
    "encoding/json"
    "errors"
    "fmt"
    "io"
    "net"
    "net/http"
    "net/url"
    "strings"
    "time"
)

var ErrUntrustedEndpoint=errors.New("endpoint requires exact trusted host admission")
var ErrUnsupported=errors.New("unsupported server protocol")
var ErrMalformed=errors.New("malformed or oversized server telemetry")

const MaxBodyBytes=65536

type Config struct {
    Engine string // ollama, llama.cpp
    BaseURL string
    TrustedRemoteHost string // empty => loopback only; HTTPS mandatory remotely
}

type Model struct {
    Name string
    Digest string
    ReportedContextTokens *int
    ReportedVRAMBytes *int64
}

type Observation struct {
    Schema string
    Engine string
    Endpoint string
    Models []Model
    ReportedDefaultSlotContextTokens *int
    ReportedTotalSlots *int
    KVCachePressure *float64 // unknown until supported by measured source API
    PromptCacheHitRate *float64 // unknown; never silently estimated
    SourcePath string
}

func validateURL(c Config) (*url.URL,error) {
    u,err:=url.Parse(c.BaseURL)
    if err!=nil || u==nil || u.Host=="" || u.User!=nil ||
       u.RawQuery!="" || u.Fragment!="" || (u.Path!="" && u.Path!="/") {
        return nil,ErrUntrustedEndpoint
    }
    host:=strings.ToLower(u.Hostname())
    ip:=net.ParseIP(host)
    loopback:=host=="localhost" || (ip!=nil && ip.IsLoopback())
    if loopback {
        if u.Scheme!="http" && u.Scheme!="https" {return nil,ErrUntrustedEndpoint}
    } else if u.Scheme!="https" || c.TrustedRemoteHost=="" ||
        !strings.EqualFold(c.TrustedRemoteHost,host) {
        return nil,ErrUntrustedEndpoint
    }
    return u,nil
}

// Probe returns no partial trusted telemetry on error. Model paths, prompts,
// prompt-cache byte contents and API credentials are never surfaced.
func Probe(ctx context.Context, client *http.Client,c Config) (Observation,error) {
    u,err:=validateURL(c)
    if err!=nil {return Observation{},err}
    endpoint:=""
    switch c.Engine {
    case "ollama": endpoint="/api/ps"
    case "llama.cpp": endpoint="/props"
    default: return Observation{},ErrUnsupported
    }
    if client==nil {client=&http.Client{Timeout:3*time.Second}}
    target:=u.ResolveReference(&url.URL{Path:endpoint})
    req,err:=http.NewRequestWithContext(ctx,http.MethodGet,target.String(),nil)
    if err!=nil {return Observation{},err}
    r,err:=client.Do(req)
    if err!=nil {return Observation{},err}
    defer r.Body.Close()
    if r.StatusCode!=http.StatusOK {return Observation{},fmt.Errorf("%w: status=%d",ErrMalformed,r.StatusCode)}
    body,err:=io.ReadAll(io.LimitReader(r.Body,MaxBodyBytes+1))
    if err!=nil || len(body)>MaxBodyBytes {return Observation{},ErrMalformed}
    result:=Observation{Schema:"hmrc-telemetry-r0",Engine:c.Engine,Endpoint:u.Scheme+"://"+u.Host,SourcePath:endpoint}
    if c.Engine=="ollama" {
        var data struct {Models []struct {
            Name string `json:"name"`
            Model string `json:"model"`
            Digest string `json:"digest"`
            ContextLength *int `json:"context_length"`
            SizeVRAM *int64 `json:"size_vram"`
        } `json:"models"`}
        if err:=json.Unmarshal(body,&data);err!=nil {return Observation{},ErrMalformed}
        for _,m:=range data.Models {
            name:=m.Model
            if name=="" {name=m.Name}
            if name=="" {continue}
            if m.ContextLength!=nil && *m.ContextLength<=0 {return Observation{},ErrMalformed}
            if m.SizeVRAM!=nil && *m.SizeVRAM<0 {return Observation{},ErrMalformed}
            result.Models=append(result.Models,Model{
                Name:name,Digest:m.Digest,
                ReportedContextTokens:m.ContextLength,ReportedVRAMBytes:m.SizeVRAM,
            })
        }
    } else {
        var data struct {
            TotalSlots *int `json:"total_slots"`
            DefaultGenerationSettings struct{
                NCtx *int `json:"n_ctx"`
            } `json:"default_generation_settings"`
        }
        if err:=json.Unmarshal(body,&data);err!=nil {return Observation{},ErrMalformed}
        if data.TotalSlots!=nil {
            if *data.TotalSlots<=0 {return Observation{},ErrMalformed}
            result.ReportedTotalSlots=data.TotalSlots
        }
        if data.DefaultGenerationSettings.NCtx!=nil {
            if *data.DefaultGenerationSettings.NCtx<=0 {return Observation{},ErrMalformed}
            result.ReportedDefaultSlotContextTokens=data.DefaultGenerationSettings.NCtx
        }
    }
    return result,nil
}
