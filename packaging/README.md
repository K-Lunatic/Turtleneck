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

## Signing requirements

Unsigned artifacts are only for CI validation. A public release must have:

- macOS Developer ID Application certificate and notarization credentials:
  `APPLE_CERTIFICATE_BASE64`, `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`,
  `APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_APP_PASSWORD`.
- Windows Authenticode certificate:
  `WINDOWS_PFX_BASE64`, `WINDOWS_PFX_PASSWORD`, and optionally
  `WINDOWS_TIMESTAMP_URL`.

The release workflow fails rather than publishing unsigned public artifacts when
these secrets are missing.
