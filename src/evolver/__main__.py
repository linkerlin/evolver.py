"""Allow `python -m evolver`."""

import sys

from evolver.cli import main

if __name__ == "__main__":
    sys.exit(main())
