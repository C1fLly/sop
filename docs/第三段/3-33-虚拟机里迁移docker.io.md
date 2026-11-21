# 3-33：验收——虚拟机里迁移 `docker.io`

主控窗口派的子代理做的（2026-11-21）。没动隔离、放行事件、事件日志；没碰 GitHub；**没调用 AI，0 美元**。sudo、装卸 docker.io 只在虚拟机里做（用户 2026-11-19 答应过）；本机没用 sudo，没碰用户原来的 Docker 和 `~/tools/docker`。

## 做了什么

新的验收脚本（都在 `tests/vm/`）：

- `migrate-io.sh <虚拟机名字> [--reboot]`（本机跑）：把工作区的代码拷进全新的虚拟机，依次跑下面三步，`--reboot` 再重启看一次。
- `migrate-io-guest.sh`（虚拟机里跑）：
  - `--prepare`（一次登录）：先记下装 docker.io 之前系统里有哪些文件（`/etc /usr /var/lib /opt /srv`，apt 索引、dpkg 自己的库等不算）、装着哪些软件包、主目录前 3 层；再用 Ubuntu 软件源装 docker.io、加 Docker 服务的代理设置（`/etc/systemd/system/docker.service.d/proxy.conf`，小白照网上教程也常这样加）、小白加进 docker 组；放两个镜像（拉的 busybox、自己 commit 的 shop-web:dev 带项目标签）、三个卷（带编排标签的 shop_pgdata、普通的 notes、匿名卷）、两个容器（在跑的「数据库样子」的 shop-db-1，里面 12 MB 随机数据、子目录、符号链接，都归 70:70；停着的 old-tool）；记下数据的校验值、归属、权限。
  - `--run1`（下一次登录，docker 组生效）：规定位置的 Docker 先不装。第一遍 `sop machine migrate`：Q2 装规定位置的 Docker；Q3 选卸 docker.io、匿名卷「不要了」、别的默认带走；Q4 停了旧容器、开始打包时 **kill -9 整组**。看旧容器停着、记录在；再执行一次别的 `sop` 命令（`sop machine tools`），看起回来、临时小镜像删掉、再执行不再提。
  - `--run2`：先把默认指向手动切到新的（模拟小白自己切过）。第二遍走完 Q1 到 Q6；Q6 切回原来那份之后**暂停整个 `sop`**，新开终端不加 sudo 敲 `docker` 看是哪份；卸完：`sop` 自己说的残留清单逐项为空、自己按 Q1 存的清单逐项再查、**拿装 docker.io 之前的系统比**（软件包、文件）、新开终端敲 `docker`、带走的数据逐字节和归属核对、再清点、再执行一次迁移说「不用迁移」。
  - `--after-reboot`：重启后敲 `docker` 还是规定位置那份、系统里没有 docker/containerd 的服务登记、`/run` 下没有旧 Docker 的东西、数据还在。
- `migrate-drive.py`：在模拟终端里跑要人回答的命令（只用标准库）。屏幕上停在问题上时按问题的文字找回答，找不到就直接回车（按默认，记一行）；屏幕上出了某一行就 kill -9 整组或者先暂停整组、跑一条命令、再接着跑。

`sop` 用 `python3 -I ~/sop-src/kernel/main.py`（启动器执行的就是这一句）；没走第零步装启动器（3-13 验过）。

## 结果

全新的虚拟机（底盘 one，Ubuntu 26.04，docker.io 29.1.3-0ubuntu4.1，规定位置的 Docker 29.10.0）：

- 第一遍 `migrate-io.sh io33 --reboot`：**38 项全对**。
- 还原成全新再跑一遍 `migrate-io.sh io33`（不重启）：**34 项全对**，2 分 18 秒。

验收标准逐条：

