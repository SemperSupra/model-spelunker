#!/usr/bin/env python3
"""Windows Job Object containment manager and suspended process spawner for sovereign actor execution."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from typing import Any

if os.name == "nt":
    from ctypes import wintypes
    import _winapi

    # Use WinDLL with use_last_error=True so ctypes.get_last_error() reliably accesses Win32 error codes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # ABI verification: on 64-bit Windows, HANDLE is a 64-bit pointer-sized integer
    assert ctypes.sizeof(wintypes.HANDLE) == ctypes.sizeof(
        ctypes.c_void_p
    ), "ABI error: wintypes.HANDLE must match pointer width"

    # Explicit Win32 function signatures to avoid 32-bit truncation of 64-bit handles
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]

    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]

    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]

    kernel32.TerminateJobObject.restype = wintypes.BOOL
    kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]

    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    kernel32.ResumeThread.restype = wintypes.DWORD
    kernel32.ResumeThread.argtypes = [wintypes.HANDLE]

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
    CREATE_SUSPENDED = 0x00000004


class WindowsJobObject:
    """Manages an OS-enforced Windows Job Object with KILL_ON_JOB_CLOSE containment."""

    def __init__(self) -> None:
        if os.name != "nt":
            self.handle: Any = None
            return

        self.handle = kernel32.CreateJobObjectW(None, None)
        if not self.handle:
            err = ctypes.get_last_error()
            raise RuntimeError(f"fail-closed: CreateJobObjectW failed with Win32 error {err}")

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

        res = kernel32.SetInformationJobObject(
            self.handle,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not res:
            err = ctypes.get_last_error()
            kernel32.CloseHandle(self.handle)
            self.handle = None
            raise RuntimeError(f"fail-closed: SetInformationJobObject failed with Win32 error {err}")

    def assign_process(self, proc_handle: int) -> None:
        """Assign a process handle to this Job Object. Fails closed on error."""
        if os.name != "nt":
            return
        if not self.handle:
            raise RuntimeError("fail-closed: cannot assign process to an uninitialized or closed Job Object")
        res = kernel32.AssignProcessToJobObject(self.handle, wintypes.HANDLE(proc_handle))
        if not res:
            err = ctypes.get_last_error()
            raise RuntimeError(f"fail-closed: AssignProcessToJobObject failed with Win32 error {err}")

    def terminate(self, exit_code: int = 1) -> None:
        """Terminate all processes assigned to this Job Object immediately."""
        if os.name != "nt":
            return
        if not self.handle:
            raise RuntimeError("fail-closed: cannot terminate an uninitialized or closed Job Object")
        res = kernel32.TerminateJobObject(self.handle, exit_code)
        if not res:
            err = ctypes.get_last_error()
            # ERROR_ACCESS_DENIED (5) can occur if all processes have already terminated; otherwise report error
            if err not in (0, 5):
                raise RuntimeError(f"fail-closed: TerminateJobObject failed with Win32 error {err}")

    def close(self) -> None:
        """Close the job object handle, triggering kernel cleanup of all child processes."""
        if os.name == "nt" and self.handle:
            h = self.handle
            self.handle = None
            res = kernel32.CloseHandle(h)
            if not res:
                err = ctypes.get_last_error()
                raise RuntimeError(f"fail-closed: CloseHandle failed with Win32 error {err}")

    def __enter__(self) -> WindowsJobObject:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        try:
            self.terminate(1)
        finally:
            self.close()


if os.name == "nt":
    class SuspendedJobPopen(subprocess.Popen):
        """Subprocess Popen that creates the process suspended, atomically assigns it to a Job Object, and resumes it."""

        def __init__(self, *args: Any, job: WindowsJobObject | None = None, **kwargs: Any) -> None:
            if job is None or not getattr(job, "handle", None):
                raise ValueError("fail-closed: SuspendedJobPopen requires an active WindowsJobObject with a valid handle")
            self._job = job
            super().__init__(*args, **kwargs)

        def _execute_child(
            self,
            args: Any,
            executable: Any,
            preexec_fn: Any,
            close_fds: Any,
            pass_fds: Any,
            cwd: Any,
            env: Any,
            startupinfo: Any,
            creationflags: int,
            shell: bool,
            p2cread: Any,
            p2cwrite: Any,
            c2pread: Any,
            c2pwrite: Any,
            errread: Any,
            errwrite: Any,
            unused_restore_signals: Any,
            unused_gid: Any,
            unused_gids: Any,
            unused_uid: Any,
            unused_umask: Any,
            unused_start_new_session: Any,
            unused_process_group: Any,
        ) -> None:
            if self._job is None or not self._job.handle:
                raise RuntimeError("fail-closed: SuspendedJobPopen requires an active WindowsJobObject before process creation")

            if isinstance(args, str):
                pass
            elif isinstance(args, bytes):
                if shell:
                    raise TypeError("bytes args is not allowed on Windows")
                args = subprocess.list2cmdline([args])
            elif isinstance(args, os.PathLike):
                if shell:
                    raise TypeError("path-like args is not allowed when shell is true")
                args = subprocess.list2cmdline([args])
            else:
                args = subprocess.list2cmdline(args)

            if executable is not None:
                executable = os.fsdecode(executable)

            if startupinfo is None:
                startupinfo = subprocess.STARTUPINFO()
            else:
                startupinfo = startupinfo.copy()

            use_std_handles = -1 not in (p2cread, c2pwrite, errwrite)
            if use_std_handles:
                startupinfo.dwFlags |= _winapi.STARTF_USESTDHANDLES
                startupinfo.hStdInput = p2cread
                startupinfo.hStdOutput = c2pwrite
                startupinfo.hStdError = errwrite

            attribute_list = startupinfo.lpAttributeList
            have_handle_list = bool(
                attribute_list and "handle_list" in attribute_list and attribute_list["handle_list"]
            )
            if have_handle_list or (use_std_handles and close_fds):
                if attribute_list is None:
                    attribute_list = startupinfo.lpAttributeList = {}
                handle_list = attribute_list["handle_list"] = list(
                    attribute_list.get("handle_list", [])
                )
                if use_std_handles:
                    handle_list += [int(p2cread), int(c2pwrite), int(errwrite)]
                handle_list[:] = self._filter_handle_list(handle_list)
                close_fds = False

            if shell:
                startupinfo.dwFlags |= _winapi.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = _winapi.SW_HIDE
                if not executable:
                    comspec = os.environ.get("ComSpec")
                    if not comspec:
                        system_root = os.environ.get("SystemRoot", "")
                        comspec = os.path.join(system_root, "System32", "cmd.exe")
                        if not os.path.isabs(comspec):
                            raise FileNotFoundError("shell not found: neither %ComSpec% nor %SystemRoot% is set")
                    if os.path.isabs(comspec):
                        executable = comspec
                else:
                    comspec = executable
                args = '{} /c "{}"'.format(comspec, args)

            if cwd is not None:
                cwd = os.fsdecode(cwd)

            sys.audit("subprocess.Popen", executable, args, cwd, env)

            # Force CREATE_SUSPENDED so child cannot execute a single instruction before job assignment
            creationflags |= CREATE_SUSPENDED

            try:
                hp, ht, pid, tid = _winapi.CreateProcess(
                    executable,
                    args,
                    None,
                    None,
                    int(not close_fds),
                    creationflags,
                    env,
                    cwd,
                    startupinfo,
                )
            finally:
                self._close_pipe_fds(p2cread, p2cwrite, c2pread, c2pwrite, errread, errwrite)

            self._child_created = True
            self._handle = subprocess.Handle(hp)
            self.pid = pid

            # Assign process to Job Object while STILL SUSPENDED
            if self._job is None or not self._job.handle:
                _winapi.TerminateProcess(hp, 1)
                _winapi.CloseHandle(ht)
                raise RuntimeError("fail-closed: Job Object handle lost prior to process assignment")

            try:
                self._job.assign_process(hp)
            except Exception:
                # Fail-closed: kill the suspended process before it ever runs
                _winapi.TerminateProcess(hp, 1)
                _winapi.CloseHandle(ht)
                raise

            # Process is safely bound to Job Object; resume primary thread to begin execution
            res = kernel32.ResumeThread(wintypes.HANDLE(ht))
            _winapi.CloseHandle(ht)
            if res == 0xFFFFFFFF:
                err = ctypes.get_last_error()
                _winapi.TerminateProcess(hp, 1)
                raise RuntimeError(f"fail-closed: ResumeThread failed with Win32 error {err}")
else:
    class SuspendedJobPopen(subprocess.Popen):  # type: ignore[no-redef]
        """Fallback for non-Windows platforms."""
        def __init__(self, *args: Any, job: Any = None, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
