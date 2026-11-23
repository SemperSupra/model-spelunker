package telemetry

import (
    "context"
    "encoding/json"
    "errors"
    "net/http"
    "net/http/httptest"
    "strings"
    "sync/atomic"
    "testing"
)

func serve(t *testing.T, path, value string) (*httptest.Server,*atomic.Int64) {
    t.Helper()
    count:=new(atomic.Int64)
    s:=httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){
        if r.Method!="GET" || r.URL.Path!=path {t.Errorf("unexpected or mutating HTTP call %s %s",r.Method,r.URL.Path)}
        count.Add(1)
        w.Header().Set("Content-Type","application/json")
        w.Write([]byte(value))
    }))
    return s,count
}
func TestOllamaNativePSContract(t *testing.T) {
    s,count:=serve(t,"/api/ps",`{"models":[{"model":"synthetic-qwen","digest":"sha256:test","context_length":32768,"size_vram":12345},{"name":"synthetic-devstral","size_vram":0}]}`)
    defer s.Close()
    got,err:=Probe(context.Background(),s.Client(),Config{Engine:"ollama",BaseURL:s.URL})
    if err!=nil {t.Fatal(err)}
    if count.Load()!=1 || got.SourcePath!="/api/ps" || len(got.Models)!=2 ||
       got.Models[0].ReportedContextTokens==nil || *got.Models[0].ReportedContextTokens!=32768 ||
       got.Models[1].ReportedContextTokens!=nil || got.KVCachePressure!=nil {
        t.Fatalf("unknown field fabricated or valid field missing: %+v",got)
    }
}
func TestLlamaPropsContractAndPathHygiene(t *testing.T) {
    s,_:=serve(t,"/props",`{"total_slots":2,"model_path":"/home/private/models/secret.gguf","default_generation_settings":{"n_ctx":8192}}`)
    defer s.Close()
    got,err:=Probe(context.Background(),s.Client(),Config{Engine:"llama.cpp",BaseURL:s.URL})
    if err!=nil {t.Fatal(err)}
    if got.ReportedTotalSlots==nil || *got.ReportedTotalSlots!=2 ||
       got.ReportedDefaultSlotContextTokens==nil || *got.ReportedDefaultSlotContextTokens!=8192 {
        t.Fatalf("native props not normalized: %+v",got)
    }
    b,err:=json.Marshal(got)
    if err!=nil || strings.Contains(string(b),"secret.gguf") || strings.Contains(string(b),"home/private") {
        t.Fatal("native file path leaked through telemetry")
    }
}
func TestUnknownLlamaMetricsAreUnknown(t *testing.T) {
    s,_:=serve(t,"/props","{}")
    defer s.Close()
    got,err:=Probe(context.Background(),s.Client(),Config{Engine:"llama.cpp",BaseURL:s.URL})
    if err!=nil {t.Fatal(err)}
    if got.ReportedTotalSlots!=nil || got.ReportedDefaultSlotContextTokens!=nil ||
       got.KVCachePressure!=nil || got.PromptCacheHitRate!=nil {
        t.Fatal("unsupported utilization was invented")
    }
}
func TestRejectNonLocalInsecureHost(t *testing.T) {
    _,err:=Probe(context.Background(),nil,Config{Engine:"ollama",BaseURL:"http://169.254.169.254/latest"})
    if !errors.Is(err,ErrUntrustedEndpoint) {t.Fatalf("metadata endpoint accepted: %v",err)}
}
func TestRejectForgedTrustedHost(t *testing.T) {
    _,err:=Probe(context.Background(),nil,Config{Engine:"llama.cpp",BaseURL:"https://model.example.com",TrustedRemoteHost:"other.example.com"})
    if !errors.Is(err,ErrUntrustedEndpoint) {t.Fatalf("host confusion accepted: %v",err)}
}
func TestRejectUnsupportedProvider(t *testing.T) {
    s,_:=serve(t,"/api/ps","{}");defer s.Close()
    _,err:=Probe(context.Background(),s.Client(),Config{Engine:"unknown",BaseURL:s.URL})
    if !errors.Is(err,ErrUnsupported) {t.Fatalf("unknown provider mapped: %v",err)}
}
func TestRejectMalformedJSON(t *testing.T) {
    s,_:=serve(t,"/api/ps","{bad-json");defer s.Close()
    _,err:=Probe(context.Background(),s.Client(),Config{Engine:"ollama",BaseURL:s.URL})
    if !errors.Is(err,ErrMalformed) {t.Fatalf("malformed JSON accepted: %v",err)}
}
func TestRejectOverlongJSON(t *testing.T) {
    s,_:=serve(t,"/api/ps",strings.Repeat(" ",MaxBodyBytes+1));defer s.Close()
    _,err:=Probe(context.Background(),s.Client(),Config{Engine:"ollama",BaseURL:s.URL})
    if !errors.Is(err,ErrMalformed) {t.Fatalf("oversized response accepted: %v",err)}
}
func TestRejectNegativeContext(t *testing.T) {
    s,_:=serve(t,"/api/ps",`{"models":[{"name":"bad","context_length":-1}]}`)
    defer s.Close()
    _,err:=Probe(context.Background(),s.Client(),Config{Engine:"ollama",BaseURL:s.URL})
    if !errors.Is(err,ErrMalformed) {t.Fatalf("negative context accepted: %v",err)}
}
func TestRejectZeroSlots(t *testing.T) {
    s,_:=serve(t,"/props",`{"total_slots":0}`)
    defer s.Close()
    _,err:=Probe(context.Background(),s.Client(),Config{Engine:"llama.cpp",BaseURL:s.URL})
    if !errors.Is(err,ErrMalformed) {t.Fatalf("zero slots accepted: %v",err)}
}
func TestDoNotFollowRedirects(t *testing.T) {
    var second atomic.Int64
    destination:=httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){second.Add(1)}))
    defer destination.Close()
    source:=httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){
        http.Redirect(w,r,destination.URL+"/api/ps",http.StatusTemporaryRedirect)
    }))
    defer source.Close()
    _,err:=Probe(context.Background(),source.Client(),Config{Engine:"ollama",BaseURL:source.URL})
    if !errors.Is(err,ErrMalformed) || second.Load()!=0 {
        t.Fatalf("cross-host redirect followed: %v calls=%d",err,second.Load())
    }
}
func TestCancelBeforeRequest(t *testing.T) {
    s,_:=serve(t,"/props","{}");defer s.Close()
    ctx,cancel:=context.WithCancel(context.Background());cancel()
    _,err:=Probe(ctx,s.Client(),Config{Engine:"llama.cpp",BaseURL:s.URL})
    if err==nil {t.Fatal("cancelled request accepted")}
}
