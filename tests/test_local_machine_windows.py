"""Machine facts on Windows: the probes run without a console window flashing."""

from __future__ import annotations

import subprocess
import sys

from coworker import procutil
from coworker.providers import local_machine


def test_console_programs_run_without_a_window_on_windows(monkeypatch):
    # Upstream keeps a `_NO_WINDOW` dict in local_machine.py; this fork routes every
    # spawn's creation flags through `procutil.popen_kwargs()` (enforced by
    # tests/test_subprocess_hygiene.py), so the probe is checked to splat exactly that.
    seen = {}

    def fake_run(args, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(args, 0, stdout="24564\n", stderr="")

    monkeypatch.setattr(local_machine.subprocess, "run", fake_run)
    monkeypatch.setattr(local_machine.shutil, "which", lambda name: "C:/nvidia-smi.exe")
    assert local_machine.nvidia_gpu_memory_bytes() == 24564 * 1024 * 1024
    for key, value in procutil.popen_kwargs().items():
        assert seen[key] == value
    if sys.platform == "win32":
        assert seen["creationflags"] & procutil.CREATE_NO_WINDOW
    else:
        assert "creationflags" not in seen
