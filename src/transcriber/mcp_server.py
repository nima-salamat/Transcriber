"""Standalone entry point: python -m transcriber.mcp_server."""

from transcriber.mcp.server import main

if __name__ == "__main__":
    raise SystemExit(main())
