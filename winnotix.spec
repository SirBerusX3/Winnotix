# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Winnotix -- roadmap Phase 4.

Build it with `python build.py package`, which installs PyInstaller, fetches
libmpv if it is missing, and then runs this.

**One-folder, not one-file.** Roadmap section 6 calls for it and the reason is
`core/mpvloader.py`: python-mpv resolves libmpv at *import* time, so the DLL
directory has to be registered before that import happens. One-file unpacks to a
fresh temp directory on every launch, which the loader would have to chase; a
one-folder layout puts the DLL at a path the running app can reason about.

The two bundled trees land where the app already looks for them, so nothing in
the app needed changing to support being frozen:

    _internal/resources/      <- paths.resources_dir(), via sys._MEIPASS
    _internal/vendor/libmpv/  <- mpvloader._candidate_dirs(), first candidate

`paths.project_root()` already returns `sys._MEIPASS` when frozen, and
`mpvloader` already yields `Path(sys.executable).parent` as a second candidate.
Neither was written for this build; both were written in anticipation of it.
"""

import sys
from pathlib import Path

ROOT = Path(SPECPATH)

# build.py is what runs this spec, and it owns the packaging concerns -- the
# signing step, and the version resource below. Importing it here keeps the
# version in one place (winnotix/__init__.py) instead of restating it as a
# literal that would quietly go stale.
sys.path.insert(0, str(ROOT))
from build import version_resource  # noqa: E402

MPV_DLL_NAMES = ("libmpv-2.dll", "mpv-2.dll", "mpv-1.dll")

binaries = [
    (str(ROOT / "vendor" / "libmpv" / name), "vendor/libmpv")
    for name in MPV_DLL_NAMES
    if (ROOT / "vendor" / "libmpv" / name).is_file()
]
if not binaries:
    raise SystemExit(
        "no libmpv DLL in vendor/libmpv -- run: python build.py setup"
    )

# The whole resources tree: flags, category art, badges, the catalogues,
# countries.list, blocklist.json, channel_genres.json, the app icon and the
# logo placeholder.
datas = [(str(ROOT / "resources"), "resources")]

# Qt ships far more than this app uses. Excluding the large unused modules is
# worth roughly half the bundle. The list is deliberately conservative -- it
# leaves QtNetwork and QtOpenGL alone, because Qt reaches for those internally
# (TLS backends, the platform plugin) even when the app never imports them.
# A wrong exclude here fails loudly at startup with an ImportError, so if
# something is missing, take it off this list rather than hunting.
excludes = [
    "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtNfc",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2", "PySide6.QtQuickWidgets",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtTextToSpeech",
    "PySide6.QtUiTools",
    "PySide6.QtWebChannel", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets", "PySide6.QtWebSockets",
    # Not Qt: pulled in by the standard library but never used here.
    "tkinter",
    # The vendored upstream tree is reference material, not a dependency.
    "hypnotix",
]

a = Analysis(
    ["launcher.py"],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

# PyInstaller's PySide6 hook collects every Qt plugin, and two of them drag in
# trees this app never touches. The `excludes` above cannot reach these: they are
# Qt's own DLLs, gathered as data by the hook rather than found as imports.
#
#   platforminputcontexts/qtvirtualkeyboardplugin.dll -> Qt6VirtualKeyboard
#                                                     -> Qt6Qml, Qt6Quick (13 MB)
#   imageformats/qpdf.dll                             -> Qt6Pdf      (4.6 MB)
#
# Neither is reachable from this app: there is no QML, and nothing renders a PDF
# as an image. Text input works without an input-context plugin on Windows.
# The SVG plugins next to them are load-bearing -- flags and icons -- so this
# names what to drop rather than filtering plugins wholesale.
DROP_NAMES = ("Qt6Qml", "Qt6Quick", "Qt6VirtualKeyboard", "Qt6Pdf")
DROP_DIRS = ("platforminputcontexts", "imageformats/qpdf", "PySide6/qml/")


def _keep(entry) -> bool:
    dest = str(entry[0]).replace("\\", "/")
    name = dest.rsplit("/", 1)[-1]
    if name.startswith(DROP_NAMES):
        return False
    return not any(part in dest for part in DROP_DIRS)


a.binaries = [e for e in a.binaries if _keep(e)]
a.datas = [e for e in a.datas if _keep(e)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Winnotix",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX mangles Qt's DLLs often enough that the size saving is not worth the
    # class of bug it produces.
    upx=False,
    # A media player has no console output worth showing, and a console window
    # would appear behind the app on every launch.
    console=False,
    icon=str(ROOT / "resources" / "appicon.ico"),
    # Properties -> Details, Task Manager, and the heuristics that look at a
    # binary's shape rather than its contents. See build.version_resource().
    version=version_resource(),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Winnotix",
)
