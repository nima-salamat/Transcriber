"""Console-free Windows compatibility launcher for Transcriber source checkouts."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from transcriber.__main__ import main


if __name__ == "__main__":
    raise SystemExit(main())
