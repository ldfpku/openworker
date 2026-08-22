"""Gemini-relay sign-in (Cloudflare Access one-time PIN).

Everything is offline: the relay Worker is stubbed at the httpx boundary. The invariants
under test are the security promises the flow rests on — the browser is only ever sent to a
loopback callback, the code exchange is bound to this process by PKCE, a code can be
redeemed exactly once, and a token the relay no longer recognizes is dropped locally instead
of lingering to 403 on the next message.
"""

from __future__ import annotations

import base64
import hashlib

import pytest

from coworker import relay_auth
from coworker.config import Config
from coworker.secrets import SecretStore

RELAY = "https://relay.test"


@pytest.fixture(autouse=True)
def _relay_env(monkeypatch):
    # resolve_base_url()'s env channel — keeps the tests off the real company hostname.
    monkeypatch.setenv("GOOGLE_GEMINI_BASE_URL", RELAY)
    monkeypatch.delenv("COWORKER_PORT", raising=False)
    relay_auth._pending_logins.clear()
    yield
    relay_auth._pending_logins.clear()


@pytest.fixture
def secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    return SecretStore(path=tmp_path / "state" / "secrets.json")


@pytest.fixture
def config():
    return Config(port=8765)


class FakeResponse:
    def __init__(self, status_code=200, body=None, text=""):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.text = text

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


def _capture_post(monkeypatch, responses):
    """Stub httpx.post, recording every (url, json) and replaying `responses` in order."""
    calls: list[tuple[str, dict]] = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append((url, json or {}))
        return responses[len(calls) - 1]

    monkeypatch.setattr(relay_auth.httpx, "post", fake_post)
    return calls


# --- starting a login ----------------------------------------------------------------


def test_begin_login_sends_loopback_callback_and_s256_challenge(config, monkeypatch):
    calls = _capture_post(
        monkeypatch, [FakeResponse(body={"sid": "SID", "login_url": RELAY + "/login/SID"})]
    )

    out = relay_auth.begin_login(config)

    assert out["ok"] is True
    assert out["login_url"] == RELAY + "/login/SID"
    url, body = calls[0]
    assert url == RELAY + "/auth/session"
    # RFC 8252 loopback redirect — the code never leaves this machine.
    assert body["callback"] == "http://127.0.0.1:8765/relay/callback"
    # PKCE S256: base64url of a SHA-256 digest is always 43 unpadded characters.
    assert len(body["challenge"]) == 43
    assert "SID" in relay_auth._pending_logins


def test_begin_login_prefers_the_port_the_shell_actually_bound(config, monkeypatch):
    # The packaged app binds a random free port and publishes it; config.port is dev-only.
    monkeypatch.setenv("COWORKER_PORT", "49813")
    calls = _capture_post(
        monkeypatch, [FakeResponse(body={"sid": "SID", "login_url": RELAY + "/login/SID"})]
    )

    relay_auth.begin_login(config)

    assert calls[0][1]["callback"] == "http://127.0.0.1:49813/relay/callback"


def test_begin_login_surfaces_a_relay_refusal(config, monkeypatch):
    _capture_post(monkeypatch, [FakeResponse(status_code=400, body={"error": "bad callback"})])

    out = relay_auth.begin_login(config)

    assert out["ok"] is False
    assert "bad callback" in out["error"]
    assert relay_auth._pending_logins == {}


# --- redeeming the code --------------------------------------------------------------


def _begin(config, monkeypatch):
    calls = _capture_post(
        monkeypatch, [FakeResponse(body={"sid": "SID", "login_url": RELAY + "/login/SID"})]
    )
    relay_auth.begin_login(config)
    return calls[0][1]["challenge"]


def test_deliver_callback_stores_the_token_and_identity(secrets, config, monkeypatch):
    challenge = _begin(config, monkeypatch)
    calls = _capture_post(
        monkeypatch,
        [
            FakeResponse(
                body={
                    "token": "owr_abc123",
                    "email": "alice@example.com",
                    "name": "张三",
                    "dept": "技术研发部",
                    "role": "lead",
                    "expires_at": "2026-09-21T00:00:00.000Z",
                }
            )
        ],
    )

    out = relay_auth.deliver_callback(secrets, "CODE", "SID")

    assert out["ok"] is True
    url, body = calls[0]
    assert url == RELAY + "/auth/token"
    assert body["code"] == "CODE"
    # The verifier we send must be the pre-image of the challenge we sent at /auth/session,
    # which is what stops another local process from redeeming our code.
    digest = hashlib.sha256(body["verifier"].encode()).digest()
    assert base64.urlsafe_b64encode(digest).decode().rstrip("=") == challenge

    profile = secrets.get("provider:gemini")
    # Its own slot, never `api_key` — that one holds the person's own Google key.
    assert profile["relay_token"] == "owr_abc123"
    assert "api_key" not in profile
    assert profile["relay_email"] == "alice@example.com"
    assert profile["relay_dept"] == "技术研发部"
    assert profile["relay_base_url"] == RELAY


