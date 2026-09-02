"""Shared pytest fixtures.

`fake_slack` boots the in-process FakeSlack harness on an ephemeral port and points the Slack
adapter at it via `SLACK_API_URL`, so the real `SlackAdapter` / `slack_bolt` stack runs
end-to-end with no network, tokens, or the Slack app console. See
`coworker.testing.fake_slack` and `platform/docs/FAKE-SLACK-SPEC.md`.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from coworker.server.manager import SessionManager
from coworker.testing.fake_slack import FakeSlack


@pytest.fixture(autouse=True)
def _no_live_model_catalog(monkeypatch):
    """The live model-catalog feature (providers/catalog.py, manager._fetch_model_catalog)
    fetches a provider's real model list over the network. Without this, every test that
    configures a catalog-supported provider (set_provider, get_providers' background kick,
    verify_provider's catalog-pull-on-Test) would reach out to the real vendor API — so
    EVERY test gets an offline stub, same reasoning as `_isolated_state_dir` below. Tests
    that specifically exercise catalog fetching (tests/test_model_catalog.py) override this
    per-test with their own monkeypatch of `list_provider_models`/`httpx`."""
    monkeypatch.setattr(
        SessionManager,
        "_fetch_model_catalog",
        lambda self, name, fields=None: {"ok": False, "error": "offline (test)"},
    )


@pytest.fixture(autouse=True)
def _isolated_state_dir(tmp_path, monkeypatch):
    """EVERY test gets an isolated SecretStore/state dir. Without this, any test that builds
    a SessionManager reads the developer's real machine-global state — including their cloud
    sign-in, which made test session creation emit REAL telemetry to prod (found 2026-07-03
    as burst noise in the ocw-connect-telemetry-events table)."""
    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "coworker-state"))
    # Universal scratch provisions a per-session dir for EVERY session — without this,
    # tests would mkdir under the developer's real ~/OpenWorker.
    monkeypatch.setenv("COWORKER_SCRATCH_BASE", str(tmp_path / "coworker-scratch"))
    monkeypatch.delenv("COWORKER_API_TOKEN", raising=False)


@pytest_asyncio.fixture
async def fake_slack(monkeypatch):
    """A running FakeSlack control object; `SLACK_API_URL` is set to it for the test's duration."""
    fake = FakeSlack()
    await fake.start()
    monkeypatch.setenv("SLACK_API_URL", fake.api_url)
    try:
        yield fake
    finally:
        await fake.stop()
