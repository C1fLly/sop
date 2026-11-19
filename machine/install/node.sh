#!/bin/bash
# 用规定位置的 nvm 装一份 Node，设成默认的那一份（设计书 4.3：Node 由 nvm 管）。
# SOP_NODE_VERSION 可以指定版本（如 24、v26.13.1；项目的 .nvmrc 用），不给就装当前的长期支持版。
. "$(dirname "$0")/lib.sh"
use_nvm
want=${SOP_NODE_VERSION:-lts/*}
nvm install --no-progress "$want" || die "nvm 装不上 Node $want"
v=$(nvm version "$want")
[ "$v" != N/A ] || die "装完了却找不到 Node $want"
nvm alias default "$v" >/dev/null || die "设不了默认的 Node"
nvm use --silent default || die "用不了刚装的 Node"
echo "Node $v 装好了，设成默认"
