# 3-63a GitHub 上 `unit` 里 2 项事件日志测试不过：新版 Git 推到地址也会顺手改指针

2026-11-22。由主控窗口派出的子代理做（从 3-41 拆出来的，3-63 的第一半）。没调用 AI，0 美元；没开虚拟机；没碰 Docker；没用 sudo；
**GitHub 上什么都没建、没改、没删**，只读看了运行 44928690351 的日志；没推送。

**这次动了事件日志的正式代码（`kernel/journal.py`）。** 按交接里的规矩（动了隔离、放行事件、事件日志三处之一，要再开一次独立审查），
已补进交接「等用户回答或处理的事」第 7 条。

## 起因

3-41 那次检查（运行 44928690351，第 2 次）里 `checks`、`docs`、`sandbox` 绿，`unit` 528 项里 2 项不过，两项都是 3-53 加的：

1. `TestWtFetch.test_journal_leaves_origin_refs_alone`：`refs/remotes/origin/sop/journal` 被建出来了；
2. `TestWtFetch.test_fetch_all_while_writing`：像 `wt` 那样 `git fetch --all` 391 次里失败 22 次，
   报 `cannot lock ref 'refs/remotes/origin/sop/journal': is at … but expected …`。

本机一直过。

## 原因（坐实了）：Git 2.56 改了推送的规矩

- 日志里 GitHub 临时电脑的 Git 是 **2.56.1**（`actions/checkout` 那一步打出来的），本机是 **2.53.0**（Ubuntu 26.04 自带）。
- Git 2.56.0 的版本说明（`RelNotes/2.56.0.adoc`）：

  > When the push remote is specified as a URL, the fetch refspec of a uniquely matching configured remote is now used
  > to find and update the remote-tracking branch (e.g., '@{push}').

  源码里是 `remote.c` 的 `repo_remote_for_push_tracking`：推送目标是一个**没配置过的远程**（直接写地址）时，
  去找地址对得上的那个已配置远程（只有一个对得上才算），照它的拉取规则更新 `refs/remotes/…`。
- 3-53 的修法里「推送直接推到 origin 的地址，Git 就不会顺手改 `refs/remotes/origin/sop/journal`」靠的正是旧行为。
  在 Git 2.56 上，事件日志每推一次都顺手改这个指针，又变回 3-53 之前「两方改同一个指针」：`wt` 的 `fetch --all` 撞上就失败。
  **这是正式代码的问题，不只是测试**：小白电脑上的 Git 升到 2.56 以后（例如装了 Git 官方的软件源），流程会又像 3-53 那样偶尔停在 T1。

### 怎么查出来的

| 试的什么 | 结果 |
|---|---|
| 本机 Git 2.53，去掉本机 Git 配置（临时主目录、`GIT_CONFIG_NOSYSTEM=1`，另试了 `GIT_CONFIG_GLOBAL=/dev/null`）跑改之前的代码 | 3 遍都过：**不是本机 gitconfig 的问题** |
| 从 Git 官方的 Launchpad 软件源（`ppa:git-core/ppa`，就是 GitHub 临时电脑装 Git 的地方）下 `git_2.56.1-0ppa1~ubuntu26.04.1_amd64.deb`，**只解开到 `/tmp`、不安装**，用一个小包装脚本放在 PATH 最前面，同样的环境跑改之前的代码 | 3 遍都不过，两项都不过；拉取 408、413、414 次里失败 23、18、21 次，和 GitHub 上一模一样 |
| 一步一步用命令行演（建日志分支、推送、取回各看一次指针） | Git 2.53：推到地址后没有 `refs/remotes/origin/sop/journal`；Git 2.56.1：第一次推到地址后就有了。取回（`--refmap=`）在两个版本上都不碰它 |
| 下 Git 2.56.1 源码看 `transport.c`、`remote.c` | 找到上面那段 |

## 修法

推送不再推到「光秃秃的地址」，改推到一个**只在这一条推送命令里用 `-c` 现定义的远程**：

```
git -c remote.sop-journal-push.url=<origin 的推送地址> push -q [--porcelain] sop-journal-push <提交>:refs/heads/sop/journal
```

它是「配置过的远程」，Git 就用它自己的拉取规则——它没有拉取规则，所以没有指针可改。`-c` 只管这一条命令，项目仓库的配置里不留它。
地址还是 `git remote get-url --push origin` 给的（insteadOf 算进去，和原来一样）。在 Git 2.53、2.56.1 上都试过：推送之后没有
`refs/remotes/origin/sop/journal`，`wt` 那样 `fetch --all` 之后才有（那是 `wt` 的，不归事件日志）。

`kernel/journal.py` 改了：文件开头的说明；加常量 `PUSH_REMOTE`、方法 `Journal._push`；建日志分支（I6）和写入线程两处推送改用它。
**事件日志的做法一点没变**：还是一个写入线程、每个事件等推上去才往下走、排着的合成一次推送、被抢先就取回重来、断网就停下；
远程上的分支名、文件放法、本机指针 `refs/sop/journal` 都没变。

