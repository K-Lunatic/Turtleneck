@echo off
setlocal
set "ROOT=%~dp0"

where py >nul 2>&1
if not errorlevel 1 (
  py -3 %*
  exit /b %errorlevel%
)

where python >nul 2>&1
if not errorlevel 1 (
  python %*
  exit /b %errorlevel%
)

echo Python 3가 설치되어 있지 않아요. Python 3.10 이상을 설치한 뒤 다시 실행해 주세요.
echo 설치 안내: https://www.python.org/downloads/
exit /b 1
