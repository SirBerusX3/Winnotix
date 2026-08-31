"""Entry point for the frozen build.

PyInstaller freezes a *script*, and `winnotix/__main__.py` is not one -- its
`from .core import mainthread` only resolves when the package is imported, which
is what `python -m winnotix` does and what running the file directly does not.
This module is the one line of indirection that makes both work: development
still uses `python -m winnotix`, and the bundle uses this.

Kept at the repository root because PyInstaller resolves the entry script
relative to the spec file.
"""

from __future__ import annotations

import sys

from winnotix.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
