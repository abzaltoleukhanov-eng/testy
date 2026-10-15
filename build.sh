#!/usr/bin/env bash
# Собирает скиллы в .zip для загрузки в claude.ai (Settings → Capabilities → Skills).
# Общие файлы из skills/shared копируются в references/ каждого скилла.
set -euo pipefail
cd "$(dirname "$0")"
rm -rf dist build && mkdir -p dist build
for skill in creative-research media-buying-analyst; do
  cp -r "skills/$skill" "build/$skill"
  cp skills/shared/*.md "build/$skill/references/"
  (cd build && zip -qr "../dist/$skill.zip" "$skill")
done
rm -rf build
ls -1 dist
