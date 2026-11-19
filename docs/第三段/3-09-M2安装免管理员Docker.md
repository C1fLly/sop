# 3-09 M2 安装：免管理员 Docker

2026-11-19。主控窗口派的子代理做的。没调用 AI、没花钱。真的安装只在虚拟机里做（`tests/vm/vm.sh new d9`，全新的 `one` 底盘，虚拟机里用了 sudo，用户 2026-11-19 已答应）；本机只跑了单元测试和全部自测，没用 sudo，没碰用户原来的 Docker（`~/tools/docker` 和它的数据一个文件都没读）。

## 做了什么

- **安装脚本** `machine/install/docker-rootless.sh`（`tools.toml` 里早就写好了名字，3-03 留给这里）：
  - 程序用 Docker 官方的两个静态压缩包（`docker-<版本>.tgz`、`docker-rootless-extras-<版本>.tgz`），装到 `~/tools/docker/bin`；设置在 `~/tools/docker/etc/daemon.json`（数据位置 `~/tools/docker/data`，网络设置里的代理）。`SOP_DOCKER_VERSION` 可指定版本，不给就取下载站上最新的（这次是 29.10.0）。先放旁边再换名顶上去。
  - **要管理员密码的只有一步，缺东西才有**：先打一句大白话「接下来这一步要管理员权限：……。系统会问这台电脑的登录密码……」，再 `sudo` 跑一个现生成的小脚本：装缺的系统软件包（uidmap、dbus-user-session、iptables）、载入网络模块 nf_tables（官方安装脚本装之前要看到它已载入）、给 `~/tools/docker/bin/rootlesskit` 写那一条系统安全规则（`/etc/apparmor.d/home.<用户>.tools.docker.bin.rootlesskit`，名字和体检 `components.py` 认的一样）并载入。规则已经在、模块已经载入时不问密码。
  - **官方安装脚本的三处（4.8）**：
    1. `--force`：只在 `/var/run/docker.sock` 小白能写时加（官方脚本只在这种时候中止；docker.io 在跑但小白不在 docker 组时不中止，不用加）。
    2. 默认指向：装之前记下 `~/.docker/config.json` 里的默认指向；电脑上另有一份 Docker（系统自带的通道在，或原来就指着别的）时，官方脚本切到 `rootless` 之后切回原来的。电脑上只有这一份时留着 `rootless`，敲 `docker` 用的就是它。
    3. 服务名写死：`~/.config/systemd/user/docker.service` 已经被另一份免管理员的 Docker 占了（登记文件不指着规定位置的程序），或者另一份没用后台服务、在默认通道上跑着，就不用官方脚本，自己写 `sop-docker.service`（运行目录和通道在 `/run/user/<编号>/sop-docker/`），旧的一样不动。
  - 后台服务的登记文件由这个脚本先写好（照官方脚本的样子，多了 `--config-file`），官方脚本看到已有就不改它，只做检查、起服务、设成登录后自己起来、建默认指向。
  - 装完核对：连得上、是免管理员的、数据目录就是 `~/tools/docker/data`；通道写进 `~/tools/docker/etc/docker-host`（工具包自己用这份时按它找）。
  - 中途失败：这一次新放的程序、服务登记文件拿掉，默认指向改回去；系统规则、系统软件包留着。
  - 已经在跑时重装（升级）：先停服务再换程序，数据不动。
  - `--plan`：只看不改，打印怎么装（给单元测试用）；系统那几个位置可以用 `SOP_` 开头的变量换成临时目录。
- **`machine/install.py`**：清单里用系统软件包装的几样（`apt:`），装之前先说一句要做什么、要密码，再合成一次 `sudo apt-get`（代理按网络设置给进去；刚开机时系统可能占着软件包的锁，等最多 5 分钟）。原来遇到这几样只说「不归这一步」、整个停下。加了 `DOCKER = ('uidmap', 'dbus-user-session', 'docker')`，`python3 -m machine.install uidmap dbus-user-session docker` 装 Docker 这一套（不给名字还是 3-08 那几样，不要密码）。
- **`machine/shellenv.py`**：终端启动文件那一段的 PATH 加上 `~/tools/docker/bin`（放在最后）。连哪一份 Docker 看默认指向，所以另有一份时敲 `docker` 看到的还是原来那份。
- `tools.toml` 只改了开头的说明；README 的目录表补了这两样。
- **虚拟机验证脚本** `tests/vm/docker.sh`（把工作区的代码打包拷进虚拟机）和 `tests/vm/docker-guest.sh`：`--system` 先装一份 docker.io、`--rootless` 先照官方一条命令装一份免管理员的、`--broken` 先让它装到一半失败一次、`--reboot` 装完重启。不进 `run_all.py`。

## 结果

### 单元测试

