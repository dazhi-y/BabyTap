#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="${PROJECT_DIR}/app/native/BabyTapTranscriber"
APP_DIR="${PROJECT_DIR}/app/.native/BabyTapTranscriber.app"
MACOS_DIR="${APP_DIR}/Contents/MacOS"

mkdir -p "${MACOS_DIR}"
cp "${SOURCE_DIR}/Info.plist" "${APP_DIR}/Contents/Info.plist"
swiftc -O -framework Speech \
  "${SOURCE_DIR}/main.swift" \
  -o "${MACOS_DIR}/BabyTapTranscriber"
codesign --force --sign - --identifier local.babytap.transcriber "${APP_DIR}" >/dev/null
echo "${MACOS_DIR}/BabyTapTranscriber"
