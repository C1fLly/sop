# 3-51 离线包挂到工具包仓库的 Releases

2026-11-22 到 23。主控窗口派的子代理做的，分两次：第一个子代理写了代码改动、开了 PR #5，在试跑之前被 AI 服务报错打断；第二个子代理（2026-11-23）接手做完。
没调用 AI，0 美元；没碰 Docker；本机没用 sudo（只在虚拟机里用）；没动隔离、放行事件、事件日志。

用户 2026-11-23 答应（只限这些）：合并 PR #5；在 `C1fLly/sop` 上发**一个** Release（标签 `offline-<打包提交前 8 位>`，挂 amd64 离线包和校验值）；虚拟机里用 sudo、在 `~/sop-vm/` 下建虚拟机；记录走 PR。GitHub 上除此之外什么都没建、没改、没删。

## 做了什么

1. **代码改动**（第一个子代理，提交 `02fdc8a`，PR #5）：
   - `bootstrap.sh` 连不上网时那句话直接写出离线包的下载地址 `https://github.com/C1fLly/sop/releases/latest`、文件名的样子（`sop-offline-（一串字母数字）-amd64.sh`）、U 盘拷过来 `bash <这个文件>`；单元测试 `test_bootstrap.py` 加 1 处核对这个地址（单元测试项数没变，还是 598）。
   - `tests/vm/offline.sh` 加两种发版用法：`--repo <仓库> [--save <本机目录>]`（能上网的虚拟机从这个仓库的 `main` 克隆，用那个提交里的 `pack.sh` 打包，另存一份到本机）；`--url <下载地址> [--sha256 <值>]`（不打包，能上网的虚拟机下载发出去的那份、核对校验值）。之后照旧做 U 盘、断网虚拟机走第零步。原来不带选项的用法不变。
   - `machine/offline/pack.sh` 开头注释写发版的三步、指向本记录「以后发版」；README 跟着改。
2. **接手时的判断**（第二个子代理）：读了 `git show 02fdc8a`，逐处判断都对、照用，没加提交：
   - `bootstrap.sh` 那句话：小白手册（3-39）还没写，这句话自己就给出了下载地址，不用等手册。`releases/latest` 指向「最新的正式 Release」，以后在这个仓库发别的 Release（不带离线包的）会把它顶掉，「以后发版」里写明。
   - `offline.sh`：`--repo` 用的是那个提交里的 `pack.sh`；工具包提交从离线包第 2 行取（第 2 行只有那一串 40 位）；`--url` 下下来的文件名按地址最后一段；四个选项的互斥检查对。真跑两遍都过（下面）。
   - 没照第一个子代理的打算「先拿旧的 `main` 试跑一遍 `--repo`」：试跑和正式跑走同一段代码，正式跑出问题再修、另开 PR 就是。结果正式跑一次过。
3. **合并 PR #5**：四个检查全绿（`02fdc8a`），合并提交 **`fd6e257`**；本机切回 `main`、`git merge --ff-only origin/main`；`sop-task/3-51` 本机和 GitHub 上都删了。合并后 `main` 上自动跑的四个检查也全绿。
4. **打包**：`tests/vm/offline.sh --repo https://github.com/C1fLly/sop.git --save /tmp/sop-3-51/pkg`。能上网的虚拟机取到 `main` = `fd6e257e351da7d2384d11f849a0b09fa014392c`，打出 `sop-offline-fd6e257e-amd64.sh`；同一次运行里断网的全新虚拟机插 U 盘走第零步，**29 处全对**。
5. **上传前查离线包里面**（解开看，见下表），干净才往下。
6. **发 Release**：`gh release create offline-fd6e257e --target fd6e257e… --latest`，挂离线包和 `.sha256` 两个文件。
7. **验下下来的那份**：`tests/vm/offline.sh --url <Releases 上的地址> --sha256 <本机那份的值>`。能上网的全新虚拟机从 Releases 下载，校验值和本机那份一样；断网的全新虚拟机插 U 盘走第零步，**30 处全对**（29 处加校验值那 1 处）。

