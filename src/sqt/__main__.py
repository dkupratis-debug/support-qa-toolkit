"""Allow `python -m sqt`."""

import sys

from sqt.cli import main

if __name__ == "__main__":
    sys.exit(main())
