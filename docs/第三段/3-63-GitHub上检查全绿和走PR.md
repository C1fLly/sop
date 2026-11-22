# 3-63 放好机密后工具包仓库的检查在 GitHub 上全绿，本机多出的提交走 PR 合进 `main`

2026-11-22。由主控窗口派出的子代理做。没调用 AI，0 美元；没开虚拟机；没碰 Docker；没用 sudo。
没动隔离、放行事件、事件日志；工具包的正式代码（`kernel/`、`runner/`、`machine/`、`checks/` 等）一行没改。
**改了 GitHub 上检查用的两个文件**（单列）：`tests/ci/prepare.sh`、`.github/workflows/check.yml`，外加 1 项单元测试——
第二个 PR 合并后 `main` 上的 `sandbox` 红在取 GitHub 主机钥匙那一步，见「第二个 PR 合并后 `main` 上 `sandbox` 红了」。

用户 2026-11-22 已放好机密 `WT_DEPLOY_KEY`，并答应在 `C1fLly/sop` 上开 PR、等检查、合并（合并提交）。
机密这次没读、没改、没重放；`C1fLly/sop` 之外 GitHub 上什么都没建、没改、没删。

## 做法

本机 `main` 比 `origin/main`（`1811286`）多 14 个提交（3-41 第二次的记录、3-63a、3-42、3-43、3-44、3-64、3-47、3-62 等的工作和总账提交）。
`main` 受保护（必须通过 `unit`、`sandbox`、`checks`、`docs`，对管理员生效，只许合并提交，不能直接推），所以：

1. 推送前保密检查（见下）；
2. 从本机 `main` 建分支 `sop-merge/3-63` 推上去，开 PR 到 `main`；
3. 等四个检查；全绿后 `gh pr merge --merge`；
4. 本机 `git fetch origin`、`git merge --ff-only origin/main` 接上，删掉临时分支（GitHub 上和本机）；
5. 看一眼合并后 `main` 上自动跑的那一次检查；
6. 这份记录、任务清单、交接走第二个只含文档的小 PR（同样四个检查全绿、合并提交）；
7. 第二个 PR 合并后 `main` 上 `sandbox` 红了，查出是检查用的准备脚本的问题，修好走第三个 PR（连同这份记录的补充）。

3-41 记录里写的「先重跑运行 44928690351」没做：那一次跑的是 `1811286`，里面没有 3-63a 的修法，`unit` 重跑也会照旧红那 2 项事件日志测试；PR 上跑的是全部 14 个提交，已经包含它要看的全部内容（钥匙经 SSH 取 wt、0 项跳过、用时）。

## 推送之前的保密检查（`origin/main..main` 的 14 个提交）

- 本机 12 个 `ANTHROPIC_…` 变量、`CLAUDE_CODE_MESSAGING_TOKEN` 的值、`ANTHROPIC_BASE_URL` 的主机名、`gh auth token` 的值、`~/.gitconfig` 里的旧邮箱（和它 `@` 前面那段）、旧名字，共 18 条，放在 `/tmp/sop-3-63/`（0700）的临时文件里，查完删了，没打印任何值：每个提交 `git grep -F -l`、`git log -S`、`git log -p --format=fuller`（含作者、提交者、提交说明）都是 0 处。
- 常见密钥写法（私钥开头、`ghp_`、`gho_`、`ghs_`、`ghu_`、`github_pat_`、`sk-ant-`、`sk-…`、`AKIA…`、`xox?-`、`AIza…`、JWT）、`qq.com`、`@qq`：0 处；二进制文件 0 个。
- 改动里出现的邮箱只有不公开邮箱、`noreply@anthropic.com`（提交说明的署名）、`git@github.com`，和测试里的假地址（`*.invalid`、`corp.example.com`）。
- 14 个提交的作者、提交者都是 `C1fLly <156543391+C1fLly@users.noreply.github.com>`（`git log --format=%ae`、`%ce` 各只有这一个）。

## 第一个 PR：14 个提交

