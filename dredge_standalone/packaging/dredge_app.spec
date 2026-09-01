# PyInstaller spec for the Dredge App single-file executable.
#
# Build (from any directory, on the OS you are targeting):
#     pyinstaller path/to/dredge_standalone/packaging/dredge_app.spec
#
# Produces dist/DredgeApp (or DredgeApp.exe on Windows). Since the app has no
# GDAL/geopandas dependency (GeoPackage export uses the built-in sqlite
# writer), no special hooks or data-file workarounds are required beyond
# PyInstaller's stock PySide6 / pyproj hooks.
import os

root = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

a = Analysis(
    [os.path.join(SPECPATH, "pyinstaller_entry.py")],
    pathex=[root],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Heavy Qt modules the app never uses — keeps the exe smaller.
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuick3D",
        "PySide6.QtQuickWidgets",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DRender",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtBluetooth",
        "PySide6.QtNfc",
        "PySide6.QtPositioning",
        "PySide6.QtLocation",
        "PySide6.QtSensors",
        "PySide6.QtSerialPort",
        "PySide6.QtWebChannel",
        "PySide6.QtWebSockets",
        "PySide6.QtRemoteObjects",
        "PySide6.QtTextToSpeech",
        "PySide6.QtDesigner",
        "PySide6.QtHelp",
        "PySide6.QtTest",
        # Non-Qt extras
        "tkinter",
        "matplotlib",
        "IPython",
        "jupyter",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DredgeApp",
    debug=False,
    strip=False,
    upx=False,
    console=False,       # no console window (pythonw-style)
    onefile=True,
)
