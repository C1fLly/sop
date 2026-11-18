#!/usr/bin/env bash
# 用法：marks.sh <仓库> <运行编号>  —— 打印一次运行日志里的标记行
repo="$1"; id="$2"
gh run view "$id" -R "$repo" --json workflowName,event,headBranch,conclusion,headSha --jq '"# \(.workflowName) event=\(.event) head=\(.headBranch) sha=\(.headSha[0:7]) => \(.conclusion)"'
gh run view "$id" -R "$repo" --log 2>/dev/null | grep -E 'DEFINITION_MARKER=|_READABLE=|PROJECT_CHECK_VERSION=|TOKEN_CAN|workflow_ref=|workflow_sha=|event=|检查不通过|检查通过|not allowed|protection rules' | grep -v 'echo ' | sed -E 's/^[^\t]*\t[^\t]*\t[0-9TZ:.-]+ /  /'
