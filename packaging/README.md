# Turtleneck desktop release

The desktop bundle is an onedir PyInstaller artifact. It contains its own Python
runtime, but keeps credentials, SQLite databases, cached files and session data
outside the bundle in `~/.university-agent` (macOS) or `%USERPROFILE%\\.university-agent`
(Windows).

## Local unsigned validation

```bash
python3 -m pip install pyinstaller==6.11.1
python3 -m pip install -r packaging/desktop-requirements.txt
pyinstaller packaging/turtleneck.spec --noconfirm --clean
dist/turtleneck/turtleneck --version

# 메뉴 바(macOS)·알림 영역(Windows) 보조 앱
dist/turtleneck/turtleneck companion

# 시험지·점수 대시보드만 열기
dist/turtleneck/turtleneck companion --dashboard

# macOS 메뉴 바 앱으로 실행하려면
pyinstaller packaging/companion.spec --noconfirm --clean
open "dist/Turtleneck Companion.app"

# Windows 알림 영역 앱으로 실행하려면
pyinstaller packaging/companion.spec --noconfirm --clean
dist/companion/turtleneck-companion.exe
```

The public release workflow runs the same companion build on macOS and Windows.
macOS places it in a menu bar app bundle and Windows places it in a notification-area
executable; both expose the same local dashboard, profile summary and login flow.
It does
not call the network, school login, or a real account during packaging tests.

## Public release policy

Public desktop artifacts are intentionally unsigned because no Apple Developer or
Windows code-signing certificate is currently used. macOS may block the first launch
with a Gatekeeper warning, and Windows may show a SmartScreen warning. This means the
operating system cannot verify the publisher signature; it is not a missing-Python
error and it is not proof that the file is safe.

Before extracting or running, confirm that the file came from the official repository
release and compare its SHA-256 value with the published `.sha256` file. Stop if the
checksum differs or the source is unclear.

The companion is optional. It reads profile markers, local file counts and saved exam
summary fields only; it does not display passwords, cookies, session values or exam
question bodies. Its dashboard is loopback-only and uses a per-run access token. The
academic skill remains usable if the companion is not installed.
