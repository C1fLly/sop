# 3-34：验收——虚拟机里迁移 `docker-ce`

主控窗口派的子代理做的（2026-11-21）。没动隔离、放行事件、事件日志；没碰 GitHub；**没调用 AI，0 美元**。sudo、装卸 docker-ce 只在虚拟机里做（用户 2026-11-19 答应过）；本机没用 sudo，没碰用户原来的 Docker 和 `~/tools/docker`。

## 做了什么

照 3-33 的验收脚本加了 docker-ce（没另起一份，两种共用）：

- `tests/vm/migrate-io.sh <虚拟机名字> [--ce] [--reboot]`：加 `--ce`。
- `tests/vm/migrate-io-guest.sh --prepare [io|ce]`：`ce` 先**造得像桌面版**（卸掉 git、curl：Ubuntu 26.04 桌面版不带，3-13 查过），写一行只管 `download.docker.com` 的 apt 代理（这台试验电脑只有经本机代理才连得上 Docker 官网；算「电脑原来的网络设置」，在记样子之前写好），记下装之前的样子，再**照 Docker 官网的步骤**装：`ca-certificates curl` → `/etc/apt/keyrings/docker.asc` → `/etc/apt/sources.list.d/docker.sources`（官网现在的 deb822 写法）→ `docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin`。之后放镜像、卷、容器，两遍迁移（Q4 打包时 kill -9 整组、下一次 `sop` 起回来；Q6 切回原来那份后暂停看、卸完核对）、重启，和 3-33 一样。装的是哪种记在 `~/io-base/kind`，后面几步照它核对。
- 两种都新加的核对：工具包自己要用的系统软件包（git、curl、wget、iptables、uidmap、dbus-user-session）卸完都还装着、git 能用、`apt-get -s autoremove` 里没有它们（以后系统清理「用不着的软件包」也不会删）。
- docker-ce 另加的核对：软件源里没有 `download.docker.com`、钥匙文件删了、`apt-cache policy` 看不到官方源的 docker-ce 和 containerd.io、`/var/lib/containerd`、`/etc/containerd`、`/opt/containerd`、`/run/containerd`、`/etc/cni`、`/var/lib/docker`、`/etc/docker` 都没了、用户组 docker 删了；apt 下载过的官方源索引执行一次 `apt-get update` 后清掉、不报错。
- 顺手改了脚本里残留清单那一行的拼接（`tr` 按字节换「，」，打出来是乱码；3-33 就有）。

## 结果

全新的虚拟机（底盘 one，Ubuntu 26.04.1，docker-ce 5:29.10.0、containerd.io 2.4.2，规定位置的 Docker 29.10.0）：

- `migrate-io.sh ce34 --ce --reboot`：**59 项全对**，2 分 25 秒。
- 还原成全新再跑 `migrate-io.sh ce34 --ce`：**55 项全对**，2 分 15 秒。
- 改过的脚本走 docker.io 那条（另建全新的 `io34`，`migrate-io.sh io34`）：**42 项全对**（3-33 的 34 项加新的 8 项），确认共用没弄坏 3-33。

验收标准逐条：

