#!/bin/bash
# 假的项目检查：仓库里有 BROKEN 文件就不通过
if [ -e BROKEN ]; then echo "项目检查：发现 BROKEN，不通过"; exit 1; fi
echo "项目检查：通过"