1. **用正式命令走通 Q1 到 Q6**：两遍 `sop machine migrate`（第一遍被强制结束），Q2 装上规定位置的 Docker，Q4 打包、试还原、核对，Q5 核对，Q6 停服务、一个一个点名卸 8 个软件包、删目录、删用户组，退出码 0。
2. **残留清单逐项为空**：`sop` 说「残留清单 22 项逐项又看了一遍，都没有了」；脚本按 Q1 存的 `inventory.json` 逐项自己再查一遍也为空。另外和装 docker.io 之前比：原来的软件包一个没少，多出来的只有规定位置那份要的 `uidmap`、`libsubid5`；多出来的文件里没有旧 Docker 的（只有规定位置那份的系统安全规则，和系统自己的 fwupd、snapd、PackageKit 等）。
3. **小白不加 sudo 敲 `docker` 看到的是原来那份（切回之后）**：Q2 装完新开终端是原来那份（`default`，`/var/lib/docker`）；默认指向被切到新的以后，Q6 卸之前先切回、暂停时新开终端看到的是原来那份和它的容器 `shop-db-1`；卸完是规定位置那份（`~/tools/docker/bin/docker`、`rootless`、`~/tools/docker/data`），重启后也是。
4. **Q4 停了容器之后强制结束 `sop`，再启动把旧容器起回来**：kill -9 时旧容器 `shop-db-1` 停着、`stopped.json` 记着它和临时小镜像；下一次 `sop machine tools` 先说一句、起回来、删掉临时放进旧的 `alpine:3.20`，记录删了，旧的里只有原来那两个容器；再执行不再提。

带走的数据：两个卷的内容（12 MB 随机数据的校验值）、归属 70:70（含符号链接）、权限、链接指向和原来一样，卷带着原来的项目标签；镜像两个都在、自己做的带标签；用带走的镜像和卷能直接起容器。选了「不要了」的匿名卷没带。

## 验出的真问题（已改正式代码，加了单元测试）

1. **符号链接的归属搬过去变成 root，Q4 试还原核对不过、迁移停下**。小镜像 alpine:3.20 里的 tar 是 busybox 的，解包时不给符号链接设归属（虚拟机里单独试过：打包前 70:70，解出来 0:0；普通文件、目录不受影响）。3-31 的假 docker 用本机的 GNU tar，所以单元测试没碰上。核对标准没放宽，改法：`machine/migrate/carry.py` 的 `unpack` 解完后从备份包里读出归属不是 root 的符号链接（`link_owners`，Python 标准库 tarfile 只读包头），再起一个用完就删的临时容器 `xargs -0 -n 2 chown -h` 补上（`fix_link_owners`；名字用 NUL 分隔，空格、中文、长名字都行；没有这样的链接就不多起容器）。试还原的临时卷、正式的卷都补，补不上就停下。
2. **卸完残留清单「逐项为空」，系统里却还留着 Docker 运行时建的东西**：`/etc/cni`、`/etc/cni/net.d`、`/opt/containerd`（bin、lib）、`/run/docker`、`/run/containerd`、`/var/run/docker.sock`。它们不属于哪个软件包，是 containerd、dockerd 运行时建的，Q1 的残留清单里没有（停了服务、卸了软件包也还在）。改法：
   - `machine/migrate/inventory.py`：系统自带的那种，这几样在就列进残留清单（`/run/docker`、通道写「运行时留下的」，`/opt/containerd` 写「容器运行时建的」）；containerd 还有别的软件在用时，containerd 那几样（`/opt/containerd`、`/run/containerd`、`/etc/cni`）不列。
   - `/etc/cni` 别的软件（容器网络插件）也可能用，所以这两项标「是空的才删」：`machine/migrate/uninstall.py` 用 `rmdir --ignore-fail-on-non-empty` 删（先里面再外面），卸完再看时里面有别的东西就不算 Docker 的残留，空的却还在才算；自己清的命令给 `sudo rmdir`。
   - 假的 sudo（`tests/fakes/system/fakesys.py`）多放过路径在测试的根下面的 `rmdir`、`find`。

