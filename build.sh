#!/usr/bin/env bash
# Собирает скиллы в .zip для загрузки в claude.ai (Settings → Capabilities → Skills).
# Общие файлы из skills/shared копируются в references/ каждого скилла.
# Перед упаковкой каждый скилл проверяется валидатором (frontmatter, длина описания).
# Собранные скиллы также кладутся в .claude/skills/, откуда Claude Code
# подхватывает их автоматически в любой сессии с этим репозиторием.
set -euo pipefail
cd "$(dirname "$0")"
rm -rf dist build .claude/skills && mkdir -p dist build .claude/skills
for skill in creative-strategy media-buying-analyst; do
  cp -r "skills/$skill" "build/$skill"
  cp skills/shared/*.md "build/$skill/references/"
  python3 scripts/validate_skill.py "build/$skill"
  (cd build && zip -qr "../dist/$skill.zip" "$skill")
  cp -r "build/$skill" ".claude/skills/$skill"
done
rm -rf build
ls -1 dist
