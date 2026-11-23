// Package evidence adds source-bound custody and a fail-closed session lease
// around the experimental HMRC R0 policy. It neither reads privileged source
// nor changes authorization, server cache state, or agent tool execution.
package evidence

import (
    "crypto/sha256"
    "encoding/hex"
    "errors"
    "fmt"
    "os"
    "path/filepath"
    "sync"

    hmrc "example.com/sempersupra/hmrc-r0"
)

var (
    ErrEvidence=errors.New("external immutable evidence missing or mismatched")
    ErrBusy=errors.New("exclusive session lease unavailable; manual reconciliation needed")
    ErrClosed=errors.New("session already closed")
)

// Source is supplied by an independently admitted immutable source catalog.
// Bytes are exact source content; a model's Verified flag alone is insufficient.
type Source struct {
    ID string
    Scope string
    Status string // accepted, advisory or superseded; never authority by retrieval
    Bytes []byte
}

type Catalog struct { Records []Source }

func digest(b []byte) string {
    h:=sha256.Sum256(b)
    return "sha256:"+hex.EncodeToString(h[:])
}

func cloneCatalog(c Catalog) (Catalog,error) {
    seen:=make(map[string]bool,len(c.Records))
    out:=Catalog{Records:make([]Source,0,len(c.Records))}
    for _,r:=range c.Records {
        if r.ID=="" || r.Scope=="" || seen[r.ID] ||
           (r.Status!="accepted" && r.Status!="advisory" && r.Status!="superseded") ||
           len(r.Bytes)==0 {
            return Catalog{},ErrEvidence
        }
        seen[r.ID]=true
        out.Records=append(out.Records,Source{
            ID:r.ID,Scope:r.Scope,Status:r.Status,
            Bytes:append([]byte(nil),r.Bytes...),
        })
    }
    return out,nil
}

// Verify independently recomputes SHA-256 of exact immutable source bytes.
// Protected context also requires an authoritative (not advisory) source.
func Verify(s hmrc.Snapshot,c Catalog) error {
    rows,err:=cloneCatalog(c)
    if err!=nil {return err}
    byID:=make(map[string]Source,len(rows.Records))
    for _,r:=range rows.Records {byID[r.ID]=r}
    checked:=func(id,scope,hash string,protected bool) bool {
        r,ok:=byID[id]
        if !ok || r.Scope!=scope || r.Status=="superseded" ||
           (protected && r.Status!="accepted") {
            return false
        }
        return digest(r.Bytes)==hash
    }
    for _,u:=range s.Units {
        if u.Kind=="protected" && !checked(u.SourceID,s.Scope,u.SourceDigest,true) {
            return ErrEvidence
        }
        if u.Kind=="historical" && u.Verified &&
           !checked(u.SourceID,s.Scope,u.SourceDigest,false) {
            return ErrEvidence
        }
    }
    for _,u:=range s.Evicted {
        if !checked(u.SourceID,s.Scope,u.SourceDigest,false) {
            return ErrEvidence
        }
    }
    return nil
}

// ExclusiveSession is a process-bound immutable-source safe wrapper; .lease is
// acquired via O_EXCL. Crash-stale leases fail closed and require explicit
// human/authorized-controller lease reconciliation; never auto-delete them.
// A shared/network filesystem requires a separate qualified lock primitive.
type ExclusiveSession struct {
    mu sync.Mutex
    path string
    leasePath string
    lease *os.File
    manager *hmrc.Manager
    catalog Catalog
    closed bool
}

func Open(path string,c Catalog,initial *hmrc.Snapshot) (_ *ExclusiveSession,err error) {
    copied,err:=cloneCatalog(c)
    if err!=nil {return nil,err}
    if err=os.MkdirAll(filepath.Dir(path),0700);err!=nil{return nil,err}
    leasePath:=path+".lease"
    f,err:=os.OpenFile(leasePath,os.O_WRONLY|os.O_CREATE|os.O_EXCL,0600)
    if err!=nil {
        if errors.Is(err,os.ErrExist){return nil,ErrBusy}
        return nil,err
    }
    ok:=false
    defer func(){
        if !ok {f.Close();os.Remove(leasePath)}
    }()
    if _,err=f.WriteString("exclusive; recover only with explicit external reconciliation\n");err!=nil{return nil,err}
    if err=f.Sync();err!=nil{return nil,err}
    var m *hmrc.Manager
    if _,e:=os.Lstat(path);e==nil {
        m,err=hmrc.Recover(path)
    } else if !errors.Is(e,os.ErrNotExist) {
        return nil,e
    } else if initial==nil {
        return nil,ErrEvidence
    } else {
        if err=Verify(*initial,copied);err!=nil{return nil,err}
        m,err=hmrc.NewManager(path,*initial)
    }
    if err!=nil{return nil,err}
    if err=Verify(m.Read(),copied);err!=nil{return nil,err}
    ok=true
    return &ExclusiveSession{
        path:path,leasePath:leasePath,lease:f,
        manager:m,catalog:copied,
    },nil
}

func (s *ExclusiveSession) Read() (hmrc.Snapshot,error) {
    s.mu.Lock();defer s.mu.Unlock()
    if s.closed{return hmrc.Snapshot{},ErrClosed}
    snap:=s.manager.Read()
    if err:=Verify(snap,s.catalog);err!=nil{return hmrc.Snapshot{},err}
    return snap,nil
}

func (s *ExclusiveSession) Propose(f hmrc.Forecast) (hmrc.Decision,error) {
    snap,err:=s.Read()
    if err!=nil{return hmrc.Decision{},err}
    return hmrc.Propose(snap,f)
}

// Apply rechecks immutable source custody at the point of commit.
// This is a single-process leased session, not a distributed transaction.
func (s *ExclusiveSession) Apply(p hmrc.Decision) (hmrc.Snapshot,error) {
    s.mu.Lock();defer s.mu.Unlock()
    if s.closed{return hmrc.Snapshot{},ErrClosed}
    before:=s.manager.Read()
    if err:=Verify(before,s.catalog);err!=nil{return hmrc.Snapshot{},err}
    next,err:=s.manager.Apply(p)
    if err!=nil{return hmrc.Snapshot{},err}
    if err:=Verify(next,s.catalog);err!=nil{return hmrc.Snapshot{},fmt.Errorf("postcommit evidence invariant: %w",err)}
    return next,nil
}

func (s *ExclusiveSession) Close() error {
    s.mu.Lock();defer s.mu.Unlock()
    if s.closed{return ErrClosed}
    s.closed=true
    // Prevent inadvertently removing a replaced/moved lease file.
    old,err:=s.lease.Stat()
    if err!=nil {s.lease.Close();return err}
    current,err:=os.Lstat(s.leasePath)
    if err!=nil {s.lease.Close();return err}
    if !os.SameFile(old,current) {
        s.lease.Close()
        return ErrBusy
    }
    if err=s.lease.Close();err!=nil{return err}
    return os.Remove(s.leasePath)
}