没选的办法（都试过或看过源码）：

- 在这一条推送命令里给 origin 加一条排除规则（`-c remote.origin.fetch=^refs/heads/sop/journal`）：试了，Git 2.56.1 照样改，
  推送找指针那段不看排除规则。
- 地址换个写法让它对不上、或再现定义一个同地址的远程让它「对得上的不止一个」：靠的是 Git 内部细节，下个版本可能又变。
- 改项目仓库 origin 的拉取规则、把日志分支排除掉：动的是 `wt` 管的配置，影响面大。
- 用 `git send-pack`：不走 https，和现在的推送路子不一样。

## 测试

- 新加 `TestWtFetch.test_push_target_has_no_fetch_refspec`：在一个新项目上记下事件日志的每次推送（建日志分支、写一个事件，共 2 次），
  核对推送目标是同一条命令里 `-c remote.<名字>.url=<origin 的推送地址>` 现定义的、没给拉取规则，不是 `origin`、也不是光秃秃的地址；
  事件确实推上去了。它不看 Git 版本，**本机 Git 2.53 上改之前就不过**（目标是光秃秃的地址），改之后过。
- 原来那两项没改一个字：它们在 Git 2.56.1 上改之前不过、改之后过，本身就是这件事的结果核对。
- 为什么不算放宽：两项旧测试的标准一点没动；新测试是多加的一道，管住本机老 Git 看不出来的那条路。

## 结果

| 跑的什么 | 环境 | 遍数 | 结果 |
|---|---|---|---|
| 改之前 `TestWtFetch`（`git archive` 导出到 `/tmp` 跑） | 像 CI：临时主目录、`GIT_CONFIG_NOSYSTEM=1`、PATH 只有系统目录和 uv/wt 的链接；Git 2.56.1 | 3 | 0 遍过（重现了） |
| 同上 | 同上，Git 2.53 | 3 | 3 遍过 |
| 改之后 `tests/unit/test_journal.py` 整个（13 项） | 像 CI，Git 2.56.1 | 30 | 全过 |
| 同上 | 像 CI，Git 2.53 | 10 | 全过 |
| 同上 | 像 CI 再加 `GIT_CONFIG_GLOBAL=/dev/null`，Git 2.56.1 | 5 | 全过 |
| 照 `tests/ci/prepare.sh` 和流程文件：`uv run python tests/run_all.py --no-skip unit` | 像 CI，Git 2.56.1 | 1 | 530 项全过、0 项跳过 |
| `uv run python tests/run_all.py --no-skip sandbox` | 像 CI，Git 2.56.1 | 1 | 43 个剧本全过、0 个跳过 |
| 全部自测 `uv run python tests/run_all.py` | 本机平常的样子（Git 2.53） | 1 | 全部通过 |

全部自测：做之前单元测试 529 项、流程沙箱 43 个剧本、总检查 108 个样例；做之后单元测试 530 项（多了上面 1 项）、流程沙箱 43 个剧本、总检查 108 个样例、文档检查 0 处悬空，全部通过。

## 没做的

- **GitHub 上真跑一遍**：归 3-63（走 PR，四个检查全绿）。这次只提交到本机，没推送。
- `kernel/projectgh.py` 里 `sop project new` 推 `main`、删试验分支、推试验分支三处也是推到地址，在 Git 2.56 上也会顺手改
  `refs/remotes/origin/main` 这些指针。那几处是建项目时一次性的、不和 `wt` 抢同一个指针同时写，没改；记在这里。
- 3-53 的记录没改（那是当时的情况），这份记录接着它。
- 设计书没改：设计书没写本机用哪个指针、怎么推送。

## 自己出的错

- 新测试第一稿最后一行写成了 `assertTrue(... or True)`，等于什么都没核对；跑之前发现，改成真读出事件来核对。
- 新测试第一稿在同一个临时目录里第二次调 `make_remote_and_clone`，撞上已有的 `seed` 目录报错；改成放在子目录里。
- 第一次在像 CI 的环境里跑全部单元测试时，我把测试临时目录设成了 `/tmp/sop-3-63a/t-256`（比默认的 `/tmp/sop-test` 长），
  `test_docker_service` 有 1 项因为专用 Docker 的通道路径超过系统 107 个字符的上限报错；和这次的改动无关，改回默认目录（CI 也是默认）重跑全过。
- 第一次找 uv 时写错了位置（本机 uv 在 `~/.local/bin`，不在 `~/tools/uv/bin`），那遍没跑起来。

## 留在外面的东西

`/tmp/sop-3-63a`（解开的 Git 2.56.1、Git 源码、日志、小脚本）用完删了；本机没装任何东西，`~/.gitconfig`、`~/tools/wt` 没动。
