"""Cloudflare Access Managed OAuth for the AI Gateway (`coworker/aigw_auth.py`).

Nothing here touches the network. What is worth pinning is the bookkeeping that decides
whether a colleague stays signed in: when a token is refreshed rather than reused, what
survives a refresh, what a spent grant does, and the two rules that keep repeated sign-ins
from littering Cloudflare with client registrations nobody can delete.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import pytest

from coworker import aigw_auth


class FakeSecrets:
    """The two-method slice of SecretStore this module uses."""

    def __init__(self, data: Optional[dict[str, Any]] = None) -> None:
        self.data: dict[str, Any] = dict(data or {})

    def get(self, profile: str) -> dict[str, Any]:
        return dict(self.data.get(profile) or {})

    def put(self, profile: str, value: dict[str, Any]) -> None:
        self.data[profile] = dict(value)

    def delete(self, profile: str) -> bool:
        return bool(self.data.pop(profile, None))


def _store(oauth: dict[str, Any], **profile: Any) -> FakeSecrets:
    return FakeSecrets({aigw_auth.PROFILE: {**profile, aigw_auth.OAUTH_FIELD: oauth}})


class _Resp:
    def __init__(self, status: int, payload: Any = None, text: str = "") -> None:
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self) -> Any:
        return self._payload


# -- the access token on the request path ----------------------------------------------


def test_a_fresh_token_is_reused_without_calling_out(monkeypatch):
    monkeypatch.setattr(
        "httpx.post", lambda *a, **k: pytest.fail("must not refresh a fresh token")
    )
    s = _store({"access_token": "live", "expires_at": time.time() + 900})
    assert aigw_auth.access_token(s) == "live"


def test_a_token_near_expiry_is_refreshed_before_it_lapses(monkeypatch):
    # Renewed AHEAD of the stated expiry: a token that dies mid-request would surface as a
    # 401 the user has to retry through, which is the whole thing silent refresh prevents.
    calls: list[dict[str, Any]] = []

    def fake_post(url, data=None, **kwargs):
        calls.append({"url": url, **(data or {})})
        return _Resp(200, {"access_token": "renewed", "expires_in": 900})

    monkeypatch.setattr("httpx.post", fake_post)
    s = _store(
        {
            "access_token": "stale",
            "refresh_token": "r1",
            "expires_at": time.time() + 5,  # inside the refresh skew
            "token_endpoint": "https://as.example/token",
            "resource": "https://gw.example",
            "client_id": "cid",
        }
    )
    assert aigw_auth.access_token(s) == "renewed"
    assert calls[0]["grant_type"] == "refresh_token"
    assert calls[0]["refresh_token"] == "r1"
    # RFC 8707: the gateway has to be named or Managed OAuth refuses the grant.
    assert calls[0]["resource"] == "https://gw.example"
    assert s.get(aigw_auth.PROFILE)[aigw_auth.OAUTH_FIELD]["access_token"] == "renewed"


def test_a_refresh_that_omits_a_new_refresh_token_keeps_the_old_one(monkeypatch):
    # "Keep using the one you have" is a legal response. Overwriting it with "" would end
    # the two-week grant early and drop the person back to a browser sign-in.
    monkeypatch.setattr(
        "httpx.post",
        lambda *a, **k: _Resp(200, {"access_token": "renewed", "expires_in": 900}),
    )
    s = _store(
        {
            "access_token": "stale",
            "refresh_token": "keep-me",
            "expires_at": 0,
            "token_endpoint": "https://as.example/token",
        }
    )
    aigw_auth.access_token(s)
    assert s.get(aigw_auth.PROFILE)[aigw_auth.OAUTH_FIELD]["refresh_token"] == "keep-me"


def test_a_spent_grant_signs_the_person_out_instead_of_failing_forever(monkeypatch):
    # A revoked or expired grant must clear the tokens so the pane offers the button
    # again; keeping them would fail every single call with a credential that can never
    # work, and the UI would still claim "signed in".
    monkeypatch.setattr("httpx.post", lambda *a, **k: _Resp(400, text="invalid_grant"))
    s = _store(
        {
            "access_token": "stale",
            "refresh_token": "dead",
            "expires_at": time.time() - 10,
            "token_endpoint": "https://as.example/token",
        }
    )
    assert aigw_auth.access_token(s) == ""
    assert aigw_auth.status(s)["signed_in"] is False


def test_nobody_signed_in_is_an_empty_string_not_an_error(monkeypatch):
    monkeypatch.setattr(
        "httpx.post", lambda *a, **k: pytest.fail("nothing to refresh")
    )
    assert aigw_auth.access_token(FakeSecrets()) == ""


def test_a_token_of_unknown_age_is_refreshed_rather_than_trusted(monkeypatch):
    # "No stated expiry" must not mean "valid forever" — that is the documented trap in
    # coworker/mcp/oauth.py, where an hour-old token kept being sent, the server 401'd,
    # and the refresh grant was never reached so nothing ever self-healed.
    monkeypatch.setattr(
        "httpx.post",
        lambda *a, **k: _Resp(200, {"access_token": "renewed", "expires_in": 900}),
    )
    s = _store(
        {
            "access_token": "unknown-age",
            "refresh_token": "r",
            "expires_at": 0,
            "token_endpoint": "https://as.example/token",
        }
    )
    assert aigw_auth.access_token(s) == "renewed"


def test_a_token_of_unknown_age_is_still_used_when_there_is_nothing_to_refresh_with():
    # With no refresh token there is no better move than sending it and letting the
    # gateway judge; refusing locally would turn a maybe-valid call into a certain failure.
    s = _store({"access_token": "opaque", "expires_at": 0})
    assert aigw_auth.access_token(s) == "opaque"


# -- client registration ----------------------------------------------------------------
# Cloudflare exposes no way to list or delete a registered client, so every avoidable
# registration is permanent litter on the Access app.

META = {
    "issuer": "https://as.example",
    "resource": "https://gw.example",
    "authorization_endpoint": "https://as.example/auth",
    "token_endpoint": "https://as.example/token",
    "registration_endpoint": "https://as.example/register",
    "revocation_endpoint": "https://as.example/revoke",
}


def _fingerprint() -> str:
    return META["issuer"] + "|" + ",".join(aigw_auth._redirect_uris())


def test_an_existing_registration_is_reused_rather_than_duplicated(monkeypatch):
    monkeypatch.setattr(
        "httpx.post", lambda *a, **k: pytest.fail("must not register twice")
    )
    s = _store({"client_id": "cid", "client_fingerprint": _fingerprint()})
    assert aigw_auth._ensure_client(s, META) == "cid"


def test_a_changed_issuer_forces_a_new_registration(monkeypatch):
    monkeypatch.setattr("httpx.post", lambda *a, **k: _Resp(201, {"client_id": "new"}))
    s = _store({"client_id": "old", "client_fingerprint": "https://elsewhere|x"})
    assert aigw_auth._ensure_client(s, META) == "new"


def test_registration_asks_for_every_candidate_port_at_once(monkeypatch):
    # One registration has to cover all of them: Cloudflare matches the redirect URI down
    # to the port (measured — a different port is a flat 400), and the app cannot know
    # which port will be free at sign-in time.
    seen: dict[str, Any] = {}

    def fake_post(url, json=None, **kwargs):
        seen.update(json or {})
        return _Resp(201, {"client_id": "cid"})

    monkeypatch.setattr("httpx.post", fake_post)
    aigw_auth._ensure_client(FakeSecrets(), META)
    assert seen["redirect_uris"] == aigw_auth._redirect_uris()
    assert len(seen["redirect_uris"]) == len(aigw_auth.CALLBACK_PORTS)
    assert all(u.startswith("http://127.0.0.1:") for u in seen["redirect_uris"])
    # Public client: a desktop app has nowhere to keep a secret.
    assert seen["token_endpoint_auth_method"] == "none"


def test_endpoints_are_re_persisted_even_when_the_client_is_cached(monkeypatch):
    # `_refresh` reads the token endpoint out of storage, so a cached registration must
    # not leave a stale address behind after the server moves one.
    monkeypatch.setattr("httpx.post", lambda *a, **k: pytest.fail("no registration"))
    s = _store(
        {
            "client_id": "cid",
            "client_fingerprint": _fingerprint(),
            "token_endpoint": "https://old.example/token",
        }
    )
    aigw_auth._ensure_client(s, META)
    stored = s.get(aigw_auth.PROFILE)[aigw_auth.OAUTH_FIELD]
    assert stored["token_endpoint"] == META["token_endpoint"]


# -- callbacks and state ------------------------------------------------------------------


def test_a_callback_with_the_wrong_state_is_refused_and_leaves_the_flow_alive():
    # The loopback port is reachable by anything else on the machine. A stray hit must not
    # be able to end someone's sign-in — that is a local denial of service, and it was a
    # real bug here before the listener looped (measured 2026-08-23).
    aigw_auth._pending = {"state": "the-real-one", "secrets": FakeSecrets()}
    try:
        _title, _detail, error = aigw_auth._complete("code", "not-it", "")
        assert error
        assert aigw_auth._pending is not None  # the genuine flow still waits
    finally:
        aigw_auth._pending = None


def test_the_matching_state_consumes_the_flow():
    aigw_auth._pending = {"state": "s", "secrets": FakeSecrets()}
    try:
        _title, _detail, error = aigw_auth._complete("", "s", "access_denied")
        assert error == "access_denied"
        assert aigw_auth._pending is None
    finally:
        aigw_auth._pending = None


# -- what the pane renders ------------------------------------------------------------


def test_status_distinguishes_signed_in_from_a_leftover_pasted_session():
    signed_in = _store({"access_token": "a"})
    assert aigw_auth.status(signed_in)["signed_in"] is True
    assert aigw_auth.status(signed_in)["pasted_session"] is False

    pasted = _store({}, access_token="cloudflared-jwt")
    assert aigw_auth.status(pasted)["signed_in"] is False
    assert aigw_auth.status(pasted)["pasted_session"] is True


def test_signing_out_drops_the_tokens_but_keeps_the_registration(monkeypatch):
    # The registration is not a credential, and re-registering on every sign-out/in cycle
    # is exactly the litter this module exists to avoid.
    monkeypatch.setattr("httpx.post", lambda *a, **k: _Resp(200, {}))
    s = _store(
        {
            "access_token": "a",
            "refresh_token": "r",
            "client_id": "cid",
            "client_fingerprint": _fingerprint(),
            "revocation_endpoint": META["revocation_endpoint"],
        }
    )
    aigw_auth.logout(s)
    stored = s.get(aigw_auth.PROFILE)[aigw_auth.OAUTH_FIELD]
    assert stored["access_token"] == "" and stored["refresh_token"] == ""
    assert stored["client_id"] == "cid"


def test_signing_out_still_clears_locally_when_revocation_is_unreachable(monkeypatch):
    import httpx

    def boom(*a, **k):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr("httpx.post", boom)
    s = _store(
        {
            "access_token": "a",
            "refresh_token": "r",
            "revocation_endpoint": META["revocation_endpoint"],
        }
    )
    assert aigw_auth.logout(s)["ok"] is True
    assert aigw_auth.status(s)["signed_in"] is False


def test_the_oauth_state_never_clobbers_the_rest_of_the_profile():
    # `put` replaces the whole profile, so a careless write here would wipe the gateway
    # address (and the pasted session) the first time anyone signed in.
    s = _store({"access_token": "a"}, base_url="https://gw.example", thinking_budget="2048")
    aigw_auth._save_state(s, {"access_token": "b"})
    profile = s.get(aigw_auth.PROFILE)
    assert profile["base_url"] == "https://gw.example"
    assert profile["thinking_budget"] == "2048"
    assert profile[aigw_auth.OAUTH_FIELD]["access_token"] == "b"