- PR **#1**：<https://github.com/C1fLly/sop/pull/1>，分支 `sop-merge/3-63`（头 `b35f786`，就是本机 `main`）→ `main`。
- 检查：`toolkit-check` 第 45027426243 次（`pull_request` 触发），**四个都绿，一次过，没有修任何东西**：

| 检查 | 结论 | 整个用时 | 说明 |
|---|---|---|---|
| `unit` | 绿 | 2 分 52 秒 | 准备电脑约 14 秒；`--no-skip` 单元测试 **597 项全过、0 项跳过**，测试本身 149 秒。Git 2.56.1 下 3-41 时红的 2 项事件日志测试（`test_journal_leaves_origin_refs_alone`、`test_fetch_all_while_writing`）这次过了 |
| `sandbox` | 绿 | 7 分 10 秒 | 准备电脑约 8 秒；`--no-skip` 流程沙箱 **45 个剧本全过、0 个跳过**，剧本本身 417 秒（本机约 5 分钟；`timeout-minutes: 30` 够用） |
| `checks` | 绿 | 13 秒 | 总检查 108 个样例，0 个不合格 |
| `docs` | 绿 | 7 秒 | 章节 89 个、编号 162 个，悬空 0 处；命令和路径都存在 |

- 准备电脑那一步（`unit`、`sandbox` 都一样）：`wt 1.3.1 装好了，在 /home/runner/tools/wt（9502f8c，从 git@github.com:C1fLly/wt.git 取的）`、`准备好了`。机密在日志里显示成 `***`。私钥装完就删是 `prepare.sh` 的写法（`rm -f`，出错也删），日志里看不到删的那一下，没另外核对。
- 合并：`gh pr merge 1 --merge`，合并提交 **`1b3a71d199cab97d5c49eb36aa30913a406f6602`**（父提交 `1811286`、`b35f786`；作者显示 `C1fLly <156543391+C1fLly@users.noreply.github.com>`）。没用 squash、rebase。
- 本机：`git fetch origin`、`git merge --ff-only origin/main` 快进到 `1b3a71d`，本机 `main` 和 `origin/main` **是同一个提交**；合并提交的文件和 `b35f786` 一字不差（`git diff --stat` 空）。
- 删了临时分支 `sop-merge/3-63`：GitHub 上（`git push origin --delete`）和本机（`git branch -d`）。之后 GitHub 上只剩 `main`。
- 合并后 `main` 上自动跑的检查：见下面「合并后 `main` 上的检查」，四个都绿。

## 合并后 `main` 上的检查

`toolkit-check` 第 45028116862 次（`push` 触发，提交 `1b3a71d`），**四个都绿**：`unit` 3 分 01 秒、`sandbox` 8 分 29 秒、`checks` 13 秒、`docs` 7 秒。`sandbox` 比 PR 上那次慢 1 分多（同样的文件），是临时电脑快慢不一，离 30 分钟的上限还远。

## 3-40 留下的「真 GitHub 上要看的几样」现在看到了哪些

接着 3-41 那张表（3-41 时已看到的几样：`actions/checkout` 钉的提交能用、临时电脑是 Ubuntu 26.04.1 加 Git 2.56.1、uv 0.13.7 装得上、bubblewrap 0.11.1 约 3.6 秒装上），这次补上：

| 要看的 | 看到了吗 | 结果 |
|---|---|---|
| 临时电脑上 bwrap 能不能用（AppArmor 放不放行） | 看到了 | 能用：`unit`、`sandbox` 都真起了受限环境，单元测试里起受限环境的那些、流程沙箱全过，没去关系统限制。`kernel.apparmor_restrict_unprivileged_userns` 的值仍没打出来（`prepare.sh` 只在起不来时打），所以还是不知道是「限制开着、规则放行」还是「本来就关着」 |
| 「往终端塞按键」开关（`legacy_tiocsti`）是多少 | 看到了 | 本来就是 0：日志只有「往终端塞按键：已禁用」，没有「设成禁用（0）」那一行，`prepare.sh` 没动它 |
| wt 部署钥匙经 SSH 能不能取 | 看到了 | 能取，wt 1.3.1（`9502f8c`） |
| `unit` 真跑多久、0 项跳过 | 看到了 | 整个 2 分 52 秒（测试 149 秒），597 项、0 项跳过 |
| `sandbox` 真跑多久、0 项跳过 | 看到了 | 整个 7 分 10 秒（剧本 417 秒），45 个、0 个跳过 |
| 临时电脑镜像 | 看到了 | `ubuntu-26.04`；这次四台里 `unit` 是 20261116.88.1，另外三台是 20261116.202.1（同一天的两个小版本），都过 |

