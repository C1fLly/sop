#!/usr/bin/env bash
# 给用户亲手试：在受限环境里打开 Claude Code 的对话窗口，接着上一次的会话。
# 用法：在你自己的终端里执行  bash /tmp/sop-spike-s9/chat.sh
# 可以试：打几句中文、按 Ctrl-C 打断、把窗口拉大拉小、输入 /exit 退出。
cd /tmp/sop-spike-s9/chat
TOOL=claude INTERACTIVE=1 STATE=/tmp/sop-spike-s9/state-chat exec /tmp/sop-spike-ai/sbx.sh /tmp/sop-spike-s9/chat --continue
