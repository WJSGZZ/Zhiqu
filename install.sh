#!/usr/bin/env bash
# 安装知衢技能：把五个技能目录复制到 AI 助手的技能文件夹。
# 用法：bash install.sh              自动装到已有的 Claude Code / Codex
#       bash install.sh --update     已装过时，用新版本替换
#       bash install.sh --dir 路径    装到指定的技能文件夹
set -euo pipefail

SKILLS=(zhiqu zhiqu-grad zhiqu-career bazi zhiqu-shared)
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UPDATE=0
TARGETS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --update) UPDATE=1 ;;
    --dir) shift; TARGETS+=("${1:?--dir 后面要跟一个文件夹路径}") ;;
    -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
    *) echo "不认识的参数：$1（可用 --update、--dir 路径）"; exit 1 ;;
  esac
  shift
done

if ! command -v python3 >/dev/null 2>&1; then
  echo "没有找到 python3。请先安装 Python 3.10 或更高版本：https://www.python.org/downloads/"
  exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "Python 版本太低（需要 3.10 或更高），当前是 $(python3 -V 2>&1)。"
  exit 1
fi

if [ ${#TARGETS[@]} -eq 0 ]; then
  [ -d "$HOME/.claude" ] && TARGETS+=("$HOME/.claude/skills")
  [ -d "$HOME/.codex" ] && TARGETS+=("$HOME/.codex/skills")
fi
if [ ${#TARGETS[@]} -eq 0 ]; then
  echo "没找到 Claude Code（~/.claude）或 Codex（~/.codex）。"
  echo "装好其中一个再运行，或者用 --dir 指定你的 AI 助手读取技能的文件夹。"
  exit 1
fi

for dest in "${TARGETS[@]}"; do
  mkdir -p "$dest"
  echo "安装到 $dest"
  for s in "${SKILLS[@]}"; do
    if [ -e "$dest/$s" ] && [ $UPDATE -eq 0 ]; then
      echo "  · $s 已存在，跳过（要换成新版本，加 --update 再运行）"
      continue
    fi
    rm -rf "${dest:?}/$s"
    cp -R "$HERE/skills/$s" "$dest/$s"
    echo "  · $s"
  done
done

echo
echo "装好了。打开问卷填一份：https://wjsgzz.github.io/Zhiqu/"
echo "填完点“复制未加密版本”，粘贴给你的 AI 助手就能开始。"
