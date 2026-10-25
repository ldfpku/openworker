"""Agent coworker platform runtime (codename: coworker)."""

# Every application entry point imports this package before constructing an SDK client.
# Normalize the Windows proxy-tool spelling here so OAuth, model calls, and connectors all
# get the same fix instead of each client needing its own workaround.
from .proxy_env import normalize_no_proxy

normalize_no_proxy()

try:
    # Generated at packaging time by packaging/write_version.py from the Tauri app
    # version (surfaces/gui/src-tauri/tauri.conf.json) — gitignored, not present in a
    # plain checkout. See that script's docstring for why this exists.
    from ._version import __version__
except ImportError:
    __version__ = "dev"
