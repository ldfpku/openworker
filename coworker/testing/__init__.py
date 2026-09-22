"""Test doubles and harnesses for the coworker platform.

Only imported from tests/ (pytest) — no production code path reaches it. But
packaging/openworker-server.spec carries no exclusion for it: the spec's
collect_submodules("coworker") call sweeps every coworker submodule with no
test-only filter, so this package's bytecode still ends up bundled into the
packaged desktop app alongside the rest of coworker.
"""
