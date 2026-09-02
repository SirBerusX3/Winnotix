"""A wrapping layout, standing in for GtkFlowBox.

Qt ships no equivalent, and the three upstream FlowBoxes (categories, VOD,
providers) all rely on reflowing to the available width. This is the standard
height-for-width layout: place items left to right, wrap when the row is full.

One addition upstream has no equivalent for: a widget carrying the `SPANS_ROW`
property takes a row to itself, at the full width available. A flow of equal
tiles otherwise has nowhere to put a label that introduces the tiles beneath
it, which is what the playlist picker needs to show where one source's
playlists end and the next source's begin.
"""

from __future__ import annotations

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout


#: Set this property on a widget to give it a row of its own, spanning the
#: full width: ``widget.setProperty(SPANS_ROW, True)``.
SPANS_ROW = "flowSpansRow"


def _spans_row(item) -> bool:
    widget = item.widget()
    return widget is not None and bool(widget.property(SPANS_ROW))


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin: int = 0, spacing: int = 10) -> None:
        super().__init__(parent)
        self._items: list = []
        self.setContentsMargins(QMargins(margin, margin, margin, margin))
        self.setSpacing(spacing)

    def __del__(self) -> None:
        while self.count():
            self.takeAt(0)

    # -- QLayout plumbing ----------------------------------------------

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._layout(rect, apply=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(),
                            margins.top() + margins.bottom())

    # -- placement -----------------------------------------------------

    def _layout(self, rect: QRect, apply: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(),
                                  -margins.right(), -margins.bottom())
        x, y = effective.x(), effective.y()
        row_height = 0
        spacing = self.spacing()
        # Whether the item just placed took the whole row, in which case the
        # next one starts a new row however much space appears to be left.
        after_span = False

        for item in self._items:
            # A hidden widget takes no space, the way it does in Qt's own
            # layouts. Without this a filtered grid keeps a gap where every
            # hidden tile used to be.
            if item.isEmpty():
                continue
            hint = item.sizeHint()
            spans = _spans_row(item)
            width = effective.width() if spans else hint.width()

            if row_height > 0 and (spans or after_span
                                   or x + width > effective.right()):
                x = effective.x()
                y = y + row_height + spacing
                row_height = 0

            # A spanning item is being given a width it did not ask for, so its
            # own height for that width is the one to use -- a word-wrapped
            # label reports a height for its natural width otherwise.
            height = (item.heightForWidth(width) if spans and item.hasHeightForWidth()
                      else hint.height())
            if apply:
                item.setGeometry(QRect(QPoint(x, y), QSize(width, height)))
            x = x + width + spacing
            row_height = max(row_height, height)
            after_span = spans

        return y + row_height - rect.y() + margins.bottom()
