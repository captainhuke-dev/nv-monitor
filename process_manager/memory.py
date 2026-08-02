"""Linux RAM accounting used by the Process Manager summary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path


MIB = 1024**2
GIB = 1024**3
MODEL_RSS_PROCESS_LIMIT = 10


def parse_meminfo(text: str) -> dict[str, int]:
    """Parse ``/proc/meminfo`` values into bytes (or raw counts without units)."""

    values: dict[str, int] = {}
    for line in text.splitlines():
        key, separator, remainder = line.partition(":")
        if not separator:
            continue
        fields = remainder.split()
        if not fields:
            continue
        try:
            value = int(fields[0])
        except ValueError:
            continue
        unit = fields[1].lower() if len(fields) > 1 else ""
        if unit == "kb":
            value *= 1024
        elif unit == "mb":
            value *= MIB
        elif unit == "gb":
            value *= GIB
        values[key.strip()] = value
    return values


def read_meminfo(path: str | Path = "/proc/meminfo") -> dict[str, int]:
    """Read kernel memory counters, returning an empty mapping on read failure."""

    try:
        return parse_meminfo(Path(path).read_text(encoding="ascii"))
    except (OSError, UnicodeError):
        return {}


def _nonnegative(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _mb(value: int) -> float:
    return round(value / MIB, 1)


def _gb(value: int) -> float:
    return round(value / GIB, 2)


def _category(
    *,
    key: str,
    label: str,
    value_bytes: int,
    scope: str,
    process_count: int,
    description: str,
) -> dict[str, object]:
    return {
        "key": key,
        "label": label,
        "bytes": value_bytes,
        "mb": _mb(value_bytes),
        "gb": _gb(value_bytes),
        "scope": scope,
        "process_count": process_count,
        "description": description,
    }


def build_memory_summary(
    meminfo: Mapping[str, int],
    processes: Sequence[object],
    *,
    model_rss_limit: int = MODEL_RSS_PROCESS_LIMIT,
) -> dict[str, object]:
    """Build the same active/cache breakdown shown by Dashboard 9000.

    ``Active other`` is a residual aggregate, not a disjoint list of PIDs:
    process RSS can overlap it. ``Cache`` is kernel reclaimable memory and has
    no process row to stop.
    """

    total_bytes = _nonnegative(meminfo.get("MemTotal", 0))
    free_bytes = min(total_bytes, _nonnegative(meminfo.get("MemFree", 0)))
    available_raw = meminfo.get("MemAvailable")
    available_bytes = _nonnegative(available_raw)

    if available_raw is not None and available_bytes > 0:
        available_bytes = min(total_bytes, available_bytes)
        used_bytes = max(0, total_bytes - available_bytes)
    else:
        available_bytes = 0
        used_bytes = max(0, total_bytes - free_bytes)

    cache_bytes = max(0, total_bytes - used_bytes - free_bytes)
    gpu_alloc_bytes = sum(_nonnegative(getattr(process, "gpu_memory_bytes", 0)) for process in processes)

    rss_processes = sorted(
        processes,
        key=lambda process: (
            -_nonnegative(getattr(process, "rss_bytes", 0)),
            _nonnegative(getattr(process, "pid", 0)),
        ),
    )[: max(0, model_rss_limit)]
    model_rss_bytes = sum(_nonnegative(getattr(process, "rss_bytes", 0)) for process in rss_processes)
    model_rss_pids = [
        _nonnegative(getattr(process, "pid", 0))
        for process in rss_processes
        if _nonnegative(getattr(process, "rss_bytes", 0)) > 0
    ]
    gpu_process_count = sum(
        1 for process in processes if _nonnegative(getattr(process, "gpu_memory_bytes", 0)) > 0
    )
    active_other_bytes = max(0, used_bytes - min(used_bytes, gpu_alloc_bytes))
    active_other_process_count = sum(
        1
        for process in processes
        if _nonnegative(getattr(process, "gpu_memory_bytes", 0)) == 0
        and _nonnegative(getattr(process, "rss_bytes", 0)) > 0
    )

    categories = [
        _category(
            key="gpu_alloc",
            label="GPU alloc",
            value_bytes=gpu_alloc_bytes,
            scope="process",
            process_count=gpu_process_count,
            description="GPU memory allocated by processes with GPU MEM > 0.",
        ),
        _category(
            key="model_rss",
            label="Model RSS*",
            value_bytes=model_rss_bytes,
            scope="process",
            process_count=len(model_rss_pids),
            description=(
                "RSS of the ten largest visible processes; file-backed model pages "
                "can overlap GPU and cache totals."
            ),
        ),
        _category(
            key="active_other",
            label="Active other",
            value_bytes=active_other_bytes,
            scope="aggregate",
            process_count=active_other_process_count,
            description=(
                "Active RAM not covered by GPU allocation. It is a residual total, "
                "so the candidate process rows are not an additive accounting."
            ),
        ),
        _category(
            key="cache",
            label="Cache",
            value_bytes=cache_bytes,
            scope="kernel",
            process_count=0,
            description="Reclaimable Linux page cache; no PID owns it and nothing can be killed for it.",
        ),
        _category(
            key="free",
            label="Free",
            value_bytes=free_bytes,
            scope="kernel",
            process_count=0,
            description="RAM currently reported free by the kernel.",
        ),
    ]

    return {
        "total_bytes": total_bytes,
        "total_mb": _mb(total_bytes),
        "total_gb": _gb(total_bytes),
        "used_bytes": used_bytes,
        "used_mb": _mb(used_bytes),
        "used_gb": _gb(used_bytes),
        "free_bytes": free_bytes,
        "free_mb": _mb(free_bytes),
        "free_gb": _gb(free_bytes),
        "available_bytes": available_bytes,
        "available_mb": _mb(available_bytes),
        "available_gb": _gb(available_bytes),
        "cache_bytes": cache_bytes,
        "cache_mb": _mb(cache_bytes),
        "cache_gb": _gb(cache_bytes),
        "gpu_alloc_bytes": gpu_alloc_bytes,
        "gpu_alloc_mb": _mb(gpu_alloc_bytes),
        "gpu_alloc_gb": _gb(gpu_alloc_bytes),
        "model_rss_bytes": model_rss_bytes,
        "model_rss_mb": _mb(model_rss_bytes),
        "model_rss_gb": _gb(model_rss_bytes),
        "active_other_bytes": active_other_bytes,
        "active_other_mb": _mb(active_other_bytes),
        "active_other_gb": _gb(active_other_bytes),
        "gpu_process_count": gpu_process_count,
        "model_rss_process_count": len(model_rss_pids),
        "active_other_process_count": active_other_process_count,
        "model_rss_pids": model_rss_pids,
        "categories": categories,
    }
