// Package hmrc is a deterministic, source-neutral harness/model/memory coordination
// oracle. It does not manage physical KV cache, call a model, or grant authority.
package hmrc

import (
    "encoding/json"
    "encoding/hex"
    "errors"
    "fmt"
    "os"
    "path/filepath"
    "reflect"
    "sort"
    "strings"
    "sync"
)

var (
    ErrInvalid = errors.New("invalid or unknown context state")
    ErrBoundary = errors.New("unresolved tool transaction")
    ErrHeadroom = errors.New("insufficient safely evictable context")
    ErrStale = errors.New("stale context generation")
    ErrUntrustedPlan = errors.New("plan does not match current validated policy")
)

// Unit is an immutable context projection of an already-persisted source item.
// Verified is a claim from an independent evidence gate, never model testimony.
type Unit struct {
    ID string
    Scope string
    Kind string // protected, active, historical
    Tokens int
    SourceID string
    SourceDigest string
    Verified bool
    Sequence uint64
}

type Snapshot struct {
    Schema string
    Generation uint64
    Scope string
    EffectiveCapacity int
    OpenToolTransactions int
    Units []Unit
    Evicted []Eviction
}

type Forecast struct {
    NextTurnTokens int
    ReserveTokens int
}

type Decision struct {
    Generation uint64
    Forecast Forecast
    Compact bool
    RemoveIDs []string
    BeforeTokens int
    ProjectedTokens int
    AfterProjectedTokens int
    InvalidatedPrefixTokens int
    EngineCacheAdvice string
}

type Eviction struct {
    ID string
    SourceID string
    SourceDigest string
    AtGeneration uint64
}

func clone(s Snapshot) Snapshot {
    s.Units = append([]Unit(nil), s.Units...)
    s.Evicted = append([]Eviction(nil), s.Evicted...)
    return s
}

func validDigest(d string) bool {
    if !strings.HasPrefix(d,"sha256:") || len(d)!=71 { return false }
    _,err:=hex.DecodeString(strings.TrimPrefix(d,"sha256:"))
    return err==nil
}

func validate(s Snapshot) error {
    if s.Schema != "hmrc-r0" || s.Generation == 0 ||
        s.EffectiveCapacity <= 0 || s.Scope == "" || s.OpenToolTransactions < 0 {
        return ErrInvalid
    }
    seen := make(map[string]bool)
    for _, u := range s.Units {
        if u.ID == "" || seen[u.ID] || u.Scope != s.Scope ||
            u.Tokens <= 0 || (u.Kind != "protected" && u.Kind != "active" && u.Kind != "historical") {
            return ErrInvalid
        }
        if u.Kind == "historical" && u.Verified &&
            (u.SourceID == "" || !validDigest(u.SourceDigest)) {
            return ErrInvalid
        }
        seen[u.ID] = true
    }
    seenEvicted:=make(map[string]bool)
    for _,e:=range s.Evicted {
        if e.ID=="" || seen[e.ID] || seenEvicted[e.ID] ||
           e.SourceID=="" || !validDigest(e.SourceDigest) ||
           e.AtGeneration<2 || e.AtGeneration>s.Generation {
            return ErrInvalid
        }
        seenEvicted[e.ID]=true
    }
    return nil
}

func total(s Snapshot) int {
    n := 0
    for _, u := range s.Units { n += u.Tokens }
    return n
}

