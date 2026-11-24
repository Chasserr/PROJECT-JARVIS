from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import os
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any


class SandboxError(RuntimeError):
    """A restricted worker failed or violated its execution contract."""


def run_restricted_worker(
    operation: str, arguments: dict[str, Any], *, timeout_seconds: float = 5.0
) -> dict[str, Any]:
    """Run a fixed pure-data operation as a low-integrity restricted Windows process.

    This is process isolation with a restricted token and Job Object limits. It is
    not an AppContainer: filesystem read access and network access are not blocked.
    Only the built-in pure-data operations are safe to dispatch here.
    """
    if os.name != "nt":
        raise SandboxError("Restricted worker is Windows-only.")
    if not 0.1 <= timeout_seconds <= 15:
        raise ValueError("timeout_seconds must be between 0.1 and 15")
    request = json.dumps(
        {"operation": operation, "arguments": arguments},
        ensure_ascii=True,
        allow_nan=False,
    )
    if len(request) > 32_768:
        raise ValueError("Worker request exceeds 32 KB")

    try:
        import win32api
        import win32con
        import win32job
        import win32security
    except ImportError as exc:
        raise SandboxError("pywin32 is required for restricted execution") from exc

    class SECURITY_ATTRIBUTES(ctypes.Structure):
        _fields_ = [
            ("nLength", ctypes.wintypes.DWORD),
            ("lpSecurityDescriptor", ctypes.c_void_p),
            ("bInheritHandle", ctypes.wintypes.BOOL),
        ]

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.wintypes.DWORD),
            ("lpReserved", ctypes.wintypes.LPWSTR),
            ("lpDesktop", ctypes.wintypes.LPWSTR),
            ("lpTitle", ctypes.wintypes.LPWSTR),
            ("dwX", ctypes.wintypes.DWORD),
            ("dwY", ctypes.wintypes.DWORD),
            ("dwXSize", ctypes.wintypes.DWORD),
            ("dwYSize", ctypes.wintypes.DWORD),
            ("dwXCountChars", ctypes.wintypes.DWORD),
            ("dwYCountChars", ctypes.wintypes.DWORD),
            ("dwFillAttribute", ctypes.wintypes.DWORD),
            ("dwFlags", ctypes.wintypes.DWORD),
            ("wShowWindow", ctypes.wintypes.WORD),
            ("cbReserved2", ctypes.wintypes.WORD),
            ("lpReserved2", ctypes.c_void_p),
            ("hStdInput", ctypes.wintypes.HANDLE),
            ("hStdOutput", ctypes.wintypes.HANDLE),
            ("hStdError", ctypes.wintypes.HANDLE),
        ]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", ctypes.wintypes.HANDLE),
            ("hThread", ctypes.wintypes.HANDLE),
            ("dwProcessId", ctypes.wintypes.DWORD),
            ("dwThreadId", ctypes.wintypes.DWORD),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    create_pipe = kernel.CreatePipe
    create_pipe.argtypes = [
        ctypes.POINTER(ctypes.wintypes.HANDLE),
        ctypes.POINTER(ctypes.wintypes.HANDLE),
        ctypes.POINTER(SECURITY_ATTRIBUTES),
        ctypes.wintypes.DWORD,
    ]
    create_pipe.restype = ctypes.wintypes.BOOL
    set_handle_info = kernel.SetHandleInformation
    set_handle_info.argtypes = [
        ctypes.wintypes.HANDLE,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.DWORD,
    ]
    set_handle_info.restype = ctypes.wintypes.BOOL
    close_handle = kernel.CloseHandle
    close_handle.argtypes = [ctypes.wintypes.HANDLE]
    close_handle.restype = ctypes.wintypes.BOOL
    write_file = kernel.WriteFile
    write_file.argtypes = [
        ctypes.wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.wintypes.DWORD,
        ctypes.POINTER(ctypes.wintypes.DWORD),
        ctypes.c_void_p,
    ]
    write_file.restype = ctypes.wintypes.BOOL
    read_file = kernel.ReadFile
    read_file.argtypes = [
        ctypes.wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.wintypes.DWORD,
        ctypes.POINTER(ctypes.wintypes.DWORD),
        ctypes.c_void_p,
    ]
    read_file.restype = ctypes.wintypes.BOOL
    create_process = advapi.CreateProcessAsUserW
    create_process.argtypes = [
        ctypes.c_void_p,
        ctypes.wintypes.LPCWSTR,
        ctypes.wintypes.LPWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.wintypes.BOOL,
        ctypes.wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.wintypes.LPCWSTR,
        ctypes.POINTER(STARTUPINFOW),
        ctypes.POINTER(PROCESS_INFORMATION),
    ]
    create_process.restype = ctypes.wintypes.BOOL

    handles: list[int] = []
    token_handle = 0
    job = None
    try:
        token_access = (
            win32con.TOKEN_DUPLICATE
            | win32con.TOKEN_QUERY
            | win32con.TOKEN_ASSIGN_PRIMARY
            | win32con.TOKEN_ADJUST_DEFAULT
            | win32con.TOKEN_ADJUST_SESSIONID
        )
        current = win32security.OpenProcessToken(win32api.GetCurrentProcess(), token_access)
        restricted = win32security.CreateRestrictedToken(
            current, win32security.DISABLE_MAX_PRIVILEGE, [], [], []
        )
        win32security.SetTokenInformation(
            restricted,
            win32security.TokenIntegrityLevel,
            (win32security.ConvertStringSidToSid("S-1-16-4096"), win32security.SE_GROUP_INTEGRITY),
        )
        token_handle = restricted.Detach()
        current.Close()

        sa = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), None, True)
        child_in, parent_in = ctypes.wintypes.HANDLE(), ctypes.wintypes.HANDLE()
        parent_out, child_out = ctypes.wintypes.HANDLE(), ctypes.wintypes.HANDLE()
        if not create_pipe(ctypes.byref(child_in), ctypes.byref(parent_in), ctypes.byref(sa), 0):
            raise ctypes.WinError(ctypes.get_last_error())
        if not create_pipe(ctypes.byref(parent_out), ctypes.byref(child_out), ctypes.byref(sa), 0):
            raise ctypes.WinError(ctypes.get_last_error())
        assert child_in.value is not None
        assert parent_in.value is not None
        assert parent_out.value is not None
        assert child_out.value is not None
        handles.extend(
            [int(child_in.value), int(parent_in.value), int(parent_out.value), int(child_out.value)]
        )
        if not set_handle_info(parent_in, 1, 0) or not set_handle_info(parent_out, 1, 0):
            raise ctypes.WinError(ctypes.get_last_error())

        startup = STARTUPINFOW()
        startup.cb = ctypes.sizeof(startup)
        startup.dwFlags = 0x00000100  # STARTF_USESTDHANDLES
        startup.hStdInput, startup.hStdOutput, startup.hStdError = child_in, child_out, child_out
        worker = Path(__file__).with_name("sandbox_worker.py")
        # A venv executable can be a Windows launcher shim which fails under a
        # restricted token. Launch the concrete base interpreter instead.
        worker_python = str(Path(sys.base_prefix) / "python.exe")
        if not Path(worker_python).is_file():
            worker_python = sys.executable
        command = ctypes.create_unicode_buffer(
            subprocess.list2cmdline([worker_python, "-I", str(worker)])
        )
        info = PROCESS_INFORMATION()
        flags = 0x00000004 | 0x08000000  # CREATE_SUSPENDED | CREATE_NO_WINDOW
        if not create_process(
            token_handle,
            worker_python,
            command,
            None,
            None,
            True,
            flags,
            None,
            str(worker.parent),
            ctypes.byref(startup),
            ctypes.byref(info),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        assert info.hProcess is not None and info.hThread is not None
        handles.extend([int(info.hProcess), int(info.hThread)])
        child_token = win32security.OpenProcessToken(int(info.hProcess), win32con.TOKEN_QUERY)
        try:
            integrity_sid, _ = win32security.GetTokenInformation(
                child_token, win32security.TokenIntegrityLevel
            )
            integrity_name = win32security.ConvertSidToStringSid(integrity_sid)
            restricted_flag = win32security.GetTokenInformation(
                child_token, win32security.TokenHasRestrictions
            )
            if integrity_name != "S-1-16-4096" or not restricted_flag:
                raise SandboxError(
                    f"Child token verification failed: integrity={integrity_name!r}, "
                    f"restricted={restricted_flag!r}"
                )
        finally:
            child_token.Close()

        job = win32job.CreateJobObject(None, "")
        limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        limits["BasicLimitInformation"]["LimitFlags"] = (
            win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            | win32job.JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            | win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY
        )
        limits["BasicLimitInformation"]["ActiveProcessLimit"] = 1
        limits["ProcessMemoryLimit"] = 256 * 1024 * 1024
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
        win32job.AssignProcessToJobObject(job, int(info.hProcess))

        resume = kernel.ResumeThread
        resume.argtypes = [ctypes.wintypes.HANDLE]
        resume.restype = ctypes.wintypes.DWORD
        if resume(info.hThread) == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        close_handle(child_in)
        handles.remove(int(child_in.value))
        close_handle(child_out)
        handles.remove(int(child_out.value))

        encoded = (request + "\n").encode("utf-8")
        buffer = ctypes.create_string_buffer(encoded)
        written = ctypes.wintypes.DWORD()
        if not write_file(parent_in, buffer, len(encoded), ctypes.byref(written), None):
            raise ctypes.WinError(ctypes.get_last_error())
        close_handle(parent_in)
        handles.remove(int(parent_in.value))

        wait = kernel.WaitForSingleObject
        wait.argtypes = [ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD]
        wait.restype = ctypes.wintypes.DWORD
        if wait(info.hProcess, int(timeout_seconds * 1000)) != 0:
            win32job.TerminateJobObject(job, 124)
            raise SandboxError("Worker exceeded its execution deadline")
        chunks: list[bytes] = []
        while True:
            chunk = ctypes.create_string_buffer(4096)
            count = ctypes.wintypes.DWORD()
            if not read_file(parent_out, chunk, 4096, ctypes.byref(count), None):
                break
            if count.value == 0:
                break
            chunks.append(chunk.raw[: count.value])
            if sum(map(len, chunks)) > 32_768:
                raise SandboxError("Worker output exceeded 32 KB")
        close_handle(parent_out)
        handles.remove(int(parent_out.value))
        try:
            response = json.loads(b"".join(chunks).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SandboxError("Worker returned invalid JSON") from exc
        if not isinstance(response, dict) or response.get("ok") is not True:
            raise SandboxError(
                str(response.get("error", "Worker failed"))[:500]
                if isinstance(response, dict)
                else "Invalid worker response"
            )
        result = response.get("result")
        if not isinstance(result, dict):
            raise SandboxError("Worker result must be an object")
        return result
    except SandboxError:
        raise
    except Exception as exc:
        raise SandboxError(f"Restricted worker failed: {type(exc).__name__}: {exc}") from exc
    finally:
        if job is not None:
            with suppress(OSError):
                win32api.CloseHandle(job)
        for handle in reversed(handles):
            with suppress(OSError):
                close_handle(handle)
        if token_handle:
            with suppress(OSError):
                close_handle(token_handle)
