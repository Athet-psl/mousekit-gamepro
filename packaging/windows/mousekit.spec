# PyInstaller spec: dist/Mousekit/ with mousekit.exe (the app) and mousekitd.exe (the service), sharing one runtime.
# Built by packaging/windows/build.ps1.
from pathlib import Path

root = Path(SPECPATH).parent.parent
icon = str(root / "data" / "mousekit.ico")
datas = [(str(root / "mousekit" / "assets" / name), "mousekit/assets") for name in ("gm500w.png", "mousekit.png")]
excludes = ["evdev", "dbus", "tkinter", "unittest", "pydoc", "PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.QtPdf",
            "PyQt6.QtSvg", "PyQt6.QtOpenGL", "PyQt6.QtMultimedia", "PyQt6.QtWebEngineCore"]

app = Analysis([str(root / "packaging" / "windows" / "app.py")], pathex=[str(root)], datas=datas,
               hiddenimports=["mousekit.winservice", "mousekit.winnotify"], excludes=excludes)
service = Analysis([str(root / "packaging" / "windows" / "service.py")], pathex=[str(root)],
                   hiddenimports=["mousekit.winnotify", "mousekit.winservice"], excludes=excludes + ["PyQt6"])

# Not needed by a widgets app: the software OpenGL fallback (20 MB) and Qt's translations.
app.binaries = [b for b in app.binaries if "opengl32sw" not in b[0].lower()]
app.datas = [d for d in app.datas if "translations" not in d[0].replace("\\", "/").split("/")]

app_exe = EXE(PYZ(app.pure), app.scripts, [], exclude_binaries=True, name="mousekit", icon=icon,
              console=False, version=str(root / "build" / "version-info.txt"))
service_exe = EXE(PYZ(service.pure), service.scripts, [], exclude_binaries=True, name="mousekitd", icon=icon,
                  console=False, version=str(root / "build" / "version-info.txt"))
COLLECT(app_exe, app.binaries, app.datas, service_exe, service.binaries, service.datas, name="Mousekit")
