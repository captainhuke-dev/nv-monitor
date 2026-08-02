"""Stable process records and system-process classification."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence


class SystemReason(str, Enum):
    ROOT = "root"
    PID1 = "pid1"
    KERNEL_THREAD = "kernel_thread"
    SYSTEMD_SERVICE = "systemd_service"

    @property
    def label(self) -> str:
        return {
            SystemReason.ROOT: "root-owned process",
            SystemReason.PID1: "init process (PID 1)",
            SystemReason.KERNEL_THREAD: "kernel thread",
            SystemReason.SYSTEMD_SERVICE: "systemd service",
        }[self]


@dataclass(frozen=True)
class ProcessClassification:
    is_system: bool
    reasons: tuple[SystemReason, ...]
    protected: bool

    @property
    def reason_labels(self) -> tuple[str, ...]:
        return tuple(reason.label for reason in self.reasons)


@dataclass(frozen=True)
class ProcessRecord:
    pid: int
    ppid: int
    uid: int | None
    user: str
    name: str
    cmdline: str
    status: str
    cpu_percent: float
    rss_bytes: int
    gpu_memory_bytes: int
    create_time: float
    pgid: int | None
    classification: ProcessClassification

    @property
    def is_system(self) -> bool:
        return self.classification.is_system

    @property
    def system_reasons(self) -> tuple[SystemReason, ...]:
        return self.classification.reasons

    def to_dict(self) -> dict[str, object]:
        return {
            "pid": self.pid,
            "ppid": self.ppid,
            "uid": self.uid,
            "user": self.user,
            "name": self.name,
            "cmdline": self.cmdline,
            "status": self.status,
            "cpu_percent": round(self.cpu_percent, 2),
            "rss_bytes": self.rss_bytes,
            "gpu_memory_bytes": self.gpu_memory_bytes,
            "create_time": self.create_time,
            "pgid": self.pgid,
            "classification": "SYSTEM" if self.classification.is_system else "USER",
            "is_system": self.classification.is_system,
            "system_reasons": [reason.value for reason in self.classification.reasons],
            "system_reason_labels": list(self.classification.reason_labels),
            "protected": self.classification.protected,
        }


def _is_systemd_cgroup(cgroup: str) -> bool:
    return any(
        marker in cgroup
        for marker in ("/system.slice/", "/system.slice", "/init.scope", ":/init.scope")
    )


def classify_process(
    *,
    pid: int,
    uid: int | None,
    name: str,
    cmdline: Sequence[str],
    cgroup: str,
) -> ProcessClassification:
    """Classify a process using observable Linux ownership/lifecycle signals."""

    reasons: list[SystemReason] = []
    is_kernel_thread = name.startswith("[") and name.endswith("]") and not cmdline

    if pid == 1:
        reasons.append(SystemReason.PID1)
    if is_kernel_thread:
        reasons.append(SystemReason.KERNEL_THREAD)
    if uid == 0:
        reasons.append(SystemReason.ROOT)
    if _is_systemd_cgroup(cgroup):
        reasons.append(SystemReason.SYSTEMD_SERVICE)

    return ProcessClassification(
        is_system=bool(reasons),
        reasons=tuple(reasons),
        protected=pid == 1 or is_kernel_thread,
    )