## 上传前的检查（`/tmp/sop-3-51/`，0700，用完删了；只打印「命中几处、在哪个文件」，没打印任何密钥）

私人字符串 11 条（本机 `ANTHROPIC_…`、`CLAUDE_CODE_MESSAGING_TOKEN` 的值、`ANTHROPIC_BASE_URL` 的主机名、`gh auth token` 的值、`~/.gitconfig` 的旧邮箱和它 `@` 前面那段、旧名字、本机名）放在临时文件里查。

| 查什么 | 结果 |
|---|---|
| 载荷校验值（离线包开头写的和实际的） | 一样 |
| 里面有什么 | `ARCH`、`VERSION`、`bootstrap.sh`（和 `fd6e257` 里的一字不差）、`debs/`（49 个 .deb，28.8 MB）和 `Packages`、`Release`、`uv/uv-x86_64-unknown-linux-gnu.tar.gz`（0.13.9）、`sop.bundle`（2.2 MB）。没有别的 |
| 49 个 .deb 是不是 Ubuntu 官方的 | sha256 全部在本机现成的 Ubuntu 官方软件包索引（`/var/lib/apt/lists`，只读）里 |
| uv | `pack.sh` 打包时已按官方的校验值核对过 |
| `sop.bundle` | 只有 `refs/heads/main` = `fd6e257e`；103 个提交，作者/提交者只有 `C1fLly <156543391+C1fLly@users.noreply.github.com>` 和合并提交的 `GitHub <noreply@github.com>`；里面的对象和本机 `fd6e257` 能到的完全一样，也就是 GitHub 上已公开的那些 |
| 11 条私人字符串：开头和文本部分、解开后的 49 个软件包、解开后的 uv、工具包全部历史的改动和提交说明 | 全部 0 处 |
| 代理地址 `127.0.0.1:7890`、虚拟机网关 `10.0.2.2` | 软件包、uv 里 0 处；只在 `bootstrap.sh` 的「要像 http://127.0.0.1:7890」示例和工具包的历史里（仓库本来就公开，用户 2026-11-22 定了不抹） |
| 常见密钥写法（私钥开头、`ghp_`、`gho_`、`ghs_`、`ghu_`、`github_pat_`、`sk-ant-`、`sk-…`、`AKIA…`、`xox?-`、`AIza…`、JWT） | 开头和文本、uv、工具包历史 0 处；只在三个 Ubuntu 官方软件包的程序里：libssh2、libgnutls 的「BEGIN … PRIVATE KEY」字样常量（libgnutls 带着它自检用的钥匙）、libunistring 的 Unicode 字名表碰巧拼出 `AKIA…`。都是官方软件包原样的，和本机无关 |
| 邮箱样的字 | 只有测试里的假地址（`*.example`、`proxy.lan`、`*.inval…`）和代码里的 `@装饰器` |

## 结果

- PR **#5**：<https://github.com/C1fLly/sop/pull/5>，四个检查全绿，合并提交 `fd6e257`。
- Release：标签 **`offline-fd6e257e`**（指向 `fd6e257e351da7d2384d11f849a0b09fa014392c`），<https://github.com/C1fLly/sop/releases/tag/offline-fd6e257e>，正式版（不是草稿、不是预发布），`https://github.com/C1fLly/sop/releases/latest` 跳到它。
  - `sop-offline-fd6e257e-amd64.sh`：48232207 字节（46 MB），sha256 `e6e17bf91fe9c3d21fe3d754e363cb3adf8e156b084f4da729fecef2786f0fd0`（GitHub 记的和本机一样）。下载地址 `https://github.com/C1fLly/sop/releases/download/offline-fd6e257e/sop-offline-fd6e257e-amd64.sh`
  - `sop-offline-fd6e257e-amd64.sh.sha256`：96 字节。
