#!/bin/bash
# 主控窗口用：只记本机关键文件的大小和修改时间，不读内容。
for f in ~/.bashrc ~/.profile ~/.gitconfig ~/.ssh ~/.ssh/known_hosts ~/.config/gh ~/.config/gh/hosts.yml ~/.claude/CLAUDE.md ~/.codex/AGENTS.md ~/.pi/agent ~/.pi/agent/install ~/.config/uv ~/tools/docker ~/tools/docker/data ~/tools/wt/.git; do
  [ -e "$f" ] && stat -c '%n %s %Y' "$f" || echo "$f 不存在"
done
ls -1 ~/tools | grep -v '^sop$' | sed 's/^/tools顶层: /'
ls -1 ~/tools/sop | sed 's/^/tools\/sop: /'
