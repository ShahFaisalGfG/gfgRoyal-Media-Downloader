# host_entry.py - entry point of gfgRoyal-Media-Downloader-host.exe, the companion's native host

import sys

from gfgmd.services.companion import run


def main() -> int:
    """Serve the browser extension over stdin and stdout."""
    return run(sys.argv, sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":
    sys.exit(main())