## 验收标准第 10 条对照

第 19 节第三段第 10 条「工具包仓库自己的检查在 GitHub 上跑通」：**做到了**。
`C1fLly/sop` 上四个检查（`unit`、`sandbox`、`checks`、`docs`）在 PR #1 上全绿，`unit`、`sandbox` 带 `--no-skip` 且 0 项跳过、经只读部署钥匙取到私有的 wt；
「改动走 PR、四个检查全绿才能合并、合并提交、本机快进接上」这条路实际走通了一遍（第二个文档 PR 又走一遍）。

## 第二个 PR：只含文档

- PR **#2**：<https://github.com/C1fLly/sop/pull/2>，分支 `sop-docs/3-63`（一个提交 `751a301`：这份记录的第一稿、任务清单、交接）→ `main`。推送前对这一个提交又做了一遍同样的保密检查，0 处（只有记录里写着「查了 `qq.com`」那一行字面）。
- 检查第 45029069391 次，四个都绿：`unit` 2 分 48 秒、`sandbox` 5 分 41 秒、`checks` 10 秒、`docs` 5 秒。（GitHub 的接口有一阵把 `docs` 显示成「还在跑」但结论已是成功、整次运行是成功、PR 显示可以合并，是 GitHub 那边显示没跟上。）
- 合并提交 **`27d1ceb69d6dc0faede9fc9abde1b98f3153a360`**；本机快进接上，和 GitHub 一致；临时分支两边都删了。

## 第二个 PR 合并后 `main` 上 `sandbox` 红了

合并 `27d1ceb` 后 `main` 上自动跑的那一次：`unit`、`checks`、`docs` 绿，**`sandbox` 51 秒就红了**，红在准备电脑那一步，测试一个都没跑：

```
往终端塞按键：已禁用
curl: (22) The requested URL returned error: 403     （共 6 次，curl 自己重试了 5 次）
json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
准备跑检查的电脑没成：取不到 GitHub 的主机钥匙
```

- 原因：`prepare.sh` 取 GitHub 的 SSH 主机钥匙用的是不带凭据的 `curl https://api.github.com/meta`。GitHub 的接口对不带凭据的调用按来源地址限次数（每小时 60 次），GitHub 临时电脑的出口地址是很多人共用的，碰上被用完就回 403。前面 PR #1、#1 合并后、PR #2 共 7 次准备电脑都没碰上，这次碰上了——是检查用的准备脚本的问题（靠运气），不是工具包本身。curl 的重试间隔只有几十秒，等不到次数恢复（按小时），多重试没用。
- 改法：取钥匙时带上这次检查自带的只读临时凭据 `github.token`（每个仓库每小时 1000 次，不和别人共用）：
  - `.github/workflows/check.yml`：`unit`、`sandbox` 的「准备跑检查的电脑」那一步 `env` 加 `GITHUB_TOKEN: ${{ github.token }}`（`checks`、`docs` 不取钥匙、不给）；开头的安全说明加一条。仓库权限还是 `contents: read`，机密还是只有 `WT_DEPLOY_KEY`。
  - `tests/ci/prepare.sh`：没给 `GITHUB_TOKEN` 就停下说清楚；凭据经标准输入给 curl（`printf … | curl -K -`，不出现在命令行、进程列表里）；取完马上 `unset GITHUB_TOKEN`，后面装 wt、测试那一步都看不到它（测试那一步本来也没给）。
  - 没选的办法：把 GitHub 的主机钥匙直接写死在仓库里（不用联网，但 GitHub 换钥匙时要手改，工具包别处 `machine/ghsetup.py` 也是从 `gh api meta` 取的，保持一样）；只重跑那一次碰运气（不解决问题）。
