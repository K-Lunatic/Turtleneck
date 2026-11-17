# PyInstaller onedir bundle. The Python runtime is included; user data remains external.
from pathlib import Path
import sys

from PyInstaller.building.build_main import Analysis, COLLECT, EXE, PYZ
from PyInstaller.utils.hooks import collect_all, collect_submodules


ROOT = Path(SPEC).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "university-agent"))
datas = [
    (str(ROOT / "skills"), "skills"),
    (str(ROOT / "server"), "server"),
    (str(ROOT / "plugin.json"), "."),
    (str(ROOT / ".claude-plugin"), ".claude-plugin"),
    (str(ROOT / "README.md"), "."),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "SECURITY.md"), "."),
]
binaries = []
hiddenimports = ["pystray", "PIL", "PIL.Image", "sqlite3", "http", "http.cookies", "email", "email.parser", "email.policy", "wsgiref", "wsgiref.simple_server", "zoneinfo", "zoneinfo._common", "zoneinfo._tzpath"]
for package in ("features", "providers", "storage", "scripts", "server", "integrations.everytime.scripts"):
    hiddenimports.extend(collect_submodules(package))
for package in ("pypdf", "imageio_ffmpeg", "webview"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hiddenimports)


a = Analysis(
    [str(ROOT / "packaging" / "turtleneck_cli.py")],
    pathex=[str(ROOT), str(ROOT / "skills" / "university-agent")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="turtleneck", console=True)
COLLECT(exe, a.binaries, a.datas, name="turtleneck")
