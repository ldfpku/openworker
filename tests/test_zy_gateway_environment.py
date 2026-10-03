from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "packaging" / "Import-ZyGatewayEnvironment.ps1"
_PWSH = shutil.which("pwsh")
pytestmark = pytest.mark.skipif(_PWSH is None, reason="PowerShell 7 is unavailable")

_VALID = (
    "# administrator environment\n"
    'ZY_AI_GATEWAY="fake_management_token"\n'
    "AIG_TOKEN='fake_run_token'\n"
    f"CLOUDFLARE_ACCOUNT_ID={'a' * 32}\n"
    f"CLOUDFLARE_ZONE_ID={'b' * 32}\n"
)


def test_template_matches_supported_environment_variables() -> None:
    template = (_ROOT / ".env.example").read_text(encoding="utf-8")
    entries = [
        line.split("=", 1)
        for line in template.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    loader = _SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"(?m)^\$allowedNames = @\((.*)\)$", loader)
    assert match is not None
    supported = set(re.findall(r"'([A-Z_]+)'", match.group(1)))
    assert {name for name, _ in entries} == supported
    assert len(entries) == len(supported) == 4
    assert all(value.startswith("REPLACE_WITH_") for _, value in entries)


def _run_import(tmp_path: Path, contents: str) -> subprocess.CompletedProcess[str]:
    env_path = tmp_path / ".env"
    env_path.write_text(contents, encoding="utf-8")
    script_path = str(_SCRIPT).replace("'", "''")
    input_path = str(env_path).replace("'", "''")
    command = (
        "$ErrorActionPreference='Stop'; "
        "try { "
        f". '{script_path}' -Path '{input_path}'; "
        "} catch { "
        "Write-Output ('IMPORT_ERROR: '+$_.Exception.Message); "
        "if ($env:CLOUDFLARE_API_TOKEN -cne 'before-import' "
        "-or $env:AIG_TOKEN -cne 'before-run') { exit 2 }; "
        "exit 1 "
        "}; "
        "@{"
        "management=($env:CLOUDFLARE_API_TOKEN -ceq 'fake_management_token');"
        "management_alias=($env:ZY_AI_GATEWAY -ceq 'fake_management_token');"
        "run=($env:AIG_TOKEN -ceq 'fake_run_token');"
        "account=($env:CLOUDFLARE_ACCOUNT_ID -ceq ('a'*32));"
        "zone=($env:CLOUDFLARE_ZONE_ID -ceq ('b'*32))"
        "} | ConvertTo-Json -Compress"
    )
    env = dict(os.environ)
    env["CLOUDFLARE_API_TOKEN"] = "before-import"
    env["AIG_TOKEN"] = "before-run"
    assert _PWSH is not None
    return subprocess.run(
        [_PWSH, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=30,
    )


def test_import_maps_management_and_preserves_run_separation(tmp_path: Path) -> None:
    result = _run_import(tmp_path, _VALID)
    assert result.returncode == 0, result.stdout + result.stderr
    assert all(json.loads(result.stdout.splitlines()[-1]).values())
    assert "fake_management_token" not in result.stdout + result.stderr
    assert "fake_run_token" not in result.stdout + result.stderr
    assert os.environ.get("CLOUDFLARE_API_TOKEN") != "fake_management_token"


@pytest.mark.parametrize(
    "contents,error",
    [
        (_VALID.replace("fake_run_token", ""), "nonempty"),
        (_VALID.replace("fake_run_token", "REPLACE_WITH_ZY_RUN_TOKEN"), "nonempty"),
        (_VALID.replace("fake_run_token", "fake_management_token"), "separate"),
        (_VALID + "AIG_TOKEN=duplicate_sensitive_token\n", "Duplicate"),
        (_VALID + "CF_AIG_TOKEN=retired_sensitive_token\n", "Unsupported"),
        (_VALID + "not an assignment\n", "syntax"),
        (_VALID.replace("a" * 32, "invalid-account"), "hexadecimal"),
        (_VALID.replace("b" * 32, "invalid-zone"), "hexadecimal"),
        (_VALID.replace("'fake_run_token'", "'fake_run_token"), "Unpaired"),
        (_VALID.replace("AIG_TOKEN='fake_run_token'\n", ""), "Missing required"),
        (_VALID.replace("'fake_run_token'", "${OTHER_SECRET}"), "literal"),
        (_VALID.replace("'fake_run_token'", "fake_run_token # comment"), "literal"),
    ],
)
def test_invalid_environment_fails_without_mutating_process(
    tmp_path: Path, contents: str, error: str
) -> None:
    result = _run_import(tmp_path, contents)
    assert result.returncode == 1, result.stdout + result.stderr
    assert error in result.stdout
    for token in (
        "fake_management_token",
        "fake_run_token",
        "duplicate_sensitive_token",
        "retired_sensitive_token",
    ):
        assert token not in result.stdout + result.stderr
