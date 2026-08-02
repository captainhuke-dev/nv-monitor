"""Linux process inventory collection."""

from __future__ import annotations

import os
import pwd
from collections.abc import Mapping, Set
from pathlib import Path

import psutil

from .gpu import gpu_memory_by_pid
from .models import ProcessRecord, classify_process


COMMAND_DISPLAY_LIMIT = 4096


def read_cgroup(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except (OSError, UnicodeError):
        return ""


def _username(uid: int | None) -> str:
    if uid is None:
        return "?"
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def _display_command(name: str, cmdline: tuple[str, ...]) -> str:
    command = " ".join(cmdline) if cmdline else name
    if len(command) > COMMAND_DISPLAY_LIMIT:
        return command[: COMMAND_DISPLAY_LIMIT - 1] + "…"
    return command


def collect_processes(
    gpu_lookup: Mapping[int, int] | None = None,
    skip_pids: Set[int] = frozenset(),
) -> list[ProcessRecord]:
    """Collect every process readable at the time of the scan."""

    if gpu_lookup is None:
        gpu_lookup = gpu_memory_by_pid()

    records: list[ProcessRecord] = []
    for process in psutil.process_iter():
        try:
            pid = process.pid
            if pid in skip_pids:
                continue
            with process.oneshot():
                name = process.name()
                ppid = process.ppid()
                uid = process.uids().real
                cmdline = tuple(process.cmdline())
                status = process.status()
                cpu_percent = process.cpu_percent(interval=None)
                rss_bytes = process.memory_info().rss
                create_time = process.create_time()
            cgroup = read_cgroup(f"/proc/{pid}/cgroup")
            classification = classify_process(
                pid=pid,
                uid=uid,
                name=name,
                cmdline=cmdline,
                cgroup=cgroup,
            )
            try:
                pgid = os.getpgid(pid)
            except (OSError, ProcessLookupError):
                pgid = None
        except (
            psutil.AccessDenied,
            psutil.NoSuchProcess,
            psutil.ZombieProcess,
            OSError,
            ProcessLookupError,
        ):
            continue

        records.append(
            ProcessRecord(
                pid=pid,
                ppid=ppid,
                uid=uid,
                user=_username(uid),
                name=name,
                cmdline=_display_command(name, cmdline),
                status=status,
                cpu_percent=cpu_percent,
                rss_bytes=rss_bytes,
                gpu_memory_bytes=int(gpu_lookup.get(pid, 0)),
                create_time=create_time,
                pgid=pgid,
                classification=classification,
            )
        )

    return sorted(records, key=lambda record: record.pid)
