#!/usr/bin/env python3
"""Start the command-line tool from a checkout, without installing the package."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "src"))

from goat_transformers.cli import main  # noqa: E402

sys.exit(main())
