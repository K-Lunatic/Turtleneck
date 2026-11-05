# Turtleneck desktop release

The desktop bundle is an onedir PyInstaller artifact. It contains its own Python
runtime, but keeps credentials, SQLite databases, cached files and session data
outside the bundle in `~/.university-agent` (macOS) or `%USERPROFILE%\\.university-agent`
(Windows).

## Local unsigned validation

```bash
python3 -m pip install pyinstaller==6.11.1
pyinstaller packaging/turtleneck.spec --noconfirm --clean
dist/turtleneck/turtleneck --version
```

The public release workflow runs the same build on macOS and Windows. It does
not call the network, school login, or a real account during packaging tests.

## Public release policy

Public desktop artifacts are intentionally unsigned. macOS may block the first launch
with a Gatekeeper warning, and Windows may show a SmartScreen warning. Verify the
published SHA-256 file before extracting and use only a copy obtained from the official
repository release.