1. **照 Docker 官网装一份 docker-ce，用正式命令走通 Q1 到 Q6**：两遍 `sop machine migrate`（第一遍 Q4 打包时被 kill -9，下一次 `sop machine tools` 起回旧容器、删临时小镜像）；第二遍 Q1 认成「照 Docker 官网装的 Docker（docker-ce）」，Q2 装好规定位置的 Docker 并切回默认指向，Q4 打包试还原核对、Q5 核对，Q6 先切回原来那份（暂停时不加 sudo 敲 docker 是原来那份和 `shop-db-1`）、停服务、一个一个点名卸 7 个软件包、删目录软件源钥匙文件用户组，退出码 0；卸完敲 docker 是规定位置那份，重启后也是。
2. **软件源、钥匙文件、containerd 等残留逐项为空**：`sop` 说「残留清单 23 项逐项又看了一遍，都没有了」；脚本按 Q1 存的清单逐项自己再查也为空。23 项：containerd.io、docker-buildx-plugin、docker-ce、docker-ce-cli、docker-ce-rootless-extras、docker-compose-plugin、pigz 七个软件包，docker.service、docker.socket、containerd.service，用户组 docker，`/var/lib/docker`、`/var/lib/containerd`、`/etc/docker`、`/etc/default/docker`、`/etc/systemd/system/docker.service.d`、`/etc/containerd`、`/run/docker`、`/var/run/docker.sock`、`/opt/containerd`、`/run/containerd`、`/etc/apt/sources.list.d/docker.sources`、`/etc/apt/keyrings/docker.asc`。和装之前比：原来的软件包一个没少；多出来的是 curl（官网步骤自己装的）、git（见下）、规定位置那份要的 uidmap、libsubid5；多出来的文件里没有旧 Docker 的（只有规定位置那份的系统安全规则，和系统自己的软件目录缓存）。

带走的数据：两个卷的内容、归属 70:70（含符号链接）、权限、链接和原来一样，带着项目标签；两个镜像都在、能直接起容器；选了「不要了」的匿名卷没带。

## 验出的真问题（已改正式代码，加了单元测试）

**照官网装 docker-ce 的桌面版电脑，Q6 会把 git 一起卸掉。** docker-ce 推荐装 git（`Recommends: apparmor, ca-certificates, docker-ce-rootless-extras, git, pigz, procps, xz-utils`），桌面版本来没有 git，照官网装 docker-ce 时 git 就作为「自动装的」进来了；之后第零步看到有 git 就不再装。Q1 算「随 Docker 一起卸的」用的是 `apt-get -s purge --autoremove` 减去本来就会自动清掉的，于是 git、git-man、liberror-perl 都算进去，Q6 照单卸掉——**工具包自己要用 git**（wt、事件日志、项目都靠它）。

- 反着试：在虚拟机里只把这次加的保护去掉（`TOOLKIT_PKGS = ()`），同样的流程走下来，Q6 的确认屏列了 git、git-man、liberror-perl，真卸了；卸完 git 没了，连装 docker-ce 之前就有的 git-man、liberror-perl 也少了（3 项「不对」）。加上保护后两遍全对。
- 改法：
  - `machine/migrate/inventory.py`：新的 `TOOLKIT_PKGS`（git、curl、wget、bubblewrap、uidmap、dbus-user-session、iptables：`machine/tools.toml` 里「apt:」那几样，加免管理员 Docker 要的 iptables、第零步的 wget）。`removal()` 算出来的里面有它们时，不算进去，再模拟一次「把它们标成手动装的」（apt-get 的「包名+」写法，只在模拟里标，普通用户能跑、不改系统，虚拟机里试过之后 `apt-mark showauto` 里 git 还是自动装的），它们要用的 git-man 等也就不算了；第二次模拟没成就只列 Docker 自己的几个（宁可少卸）。留下的记进这份 Docker 的 `keep_pkgs`，加一条提醒。
  - `machine/migrate/uninstall.py`：确认那一屏多一行「不卸的：git（随这份 Docker 装进来的，工具包自己也要用；标成「手动装的」留着）」；卸软件包那一次 apt 里同时写 `git+`，**标成手动装的**（不然以后 `sudo apt autoremove` 或系统提示「这些软件包不再需要」时还会被清掉）。Q1 之后小白自己卸了的就不写（「包名+」会去装它）。卸之前那次 `apt-get -s` 核对也带着它。
  - 假的 apt-get（`tests/fakes/system/fakesys.py`）认「包名+」：装着的标成手动装的，没装的报错（Q6 不该去装东西）。
