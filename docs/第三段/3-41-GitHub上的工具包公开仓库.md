# 3-41 在 GitHub 上建工具包公开仓库，检查跑通

2026-11-22，主控窗口派的子代理做的。**做了一部分：推送之前的保密检查查出提交历史里有本机的邮箱，照主控的规矩没有建仓库、没有推送，停下等用户定。** GitHub 上什么都没建、没改、没删（只做了只读的查看）。没动隔离、放行事件、事件日志；没碰 Docker；没用 sudo；没调用 AI，0 美元。

## 做了什么

### 1. 先看仓库在不在（只读）

`gh repo view C1fLly/sop`：「Could not resolve to a Repository」，**还没有**。账号下现有 6 个仓库（`sop-w40-trial` 公开，其余私有），没动。

### 2. 推送之前的保密检查（整个 Git 历史，78 个提交）

临时文件都在 `/tmp/sop-3-41/`（0700，用完删了）。只打印「命中几处」，没有打印任何密钥。

| 查什么 | 怎么查 | 结果 |
|---|---|---|
| 本机的 `ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_BASE_URL`（整串和主机名）、`CLAUDE_CODE_MESSAGING_TOKEN`、`gh auth token` 的值 | 每个提交 `git grep -F -l`；全部提交说明、作者；`git log --all -p` 全部改动行 `grep -F -c` | 全部 0 处 |
| 常见密钥写法：私钥开头 `BEGIN … PRIVATE KEY`、`ghp_`、`gho_`、`ghs_`、`github_pat_`、`sk-ant-`、`sk-…`、`AKIA…`、`xox?-`、`AIza…`、JWT | `git log --all -p` 上按正则数 | 全部 0 处；历史里没有二进制文件（`--numstat` 没有 `-`） |
| 本机的 IP、服务地址 | 同上 | 只有虚拟机网关 `10.0.2.2`、本机代理端口 `127.0.0.1:7890`、各处的 `example.invalid` 假地址；AI 服务的地址 0 处 |
| 邮箱 | 同上，列出所有像邮箱的字 | 除了 `noreply@anthropic.com` 和测试里的假邮箱，**只有一个真邮箱，见下** |
| 本机用户名、提交作者的名字 | 本机用户名的几种大小写写法 | 见下 |
| 用户的私有仓库名（`system-admin`、`SanChuanZL`、`myapp`、`Matt`） | 同上 | 0 处（`C1fLly/` 后面只出现工具包、wt、几个试验仓库的名字） |

**查出来的（所以没推送）：**

1. **78 个提交的作者和提交者都是本机 `~/.gitconfig` 里的身份：一个名字加一个 QQ 邮箱**（这里故意不写原文，免得改写历史之后文件里还留着）。这是 QQ 邮箱，邮箱前面就是 QQ 号。仓库一公开，任何人 `git log` 就看得到。用户的 GitHub 资料里邮箱是不公开的（`gh api user` 的 `email` 是 null）。
   - **已经公开过一次**：公开的试验仓库 `C1fLly/sop-w40-trial` 的提交也是这个邮箱（只读查了最近 5 个提交）。那个仓库 W40 第二部分做完要删（3-46，删之前问）。
2. **本机用户名 `sanchuanzl` 在历史里出现约 16 处**：都是路径（`/home/sanchuanzl/...`，在第一段的试验脚本、几份记录里），另有交接里一句 `~/999_/SanChuanZL`。和提交作者的名字是同一个称呼。

`docs/` 也一并看了一眼（按关键词，没有逐字通读 3.8 MB）：里面有用户的原始要求、他和写设计的人定下的事、AI 花了多少钱、他电脑上在用哪些程序（微信、QQ、cc-switch、Codex 等，出现在「本机有没有被改动」的核对里）、本机代理端口 7890、本机 AppArmor 规则的文件名。**没有找到密钥、账号密码、手机号、身份证号之类**（「身份证号、手机号、住址、银行卡」只出现在产品风险分级的说明里，「12 个人的小设计公司」是试验用的假需求）。这些是不是可以公开，按交接「`docs/` 里写着的事实已告诉他」处理；用户想再看一眼的话，可以在决定邮箱时一起说。

### 3. 先做好的本地部分（不碰 GitHub）

