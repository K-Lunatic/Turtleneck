# PyInstaller onedir bundle. The Python runtime is included; user data remains external.
from pathlib import Path

from PyInstaller.building.build_main import Analysis, COLLECT, EXE, PYZ


ROOT = Path(SPEC).resolve().parents[1]
datas = [
    (str(ROOT / "skills"), "skills"),
    (str(ROOT / "server"), "server"),
    (str(ROOT / "plugin.json"), "."),
    (str(ROOT / ".claude-plugin"), ".claude-plugin"),
    (str(ROOT / "README.md"), "."),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "SECURITY.md"), "."),
]


a = Analysis(
    [str(ROOT / "packaging" / "turtleneck_cli.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="turtleneck", console=True)
COLLECT(exe, a.binaries, a.datas, name="turtleneck")
