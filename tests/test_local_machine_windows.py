"""Machine facts on Windows: no console window flashes, and a readable processor name."""

from __future__ import annotations

import subprocess
import sys
import types

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


def test_windows_processor_name_comes_from_the_registry(monkeypatch):
    fake = types.SimpleNamespace(
        HKEY_LOCAL_MACHINE=object(),
        OpenKey=lambda root, path: ("key", path),
        QueryValueEx=lambda key, name: ("Intel(R) Core(TM)  i7-12700H  ", 1),
        CloseKey=lambda key: None,
    )
    monkeypatch.setitem(sys.modules, "winreg", fake)
    assert local_machine._windows_processor() == "Intel(R) Core(TM) i7-12700H"
    monkeypatch.setitem(sys.modules, "winreg", None)  # not Windows: import fails
    assert local_machine._windows_processor() == ""
