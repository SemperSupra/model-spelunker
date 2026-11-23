#!/usr/bin/env python3
"""R16 unprivileged same-run Linux cgroup-v2 CPU/RAM observer.

This is an opt-in observer for the existing R6/R7 #139 task interview.
No process inspection, external endpoints, state mutation or raw task capture.
Reported headroom is observed occupancy only, never an assured surge reservation.
"""
import os
from pathlib import Path
import threading
import time

CG = Path("/sys/fs/cgroup")
MAX_SAMPLES = 24000

def read(path):
    try:
        return Path(path).read_text().strip()
    except (OSError, UnicodeError):
        return None

def cpu_capacity():
    raw=read(CG/"cpu.max")
    if raw:
        p=raw.split()
        if len(p)==2 and p[0]!="max":
            try:
                quota, period=int(p[0]),int(p[1])
                if quota>0 and period>0:
                    return quota/period,"cgroup-v2-quota"
            except ValueError:
                pass
    try:
        cpus=len(os.sched_getaffinity(0))
    except (AttributeError,OSError):
        cpus=os.cpu_count() or 0
    if cpus>0:
        return float(cpus),"visible-affinity-capacity-proxy"
    return None,"UNKNOWN"

def cpu_usage_usec():
    raw=read(CG/"cpu.stat")
    if raw:
        for line in raw.splitlines():
            p=line.split()
            if len(p)==2 and p[0]=="usage_usec":
                try:
                    n=int(p[1])
                    return n if n>=0 else None
                except ValueError:
                    pass
    return None

def memory_fraction():
    cap=read(CG/"memory.max")
    cur=read(CG/"memory.current")
    if cap and cur and cap!="max":
        try:
            maximum,used=int(cap),int(cur)
            if maximum>0 and used>=0:
                return used/maximum,"cgroup-v2-memory-limit"
        except ValueError:
            pass
    data=read("/proc/meminfo")
    if data:
        m={}
        for line in data.splitlines():
            x=line.replace(":"," ").split()
            if len(x)>=2 and x[0] in ("MemTotal","MemAvailable"):
                try:
                    m[x[0]]=int(x[1])
                except ValueError:
                    pass
        if m.get("MemTotal",0)>0 and "MemAvailable" in m and 0<=m["MemAvailable"]<=m["MemTotal"]:
            return 1-m["MemAvailable"]/m["MemTotal"],"host-memory-availability-proxy"
    return None,"UNKNOWN"

class ResourceSampler:
    def __init__(self,interval_seconds=.25,clock=time.monotonic,usage=cpu_usage_usec,
                 mem=memory_fraction,capacity=cpu_capacity):
        if not .1<=interval_seconds<=5:
            raise ValueError("bounded sampling interval required")
        self.interval=interval_seconds
        self.clock=clock
        self.usage=usage
        self.mem=mem
        self.capacity,self.capacity_source=capacity()
        self.rows=[]
        self.stop_event=threading.Event()
        self.lock=threading.Lock()
        self.thread=None
        self.overhead_seconds=0.0

    def sample(self):
        started=self.clock()
        usage=self.usage()
        fraction,source=self.mem()
        ended=self.clock()
        row=(ended,usage,fraction,source)
        with self.lock:
            if len(self.rows)<MAX_SAMPLES:
                self.rows.append(row)
            self.overhead_seconds+=max(0,ended-started)

    def _loop(self):
        self.sample()
        while not self.stop_event.wait(self.interval):
            self.sample()

    def start(self):
        if self.thread is not None:
            raise RuntimeError("observer already started")
        self.thread=threading.Thread(target=self._loop,daemon=True,name="r16-readonly-resource")
        self.thread.start()
        return self

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)
        return self

    def window(self,started,ended):
        if not isinstance(started,(int,float)) or not isinstance(ended,(int,float)) or ended<=started:
            raise ValueError("invalid monotonic window")
        with self.lock:
            rows=[r for r in self.rows if started<=r[0]<=ended]
            overhead=self.overhead_seconds
        out={"schema":"r16-observed-phase-resource/v1","observation_source":"LINUX_CGROUP_AND_HOST_READ_ONLY",
             "sample_count":len(rows),
             "sample_interval_requested_seconds":self.interval,
             "cpu_capacity_cores":self.capacity,
             "cpu_capacity_source":self.capacity_source,
             "cpu_core_seconds_measured":None,
             "cpu_peak_fraction_of_visible_capacity":None,
             "memory_peak_fraction_of_capacity":None,
             "memory_source":"UNKNOWN",
             "observed_free_fraction_min":None,
             "surge_reservation_guarantee":"NOT_ESTABLISHED",
             "observer_total_time_seconds_so_far":round(overhead,6),
             "observation_status":"UNKNOWN_INSUFFICIENT_SAMPLES"}
        if len(rows)<2:
            return out
        cpu_intervals=[]
        cpu_core_seconds=0.0
        for a,b in zip(rows,rows[1:]):
            if a[1] is None or b[1] is None or b[1]<a[1] or b[0]<=a[0]:
                continue
            dt=b[0]-a[0]
            active=(b[1]-a[1])/1e6
            cpu_core_seconds+=active
            if self.capacity and self.capacity>0:
                cpu_intervals.append(active/(dt*self.capacity))
        if cpu_intervals:
            out["cpu_core_seconds_measured"]=round(cpu_core_seconds,6)
            out["cpu_peak_fraction_of_visible_capacity"]=round(max(cpu_intervals),6)
        mem_values=[(r[2],r[3]) for r in rows if r[2] is not None]
        if mem_values:
            out["memory_peak_fraction_of_capacity"]=round(max(x[0] for x in mem_values),6)
            kinds={x[1] for x in mem_values}
            out["memory_source"]=next(iter(kinds)) if len(kinds)==1 else "MIXED_SOURCE_INVALID"
        if out["cpu_peak_fraction_of_visible_capacity"] is None or out["memory_peak_fraction_of_capacity"] is None:
            return out
        strong=(self.capacity_source=="cgroup-v2-quota" and
                out["memory_source"]=="cgroup-v2-memory-limit")
        if strong:
            out["observed_free_fraction_min"]=round(1-max(out["cpu_peak_fraction_of_visible_capacity"],
                                                           out["memory_peak_fraction_of_capacity"]),6)
            out["observation_status"]="OBSERVED_BOUNDED_OCCUPANCY_NOT_RESERVED_SURGE"
        else:
            out["observation_status"]="OBSERVED_PROXY_NOT_RESERVE_PROOF"
        return out
