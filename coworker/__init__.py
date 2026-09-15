"""Agent coworker platform runtime (codename: coworker)."""

try:
    # Generated at packaging time by packaging/write_version.py from the Tauri app
    # version (surfaces/gui/src-tauri/tauri.conf.json) — gitignored, not present in a
    # plain checkout. See that script's docstring for why this exists.
    from ._version import __version__
except ImportError:
    __version__ = "dev"