- 测试：`tests/unit/test_ci_workflow.py` 加 1 项 `test_host_keys_fetched_with_token`（`unit`、`sandbox` 给了 `github.token`、`checks`、`docs` 没给；`prepare.sh` 取钥匙带凭据头、经 `-K -`、在装 wt 之前去掉凭据）。反着试：把两个文件换回改之前，这项不过；换回改之后 8 项全过。本机另用一个只听 127.0.0.1 的小网页服务核对了「`printf … | curl -K -`」确实把凭据头带上（不带回 403、带了回钥匙），这台电脑上要加 `--noproxy` 才连得到本机（终端里有代理设置），GitHub 临时电脑上没有代理，脚本里不加。
- `prepare.sh` 只能在 GitHub 上真跑，改后的结果看第三个 PR。

## 第三个 PR：修准备脚本（连同这份记录的补充）

分支 `sop-fix/3-63` → `main`，内容：上面两个检查用的文件、1 项单元测试、这份记录的补充、任务清单和交接的更新。
保护要求四个检查全绿才能合并，所以合并了就说明 PR 上四个都绿；它的 PR 编号、每个检查的用时、合并提交编号、合并后 `main` 上那一次的结果写不进它自己里面，见主控窗口的总账。

## 自测

做之前主控的基数：单元测试 597 项、流程沙箱 45 个剧本、总检查 108 个样例，全部通过。

- 开 PR 之后在本机跑了一遍 `uv run python tests/run_all.py`：单元测试 597 项、流程沙箱 45 个剧本、总检查 108 个样例 0 个不合格、文档检查 0 处悬空，**全部通过**。
- 合并、写完文档后又跑一遍：单元测试 597 项、流程沙箱 45 个剧本、总检查 108 个样例 0 个不合格、文档检查 0 处悬空，**全部通过**。
- 修了准备脚本、加了 1 项测试之后再跑一遍：单元测试 **598 项**（多 1 项 `test_host_keys_fetched_with_token`）、流程沙箱 45 个剧本、总检查 108 个样例 0 个不合格、文档检查 0 处悬空，**全部通过**。

## 本机

- 没用 sudo、没碰 Docker、没调用 AI、没开虚拟机。`~/.gitconfig`、`~/.ssh`、gh 登录只用没改；`~/tools/wt` 没碰；技能文件没碰。
- 开发仓库：多了两个合并提交（快进），`git fetch` 顺带建了本机的 `refs/remotes/origin/HEAD`（新版 Git 拉取时自动记远程的默认分支），临时分支建了又删了。
- 核对凭据头时在本机起过一个只听 127.0.0.1 的小网页服务，收两个请求就自己退出了，没留进程。
- 临时目录 `/tmp/sop-3-63/`（0700：PR 说明、检查日志、自测输出）用完删了；查密钥的临时文件查完就删了。

## 没做的

- 没重跑运行 44928690351（理由见「做法」）。
- `prepare.sh` 起得来时仍不打 `kernel.apparmor_restrict_unprivileged_userns`，没为这个改流程文件（改了要多走一次 PR，用处不大）。
- 主控的总账提交不在这次两个 PR 里；以后主控的提交也要照「推分支、开 PR、四个全绿、合并提交、本机快进」走。

## 自己出的错

- 推分支时 `git push -u` 给本机临时分支设了跟踪，随手又取消了，没有影响（分支后来删了）。
- 第二个 PR 的记录第一稿写着「没改任何代码」，合并后 `main` 上 `sandbox` 红了，才有了第三个 PR 和这些补充；第一稿那两句在这一版改了。
- 3-41、3-40 时只想到「钥匙能不能取」，没想到不带凭据的接口会被共用地址的次数限制挡住；前 7 次没碰上，第 8 次才碰上。
