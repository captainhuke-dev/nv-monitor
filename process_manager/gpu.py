"""Optional GPU-process enrichment through nvidia-smi."""

from __future__ import annotations

import re
import subprocess


_MEMORY_RE = re.compile(r"^([0-9]+(?:\.[0-9]+)?)\s*([a-z]+)?$", re.IGNORECASE)
_UNIT_MULTIPLIERS = {
    "b": 1,
    "kb": 1024,
    "kib": 1024,
    "mb": 1024**2,
    "mib": 1024**2,
    "gb": 1024**3,
    "gib": 1024**3,
}


def _parse_memory_bytes(value: str) -> int | None:
    value = value.strip()
    if not value or value.lower() in {"[n/a]", "n/a", "na"}:
        return None
    match = _MEMORY_RE.match(value)
    if not match:
        return None
    number, unit = match.groups()
    multiplier = _UNIT_MULTIPLIERS.get((unit or "mib").lower())
    if multiplier is None:
        return None
    return int(float(number) * multiplier)


def parse_gpu_memory_csv(text: str) -> dict[int, int]:
    """Parse PID and memory rows, summing a PID seen on multiple GPUs."""

    result: dict[int, int] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = [field.strip() for field in line.split(",", maxsplit=1)]
        if len(fields) != 2:
            continue
        try:
            pid = int(fields[0])
        except ValueError:
            continue
        memory_bytes = _parse_memory_bytes(fields[1])
        if memory_bytes is None:
            continue
        result[pid] = result.get(pid, 0) + memory_bytes
    return result


def gpu_memory_by_pid(timeout_seconds: float = 1.5) -> dict[int, int]:
    """Read compute-process GPU memory without allowing the command to hang."""

    command = (
        "nvidia-smi",
        "--query-compute-apps=pid,used_gpu_memory",
        "--format=csv,noheader,nounits",
    )
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if completed.returncode != 0:
        return {}
    return parse_gpu_memory_csv(completed.stdout)