`tests/unit/test_machine_install.py` 从 12 项加到 21 项（多 9 项）：
- `--plan` 七项：全新的电脑（服务名 docker、不加 `--force`、不切回、要写规则，规则名和体检认的一样，只看没改任何东西）；系统自带的通道能写才加 `--force`、不能写不加，两种都切回、原来指着别的就切回那个、已经是 rootless 不动；没有系统自带的时只在原来指着别的时切回、`config.json` 读不懂就停；服务名被占用 sop-docker 和另一条通道、不切默认指向、是规定位置自己的就照用 docker；另一份手动跑在默认通道上也让开；模块载入了、编进内核的不再载入，系统没开安全模块不写规则；路径带空格不装。
- 系统软件包两项：几样合成一次 apt、先说一句要密码、代理只给小写那一套；没东西要装不调用、装不上明说。
- 原有的几项补了：那一段里有 `$HOME/tools/docker/bin`；Docker 的安装脚本在、bash 语法对、不写终端启动文件。

全部自测：做之前单元测试 119 项、流程沙箱 24 个剧本、总检查 62 个样例全过；做之后单元测试 128 项（多了这 9 项）、其余一样，全部通过。

### 虚拟机（全新的 Ubuntu 26.04.1，内核 7.0，`one` 底盘）

每种情况都从全新的虚拟机开始（`vm.sh reset`），最后一版代码各跑了一遍：

| 情况 | 结果 |
|---|---|
| 全新的电脑（`--reboot`） | 先说一句再装 uidmap（apt），再说一句再写系统规则、载入网络模块；Docker 29.10.0 装好，约 36 秒。数据在 `~/tools/docker/data`、是免管理员的、经网络设置的代理拉镜像起容器、端口映射能用；新开终端敲 `docker` 用的是规定位置这份；再装全跳过、三个文件都没再改；直接再跑安装脚本（重装）不要密码、之前拉的镜像还在。**重启后**登录进来服务自己起来、容器能跑、端口映射能用 |
| 装到一半失败（`--broken`） | 给用户级后台服务设一个坏的网络设置让 Docker 起不来：明说没装好，新放的程序和服务登记文件拿掉了、没留下在跑的服务、默认指向没留在新的上、系统规则留着；去掉坏设置后再装一次成功（不再要密码） |
| 有系统自带的 docker.io 在跑、小白在 docker 组里（`--system`，第一遍带 `--reboot`） | 官方脚本加了 `--force`；装完把默认指向切回 `default`；新开终端不加 sudo 敲 `docker` 看到的是 `/var/lib/docker` 那份和它的容器；`/var/lib/docker`、`/etc/docker`、旧程序 23 项大小时间权限都没变；重装后默认指向还是原来那份；重启后两份各自正常 |
| 有一份照官方一条命令装的免管理员 Docker（`~/bin`、服务名 docker，`--rootless`，第一遍带 `--reboot`） | 规定位置的用 `sop-docker` 起，通道 `/run/user/1000/sop-docker/docker.sock`；旧的服务照常、默认指向没动、敲 `docker` 看到的还是旧的和它的容器；旧的 44 项（`~/bin`、`~/.local/share/docker`、旧的服务登记文件、`~/.docker`）都没变；重启后两份各自正常 |

`~/tools` 之外这次新出现或改了的（全新那台）：`~/.bashrc`（那一段）、`~/.config/systemd/user/docker.service` 和登录后自己起来的链接、`~/.docker/`（默认指向）；系统上：`/etc/apparmor.d/home.xiaobai.tools.docker.bin.rootlesskit`、新装的软件包 uidmap 和随它来的 libsubid5。大小：程序 240 MB，数据（一个 alpine 加一个 busybox）13 MB。

**网络模块要不要写开机配置**：第一版写过 `/etc/modules-load.d/sop-docker.conf`。在虚拟机里删掉它再重启，Docker 起来时系统自己把 nf_tables 载入了、容器照常（全新的虚拟机开机后这个模块是没载入的，所以是 Docker 用到时自动载入的）。所以改成只在装的时候载入一次、不写开机配置，少改一处系统。之后几遍重启验的都是不写开机配置的版本。

## 没做的

- 虚拟机里 sudo 免密码，**真的输密码那一下没验**：说明那句话出现了，系统真问密码、输错、不在终端里运行（`install.py` 跑安装脚本时 stdin 是空的，sudo 从终端读密码）这几种没试。桌面上开的终端也没试，都是 ssh 登录。留给 3-15（全新虚拟机从第零步走到体检）时一起看。
- docker-ce、snap 版、Docker Desktop 并存没试（docker-ce 是 3-33、3-34 的事）。iptables 没装、老系统用 ip_tables 的情况没碰到（26.04 的底盘自带 iptables、用 nf_tables），只有单元测试。arm 的电脑没试。
- **Docker 的 compose 插件没装**：官方静态压缩包里没有它，`docker compose` 用不了。项目要不要用 compose、装在哪，第 2a 期做技术栈档案时定；要的话加进清单，没拆新任务（第三段用不到）。
- 官方的静态压缩包没有校验值文件，只靠 HTTPS，不像 gh 那样能核对。
- 网络设置里的代理是装的时候写进 `daemon.json` 的；之后改了网络设置，要重跑安装脚本（或 3-12 的 setup）才生效。
- 体检（3-06）没在虚拟机里跑；清单里 Docker 的检查命令还是只看程序的版本（不看服务在不在跑），没改。本机用户原来那份 Docker 也在 `~/tools/docker`，改检查命令会影响它在体检里的结果，没动。
- 这台试验电脑（本机）的 Docker 怎么装的、`~/tools/docker` 下有没有 `etc/` 这些，没看（不碰）。

