#!/bin/bash
# 往规定位置那份 nvm 的默认 Node 下装 pnpm（tools.toml：pnpm 在 ~/tools/nvm 下）。
# pnpm 的包仓库、缓存、状态的位置由环境里 pnpm_config_ 开头的变量指定（W36），npm 的缓存由 npm_config_cache 指定。
# SOP_PNPM_VERSION 可以指定版本，不给就装最新的。
. "$(dirname "$0")/lib.sh"
use_nvm
nvm use --silent default || die "规定位置的 nvm 还没有默认的 Node，要先装 Node"
npm install -g --no-fund --no-audit "pnpm@${SOP_PNPM_VERSION:-latest}" || die "npm 装不上 pnpm"
"$NVM_BIN/pnpm" --version || die "装完了却运行不了 pnpm"
