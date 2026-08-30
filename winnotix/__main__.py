"""Winnotix entry point.  Run with:  python -m winnotix"""

from __future__ import annotations

import locale
import sys

from PySide6.QtWidgets import QApplication

from .core import mainthread
from .core.paths import APP_NAME, ensure_dirs


def main() -> int:
    ensure_dirs()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)

    # libmpv requires LC_NUMERIC="C". Qt sets the process locale from the system
    # on startup, and on a locale that uses comma as the decimal separator that
    # makes libmpv misparse its own float options. Must be reset *after* the
    # QApplication is constructed, or Qt overwrites it again.
    locale.setlocale(locale.LC_NUMERIC, "C")

    # Must happen on the GUI thread before any @idle_function fires.
    mainthread.init()

    # Imported late: this pulls in libmpv, and a load failure should surface
    # after the QApplication exists so it can be reported properly.
    from .ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
