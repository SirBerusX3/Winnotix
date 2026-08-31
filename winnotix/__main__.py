"""Winnotix entry point.  Run with:  python -m winnotix"""

from __future__ import annotations

import locale
import sys

from PySide6.QtWidgets import QApplication

from .core import mainthread
from .core.paths import APP_NAME, ensure_dirs

#: Windows groups task bar buttons by this, and takes the button's icon from
#: the group rather than from the window. Without it a Python-hosted app is
#: filed under python.exe and shows Python's icon next to our window's.
APP_ID = "Winnotix.Winnotix"


def _claim_taskbar_identity() -> None:
    """Tell Windows this process is Winnotix, not the Python that launched it.

    Must run before the first window exists, or the button is already grouped.
    Absent or failing -- any non-Windows host -- costs only the icon.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def main() -> int:
    ensure_dirs()
    _claim_taskbar_identity()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)

    # Set on the application, not the window, so every dialog inherits it --
    # About, the provider forms and the error boxes included.
    from .ui.icons import app_icon

    app.setWindowIcon(app_icon())

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
