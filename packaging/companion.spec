# Native menu-bar/notification-area app for the optional Turtleneck companion.
from pathlib import Path
import sys

from PyInstaller.building.build_main import Analysis, EXE, PYZ
if sys.platform == "darwin":
    from PyInstaller.building.osx import BUNDLE
from PyInstaller.utils.hooks import collect_all


ROOT = Path(SPEC).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "university-agent"))
datas, binaries, hiddenimports = [], [], ["pystray", "PIL", "PIL.Image", "sqlite3", "zoneinfo", "zoneinfo._common", "zoneinfo._tzpath"]
# Companion status/dashboard imports are discovered from companion.py. Avoid
# shipping every study and provider module in the tray process; the main CLI
# owns those heavy workflows.
# The companion never parses documents or converts media itself. Keeping those
# runtimes out avoids a large cold-start archive; the main CLI owns them.
for package in ("webview",):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hiddenimports)
datas.extend([
    (str(ROOT / "skills" / "university-agent"), "skills/university-agent"),
    (str(ROOT / "skills" / "university-agent" / "assets" / "turtleneck.png"), "assets"),
    (str(ROOT / "skills" / "university-agent" / "assets" / "companion.html"), "assets"),
])

a = Analysis(
    [str(ROOT / "skills" / "university-agent" / "scripts" / "companion.py")],
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
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="turtleneck-companion", console=False)
if sys.platform == "darwin":
    BUNDLE(
        exe,
        name="Turtleneck Companion.app",
        bundle_identifier="org.k-lunatic.turtleneck.companion",
        info_plist={"LSUIElement": True},
    )