def test_deliver_callback_rejects_a_state_we_did_not_start(secrets, monkeypatch):
    monkeypatch.setattr(
        relay_auth.httpx, "post", lambda *a, **k: pytest.fail("must not call the relay")
    )

    out = relay_auth.deliver_callback(secrets, "CODE", "SOMEONE-ELSES-SID")

    assert out["ok"] is False
    assert secrets.get("provider:gemini") is None


def test_deliver_callback_is_single_use(secrets, config, monkeypatch):
    _begin(config, monkeypatch)
    _capture_post(monkeypatch, [FakeResponse(body={"token": "owr_abc123", "email": "a@b.com"})])
    assert relay_auth.deliver_callback(secrets, "CODE", "SID")["ok"] is True

    # A replayed tab must not mint a second token off the same pending login.
    monkeypatch.setattr(
        relay_auth.httpx, "post", lambda *a, **k: pytest.fail("must not call the relay")
    )
    assert relay_auth.deliver_callback(secrets, "CODE", "SID")["ok"] is False


def test_deliver_callback_rejects_a_token_that_is_not_a_relay_token(secrets, config, monkeypatch):
    _begin(config, monkeypatch)
    _capture_post(monkeypatch, [FakeResponse(body={"token": "AIzaSomethingElse"})])

    out = relay_auth.deliver_callback(secrets, "CODE", "SID")

    assert out["ok"] is False
    assert secrets.get("provider:gemini") is None


def test_deliver_callback_keeps_a_hidden_base_url_override(secrets, config, monkeypatch):
    secrets.put("provider:gemini", {"base_url": "https://pinned.example"})
    _begin(config, monkeypatch)
    _capture_post(monkeypatch, [FakeResponse(body={"token": "owr_abc123", "email": "a@b.com"})])

    relay_auth.deliver_callback(secrets, "CODE", "SID")

    assert secrets.get("provider:gemini")["base_url"] == "https://pinned.example"


def test_deliver_callback_keeps_the_persons_own_api_key(secrets, config, monkeypatch):
    """Signing in must not disturb the credential Google bills — they are independent, and
    clobbering the key here would silently break the very call the login was meant to enable."""
    secrets.put("provider:gemini", {"api_key": "AIza-mine"})
    _begin(config, monkeypatch)
    _capture_post(monkeypatch, [FakeResponse(body={"token": "owr_abc123", "email": "a@b.com"})])

    relay_auth.deliver_callback(secrets, "CODE", "SID")

    profile = secrets.get("provider:gemini")
    assert profile["api_key"] == "AIza-mine"
    assert profile["relay_token"] == "owr_abc123"


# --- status and sign-out ---------------------------------------------------------------


def test_status_is_signed_out_without_a_token(secrets):
    out = relay_auth.status(secrets)
    assert out["signed_in"] is False
    assert out["relay"] == RELAY


def test_status_reads_the_stored_identity_without_touching_the_network(secrets, monkeypatch):
    secrets.put(
        "provider:gemini",
        {
            "relay_token": "owr_abc123",
            "api_key": "AIza-mine",
            "relay_email": "alice@example.com",
            "relay_name": "张三",
            "relay_base_url": RELAY,
        },
    )
    monkeypatch.setattr(
        relay_auth.httpx, "get", lambda *a, **k: pytest.fail("must not call the relay")
    )

    out = relay_auth.status(secrets)

    assert out["signed_in"] is True
    assert out["email"] == "alice@example.com"
    assert out["stale_relay"] is False
    assert out["has_api_key"] is True


