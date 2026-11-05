#!/bin/zsh
set -e
ROOT="${0:A:h}"

if command -v python3 >/dev/null 2>&1; then
  exec "$(command -v python3)" "$@"
fi

echo "Python 3가 설치되어 있지 않아요. Python 3.10 이상을 설치한 뒤 다시 실행해 주세요."
echo "설치 안내: https://www.python.org/downloads/"
exit 1