- `bootstrap.sh`：`DEFAULT_REPO='https://github.com/C1fLly/sop.git'`（公开仓库，不登录也能取）；说明和报错文字跟着改。
- `kernel/projectnew.py`：`DEFAULT_REPO` 同一个地址（`sop project new` 写进项目 `sop.json` 的工具包仓库）。
- `tests/unit/test_bootstrap.py`：原来那项「不给 `--repo` 要报『没有仓库地址』」改成「不给 `--repo` 用默认仓库，照样先看系统、不是 26.04 就停、没上网、什么都没建」；新加一项核对两处默认地址一样、是 `C1fLly/sop`，环境变量 `SOP_TOOLKIT_REPO` 照样能换（自测、虚拟机都靠它，不会去连真 GitHub）。

仓库还没建，地址先填上没有坏处：`bootstrap.sh` 还没发给任何人；自测、虚拟机验证都用 `--repo` 或 `SOP_TOOLKIT_REPO`。

### 4. 改写身份的试跑（只在 `/tmp` 的克隆上，真仓库没动）

为了给用户一个有数的选项，在 `/tmp/sop-3-41/rw`（`git clone --no-local` 出来的一份）上用 `git filter-branch --env-filter` 把作者和提交者换成 GitHub 给的不公开邮箱 `156543391+C1fLly@users.noreply.github.com`、名字 `C1fLly`：78 个提交全部换掉，**每个提交里的文件一字不差**（78 个目录指纹前后一样），历史里再也找不到那个 QQ 号；代价是 78 个提交编号全变。现在的文档里有 42 个本仓库的提交编号被引用（在交接和主控总账这 2 份里），代码里没有用到本仓库自己的提交编号。克隆试完删了。

## 要用户定的

**提交历史里的 QQ 邮箱怎么办**（推荐乙）：

- **甲、照原样公开。** 最省事。代价：QQ 号和邮箱永久公开在工具包仓库上（`sop-w40-trial` 上已经公开着，但那个仓库 12 月要删）；以后每个提交也带着它。
- **乙（推荐）、推送之前把本地历史的身份换成 GitHub 的不公开邮箱**，以后在这个仓库里提交也用它（只设在这个仓库自己的 `.git/config`，不改 `~/.gitconfig`）。理由：3-10 已经替新电脑定了「提交邮箱用 GitHub 给的不公开邮箱」，说明本来就打算不公开；文件内容一字不变（试跑过）。代价：本地 78 个提交编号全变，交接、主控总账里引用的 42 个旧编号对不上，要附一张新旧对照表（由做这一步的子代理生成，放进 `docs/`）；改写前先 `git bundle` 备份一份旧历史。名字要不要也换成 `C1fLly`、路径里的 `sanchuanzl` 要不要一起抹，也请一起定（推荐：名字换成 `C1fLly`；路径里的用户名不抹，抹了要改文件内容，第一段的试验脚本就不是原样了）。
- **丙、GitHub 上只放一个「从现在开始」的提交**（把现在的文件做成一个新的起点推上去，旧历史只留在本机）。代价：GitHub 上看不到开发过程；本地和 GitHub 的历史接不上，以后每次推送都要额外处理，不推荐。

另外两件 3-41 做下去时要定、但不挡现在这一步的（推荐的做法写在下面「接着做的步骤」里，主控可以连同上面一起问）：

- **主线保护对管理员也生效、必须走 PR。** 照设计书 16.5 第 4 条「检查全过……然后才合并」和项目仓库的做法（`kernel/projectgh.py` 的 `MAIN_PROTECTION`），推荐对管理员同样生效。后果：之后本机的提交不能直接 `git push` 到 `main`，要推一条分支、开 PR、四个检查全绿再合并。为了合并后本机还能直接接上（提交编号不变），推荐仓库只开「合并提交」一种合并方式（不开「压成一个」「变基」）——这一点和项目仓库「只允许压成一次提交」不同，因为工具包按提交编号装，本机和 GitHub 的编号要一致。另一条路：对管理员不生效（用户和主控能直接推 `main`，检查只是事后看），不推荐。
- 别人从分叉仓库发来的 PR 拿不到机密、`unit`、`sandbox` 会红（3-40 已写），不处理。

## 接着做的步骤（用户定了之后，下一个子代理照做）