def test_status_reports_a_signed_in_person_with_no_key_of_their_own(secrets, monkeypatch):
    """Half-configured is the likeliest state right after a first sign-in. The pane has to
    be able to say which half, or the symptom is a 400 mentioning a key nobody asked for."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    secrets.put("provider:gemini", {"relay_token": "owr_abc123", "relay_base_url": RELAY})

    out = relay_auth.status(secrets)

    assert out["signed_in"] is True
    assert out["has_api_key"] is False


def test_status_flags_a_token_issued_by_a_different_relay(secrets):
    secrets.put(
        "provider:gemini", {"relay_token": "owr_abc123", "relay_base_url": "https://old.example"}
    )
    assert relay_auth.status(secrets)["stale_relay"] is True


def test_verify_drops_a_revoked_token(secrets, monkeypatch):
    secrets.put(
        "provider:gemini", {"relay_token": "owr_abc123", "relay_email": "gone@example.com"}
    )
    monkeypatch.setattr(
        relay_auth.httpx, "get", lambda *a, **k: FakeResponse(status_code=403, body={})
    )

    out = relay_auth.status(secrets, verify=True)

    # Leaving it on disk would show "signed in" and then 403 on the first message.
    assert out["signed_in"] is False
    assert out["verify_error"]
    assert secrets.get("provider:gemini") is None


def test_verify_drops_the_token_but_not_the_key(secrets, monkeypatch):
    """Being removed from the roster says nothing about the person's own Google key. Wiping
    it would make re-admitting them a re-onboarding."""
    secrets.put("provider:gemini", {"relay_token": "owr_abc123", "api_key": "AIza-mine"})
    monkeypatch.setattr(
        relay_auth.httpx, "get", lambda *a, **k: FakeResponse(status_code=401, body={})
    )

    relay_auth.status(secrets, verify=True)

    assert secrets.get("provider:gemini") == {"api_key": "AIza-mine"}


def test_verify_refreshes_display_fields(secrets, monkeypatch):
    secrets.put(
        "provider:gemini",
        {"relay_token": "owr_abc123", "relay_email": "a@b.com", "relay_dept": "旧部门"},
    )
    quota = {
        "limits": {"rpm": 30, "rpd": 1200, "tpd": 5000000},
        "used": {"minuteRequests": 1, "dayRequests": 12, "dayTokens": 34567},
        "resets_in": 3600,
    }
    monkeypatch.setattr(
        relay_auth.httpx,
        "get",
        lambda *a, **k: FakeResponse(
            body={"email": "a@b.com", "name": "张三", "dept": "新部门", "quota": quota}
        ),
    )

    out = relay_auth.status(secrets, verify=True)

    assert out["signed_in"] is True
    assert out["dept"] == "新部门"
    # The relay is the only thing that knows the counters; verify is when they arrive.
    assert out["quota"] == quota


def test_verify_keeps_the_token_when_the_relay_is_unreachable(secrets, monkeypatch):
    import httpx as _httpx

    secrets.put("provider:gemini", {"relay_token": "owr_abc123"})

    def boom(*args, **kwargs):
        raise _httpx.ConnectError("no route")

    monkeypatch.setattr(relay_auth.httpx, "get", boom)

    out = relay_auth.status(secrets, verify=True)

    # A flaky network is not a revocation — signing the user out here would be wrong.
    assert out["signed_in"] is True
    assert "verify_error" in out
    assert secrets.get("provider:gemini")["relay_token"] == "owr_abc123"


def test_logout_clears_the_token_and_survives_an_unreachable_relay(secrets, monkeypatch):
    import httpx as _httpx

    secrets.put("provider:gemini", {"relay_token": "owr_abc123", "relay_email": "a@b.com"})

    def boom(*args, **kwargs):
        raise _httpx.ConnectError("no route")

    monkeypatch.setattr(relay_auth.httpx, "post", boom)

    assert relay_auth.logout(secrets)["ok"] is True
    assert secrets.get("provider:gemini") is None


def test_logout_leaves_the_persons_own_key_alone(secrets, monkeypatch):
    """Signing out is not the same as throwing a credential away."""
    secrets.put("provider:gemini", {"relay_token": "owr_abc123", "api_key": "AIza-mine"})
    monkeypatch.setattr(relay_auth.httpx, "post", lambda *a, **k: FakeResponse(body={"ok": True}))

    assert relay_auth.logout(secrets)["ok"] is True
    assert secrets.get("provider:gemini") == {"api_key": "AIza-mine"}
