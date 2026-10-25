"""Compatibility for proxy environment variables used by outbound HTTP clients."""

from __future__ import annotations

import ipaddress
import os


def normalize_no_proxy() -> None:
    """Convert bracketed IPv6 entries in ``NO_PROXY`` to HTTPX's expected form.

    ``NO_PROXY=::1,[::1]`` is emitted by common Windows proxy tools. HTTPX accepts the
    first spelling but parses the brackets in the second as a port separator and raises
    ``Invalid port: ':1]'`` while constructing *any* environment-aware client. Normalize
    only entries that are exactly a bracketed IPv6 address; leave every other rule alone.
    """
    for name in ("NO_PROXY", "no_proxy"):
        raw = os.environ.get(name)
        if not raw or "[" not in raw:
            continue
        entries = []
        changed = False
        for entry in raw.split(","):
            host = entry.strip()
            if len(host) > 2 and host.startswith("[") and host.endswith("]"):
                try:
                    ipaddress.IPv6Address(host[1:-1])
                except ValueError:
                    pass
                else:
                    host = host[1:-1]
                    changed = True
            entries.append(host)
        if changed:
            os.environ[name] = ",".join(entries)
