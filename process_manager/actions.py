"""Guarded process-stop policy and audit logging."""

from __future__ import annotations

import json
import math
import os
import signal
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import psutil

from .collector import read_cgroup
from .models import ProcessClassification, classify_process


CREATE_TIME_TOLERANCE = 0.001


@dataclass(frozen=True)
class StopRequest:
    pid: int
    expected_create_time: float | None
    confirm_system: bool = False
    force: bool = False


@dataclass(frozen=True)
class ProcessTarget:
    pid: int
    create_time: float
    classification: ProcessClassification


@dataclass(frozen=True)
class StopResult:
    ok: bool
    pid: int
    signal: str | None
    status: str
    message: str
    error_code: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "pid": self.pid,
            "signal": self.signal,
            "status": self.status,
            "message": self.message,
            "error_code": self.error_code,
        }


def _rejected(pid: int, code: str, message: str) -> StopResult:
    return StopResult(
        ok=False,
        pid=pid,
        signal=None,
        status="rejected",
        message=message,
        error_code=code,
    )


def validate_stop_request(
    request: StopRequest,
    target: ProcessTarget,
    *,
    manager_pid: int,
) -> StopResult:
    """Validate an action against a freshly inspected process target."""

    if request.expected_create_time is None:
        return _rejected(
            request.pid,
            "missing_fingerprint",
            "expected process creation time is required",
        )
    if target.pid == manager_pid:
        return _rejected(request.pid, "manager_process", "cannot stop the process manager")
    if not math.isclose(
        request.expected_create_time,
        target.create_time,
        abs_tol=CREATE_TIME_TOLERANCE,
    ):
        return _rejected(
            request.pid,
            "pid_reused",
            "process identity changed since the list was rendered",
        )
    if target.classification.protected:
        return _rejected(
            request.pid,
            "protected_process",
            "PID 1 and kernel threads are protected",
        )
    if target.classification.is_system and not request.confirm_system:
        return _rejected(
            request.pid,
            "system_confirmation_required",
            "explicit system-process confirmation is required",
        )
    return StopResult(
        ok=True,
        pid=request.pid,
        signal=None,
        status="approved",
        message="process identity and stop policy approved",
    )


def _audit_path_ready(path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8"):
            pass
    except OSError:
        return False
    return True


def _append_audit(path: Path, request: StopRequest, result: StopResult) -> bool:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": "stop_process",
        "pid": request.pid,
        "expected_create_time": request.expected_create_time,
        "confirm_system": request.confirm_system,
        "force": request.force,
        "outcome": result.status if result.ok else "rejected",
        "signal": result.signal,
        "error_code": result.error_code,
        "message": result.message,
    }
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
    except OSError:
        return False
    return True


def _inspect_target(process: psutil.Process) -> ProcessTarget:
    with process.oneshot():
        pid = process.pid
        uid = process.uids().real
        name = process.name()
        cmdline = tuple(process.cmdline())
        create_time = process.create_time()
    classification = classify_process(
        pid=pid,
        uid=uid,
        name=name,
        cmdline=cmdline,
        cgroup=read_cgroup(f"/proc/{pid}/cgroup"),
    )
    return ProcessTarget(
        pid=pid,
        create_time=create_time,
        classification=classification,
    )


def stop_process(
    request: StopRequest,
    audit_log_path: str | Path,
    manager_pid: int | None = None,
) -> StopResult:
    """Stop exactly one process after revalidating its identity and policy."""

    if manager_pid is None:
        manager_pid = os.getpid()
    audit_path = Path(audit_log_path)

    if not _audit_path_ready(audit_path):
        return _rejected(
            request.pid,
            "audit_log_failure",
            "audit log is not writable; no signal was sent",
        )

    if request.expected_create_time is None:
        result = _rejected(
            request.pid,
            "missing_fingerprint",
            "expected process creation time is required",
        )
        _append_audit(audit_path, request, result)
        return result

    try:
        process = psutil.Process(request.pid)
        target = _inspect_target(process)
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        result = _rejected(request.pid, "process_gone", "process no longer exists")
        _append_audit(audit_path, request, result)
        return result
    except psutil.AccessDenied:
        result = _rejected(request.pid, "permission_denied", "cannot inspect process")
        _append_audit(audit_path, request, result)
        return result

    result = validate_stop_request(request, target, manager_pid=manager_pid)
    if not result.ok:
        _append_audit(audit_path, request, result)
        return result

    selected_signal = signal.SIGKILL if request.force else signal.SIGTERM
    selected_name = selected_signal.name
    try:
        if request.force:
            process.kill()
        else:
            process.terminate()
    except psutil.NoSuchProcess:
        result = _rejected(request.pid, "process_gone", "process exited before signaling")
    except psutil.AccessDenied:
        result = _rejected(request.pid, "permission_denied", "signal permission denied")
    else:
        result = StopResult(
            ok=True,
            pid=request.pid,
            signal=selected_name,
            status="signal_sent",
            message=f"{selected_name} sent to PID {request.pid}",
        )
    _append_audit(audit_path, request, result)
    return result
