"""Serve the deterministic Browser live-test fixture on localhost only."""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


FIXTURE_ROOT = Path(__file__).with_name("fixture")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the fixture server."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8876)
    return parser.parse_args()


def main() -> None:
    """Run the fixture server until the GUI task stops it."""
    args = parse_args()
    handler = partial(SimpleHTTPRequestHandler, directory=FIXTURE_ROOT)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"BROWSER_FIXTURE_READY http://127.0.0.1:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