- 单元测试加 4 项：`test_docker_ce_brought_git`（输出是虚拟机里取的原样，`tests/fakes/migrate/ce/purge-sim-desktop.out`、`purge-sim-desktop-keep.out`；含反着试 keep 为空就把 git 一起卸、第二次模拟没成只列 Docker 自己的）、`test_toolkit_pkgs_cover_tools_toml`（清单里「apt:」那几样都在 `TOOLKIT_PKGS` 里）、`test_docker_ce_keeps_toolkit_pkg`、`test_docker_ce_kept_pkg_gone_since_q1`。

docker.io 那边按 3-33 的虚拟机没碰上（云镜像里 git 本来就有），但同样会推荐装 git，这次的改法对它一样起作用。

## 看到但不是问题的

- **apt 下载过的官方源索引**（`/var/lib/apt/lists/download.docker.com_*`，2 个）在删掉软件源之后还在，要等下一次更新软件列表才清掉。软件源不在了 apt 就不读它们（`apt-cache policy` 已经看不到官方源的 docker-ce）；执行一次 `sudo apt-get update` 正常、不报错、不去连 download.docker.com，这两个随之清掉；系统每天自己更新软件列表时也一样。没列进残留清单、没让 Q6 去删（这是 apt 自己的缓存，Q6 去 `apt-get update` 还要联网）。
- `/etc/apparmor.d/disable` 和 3-33 一样少了：docker-ce 自己的卸载脚本（`/var/lib/dpkg/info/docker-ce.postrm`）purge 时删这个空目录，`sudo apt purge docker-ce` 也一样，不是工具包删的。
- `/etc/apparmor.d/rootlesskit` 是 apparmor 软件包自己带的，不是 docker-ce 的，没动。
- docker-ce 29.10 新装时用 containerd 存镜像（`overlayfs` 驱动），镜像在 `/var/lib/containerd` 里；3-30 起清点就连它一起量、一起列进残留，这次照样带走、照样删干净。
- `/etc/cni` 这次没出现（containerd.io 2.4 没建），残留清单里也就没有它。
- 有 docker-ce-rootless-extras（`/usr/bin/rootlesskit` 等）不影响规定位置那份的安装和接管。

## 自测结果

`uv run python tests/run_all.py`：单元测试 507 → 511 项，流程沙箱 43 个剧本，总检查 95 个样例，全部通过（临时主目录，3-59 的保险）。

## 和设计书的出入（留给 3-48）

1. 4.8 Q6「连同随装的软件包一起卸」要补一句：工具包自己要用的系统软件包（git、curl、wget、bubblewrap、uidmap、dbus-user-session、iptables）即使是随旧 Docker 进来的也不卸，卸的同时标成手动装的。
2. 4.8 Q6 的残留：apt 下载过的官方源索引不算残留（下一次更新软件列表时 apt 自己清掉）。

## 没做的

- 和 3-33 一样：没走第零步装的启动器；真的输管理员密码（虚拟机 sudo 免密码）没验，留给 3-15；旧 Docker 停着要先起来、小白不在 docker 组这两条路没走。
- 「像桌面版」只是在云镜像上卸掉 git、curl，不是真的桌面版（3-36 装真的桌面版）。
- 别的会被旧 Docker 当成「自动装的」带进来、工具包又要用的东西，只按 `TOOLKIT_PKGS` 这一份名单管；以后 `tools.toml` 加「apt:」的工具要记得加进来（单元测试会提醒）。
- 免管理员但位置不对的是 3-35。

## 自己出的错

- 没有犯错要记的。摸底用的虚拟机 `ce34m` 只用来手动看 apt 的推荐和模拟输出（取了单元测试的样例），正式结果都在全新的 `ce34`（建好跑一遍带重启、还原成全新再跑一遍）和 `io34` 上；反着试那一遍在 `ce34` 还原后的全新状态上做，做完再还原才跑第二遍正式的。

## 留下的东西

- 虚拟机 `ce34m`、`ce34`、`io34` 都删了；`/tmp/sop-3-34/`、`/tmp/sop-io-vm.*` 删了。
- 本机：只跑了自测（临时主目录）；没用 sudo，没碰 `~/tools/docker` 和用户原来的 Docker，`~/tools/sop/config` 没建。