// Propose is a read-only policy. It never treats KV pressure as evidence that
// semantic history is safely discardable. It is independent of Agent Dispatch.
func Propose(s Snapshot, f Forecast) (Decision, error) {
    if err := validate(s); err != nil { return Decision{}, err }
    if f.NextTurnTokens < 0 || f.ReserveTokens < 0 ||
        f.NextTurnTokens > s.EffectiveCapacity ||
        f.ReserveTokens > s.EffectiveCapacity-f.NextTurnTokens {
        return Decision{}, ErrInvalid
    }
    before := total(s)
    projected := before + f.NextTurnTokens + f.ReserveTokens
    d := Decision{
        Generation: s.Generation, Forecast: f, BeforeTokens: before,
        ProjectedTokens: projected, AfterProjectedTokens: projected,
        EngineCacheAdvice: "engine-owns-physical-kv",
    }
    // Use both forward demand and a safety margin; avoid compulsory churn.
    if int64(projected)*100 < int64(s.EffectiveCapacity)*85 { return d, nil }
    if s.OpenToolTransactions != 0 { return Decision{}, ErrBoundary }
    target := s.EffectiveCapacity * 70 / 100
    type candidate struct { id string; tokens int; seq uint64; idx int }
    candidates := make([]candidate, 0)
    for i, u := range s.Units {
        if u.Kind == "historical" && u.Verified && u.SourceID != "" &&
            strings.HasPrefix(u.SourceDigest, "sha256:") {
            candidates = append(candidates, candidate{u.ID,u.Tokens,u.Sequence,i})
        }
    }
    sort.SliceStable(candidates, func(i,j int)bool {
        if candidates[i].seq == candidates[j].seq { return candidates[i].idx < candidates[j].idx }
        return candidates[i].seq < candidates[j].seq
    })
    deleted := make(map[string]bool)
    for _, c := range candidates {
        if d.AfterProjectedTokens <= target { break }
        d.RemoveIDs = append(d.RemoveIDs,c.id)
        deleted[c.id] = true
        d.AfterProjectedTokens -= c.tokens
    }
    if d.AfterProjectedTokens > target { return Decision{}, ErrHeadroom }
    // Exact affected suffix estimate, not an observed cache hit metric.
    first := -1
    for i,u := range s.Units {
        if deleted[u.ID] { first=i; break }
    }
    if first >= 0 {
        for _,u := range s.Units[first:] { d.InvalidatedPrefixTokens += u.Tokens }
    }
    d.Compact = true
    return d,nil
}

// Manager is deliberately single-process/single-writer per session. A remote
// multi-process deployment requires an external lease or transactional CAS.
type Manager struct {
    mu sync.Mutex
    path string
    state Snapshot
}

func NewManager(path string, s Snapshot) (*Manager,error) {
    if err := validate(s); err != nil { return nil,err }
    // Creation must not erase a previously committed recovery checkpoint.
    // Cross-process initialization must additionally hold an external lease.
    if _,err := os.Lstat(path); err==nil { return nil,ErrStale } else if !errors.Is(err,os.ErrNotExist) { return nil,err }
    if err := writeAtomic(path,s); err != nil { return nil,err }
    return &Manager{path:path,state:clone(s)},nil
}

func Recover(path string) (*Manager,error) {
    data,err := os.ReadFile(path)
    if err != nil { return nil,err }
    var s Snapshot
    if err := json.Unmarshal(data,&s); err != nil { return nil,err }
    if err := validate(s); err != nil { return nil,err }
    return &Manager{path:path,state:clone(s)},nil
}

func (m *Manager) Read() Snapshot {
    m.mu.Lock(); defer m.mu.Unlock()
    return clone(m.state)
}

// Apply writes the full next projection before modifying in-memory state.
// It rejects stale and fabricated decisions, and records evidence for eviction.
func (m *Manager) Apply(d Decision) (Snapshot,error) {
    m.mu.Lock(); defer m.mu.Unlock()
    if d.Generation != m.state.Generation { return Snapshot{},ErrStale }
    expected,err := Propose(m.state,d.Forecast)
    if err != nil { return Snapshot{},err }
    if !reflect.DeepEqual(expected,d) { return Snapshot{},ErrUntrustedPlan }
    if !d.Compact { return clone(m.state),nil }
    removed := make(map[string]bool,len(d.RemoveIDs))
    for _,id := range d.RemoveIDs { removed[id]=true }
    next := clone(m.state)
    next.Generation++
    next.Units = nil
    for _,u := range m.state.Units {
        if removed[u.ID] {
            next.Evicted = append(next.Evicted,Eviction{
                ID:u.ID,SourceID:u.SourceID,SourceDigest:u.SourceDigest,
                AtGeneration:next.Generation,
            })
        } else { next.Units=append(next.Units,u) }
    }
    if err := validate(next); err != nil { return Snapshot{},err }
    if err := writeAtomic(m.path,next); err != nil { return Snapshot{},err }
    m.state=next
    return clone(next),nil
}

func writeAtomic(path string, s Snapshot) error {
    dir := filepath.Dir(path)
    if err := os.MkdirAll(dir,0700); err != nil { return err }
    f,err := os.CreateTemp(dir,".hmrc-pending-")
    if err != nil { return err }
    tmp := f.Name()
    defer os.Remove(tmp)
    if err := f.Chmod(0600); err != nil { f.Close(); return err }
    if err := json.NewEncoder(f).Encode(s); err != nil { f.Close(); return err }
    if err := f.Sync(); err != nil { f.Close(); return err }
    if err := f.Close(); err != nil { return err }
    if err := os.Rename(tmp,path); err != nil { return fmt.Errorf("checkpoint rename: %w",err) }
    d,err := os.Open(dir)
    if err != nil { return err }
    defer d.Close()
    return d.Sync()
}
