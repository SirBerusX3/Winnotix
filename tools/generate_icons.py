#!/usr/bin/env python3
"""Derive the bundled icon resources from the masters in `assets/`.

`assets/` holds the artwork as drawn -- 2048x2048 PNGs and a Windows .ico with
the full 16..256 size ladder, in a blue and a grey variant. `resources/` holds
only what the app loads at run time, so the two are kept apart and this script
is the link between them.

    python tools/generate_icons.py

Two outputs:

* `resources/appicon.ico` -- the blue mark, used for the window, the task bar
  and Alt-Tab, and by PyInstaller when Phase 4 arrives. Copied rather than
  regenerated: the .ico already carries every size Windows asks for.
* `resources/generic_tv_logo.png` -- the grey mark, shown for a channel whose
  playlist gives no logo, or whose logo will not load. Downscaled to
  :data:`PLACEHOLDER` from the 2048px master.

The file it replaces was Hypnotix's own logo, byte-identical to upstream's, at
22x22 -- so every VOD poster was a 9x upscale of a 22px image. Roadmap section 8
asks that we not ship Mint's icon set; this is that, and it fixes the blur.

Uses Qt rather than Pillow so it runs in the project venv with no extra
dependency.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtCore import Qt

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
RESOURCES = ROOT / "resources"

#: Large enough that the 200x200 VOD poster is a downscale even on a HiDPI
#: screen at devicePixelRatio 2, which wants 400px. Never an upscale, which is
#: the defect being fixed.
PLACEHOLDER = 512


def main() -> int:
    # QImage resolves its format plugins through a Qt application object. It
    # needs no display, so this runs headless under QT_QPA_PLATFORM=offscreen.
    app = QGuiApplication(sys.argv)  # noqa: F841 -- kept alive for QImage

    missing = [p for p in (ASSETS / "appicon.ico", ASSETS / "appiconfullresG.png")
               if not p.is_file()]
    if missing:
        raise SystemExit("missing masters: "
                         + ", ".join(str(p.relative_to(ROOT)) for p in missing))

    RESOURCES.mkdir(parents=True, exist_ok=True)

    shutil.copyfile(ASSETS / "appicon.ico", RESOURCES / "appicon.ico")
    print("copied   resources/appicon.ico")

    master = QImage(str(ASSETS / "appiconfullresG.png"))
    if master.isNull():
        raise SystemExit("could not read assets/appiconfullresG.png")
    scaled = master.scaled(
        PLACEHOLDER, PLACEHOLDER,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    out = RESOURCES / "generic_tv_logo.png"
    if not scaled.save(str(out), "PNG"):
        raise SystemExit(f"could not write {out}")
    print(f"wrote    resources/generic_tv_logo.png "
          f"({scaled.width()}x{scaled.height()}, {out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