- 打包用了 10 秒（虚拟机的软件源 cn.archive 直连，GitHub 经本机代理）；断网虚拟机里第零步 2 秒。
- 两次虚拟机运行都是 offp（能上网）用完就删、offa（断网）脚本结束时删；`~/sop-vm/vms/` 空、没有 qemu 在跑。
- 全部自测（本机，`fd6e257` 加这份记录）：单元测试 598 项、流程沙箱 45 个剧本、总检查 108 个样例、文档检查 0 处悬空，全部通过（和接手前一样）。合并后 `main`（`fd6e257`）上自动跑的四个检查全绿。

## 以后发版

每次工具包 `main` 有了要给小白的新版本（至少第零步 `bootstrap.sh`、`machine/offline/` 改了的时候），照这几步再发一个离线包。在 GitHub 上发 Release 要先问用户。

1. 确认 `main` 上四个检查全绿；记下提交编号 `<提交>`（前 8 位 `<短>`）。
2. 在本机（Ubuntu 26.04，amd64）：
   `mkdir -m 700 /tmp/sop-rel && mkdir /tmp/sop-rel/pkg && tests/vm/offline.sh --repo https://github.com/C1fLly/sop.git --save /tmp/sop-rel/pkg`
   看最后是「全部对」、打出来的文件名里是 `<短>`（打包时 `main` 又动了就重来）。
3. 上传前查里面：照本记录「上传前的检查」那张表逐项做（解开载荷、.deb 和 Ubuntu 官方索引比 sha256、`git bundle list-heads` 只有 `main`、对象集合和 `<提交>` 的一样、私人字符串和常见密钥写法只看命中几处不打印值）。有说不清来路的命中就不传、停下。
4. `cd /tmp/sop-rel/pkg && sha256sum sop-offline-<短>-amd64.sh > sop-offline-<短>-amd64.sh.sha256`
5. `gh release create offline-<短> -R C1fLly/sop --target <提交> --title "离线包 <短>（amd64）" --notes-file <说明> --latest sop-offline-<短>-amd64.sh sop-offline-<短>-amd64.sh.sha256`（说明照 `offline-fd6e257e` 那份改提交、校验值、uv 版本）。
6. 验下下来的那份：`tests/vm/offline.sh --url https://github.com/C1fLly/sop/releases/download/offline-<短>/sop-offline-<短>-amd64.sh --sha256 <本机那份的值>`，要「全部对」。
7. 确认 `https://github.com/C1fLly/sop/releases/latest` 跳到新的这个（`curl -sI … | grep -i location`）。旧的离线包 Release 留不留、删不删，问用户。
8. 删 `/tmp/sop-rel`；`ls ~/sop-vm/vms/` 空。

注意：`bootstrap.sh` 指的是 `releases/latest`。这个仓库以后要是发别的 Release（不带离线包），会把离线包那个顶下去，小白就找不到了——那时要么每个 Release 都挂离线包，要么把 `bootstrap.sh` 的地址改成别的固定页面。arm64 的没打（`pack.sh` 支持，要在 arm64 的 Ubuntu 26.04 上打）。

## 没做的

- 小白手册「完全连不上网」那一节：手册还没有（3-39），`bootstrap.sh` 那句话已经直接给了地址。在任务清单 3-39 那一行加了一句「3-51 加：写上离线包的下载地址」。
- arm64 的离线包。
- 没把「上传前的检查」做成仓库里的脚本（这次的脚本在 `/tmp`，用完删了；每次发版照表手做）。

## 和设计书的出入

没有。设计书 4.2 第 3 条只说「从另一台电脑下载离线包后用 U 盘拷入」，没写放在哪；放在 `C1fLly/sop` 的 Releases、`bootstrap.sh` 指 `releases/latest`，留给 3-48 写进设计书。

## 自己出的错

- 第一个子代理：被 AI 服务报错打断，草稿没纳入 Git（主控存了副本）。
- 第二个子代理：没有。
