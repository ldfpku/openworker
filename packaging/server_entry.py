"""PyInstaller entry point for the bundled desktop sidecar server.

Thin wrapper so PyInstaller has a concrete script to analyze (the console_script
`openworker-server` is generated metadata, not a file). Runs the same `main()`.
"""

import os

# The cryptography library looks for OpenSSL's legacy-algorithms module and warns on
# every start when it is not there ("OpenSSL 3's legacy provider failed to load"); the
# Intel Mac build, with OpenSSL linked in statically, has no such module. OpenWorker
# uses no legacy algorithm, so tell it not to look. Set before any coworker import:
# cryptography reads it when its OpenSSL binding is first loaded.
os.environ.setdefault("CRYPTOGRAPHY_OPENSSL_NO_LEGACY", "1")

from coworker.server.run import main  # noqa: E402

if __name__ == "__main__":
    main()
