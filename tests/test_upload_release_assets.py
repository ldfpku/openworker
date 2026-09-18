"""packaging/upload_release_assets.py — the release job's serial, idempotent uploader.

Written after v0.6.2 (2026-09-17), where the release job failed twice because
uploads.github.com returned a transient HTTP 500 while `softprops/action-gh-release`
pushed 14 files at once — and each re-run made it worse, because that action defaults to
`overwrite_files: true` and deletes the assets that DID land before starting over.

The single invariant everything here protects:

    an asset whose state is "uploaded" is NEVER deleted.

`FakeGh.delete_asset` below raises on the spot if the code under test ever breaks it, so
every case in this file enforces it, not just the ones that say so in their name.

Nothing here touches the network or the real `gh`: the uploader takes its GitHub client,
its clock and its sleep function by injection, so a 30-minute timeout and a five-minute
backoff cost zero wall-clock seconds.
"""

from __future__ import annotations

import ast
import importlib.util
import itertools
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, relative: str):
    # Same dance as tests/test_version.py: the repo's `packaging/` directory is NOT the
    # `packaging` PyPI distribution (installed in this venv as a transitive dependency),
    # so `import packaging.upload_release_assets` would resolve to the wrong thing. Load
    # by file path under a private module name instead.
    spec = importlib.util.spec_from_file_location(name, _REPO_ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    # Register before exec: @dataclass resolves `cls.__module__` through sys.modules
    # while the class body is being processed, and blows up on a module that is not
    # there yet. (test_version.py's script has no dataclasses, hence no such line.)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


mod = _load("_ow_upload_release_assets", "packaging/upload_release_assets.py")
manifest_mod = _load("_ow_make_update_manifest_probe", "packaging/make_update_manifest.py")

REPO = "ldfpku/openworker"
TAG = "v1.2.3"
VERSION = "1.2.3"
RELEASE_ID = 42


# --------------------------------------------------------------------------------------
# fixtures: a local dist/ and a fake GitHub
# --------------------------------------------------------------------------------------


def _sig_text(name: str) -> str:
    return "dW50cnVzdGVkIGNvbW1lbnQ6" + name.replace(".", "_")


def build_dist(root: Path, *, version: str = VERSION, tag: str = TAG, repo: str = REPO) -> Path:
    """A dist/ with exactly the 14 expected files and a well-formed latest.json."""
    dist = root / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    for name in mod.expected_assets(version):
        if name == mod.MANIFEST_ASSET:
            continue
        if name.endswith(".sig"):
            (dist / name).write_text(_sig_text(name) + "\n", encoding="utf-8")
        else:
            (dist / name).write_bytes((name + "-payload").encode("utf-8") * 8)
    write_manifest(dist, version=version, tag=tag, repo=repo)
    return dist


def write_manifest(dist: Path, *, version: str = VERSION, tag: str = TAG, repo: str = REPO) -> None:
    """Byte-shape copy of what packaging/make_update_manifest.py writes."""
    platforms = {}
    for asset, platform in manifest_mod.ARTIFACTS.items():
        platforms[platform] = {
            "signature": (dist / (asset + ".sig")).read_text(encoding="utf-8").strip(),
            "url": f"https://github.com/{repo}/releases/download/{tag}/{asset}",
        }
    payload = {
        "version": version,
        "notes": f"OpenWorker {version}",
        "pub_date": "2026-09-18T00:00:00Z",
        "platforms": platforms,
    }
    (dist / mod.MANIFEST_ASSET).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def patch_manifest(dist: Path, mutate) -> None:
    payload = json.loads((dist / mod.MANIFEST_ASSET).read_text(encoding="utf-8"))
    mutate(payload)
    (dist / mod.MANIFEST_ASSET).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def remote_assets(
    dist: Path,
    *,
    version: str = VERSION,
    omit: tuple[str, ...] = (),
    starter: tuple[str, ...] = (),
    digest_override: dict[str, str] | None = None,
    extra: tuple[str, ...] = (),
) -> list[dict]:
    """The assets API's view of a release that already holds (some of) dist/."""
    ids = itertools.count(1000)
    out: list[dict] = []
    for name in mod.expected_assets(version):
        if name in omit:
            continue
        settled = name not in starter
        digest = mod.sha256_file(dist / name) if settled else ""
        if digest_override and name in digest_override:
            digest = digest_override[name]
        out.append(
            {
                "id": next(ids),
                "name": name,
                "state": "uploaded" if settled else "starter",
                "size": (dist / name).stat().st_size,
                "digest": digest,
            }
        )
    for name in extra:
        out.append(
            {"id": next(ids), "name": name, "state": "uploaded", "size": 9, "digest": "sha256:" + "0" * 64}
        )
    return out


class FakeClock:
    """A clock that only moves when the code under test sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


@dataclass
class Behavior:
    """What one `gh release upload` invocation does, in fake-clock seconds.

    effect: "upload" (bytes land), "starter" (a half-finished stub is left), "nothing".
    exit_at: None means the process never exits on its own (the proxy-hang case).
    """

    effect: str = "upload"
    effect_at: float = 0.0
    exit_at: float | None = 0.0
    returncode: int = 0
    digest: str | None = None


class FakeUpload:
    def __init__(self, gh: "FakeGh", name: str, behavior: Behavior) -> None:
        self.gh = gh
        self.name = name
        self.behavior = behavior
        self.started = gh.clock.monotonic()
        self.applied = False
        self.stopped = False
        self.returncode: int | None = None

    def _elapsed(self) -> float:
        return self.gh.clock.monotonic() - self.started

    def tick(self) -> None:
        if self.stopped or self.applied or self._elapsed() < self.behavior.effect_at:
            return
        self.applied = True
        if self.behavior.effect == "upload":
            self.gh.put_asset(
                self.name, "uploaded", self.behavior.digest or self.gh.digests[self.name]
            )
        elif self.behavior.effect == "starter":
            self.gh.put_asset(self.name, "starter", "")

    def poll(self) -> int | None:
        self.tick()
        if self.behavior.exit_at is not None and self._elapsed() >= self.behavior.exit_at:
            self.returncode = self.behavior.returncode
            return self.behavior.returncode
        return None

    def stop(self) -> None:
        self.stopped = True
        self.gh.stopped.append(self.name)

    def output_tail(self, lines: int = 20) -> str:
        return "(fake gh output)"

    def close(self) -> None:
        pass


class FakeGh:
    """In-memory GitHub. Fails the test the moment an uploaded asset is deleted."""

    def __init__(
        self,
        dist: Path,
        *,
        clock: FakeClock,
        version: str = VERSION,
        assets: list[dict] | None = None,
        releases: list[dict] | None = None,
        behaviors: dict[str, list[Behavior]] | None = None,
        promote_on_get: tuple[str, ...] = (),
        on_list_assets=None,
    ) -> None:
        self.repo = REPO
        self.clock = clock
        self.dist = dist
        self.digests = {n: mod.sha256_file(dist / n) for n in mod.expected_assets(version) if (dist / n).exists()}
        self.releases = releases if releases is not None else [
            {"id": RELEASE_ID, "tag_name": TAG, "draft": True}
        ]
        self.assets: dict[int, dict] = {a["id"]: dict(a) for a in (assets or [])}
        self.behaviors = {k: list(v) for k, v in (behaviors or {}).items()}
        self.promote_on_get = set(promote_on_get)
        # Called with this FakeGh at the top of every list_assets, so a test can make
        # api.github.com misbehave at a precise moment: raise GhError, or rewrite an
        # asset the way GitHub would if the draft were filled by a different build.
        self.on_list_assets = on_list_assets
        self.list_calls = 0
        self._ids = itertools.count(9000)
        self._live: list[FakeUpload] = []
        self.uploads: list[str] = []
        self.deleted: list[tuple[str, str]] = []
        self.deleted_releases: list[int] = []
        self.illegal_deletes: list[str] = []
        self.stopped: list[str] = []

    # -- internals ---------------------------------------------------------------------

    def _tick(self) -> None:
        for handle in list(self._live):
            handle.tick()

    def put_asset(self, name: str, state: str, digest: str) -> dict:
        asset = {
            "id": next(self._ids),
            "name": name,
            "state": state,
            "size": (self.dist / name).stat().st_size if (self.dist / name).exists() else 0,
            "digest": digest,
        }
        self.assets[asset["id"]] = asset
        return asset

    # -- reads -------------------------------------------------------------------------

    def list_releases(self) -> list[dict]:
        return [dict(r) for r in self.releases]

    def list_assets(self, release_id: int) -> list[dict]:
        assert release_id == RELEASE_ID or any(r["id"] == release_id for r in self.releases)
        self.list_calls += 1
        if self.on_list_assets is not None:
            self.on_list_assets(self)
        self._tick()
        return [dict(a) for a in self.assets.values()]

    def get_asset(self, asset_id: int) -> dict | None:
        self._tick()
        asset = self.assets.get(asset_id)
        if asset is None:
            return None
        if asset["name"] in self.promote_on_get and asset["state"] != "uploaded":
            # The listing was stale: this half-finished record actually finished.
            asset["state"] = "uploaded"
            asset["digest"] = self.digests[asset["name"]]
        return dict(asset)

    def get_release(self, release_id: int) -> dict | None:
        for release in self.releases:
            if release["id"] == release_id:
                return dict(release)
        return None

    def list_tag_refs(self, prefix: str) -> list[dict]:
        return []

    # -- writes ------------------------------------------------------------------------

    def delete_asset(self, asset_id: int) -> None:
        asset = self.assets.get(asset_id)
        if asset is None:
            return  # a 404 is a successful delete
        if asset["state"] == "uploaded":
            self.illegal_deletes.append(asset["name"])
            raise AssertionError(
                f"INVARIANT BROKEN: the uploader deleted uploaded asset {asset['name']!r}"
            )
        del self.assets[asset_id]
        self.deleted.append((asset["name"], asset["state"]))

    def delete_release(self, release_id: int) -> None:
        self.deleted_releases.append(release_id)
        self.releases = [r for r in self.releases if r["id"] != release_id]

    def start_upload(self, tag: str, path: Path) -> FakeUpload:
        assert tag == TAG
        name = Path(path).name
        self.uploads.append(name)
        queue = self.behaviors.get(name)
        behavior = queue.pop(0) if queue else Behavior()
        handle = FakeUpload(self, name, behavior)
        self._live.append(handle)
        return handle


def run_upload(gh: FakeGh, clock: FakeClock, dist: Path, **kwargs):
    kwargs.setdefault("max_attempts", 6)
    kwargs.setdefault("attempt_timeout", 1800.0)
    kwargs.setdefault("poll_interval", 15.0)
    return mod.run_upload(
        gh,
        tag=TAG,
        version=VERSION,
        dist=dist,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        rand=lambda: 0.0,
        log=lambda message: None,
        **kwargs,
    )


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    return build_dist(tmp_path)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


# --------------------------------------------------------------------------------------
# 1-3: the three states a release can be in when the job starts
# --------------------------------------------------------------------------------------


def test_fresh_draft_uploads_all_fourteen_with_the_manifest_last(dist, clock):
    gh = FakeGh(dist, clock=clock)
    run = run_upload(gh, clock, dist)

    assert run.ok, run.errors
    assert (run.uploaded, run.skipped) == (14, 0)
    assert len(run.results) == 14
    # Spelled out rather than derived from upload_order(): an expectation computed by the
    # code under test asserts nothing at all.
    assert gh.uploads == [
        "OpenWorker-macos-arm64.app.tar.gz",
        "OpenWorker-macos-arm64.app.tar.gz.sig",
        "OpenWorker-macos-arm64.dmg",
        "OpenWorker-macos-x64.app.tar.gz",
        "OpenWorker-macos-x64.app.tar.gz.sig",
        "OpenWorker-macos-x64.dmg",
        "OpenWorker-windows-setup.exe",
        "OpenWorker-windows-setup.exe.sig",
        "OpenWorker-windows.msi",
        "OpenWorker_1.2.3_aarch64.dmg",
        "OpenWorker_1.2.3_x64-setup.exe",
        "OpenWorker_1.2.3_x64_en-US.msi",
        "OpenWorker_1.2.3_x86_64.dmg",
        "latest.json",
    ]
    assert gh.deleted == []
    assert {r.action for r in run.results} == {"uploaded"}


def test_the_manifest_goes_last_even_when_sorting_alone_would_not_put_it_there():
    # latest.json is what shipped apps poll: it must never advertise a payload that has
    # not landed yet. With the real asset names every other name happens to start with an
    # uppercase 'O', which sorts before lowercase 'l' — so the fresh-draft test above
    # cannot tell `upload_order` apart from a plain `sorted()`. This one can.
    assert mod.upload_order(["zzz.bin", "latest.json"]) == ["zzz.bin", "latest.json"]
    assert mod.upload_order(["latest.json", "zzz.bin", "aaa.bin"]) == [
        "aaa.bin",
        "zzz.bin",
        "latest.json",
    ]
    assert mod.upload_order(["latest.json"]) == ["latest.json"]
    assert mod.upload_order(["b", "a"]) == ["a", "b"]


def test_rerun_over_a_complete_release_uploads_and_deletes_nothing(dist, clock):
    gh = FakeGh(dist, clock=clock, assets=remote_assets(dist))
    run = run_upload(gh, clock, dist)

    assert run.ok, run.errors
    assert (run.uploaded, run.skipped) == (0, 14)
    assert gh.uploads == []
    assert gh.deleted == []


def test_partial_release_fills_the_gaps_and_deletes_only_half_finished_records(dist, clock):
    missing = ("OpenWorker-macos-x64.dmg", "OpenWorker-windows.msi", "latest.json")
    half_done = ("OpenWorker-windows-setup.exe", "OpenWorker-windows-setup.exe.sig")
    gh = FakeGh(dist, clock=clock, assets=remote_assets(dist, omit=missing, starter=half_done))

    run = run_upload(gh, clock, dist)

    assert run.ok, run.errors
    assert gh.uploads == [
        "OpenWorker-macos-x64.dmg",
        "OpenWorker-windows-setup.exe",
        "OpenWorker-windows-setup.exe.sig",
        "OpenWorker-windows.msi",
        "latest.json",
    ]
    assert sorted(gh.deleted) == sorted((name, "starter") for name in half_done)
    assert (run.uploaded, run.skipped) == (5, 9)
    by_name = {r.name: r.action for r in run.results}
    assert by_name["OpenWorker-windows-setup.exe"] == "replaced-stale"
    assert by_name["OpenWorker-macos-x64.dmg"] == "uploaded"
    assert by_name["OpenWorker-macos-arm64.dmg"] == "skipped"


# --------------------------------------------------------------------------------------
# 4, 11: preflight refuses to start rather than half-fix a bad draft
# --------------------------------------------------------------------------------------


def test_preflight_refuses_a_draft_holding_another_builds_bytes(dist, clock):
    poisoned = {"OpenWorker-macos-arm64.dmg": "sha256:" + "b" * 64}
    gh = FakeGh(dist, clock=clock, assets=remote_assets(dist, digest_override=poisoned))

    run = run_upload(gh, clock, dist)

    assert not run.ok
    assert any("different digest" in e for e in run.errors)
    assert gh.uploads == []
    assert gh.deleted == []
    assert gh.illegal_deletes == []


def test_a_mismatching_digest_discovered_after_preflight_still_aborts(dist, clock):
    # Preflight lets an uploaded asset with an EMPTY digest through (GitHub fills the
    # field a moment after the state flips), so the mismatch is caught later, by
    # _judge_uploaded, on the per-file pass. Nothing may be uploaded or deleted after it.
    name = "OpenWorker-windows.msi"
    wrong = "sha256:" + "d" * 64

    def fill_in_the_wrong_digest(gh):
        if gh.list_calls < 2:
            return  # let preflight see the empty digest
        for asset in gh.assets.values():
            if asset["name"] == name:
                asset["digest"] = wrong

    gh = FakeGh(
        dist,
        clock=clock,
        assets=remote_assets(dist, digest_override={name: ""}),
        on_list_assets=fill_in_the_wrong_digest,
    )

    run = run_upload(gh, clock, dist)

    assert not run.ok
    blob = "\n".join(run.errors)
    assert name in blob
    assert wrong in blob
    assert mod.sha256_file(dist / name) in blob
    assert gh.uploads == []
    assert gh.deleted == []
    assert gh.illegal_deletes == []


def test_judge_uploaded_accepts_a_matching_digest_and_rejects_anything_else(dist, clock):
    # The direct unit test for the branch above: `if digest == local_digest` is the one
    # line standing between a re-run and an asset set that mixes two builds.
    gh = FakeGh(dist, clock=clock, assets=remote_assets(dist))
    ctx = mod._Ctx(
        api=gh,
        release_id=RELEASE_ID,
        tag=TAG,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        log=lambda message: None,
    )
    name = "OpenWorker-windows.msi"
    local = mod.sha256_file(dist / name)

    good = mod._judge_uploaded(ctx, name, {"id": 1, "name": name, "state": "uploaded", "digest": local}, local)
    assert good.done and good.fatal is None

    other = "sha256:" + "e" * 64
    bad = mod._judge_uploaded(ctx, name, {"id": 1, "name": name, "state": "uploaded", "digest": other}, local)
    assert not bad.done
    assert bad.fatal is not None
    assert name in bad.fatal and other in bad.fatal and local in bad.fatal
    assert gh.deleted == []


def test_preflight_refuses_an_unexpected_uploaded_asset(dist, clock):
    gh = FakeGh(dist, clock=clock, assets=remote_assets(dist, extra=("OpenWorker-linux.AppImage",)))

    run = run_upload(gh, clock, dist)

    assert not run.ok
    assert any("unexpected uploaded asset" in e for e in run.errors)
    assert gh.uploads == []


def test_preflight_fails_when_a_local_file_is_missing(dist, clock):
    (dist / "OpenWorker-windows.msi").unlink()
    gh = FakeGh(dist, clock=clock)

    run = run_upload(gh, clock, dist)

    assert not run.ok
    assert any("missing from" in e and "OpenWorker-windows.msi" in e for e in run.errors)
    assert gh.uploads == []
    assert gh.deleted == []


def test_preflight_fails_when_dist_holds_an_extra_file(dist, clock):
    (dist / "OpenWorker-linux.AppImage").write_bytes(b"surprise")
    gh = FakeGh(dist, clock=clock)

    run = run_upload(gh, clock, dist)

    assert not run.ok
    assert any("unexpected file" in e for e in run.errors)
    assert gh.uploads == []
    assert gh.deleted == []


# --------------------------------------------------------------------------------------
# 5-6: retries
# --------------------------------------------------------------------------------------


def test_retries_with_the_documented_backoff_and_clears_the_stub_each_time(dist, clock):
    name = "OpenWorker-windows-setup.exe"
    gh = FakeGh(
        dist,
        clock=clock,
        behaviors={
            name: [
                Behavior(effect="starter", returncode=1),
                Behavior(effect="starter", returncode=1),
                Behavior(effect="upload"),
            ]
        },
    )

    run = run_upload(gh, clock, dist)

    assert run.ok, run.errors
    result = next(r for r in run.results if r.name == name)
    assert result.attempts == 3
    assert result.action == "replaced-stale"
    # min(10 * 2**(n-1), 300), jitter pinned to zero.
    assert run.backoffs == [10.0, 20.0]
    assert gh.deleted == [(name, "starter"), (name, "starter")]
    assert gh.uploads.count(name) == 3


def test_backoff_is_capped_at_five_minutes():
    assert [mod._backoff_delay(n, lambda: 0.0) for n in range(1, 8)] == [
        10.0,
        20.0,
        40.0,
        80.0,
        160.0,
        300.0,
        300.0,
    ]


def test_giving_up_never_touches_what_already_landed(dist, clock):
    name = "OpenWorker-windows.msi"
    already = tuple(n for n in mod.expected_assets(VERSION) if n != name)
    gh = FakeGh(
        dist,
        clock=clock,
        assets=remote_assets(dist, omit=(name,)),
        behaviors={name: [Behavior(effect="starter", returncode=1) for _ in range(9)]},
    )

    run = run_upload(gh, clock, dist, max_attempts=3)

    assert not run.ok
    assert any("gave up after 3 attempts" in e for e in run.errors)
    assert gh.uploads.count(name) == 3
    assert gh.illegal_deletes == []
    still_there = {a["name"] for a in gh.assets.values() if a["state"] == "uploaded"}
    assert still_there == set(already)


def test_a_transient_api_error_mid_attempt_is_only_a_failed_attempt(dist, clock):
    # api.github.com having a bad minute must not abandon the run: the files that already
    # landed would be left for the next re-run to redo. _api's own retry has already spent
    # ~30s by the time this GhError escapes, so the right move is the normal backoff.
    name = "OpenWorker-macos-arm64.app.tar.gz"  # first in upload order
    fired = []

    def flaky(gh):
        if gh.uploads and not fired:
            fired.append(gh.list_calls)
            raise mod.GhError("gh api GET repos/x/y/releases/42/assets failed: HTTP 502")

    gh = FakeGh(
        dist,
        clock=clock,
        behaviors={name: [Behavior(effect="nothing", exit_at=None)]},
        on_list_assets=flaky,
    )

    run = run_upload(gh, clock, dist)

    assert run.ok, run.errors
    assert fired, "the fake never raised"
    assert next(r for r in run.results if r.name == name).attempts == 2
    assert run.backoffs == [10.0]
    assert gh.uploads.count(name) == 2
    assert gh.stopped.count(name) == 2  # the interrupted gh was killed, not orphaned
    assert (run.uploaded, run.skipped) == (14, 0)


def test_repeated_api_errors_exhaust_the_attempts_and_damage_nothing(dist, clock):
    name = "OpenWorker-macos-arm64.app.tar.gz"

    def always(gh):
        if gh.uploads:
            raise mod.GhError("gh api GET repos/x/y/releases/42/assets failed: HTTP 502")

    gh = FakeGh(
        dist,
        clock=clock,
        assets=remote_assets(dist, omit=(name,)),
        behaviors={name: [Behavior(effect="nothing", exit_at=None) for _ in range(5)]},
        on_list_assets=always,
    )

    run = run_upload(gh, clock, dist, max_attempts=3)

    assert not run.ok
    assert any("GitHub API error" in e and "gave up after 3 attempts" in e for e in run.errors)
    assert run.backoffs == [10.0, 20.0]
    # Attempts 2 and 3 fail in the pre-upload reconcile, before gh is even started: with
    # the API unreadable there is no safe way to decide what to do with the name.
    assert gh.uploads == [name]
    assert gh.deleted == []
    assert gh.illegal_deletes == []
    survivors = {a["name"] for a in gh.assets.values() if a["state"] == "uploaded"}
    assert survivors == set(mod.expected_assets(VERSION)) - {name}


def test_preflight_api_errors_still_abort_immediately(dist, clock):
    # The other side of the coin: nothing has been written yet, so there is nothing to
    # protect and no reason to spend six attempts finding that out.
    def always(gh):
        raise mod.GhError("gh api GET repos/x/y/releases/42/assets failed: HTTP 502")

    gh = FakeGh(dist, clock=clock, on_list_assets=always)

    run = run_upload(gh, clock, dist)

    assert not run.ok
    assert any("HTTP 502" in e for e in run.errors)
    assert gh.uploads == []
    assert run.backoffs == []


# --------------------------------------------------------------------------------------
# 7: gh's exit code is not evidence, in either direction
# --------------------------------------------------------------------------------------


def test_nonzero_exit_counts_as_success_when_the_bytes_are_on_github(dist, clock):
    name = "OpenWorker-macos-arm64.dmg"
    gh = FakeGh(dist, clock=clock, behaviors={name: [Behavior(effect="upload", returncode=1)]})

    run = run_upload(gh, clock, dist)

    assert run.ok, run.errors
    assert next(r for r in run.results if r.name == name).attempts == 1
    assert gh.uploads.count(name) == 1


def test_zero_exit_counts_as_failure_when_nothing_landed(dist, clock):
    name = "OpenWorker-macos-arm64.dmg"
    gh = FakeGh(
        dist,
        clock=clock,
        behaviors={name: [Behavior(effect="nothing", returncode=0), Behavior(effect="upload")]},
    )

    run = run_upload(gh, clock, dist)

    assert run.ok, run.errors
    assert next(r for r in run.results if r.name == name).attempts == 2
    assert gh.uploads.count(name) == 2
    assert run.backoffs == [10.0]


# --------------------------------------------------------------------------------------
# 8: a gh that never returns
# --------------------------------------------------------------------------------------


def test_a_hung_gh_is_stopped_once_the_asset_matches(dist, clock):
    name = "OpenWorker-macos-x64.dmg"
    gh = FakeGh(
        dist,
        clock=clock,
        behaviors={name: [Behavior(effect="upload", effect_at=30.0, exit_at=None)]},
    )

    run = run_upload(gh, clock, dist)

    assert run.ok, run.errors
    assert gh.stopped.count(name) == 1
    assert next(r for r in run.results if r.name == name).attempts == 1
    assert clock.now == pytest.approx(30.0)


def test_an_attempt_that_never_finishes_times_out_and_retries(dist, clock):
    name = "OpenWorker-macos-x64.dmg"
    gh = FakeGh(
        dist,
        clock=clock,
        behaviors={
            name: [Behavior(effect="nothing", exit_at=None), Behavior(effect="upload")]
        },
    )

    run = run_upload(gh, clock, dist, attempt_timeout=60.0, poll_interval=15.0)

    assert run.ok, run.errors
    assert gh.stopped.count(name) == 2  # the hung attempt, then the successful one
    assert next(r for r in run.results if r.name == name).attempts == 2
    assert run.backoffs == [10.0]


# --------------------------------------------------------------------------------------
# 9: the listing can lag behind reality
# --------------------------------------------------------------------------------------


def test_a_stub_that_finished_between_the_listing_and_the_recheck_is_not_deleted(dist, clock):
    name = "OpenWorker-windows.msi"
    gh = FakeGh(
        dist,
        clock=clock,
        assets=remote_assets(dist, starter=(name,)),
        promote_on_get=(name,),
    )

    run = run_upload(gh, clock, dist)

    assert run.ok, run.errors
    assert gh.deleted == []
    assert gh.illegal_deletes == []
    assert gh.uploads == []
    assert next(r for r in run.results if r.name == name).action == "skipped"


def test_the_fake_itself_catches_a_delete_of_an_uploaded_asset(dist, clock):
    gh = FakeGh(dist, clock=clock, assets=remote_assets(dist))
    victim = next(a["id"] for a in gh.assets.values() if a["state"] == "uploaded")
    with pytest.raises(AssertionError, match="INVARIANT BROKEN"):
        gh.delete_asset(victim)


# --------------------------------------------------------------------------------------
# 10: resolving the tag to exactly one release
# --------------------------------------------------------------------------------------


def test_no_release_for_the_tag_is_a_failure(dist, clock):
    gh = FakeGh(dist, clock=clock, releases=[{"id": 7, "tag_name": "v9.9.9", "draft": True}])
    run = run_upload(gh, clock, dist)
    assert not run.ok
    assert any("no release for tag" in e for e in run.errors)
    assert gh.uploads == []


def test_duplicate_releases_for_the_tag_are_a_failure_and_are_listed(dist, clock):
    gh = FakeGh(
        dist,
        clock=clock,
        releases=[
            {"id": 42, "tag_name": TAG, "draft": True},
            {"id": 43, "tag_name": TAG, "draft": True},
        ],
    )
    run = run_upload(gh, clock, dist)
    assert not run.ok
    assert any("42" in e and "43" in e for e in run.errors)
    assert gh.uploads == []


def test_a_release_id_that_is_not_the_tags_release_is_a_failure(dist, clock):
    gh = FakeGh(dist, clock=clock)
    run = run_upload(gh, clock, dist, release_id=999)
    assert not run.ok
    assert any("--release-id 999" in e for e in run.errors)
    assert gh.uploads == []


def test_the_matching_release_id_is_accepted(dist, clock):
    gh = FakeGh(dist, clock=clock, assets=remote_assets(dist))
    run = run_upload(gh, clock, dist, release_id=RELEASE_ID)
    assert run.ok, run.errors


# --------------------------------------------------------------------------------------
# 12: verify
# --------------------------------------------------------------------------------------


def _verify(dist: Path, gh: FakeGh):
    return mod.run_verify(gh, tag=TAG, version=VERSION, dist=dist, log=lambda m: None)


def test_verify_passes_on_a_complete_consistent_release(dist, clock):
    gh = FakeGh(dist, clock=clock, assets=remote_assets(dist))
    out = _verify(dist, gh)
    assert out.ok, out.problems
    assert len(out.rows) == 14
    assert all(ok for _, _, _, ok in out.rows)


@pytest.mark.parametrize(
    "mutate, needle",
    [
        pytest.param(
            lambda dist, kw: kw.update(omit=("OpenWorker-macos-x64.dmg",)),
            "asset missing from the release: OpenWorker-macos-x64.dmg",
            id="missing-asset",
        ),
        pytest.param(
            lambda dist, kw: kw.update(starter=("OpenWorker-windows.msi",)),
            "half-finished asset left on the release",
            id="leftover-stub",
        ),
        pytest.param(
            lambda dist, kw: kw.update(extra=("OpenWorker-linux.AppImage",)),
            "unexpected asset on the release",
            id="extra-asset",
        ),
        pytest.param(
            lambda dist, kw: kw.update(
                digest_override={"OpenWorker-windows.msi": "sha256:" + "c" * 64}
            ),
            "digest mismatch",
            id="digest-mismatch",
        ),
        pytest.param(
            lambda dist, kw: kw.update(digest_override={"OpenWorker-windows.msi": ""}),
            "reports no digest",
            id="empty-digest",
        ),
        pytest.param(
            lambda dist, kw: kw.update(omit=("OpenWorker-windows-setup.exe",)),
            "OpenWorker-windows-setup.exe.sig is uploaded but its payload",
            id="orphan-sig",
        ),
    ],
)
def test_verify_catches_remote_problems(dist, clock, mutate, needle):
    kwargs: dict = {}
    mutate(dist, kwargs)
    gh = FakeGh(dist, clock=clock, assets=remote_assets(dist, **kwargs))
    out = _verify(dist, gh)
    assert not out.ok
    assert any(needle in p for p in out.problems), out.problems


def _drop_windows_platform(payload):
    del payload["platforms"]["windows-x86_64"]


@pytest.mark.parametrize(
    "mutate, needle",
    [
        pytest.param(
            lambda p: p.__setitem__("version", "9.9.9"),
            "version is '9.9.9', expected '1.2.3'",
            id="version-mismatch",
        ),
        pytest.param(
            lambda p: p["platforms"]["windows-x86_64"].__setitem__(
                "url",
                "https://github.com/andrewyng/openworker/releases/download/v1.2.3/"
                "OpenWorker-windows-setup.exe",
            ),
            "url does not start with",
            id="url-points-at-the-upstream-repo",
        ),
        pytest.param(
            lambda p: p["platforms"]["windows-x86_64"].__setitem__(
                "url",
                "https://github.com/ldfpku/openworker/releases/download/v0.0.1/"
                "OpenWorker-windows-setup.exe",
            ),
            "url does not start with",
            id="url-points-at-another-tag",
        ),
        pytest.param(
            lambda p: p["platforms"]["windows-x86_64"].__setitem__(
                "url",
                "https://github.com/ldfpku/openworker/releases/latest/download/"
                "OpenWorker-windows-setup.exe",
            ),
            "url does not start with",
            id="url-points-at-latest",
        ),
        pytest.param(
            lambda p: p["platforms"]["windows-x86_64"].__setitem__(
                "url",
                "https://github.com/ldfpku/openworker/releases/download/v1.2.3/"
                "OpenWorker-does-not-exist.exe",
            ),
            "which is not an uploaded asset",
            id="url-points-at-a-file-that-is-not-there",
        ),
        pytest.param(
            lambda p: p["platforms"]["windows-x86_64"].__setitem__("signature", "bogus"),
            "signature does not match OpenWorker-windows-setup.exe.sig",
            id="signature-mismatch",
        ),
        pytest.param(
            _drop_windows_platform,
            "OpenWorker-windows-setup.exe.sig ships in the release but no latest.json platform",
            id="sig-referenced-by-nobody",
        ),
    ],
)
def test_verify_catches_manifest_problems(dist, clock, mutate, needle):
    patch_manifest(dist, mutate)
    # Rebuild the remote view AFTER the edit, so the manifest's own digest still matches
    # and the only problem is the one under test.
    gh = FakeGh(dist, clock=clock, assets=remote_assets(dist))
    out = _verify(dist, gh)
    assert not out.ok
    assert any(needle in p for p in out.problems), out.problems


def test_verify_reports_a_missing_local_file(dist, clock):
    gh = FakeGh(dist, clock=clock, assets=remote_assets(dist))
    (dist / "OpenWorker-macos-arm64.dmg").unlink()
    out = _verify(dist, gh)
    assert not out.ok
    assert any("missing from" in p for p in out.problems)


# --------------------------------------------------------------------------------------
# 13: the expected-asset list is a tripwire — cross-check it against its sources
# --------------------------------------------------------------------------------------


def test_the_expected_set_is_exactly_fourteen_names():
    names = mod.expected_assets(VERSION)
    assert len(names) == 14 == mod.EXPECTED_ASSET_COUNT
    assert len(set(names)) == 14
    # These are the names the real v0.6.2 release carries, with 0.6.2 -> 1.2.3.
    assert sorted(names) == sorted(
        [
            "latest.json",
            "OpenWorker-macos-arm64.app.tar.gz",
            "OpenWorker-macos-arm64.app.tar.gz.sig",
            "OpenWorker-macos-arm64.dmg",
            "OpenWorker-macos-x64.app.tar.gz",
            "OpenWorker-macos-x64.app.tar.gz.sig",
            "OpenWorker-macos-x64.dmg",
            "OpenWorker-windows-setup.exe",
            "OpenWorker-windows-setup.exe.sig",
            "OpenWorker-windows.msi",
            "OpenWorker_1.2.3_aarch64.dmg",
            "OpenWorker_1.2.3_x86_64.dmg",
            "OpenWorker_1.2.3_x64-setup.exe",
            "OpenWorker_1.2.3_x64_en-US.msi",
        ]
    )


def test_every_updater_artifact_and_its_signature_are_in_the_expected_set():
    # make_update_manifest.py is the other half of the tripwire: an artifact it wires
    # into latest.json but that this uploader does not expect would never be uploaded.
    names = set(mod.expected_assets(VERSION))
    for asset in manifest_mod.ARTIFACTS:
        assert asset in names, asset
        assert asset + ".sig" in names, asset


def test_the_versioned_names_track_the_version():
    assert "OpenWorker_0.6.2_x64-setup.exe" in mod.expected_assets("0.6.2")
    assert "OpenWorker_0.6.2_x64-setup.exe" not in mod.expected_assets("0.6.3")


# --------------------------------------------------------------------------------------
# GhApi._paginated — offline, with a stub executor in place of the gh subprocess
# --------------------------------------------------------------------------------------


def _stub_api(api, pages: dict[int, list]) -> list[str]:
    """Replace GhApi._api with a page server. Returns the list of paths it was asked for."""
    seen: list[str] = []

    def fake(path: str, *, method: str = "GET", allow_404: bool = False):
        seen.append(path)
        return pages.get(int(path.rsplit("page=", 1)[1]), [])

    api._api = fake
    return seen


def test_paginated_fetches_the_next_page_after_a_full_one_and_stops_on_a_short_one():
    # 100 is the boundary that matters: the repo's release list will cross it, and a
    # single-page fetch would silently hide the tag we are looking for.
    api = mod.GhApi(REPO, sleep=lambda seconds: None)
    pages = {1: [{"i": n} for n in range(100)], 2: [{"i": 100}, {"i": 101}]}
    seen = _stub_api(api, pages)

    out = api._paginated("repos/x/y/releases")

    assert [item["i"] for item in out] == list(range(102))
    assert seen == [
        "repos/x/y/releases?per_page=100&page=1",
        "repos/x/y/releases?per_page=100&page=2",
    ]


def test_paginated_stops_on_an_empty_page():
    api = mod.GhApi(REPO, sleep=lambda seconds: None)
    seen = _stub_api(api, {1: [{"i": n} for n in range(100)], 2: []})

    out = api._paginated("repos/x/y/releases")

    assert len(out) == 100
    assert len(seen) == 2  # asked for page 2, believed the empty answer


def test_paginated_stops_after_one_short_page():
    api = mod.GhApi(REPO, sleep=lambda seconds: None)
    seen = _stub_api(api, {1: [{"i": 0}, {"i": 1}]})

    assert len(api._paginated("repos/x/y/releases")) == 2
    assert seen == ["repos/x/y/releases?per_page=100&page=1"]


def test_paginated_appends_to_a_path_that_already_has_a_query():
    api = mod.GhApi(REPO, sleep=lambda seconds: None)
    seen = _stub_api(api, {1: []})

    api._paginated("repos/x/y/releases?draft=true")

    assert seen == ["repos/x/y/releases?draft=true&per_page=100&page=1"]


def test_every_runtime_string_is_plain_ascii():
    # A Chinese-locale Windows console is cp936. Anything this script PRINTS has to
    # survive that, so no string literal outside a docstring may carry a non-ASCII
    # character (an em dash in an error message is the easy way to get this wrong —
    # `sys.stdout.reconfigure(errors="replace")` then turns it into mojibake). Comments
    # and docstrings are exempt: they are never written to a stream.
    tree = ast.parse(
        (_REPO_ROOT / "packaging" / "upload_release_assets.py").read_text(encoding="utf-8")
    )
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    offenders = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and not node.value.isascii()
    ]
    assert offenders == []


# --------------------------------------------------------------------------------------
# 14: cleanup-selftest's guards
# --------------------------------------------------------------------------------------


def _cleanup_gh(dist, clock, release):
    return FakeGh(dist, clock=clock, releases=[release])


def test_cleanup_refuses_a_published_release(dist, clock):
    gh = _cleanup_gh(dist, clock, {"id": 5, "tag_name": "selftest-upload-1-1", "draft": False})
    assert mod.run_cleanup_selftest(gh, release_id=5, log=lambda m: None) == 2
    assert gh.deleted_releases == []


def test_cleanup_refuses_a_tag_outside_the_selftest_namespace(dist, clock):
    gh = _cleanup_gh(dist, clock, {"id": 5, "tag_name": "v0.6.2", "draft": True})
    assert mod.run_cleanup_selftest(gh, release_id=5, log=lambda m: None) == 2
    assert gh.deleted_releases == []


def test_cleanup_deletes_a_selftest_draft(dist, clock):
    gh = _cleanup_gh(dist, clock, {"id": 5, "tag_name": "selftest-upload-9-1", "draft": True})
    assert mod.run_cleanup_selftest(gh, release_id=5, log=lambda m: None) == 0
    assert gh.deleted_releases == [5]


def test_cleanup_is_a_no_op_when_the_release_is_already_gone(dist, clock):
    gh = _cleanup_gh(dist, clock, {"id": 5, "tag_name": "selftest-upload-9-1", "draft": True})
    assert mod.run_cleanup_selftest(gh, release_id=6, log=lambda m: None) == 0
    assert gh.deleted_releases == []


def test_cleanup_reports_a_leftover_tag_but_never_deletes_it(dist, clock):
    gh = _cleanup_gh(dist, clock, {"id": 5, "tag_name": "selftest-upload-9-1", "draft": True})
    gh.list_tag_refs = lambda prefix: [{"ref": "refs/tags/selftest-upload-9-1"}]
    assert mod.run_cleanup_selftest(gh, release_id=5, log=lambda m: None) == 1
    assert gh.deleted_releases == [5]
