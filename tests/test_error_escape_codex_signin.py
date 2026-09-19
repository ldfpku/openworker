"""Regression tests for `SessionManager.codex_signin` (coworker/server/manager.py):
the try/except only used to wrap the call to `codex_auth.sign_in(...)`. The lines
that run right after a SUCCESSFUL sign-in — `_refresh_provider`, `add_model`,
`_provider_configured`, `set_default_model` — now have their own try/except so that
a failure there (even though the tokens are already persisted and the user IS
signed in) cannot escape `codex_signin`, gets logged, and lands in `_codex_error`
(the same channel `codex_status()` already exposes to the GUI).

2026-09-19 audit, item 3. `_codex_error` is displayed by the GUI as-is (no i18n
pass — see `surfaces/gui/src/providers/ProviderSetup.tsx`'s `{error}}` span), so the
bilingual "signed in, but setup didn't finish" framing lives entirely in the
frontend's `provider.oauth_post_signin_error` wrapper string; `_codex_error` itself
carries just the raw exception text (`str(exc) or exc.__class__.__name__`, the
file's existing convention), same as the sign-in-failure branch above it — no
"post-signin"/"setup" prefix, since that would be redundant with the frontend
framing and never gets translated anyway. What actually tells a post-signin
failure apart from a bare sign-in failure is `codex_status()`'s `signed_in=True`
alongside a non-empty `last_error` — a bare sign-in failure never reaches that
state, since no tokens were saved. That combination is what's asserted here.

Isolation: a fresh `SessionManager(data_dir=tmp_path / "data")` (no real user state
dir, no keyring). `codex_auth.sign_in` is monkeypatched to a fake that persists a
harmless opaque token pair via the real `CodexTokenStore` — no browser, no OAuth, no
network. The two "later step" functions are monkeypatched to raise directly; nothing
here touches threads, sockets, or sleeps, so both tests run in well under a second.
"""

from __future__ import annotations

import logging

from coworker.providers import codex_auth
from coworker.providers.codex_auth import CodexTokenStore
from coworker.server.manager import SessionManager


async def _fake_sign_in_persists_tokens(secrets, **kwargs) -> dict:
    """Stands in for `codex_auth.sign_in`: as if the browser round trip already
    succeeded and the backend already returned a token pair. Uses plain opaque
    strings (not real JWTs) — `CodexTokenStore.save` only cares that the fields are
    non-empty; the account-id/email extraction degrades gracefully for non-JWT
    input (see `test_account_id_from_token_claim`'s `"not-a-jwt"` case)."""
    CodexTokenStore(secrets).save(
        {"access_token": "test-access-token", "refresh_token": "test-refresh-token"}
    )
    return {"ok": True, "account": "user@example.com"}


async def test_refresh_provider_failure_is_caught_and_reported(
    tmp_path, monkeypatch, caplog
):
    """Inject: `manager._refresh_provider` raises RuntimeError right after a
    successful `codex_auth.sign_in`.

    Expected: `codex_signin` does not let the exception escape; it returns
    normally, `_codex_authorizing` ends up false, `_codex_error` carries the
    injected exception's text, a WARNING+ log record is emitted, and
    `codex_status()` reports `signed_in=True` together with the non-empty
    `last_error` — the combination that can only happen when sign-in itself
    succeeded but a later step didn't (this, not the `_codex_error` wording, is
    what makes the failure distinguishable from a bare sign-in failure — see
    module docstring).
    """
    manager = SessionManager(data_dir=tmp_path / "data")
    monkeypatch.setattr(codex_auth, "sign_in", _fake_sign_in_persists_tokens)

    def boom_refresh_provider(name=None):
        raise RuntimeError("refresh-provider-boom")

    monkeypatch.setattr(manager, "_refresh_provider", boom_refresh_provider)

    caplog.set_level(logging.WARNING, logger="coworker.manager")

    result = await manager.codex_signin()  # must not raise

    assert manager._codex_authorizing is False

    # Loose substring check, not the whole sentence — _codex_error just carries the
    # exception's own text, same convention as the sign-in-failure branch above it.
    assert manager._codex_error and "refresh-provider-boom" in manager._codex_error

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "the caught _refresh_provider failure must still be logged"

    # This is the actual discriminator: a bare sign-in failure never saves tokens,
    # so it could never produce signed_in=True together with a non-empty last_error.
    status = manager.codex_status()
    assert status["signed_in"] is True  # tokens were saved before the crash
    assert status["last_error"]
    assert result is not None  # sign-in's own result is still returned


async def test_add_model_failure_is_caught_and_reported(tmp_path, monkeypatch, caplog):
    """Inject: `manager.add_model` raises OSError right after a successful
    `codex_auth.sign_in` (a real, plausible failure mode: `_save_prefs`'s
    `tmp.write_text`/`os.replace` hitting a full or locked disk).

    Same expectations as test_refresh_provider_failure_is_caught_and_reported, just
    a different one of the calls now covered by the shared try/except
    (_refresh_provider/add_model/_provider_configured/set_default_model).
    """
    manager = SessionManager(data_dir=tmp_path / "data")
    monkeypatch.setattr(codex_auth, "sign_in", _fake_sign_in_persists_tokens)

    def boom_add_model(model):
        raise OSError("add-model-boom: disk full while saving prefs")

    monkeypatch.setattr(manager, "add_model", boom_add_model)

    caplog.set_level(logging.WARNING, logger="coworker.manager")

    result = await manager.codex_signin()  # must not raise

    assert manager._codex_authorizing is False

    assert manager._codex_error and "add-model-boom" in manager._codex_error

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "the caught add_model failure must still be logged"

    # Same discriminator as the _refresh_provider case: signed_in=True + non-empty
    # last_error is what marks this as a post-signin failure, not the text itself.
    status = manager.codex_status()
    assert status["signed_in"] is True
    assert status["last_error"]
    assert result is not None
