# PyInstaller spec for Dragognosificator single-file executable.
#
# Build on the OS you are targeting (a Windows .exe must be built on Windows):
#     pyinstaller dredge_standalone/packaging/dragognosificator.spec
#
# Or double-click / run:
#     dredge_standalone/packaging/build_windows.bat
#
# Produces dist/Dragognosificator.exe (Windows) or dist/Dragognosificator
# (macOS/Linux).  No GDAL/geopandas — GeoPackage export uses the built-in
# sqlite writer, so no special PyInstaller hooks are required.
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
    name="Dragognosificator",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    onefile=True,
)
