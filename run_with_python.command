#!/bin/zsh
set -e
ROOT="${0:A:h}"

if command -v python3 >/dev/null 2>&1; then
  exec "$(command -v python3)" "$@"
fi

echo "Python 3가 설치되어 있지 않아요."
echo "방법 1: Python 3.10 이상 설치 후 이 실행기를 다시 열어 주세요."
echo "설치 안내: https://www.python.org/downloads/"
echo "방법 2: Python 없이 쓰려면 공식 무설치 번들을 받으세요."
echo "번들 안내: https://github.com/K-Lunatic/Turtleneck/releases"
exit 1