1. （选乙时）`git bundle create /tmp/…/sop-old.bundle --all` 备份；`git filter-branch --env-filter … -- --all` 改写（作者邮箱、提交者邮箱等于 `git config --global user.email` 的，邮箱换成不公开邮箱、名字换成 `C1fLly`；旧邮箱从 `~/.gitconfig` 读、不要写进任何文件）；核对改写前后每个提交的目录指纹（`git log --format=%T`）一样；删掉 `refs/original/`；`git config user.email 156543391+C1fLly@users.noreply.github.com`、`git config user.name C1fLly`（只这个仓库）；生成新旧提交编号对照表；**再跑一遍第 2 节的保密检查**，0 处才往下。
2. `gh repo view C1fLly/sop` 再确认没有；`gh repo create C1fLly/sop --public --description …`（不加 README、许可，空仓库）。
3. `git remote add origin git@github.com:C1fLly/sop.git`；`git push -u origin main`（**先推送再开保护**，不会把自己锁死）。推送会触发一次检查。
4. 开主线保护：`gh api -X PUT repos/C1fLly/sop/branches/main/protection --input -`，内容：
   ```json
   {"required_status_checks": {"strict": false, "contexts": ["unit", "sandbox", "checks", "docs"]},
    "enforce_admins": true,
    "required_pull_request_reviews": {"required_approving_review_count": 0},
    "restrictions": null, "allow_force_pushes": false, "allow_deletions": false}
   ```
   读回来核对四个检查名、对管理员生效、禁止强推和删除（和 `projectgh.check_protection` 一样的核对）。合并方式按上面定的设（`gh api -X PATCH repos/C1fLly/sop -f allow_merge_commit=true -F allow_squash_merge=false -F allow_rebase_merge=false`）。
5. 看推送触发的那一次检查（`gh run list -R C1fLly/sop`、`gh run view <编号> --log`）：预期 `checks`、`docs` 绿；`unit`、`sandbox` 红在「准备跑检查的电脑」那一步、wt 之前（没有机密 `WT_DEPLOY_KEY`，`prepare.sh` 说清要什么后退出码 1）。在日志里看 3-40 留下要在真 GitHub 上看的几样：`actions/checkout` 那个提交编号能不能取代码；`ubuntu-26.04` 上 `apt-get install bubblewrap` 要多久、受限环境起不起得来（AppArmor 放不放行 bwrap）；`legacy_tiocsti` 是多少；`checks`、`docs` 各跑多久。哪样不对照实改，**不用关系统限制、去掉 `--no-skip` 的办法让它过**。
6. 用户在 `C1fLly/sop` 的 Settings → Secrets and variables → Actions 放好 `WT_DEPLOY_KEY` 之后，主控重跑：`gh run rerun <编号> -R C1fLly/sop --failed`（或 `gh workflow run toolkit-check -R C1fLly/sop --ref main` 新跑一次），然后看：`unit`、`sandbox` 的「准备」那一步 wt 1.3.1 经 SSH 取到、私钥删了（日志里有「装完删掉」那一行）；`unit` 0 项跳过、521+ 项全过；`sandbox` 43 个剧本全过、要多久（本机约 5 分钟，`timeout-minutes: 30`）；四个都绿后，`gh api repos/C1fLly/sop/commits/main/check-runs` 四个名字都是 `success`。
7. 记录补上真 GitHub 上看到的，任务清单改成「做完」。

## 结果

- 全部自测全过（下面「自测」一节）。
- GitHub 上：什么都没建、没改、没删。只读用了 `gh repo view C1fLly/sop`、`gh repo list C1fLly`、`gh api user`、`gh api repos/C1fLly/sop-w40-trial/commits`（只读）。
- 本机：`/tmp/sop-3-41/` 用完删了；`~/.gitconfig`、`~/.ssh`、gh 登录只读；`~/tools/wt` 没碰；`/tmp/wt-deploy/key` 没读、没动。

## 自测

做之前主控的基数：单元测试 527 项、流程沙箱 43 个剧本、总检查 108 个样例，全部通过。做完 `uv run python tests/run_all.py`：单元测试 528 项（多 1 项 `test_default_repo`）、流程沙箱 43 个剧本、总检查 108 个样例 0 个不合格、文档检查 0 处悬空，全部通过。

## 没做的

- 建仓库、开保护、推送、看真 GitHub 上的检查：全部没做，等用户定邮箱的事（上面「接着做的步骤」）。
- 3-40 留下的真 GitHub 上要看的几样（临时电脑上 bwrap、`actions/checkout` 那个提交编号、跑多久、`legacy_tiocsti`、wt 部署钥匙经 SSH 能不能取）：一样都还没看到。

## 自己出的错

- 没有。
