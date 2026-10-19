"""What this machine can give a local model: the memory models run in, and the context
size that memory supports.

A local model's context window is a trade: every token of context costs memory while the
model is loaded, and a window the machine cannot hold either fails to load or crawls. The
model's trained maximum (131K to 1M on current models) is the wrong default; the machine
decides. Ollama does the same on its side (4K under 24 GiB of GPU memory, 32K to 48 GiB,
256K above) but its lowest tier is smaller than OpenWorker's first request, so OpenWorker
sets the window itself (ollama_context.py) and uses the tiers here.

Memory is read once per process: it does not change while OpenWorker runs. An NVIDIA card
reports its own memory through `nvidia-smi`; everything else (Apple silicon, CPU-only
machines, DGX Spark with its shared memory, where nvidia-smi reports none) uses system
memory, which is what those models load into.
"""

from __future__ import annotations

import functools
import os
import shutil
import subprocess
import sys
from typing import Optional

from .. import procutil

GB = 1024**3

# Context tiers by the memory models run in. Each step keeps the KV cache well inside
# what is left beside a 20 to 30 GB model: measured on a 30B Q4 model, 128K of context
# costs about 13 GB on top of the weights.
CONTEXT_TIERS: tuple[tuple[int, int], ...] = (
    (16 * GB, 16_384),
    (32 * GB, 32_768),
    (64 * GB, 65_536),
)
CONTEXT_ABOVE_TIERS = 131_072

# Below this, OpenWorker's own first request (system prompt plus tools, ~6K tokens) does
# not fit with room to work.
MIN_AGENT_CONTEXT = 16_384


def system_memory_bytes() -> Optional[int]:
    """Total system memory, or None when it cannot be read."""
    try:
        if sys.platform == "win32":
            import ctypes

            class _Status(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _Status()
            status.dwLength = ctypes.sizeof(_Status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
                return int(status.ullTotalPhys)
            return None
        pages = os.sysconf("SC_PHYS_PAGES")
        page = os.sysconf("SC_PAGE_SIZE")
        if pages > 0 and page > 0:
            return int(pages) * int(page)
    except (AttributeError, ValueError, OSError):
        pass
    return None


def nvidia_gpu_memory_bytes() -> Optional[int]:
    """Memory of the largest NVIDIA card `nvidia-smi` reports, or None: no tool, no
    card, or a card with no memory of its own (DGX Spark answers "N/A")."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    out = _run([exe, "--query-gpu=memory.total", "--format=csv,noheader,nounits"])
    best = 0
    for line in out.splitlines():
        try:
            best = max(best, int(float(line.strip())) * 1024 * 1024)
        except ValueError:
            continue
    return best or None


def _run(args: list[str]) -> str:
    # Windows: a console program started from the desktop app would flash a black window.
    # This fork keeps every spawn's creation flags in one place (procutil.popen_kwargs);
    # tests/test_subprocess_hygiene.py enforces it.
    try:
        return subprocess.run(
            args, capture_output=True, text=True, timeout=5, check=False,
            **procutil.popen_kwargs(),
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


@functools.lru_cache(maxsize=1)
def model_memory_bytes() -> Optional[int]:
    """The memory a local model loads into on this machine."""
    return nvidia_gpu_memory_bytes() or system_memory_bytes()


def recommended_context(
    model_max: Optional[int], memory_bytes: Optional[int]
) -> Optional[int]:
    """The context window to run a local model at, from the memory available.

    None when the memory is unknown: the caller keeps its own default. Never above the
    model's own maximum, never below the smallest tier."""
    if memory_bytes is None:
        return None
    tier = CONTEXT_ABOVE_TIERS
    for limit, ctx in CONTEXT_TIERS:
        if memory_bytes < limit:
            tier = ctx
            break
    if model_max:
        tier = min(tier, model_max)
    return max(tier, min(MIN_AGENT_CONTEXT, model_max or MIN_AGENT_CONTEXT))
