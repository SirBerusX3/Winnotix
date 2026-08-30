"""Marshal calls onto the Qt GUI thread.

This is the Qt equivalent of ``GObject.idle_add``, which upstream Hypnotix uses
in ``common.py:34`` to let background download/parse threads touch widgets.

A queued signal connection is the right primitive: a signal emitted from a worker
thread onto a QObject that lives on the GUI thread is delivered on the GUI
thread's event loop. ``QTimer.singleShot`` is *not* a substitute -- called from a
worker thread it would start a timer on that thread instead.

The invoker must be constructed on the GUI thread, hence the explicit
:func:`init` rather than module-import-time construction.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

_invoker: "_Invoker | None" = None


class _Invoker(QObject):
    # `object` rather than `tuple` for the args payload: PySide6 marshals a
    # plain Python object through without attempting a C++ type conversion.
    invoke = Signal(object, object)

    def __init__(self) -> None:
        super().__init__()
        self.invoke.connect(self._run)

    @staticmethod
    def _run(func, args) -> None:
        func(*args)


def init() -> None:
    """Call once from the GUI thread, after the QApplication exists."""
    global _invoker
    if _invoker is None:
        _invoker = _Invoker()


def run_on_main_thread(func, args=()) -> None:
    if _invoker is None:
        raise RuntimeError(
            "winnotix.core.mainthread.init() must be called on the GUI thread "
            "before any background thread schedules work."
        )
    _invoker.invoke.emit(func, args)
