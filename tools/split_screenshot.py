#!/usr/bin/env python3
"""Composite two screenshots of the same window into one diagonally split image.

    python tools/split_screenshot.py assets/screenshot-light.png \\
                                     assets/screenshot-dark.png \\
                                     assets/splitexample.png

Used for the README image that shows both themes at once. Take the two captures
with the theme button in the header, without moving or resizing the window and
with playback paused, so the only difference between them is the theme -- the
video frame has to be identical or the seam shows.

**The cut starts at the sidebar edge rather than the window corner.** A
corner-to-corner diagonal slices through the top of the channel list, which
reads as a rendering fault; starting at the boundary the app already draws
leaves the list whole, crosses the header where there is empty space between
the title and the buttons, and crosses the video where the two frames are
identical and the seam is invisible.
"""

from __future__ import annotations

import argparse
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import (QBrush, QColor, QGuiApplication, QImage, QPainter,
                           QPainterPath, QPen, QPixmap)

#: Where the sidebar meets the player at the window's default width.
DEFAULT_TOP_X = 345


def split(base_path: str, overlay_path: str, out_path: str,
          top_x: int = DEFAULT_TOP_X, divider: str | None = None) -> None:
    """Draw `overlay` right of the diagonal, over `base`."""
    base = QImage(base_path)
    overlay = QPixmap(overlay_path)
    if base.isNull() or overlay.isNull():
        raise SystemExit("could not read one of the images")
    if base.size() != overlay.size():
        raise SystemExit(
            f"the captures differ in size: {base.width()}x{base.height()} vs "
            f"{overlay.width()}x{overlay.height()}. Take both without resizing "
            "the window."
        )

    width, height = base.width(), base.height()
    result = QImage(base)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    path = QPainterPath()
    path.moveTo(top_x, 0)
    path.lineTo(width, 0)
    path.lineTo(width, height)
    path.closeSubpath()
    painter.setPen(Qt.PenStyle.NoPen)
    # A texture brush aligns to the origin, so the overlay lands exactly where
    # it would have been drawn whole.
    painter.setBrush(QBrush(overlay))
    painter.drawPath(path)

    if divider:
        pen = QPen(QColor(divider))
        pen.setWidthF(1.4)
        painter.setPen(pen)
        painter.drawLine(top_x, 0, width, height)
    painter.end()

    if not result.save(out_path):
        raise SystemExit(f"could not write {out_path}")
    print(f"{out_path}  ({width}x{height})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base", help="the capture kept on the lower left")
    parser.add_argument("overlay", help="the capture drawn on the upper right")
    parser.add_argument("out", help="where to write the composite")
    parser.add_argument("--top-x", type=int, default=DEFAULT_TOP_X,
                        help=f"where the cut meets the top edge (default {DEFAULT_TOP_X})")
    parser.add_argument("--divider", metavar="COLOUR", default=None,
                        help="draw a hairline along the cut, e.g. #9aa0a6")
    args = parser.parse_args(argv)

    # QImage needs a Qt application before it will render anything.
    QGuiApplication(sys.argv[:1])
    split(args.base, args.overlay, args.out, args.top_x, args.divider)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
