"""Module entry point — enables ``python -m avbpowertool``.

Runs the same CLI parser as the ``avbpowertool`` console script: with no
arguments it launches the TUI, with arguments it runs the CLI. This is the
robust entry point on systems where ``pip3`` could not put the console
script's ``bin``/``Scripts`` directory on ``PATH``.
"""

from __future__ import annotations

import sys

from avbpowertool.presentation.cli.parser import main

if __name__ == "__main__":
    sys.exit(main())