单元测试加 6 项：`test_link_owners_from_backup`（长名字、中文空格、硬链接、归 root 的不补）、`test_restore_fixes_symlink_owners`、`test_symlink_owner_fix_failure_stops`（Q4）、`test_runtime_leftovers`（清点）、`test_runtime_leftovers_removed_and_shared_dir_kept`、`test_empty_shared_dir_left_is_reported`（卸载）。

## 看到但不是问题的

- docker.io 自己的卸载脚本（dh_apparmor 自动加的那段）purge 时会 `rmdir /etc/apparmor.d/disable`（空的话），所以和装之前比少了这个空目录。这是 Ubuntu 软件包自己的做法，`sudo apt purge docker.io` 也一样，不是工具包删的，没改。
- 虚拟机里系统自己的自动更新（unattended-upgrades）紧接着卸载跑了一阵，`sop_apt` 等锁没出问题。
- Q1 不用管理员量的 `/var/lib/docker` 只写「至少 4.1 KB」（3-30 定的，`--admin` 才量全），确认卸载那一屏照写。

## 自测结果

`uv run python tests/run_all.py`：单元测试 501 → 507 项，流程沙箱 43 个剧本，总检查 95 个样例，全部通过（临时主目录，3-59 的保险）。

## 和设计书的出入（留给 3-48）

1. 4.8 Q6 的残留清单补了运行时建的那几样（`/run/docker`、`/var/run/docker.sock`、`/opt/containerd`、`/run/containerd`），和「别的软件也可能用、只在空的时候删」的 `/etc/cni`、`/etc/cni/net.d`；设计书只写了数据目录、设置、服务、用户组、软件源。
2. 4.8 Q4 的打包工具：小镜像里是 busybox 的 tar，解完要补符号链接的归属（设计书没写到这一层）。

## 没做的

- 没走第零步装的启动器 `sop`，直接执行启动器调的那一句（3-13 验过启动器）。
- 真的输管理员密码（虚拟机 sudo 免密码）没验，留给 3-15。
- 旧 Docker 停着、要先起来的那条路（3-31 替用户定的）这次没在真 Docker 上走：这台的旧 Docker 一直在跑；3-30 在虚拟机里验过「停着时清点不去连它」。
- 小白不在 docker 组、要管理员才连得上旧的那条路没走（这次在组里）。
- docker-ce、免管理员但位置不对是 3-34、3-35；这次改的残留清单对 docker-ce 也起作用，到时一起看。
- 测试数据只有几十 MB，大数据没试（3-31 记过）。

## 自己出的错

- 验收脚本自己的三处错，第一遍摸底时查出来改了：(1)「数据库样子」的容器命令每次起来都重写随机数据（`--restart` 和 Q4 停了再起都会重跑），看起来像带走的数据变了；改成写过就不再写。(2) 核对时先跑了 `docker run -v shop_pgdata:…`，卷不在时 Docker 会自己建一个空的，把「卷没带过去」盖住了；改成先看卷在不在再跑。(3) 「都装好了」只在单独跑安装时打印，Q2 里没有；改看 `docker：装好了`。还有一处判断写成了「输出里有 `/data/blob` 就算对」，报错信息里也有这几个字，改成要一字不差。
- 摸底用的虚拟机 `mio` 跑过半截改动，正式结果都在全新的 `io33` 上（建好就跑一遍、还原成全新再跑一遍）。

## 留下的东西

- 虚拟机 `mio`、`io33` 都删了；`/tmp/sop-3-33/`、`/tmp/sop-io-vm.*` 删了。
- 本机：只跑了自测（临时主目录）和一个只读的小试验（`/tmp` 里用假脚本试模拟终端的驱动）；没用 sudo，没碰 `~/tools/docker` 和用户原来的 Docker，`~/tools/sop/config` 没建。
