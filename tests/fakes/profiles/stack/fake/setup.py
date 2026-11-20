#!/usr/bin/env python3
"""档案 fake 的装依赖（在受限环境里、工作目录里跑，3-58）。每装一次在 .fake-deps/installed.log 记一行，测试按行数数装了几次。
.fake-deps/ 里放一个忽略一切的 .gitignore，像 node_modules 那样被 Git 忽略，工作区还是干净的。"""
import os
import time

os.makedirs('.fake-deps', exist_ok=True)
with open('.fake-deps/.gitignore', 'w') as f:
    f.write('*\n')
with open('.fake-deps/installed.log', 'a') as f:
    f.write(f'{time.time()}\n')
