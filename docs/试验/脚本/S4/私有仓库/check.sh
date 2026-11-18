#!/usr/bin/env bash
# 试验用的「项目检查」：代表 PR 里的项目代码。文件 BROKEN 存在就不通过。
set -u
echo "PROJECT_CHECK_VERSION=v1"
if [ -e BROKEN ]; then echo "检查不通过：发现 BROKEN 文件"; exit 1; fi
echo "检查通过"
