"""Regression tests for proxy environment compatibility."""

from __future__ import annotations

import os

import httpx

from coworker.proxy_env import normalize_no_proxy


def test_bracketed_ipv6_no_proxy_entries_do_not_break_httpx(monkeypatch):
    # v2rayN and similar Windows proxy tools commonly emit both spellings. HTTPX 0.28
    # accepts ::1 but raises Invalid port: ':1]' for [::1] during Client construction.
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "localhost,127.0.0.1,::1,[::1]")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:10808")
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:10808")

    normalize_no_proxy()

    assert os.environ["NO_PROXY"] == "localhost,127.0.0.1,::1,::1"
    with httpx.Client():
        pass


def test_non_ipv6_bracketed_rules_are_left_unchanged(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "example.com,[not-an-ip]")
    normalize_no_proxy()
    assert os.environ["NO_PROXY"] == "example.com,[not-an-ip]"
