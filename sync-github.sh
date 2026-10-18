#!/usr/bin/env bash
# 网络恢复后，运行本脚本把本地 main 分支与 GitHub 远程对齐。
# 用法：在 Git Bash 里执行  ./sync-github.sh
set -e

# 有未提交改动时先停下来，避免 reset --hard 误删
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "检测到未提交的改动，请先提交或暂存（git stash）后再运行本脚本。"
  exit 1
fi

echo "正在从 GitHub 拉取最新状态..."
git fetch origin

echo "将本地 main 重置为 origin/main（内容相同，不会丢失）..."
git reset --hard origin/main

echo "对齐完成，当前状态："
git status