## 和设计书的出入（留给 3-48 并入）

1. **要管理员密码的那一步做的事**比 4.5 写的「装一条系统安全规则」多：缺的系统软件包（uidmap、dbus-user-session、iptables，uidmap 会带一个 libsubid5）、载入一次网络模块 nf_tables（官方安装脚本装之前要看到它；不写开机配置，Docker 用到时系统自动载入，虚拟机里重启验过）、那条规则。4.3「在系统盘上的」可以补上 iptables（Ubuntu 默认就有）。
2. **后台服务登记文件由工具包写**（照官方的样子，多 `--config-file ~/tools/docker/etc/daemon.json`），官方安装脚本只做检查、起服务、设开机后自己起来、建默认指向。设置文件 `~/tools/docker/etc/daemon.json`、通道记录 `~/tools/docker/etc/docker-host` 都在 `~/tools/docker` 里，4.3 的表可以写上。
3. **`--force` 只在小白能写 `/var/run/docker.sock` 时加**（官方脚本中止的条件就是这个）。4.8 写的是「系统自带的 Docker 正在运行时」。
4. **默认指向只在另有一份 Docker 时切回**（系统自带的通道在、或原来指着别的）。电脑上只有这一份时留着官方脚本切到的 `rootless`，不然敲 `docker` 什么也连不上。4.8 那一句是放在迁移里说的，没说只有一份时怎么办。
5. **服务名被占时**用 `sop-docker.service`，运行目录和通道在 `/run/user/<编号>/sop-docker/`（第一段 W27 的试验原型放在 `~/tools/docker/run`）。和专用 Docker 的 `sop-docker-<项目名>` 不会撞名。迁移卸掉旧的之后接过 `docker` 这个名字是 3-31、3-32 的事。
6. 规定位置这份 Docker **登录后自己起来**（官方脚本的做法，不开 linger）。专用 Docker 是用时才起（用户定的），这份是小白自己日常用的，设计书没写，照官方。
7. 终端启动文件那一段的 PATH 加了 `~/tools/docker/bin`：另有一份 Docker 时，敲 `docker` 用的是新的程序、连的是原来那份（看默认指向）。这个目录里还有 containerd、runc 等，也排在前面（系统服务用完整路径，不受影响）。

## 自己出的错

1. 第一遍虚拟机全新装失败了，没看到原因：虚拟机跟着重启，`/tmp` 里的完整输出没了，屏幕上只截了最后几十行（还混着验证脚本自己的一个 Python 写法错误）。同一台还原后再跑就成了。怀疑是刚开机时系统自己在更新、占着软件包的锁，给 apt 加了「等锁最多 5 分钟」，并让验证脚本没装好时打印完整输出；之后八遍都没再碰到，原因没坐实。
2. 第一版把网络模块写进了开机配置，后来试出不需要，删了（见上）。
3. 现生成给 sudo 跑的小脚本里，写开机配置那一行的引号写错了（`%s\n` 没加引号），跑之前看出来改了；后来那一行整个删了。
4. `--plan` 打印成了「1」「yes1」，单元测试抓出来的。
5. 切回默认指向时 Docker 打了一行英文（`Current context is now "default"`），改成不显示。
6. 验证「装到一半失败」第一次用的是把数据目录设成不能写，免管理员的 Docker 照样起来了（它在自己的隔离空间里是「管理员」，权限挡不住），改成给后台服务设一个坏的网络设置。
7. 验证脚本里一条检查用了「两个文件拼起来再找」，有一个文件不存在时整条算失败，报了两个假的「不对」；改了之后两种情况各重跑了一遍。
8. 新写的两个验证脚本和安装脚本一开始没有可执行权限，第一次跑报「拒绝」。

## 留下的东西

- 虚拟机 `d9` 用完删了（`vm.sh list` 是空的）。
- 本机：没在 HOME 里装任何东西，没用 sudo，没读也没碰 `~/tools/docker`；只跑了单元测试和全部自测（都在 `/tmp` 的临时目录里，`uv run` 用的是仓库里原来的 `.venv`）。`/tmp` 下这次的日志和从虚拟机拷出来看的官方安装脚本副本都删了。
