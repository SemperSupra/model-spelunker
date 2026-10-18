#!/usr/bin/env python3
"""Windows Job Object containment manager for sovereign actor execution."""

from __future__ import annotations

import ctypes
import os
import sys
from typing import Any

if os.name == "nt":
    from ctypes import wintypes
    kernel32 = ctypes.windll.kernel32

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryLimit", ctypes.c_size_t),
            ("PeakJobMemoryLimit", ctypes.c_size_t),
        ]

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JobObjectExtendedLimitInformation = 9


class WindowsJobObject:
    """Manages an OS-enforced Windows Job Object with KILL_ON_JOB_CLOSE containment."""

    def __init__(self) -> None:
        if os.name != "nt":
            self.handle = None
            return

        self.handle = kernel32.CreateJobObjectW(None, None)
        if not self.handle:
            err = ctypes.GetLastError()
            raise RuntimeError(f"fail-closed: CreateJobObjectW failed with error {err}")

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

        res = kernel32.SetInformationJobObject(
            self.handle,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not res:
            err = ctypes.GetLastError()
            kernel32.CloseHandle(self.handle)
            self.handle = None
            raise RuntimeError(f"fail-closed: SetInformationJobObject failed with error {err}")

    def assign_process(self, proc_handle: int) -> None:
        """Assign a process handle to this Job Object."""
        if os.name != "nt" or not self.handle:
            return
        res = kernel32.AssignProcessToJobObject(self.handle, proc_handle)
        if not res:
            err = ctypes.GetLastError()
            raise RuntimeError(f"fail-closed: AssignProcessToJobObject failed with error {err}")

    def terminate(self, exit_code: int = 1) -> None:
        """Terminate all processes assigned to this Job Object immediately."""
        if os.name != "nt" or not self.handle:
            return
        kernel32.TerminateJobObject(self.handle, exit_code)

    def close(self) -> None:
        """Close the job object handle, triggering kernel cleanup if configured."""
        if os.name == "nt" and self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self) -> "WindowsJobObject":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        try:
            self.terminate()
        finally:
            self.close()
