#!/bin/bash
# 第 1 期第一段：装虚拟机软件。要管理员密码，由用户本人在自己的终端里执行。
set -euo pipefail
cat <<'TXT'

要装什么：虚拟机软件 QEMU 的两个软件包（qemu-system-x86、qemu-utils），
          连同它们依赖的十几个小软件包。
装在哪：  系统盘上，系统软件包的默认位置，一共几百 MB。
          虚拟机的磁盘文件以后放在 ~/sop-vm/，在主目录那个分区上，不占系统盘。
不会做的：不改 Docker，不改别的系统设置，不加开机自动运行的服务。
用来做什么：只用来验证 SOP 工具包本身，用完可以卸掉。

接下来会请你输入管理员密码（输入时屏幕上不显示字，这是正常的）。
TXT
read -r -p "继续请按回车；不装请按 Ctrl-C：" _
sudo apt-get update
sudo apt-get install -y --no-install-recommends qemu-system-x86 qemu-utils
echo
echo "装好了：$(qemu-system-x86_64 --version | head -1)"
echo "可以关掉这个终端，回到对话里告诉我「装好了」。"
