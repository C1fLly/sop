# 3-41 在 GitHub 上建工具包公开仓库，检查跑通

2026-11-22，主控窗口派的子代理分两次做。**第一次**（提交 `181716a`，改写前是 `27847dc`）：推送之前的保密检查查出提交历史里有本机的 QQ 邮箱，没建仓库、没推送，停下等用户定（下面「第一次」各节，原样留着）。**第二次**（用户答「按推荐」之后接着做，见文末「第二次」各节）：备份旧历史、把全部 80 个提交的作者和提交者换成 GitHub 不公开邮箱（文件内容一字不差）、建公开仓库 `C1fLly/sop`、推送、看了第一次检查、开主线保护、只开合并提交。**还是做了一部分**：真 GitHub 上 `checks`、`docs` 绿；`unit`、`sandbox` 照预期红在「准备跑检查的电脑」取 wt 那一步，要用户放好机密 `WT_DEPLOY_KEY` 再重跑，拆成 **3-63**。

## 第一次：做了什么

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

## 第一次：要用户定的

**提交历史里的 QQ 邮箱怎么办**（推荐乙）：

- **甲、照原样公开。** 最省事。代价：QQ 号和邮箱永久公开在工具包仓库上（`sop-w40-trial` 上已经公开着，但那个仓库 12 月要删）；以后每个提交也带着它。
- **乙（推荐）、推送之前把本地历史的身份换成 GitHub 的不公开邮箱**，以后在这个仓库里提交也用它（只设在这个仓库自己的 `.git/config`，不改 `~/.gitconfig`）。理由：3-10 已经替新电脑定了「提交邮箱用 GitHub 给的不公开邮箱」，说明本来就打算不公开；文件内容一字不变（试跑过）。代价：本地 78 个提交编号全变，交接、主控总账里引用的 42 个旧编号对不上，要附一张新旧对照表（由做这一步的子代理生成，放进 `docs/`）；改写前先 `git bundle` 备份一份旧历史。名字要不要也换成 `C1fLly`、路径里的 `sanchuanzl` 要不要一起抹，也请一起定（推荐：名字换成 `C1fLly`；路径里的用户名不抹，抹了要改文件内容，第一段的试验脚本就不是原样了）。
- **丙、GitHub 上只放一个「从现在开始」的提交**（把现在的文件做成一个新的起点推上去，旧历史只留在本机）。代价：GitHub 上看不到开发过程；本地和 GitHub 的历史接不上，以后每次推送都要额外处理，不推荐。

另外两件 3-41 做下去时要定、但不挡现在这一步的（推荐的做法写在下面「接着做的步骤」里，主控可以连同上面一起问）：

- **主线保护对管理员也生效、必须走 PR。** 照设计书 16.5 第 4 条「检查全过……然后才合并」和项目仓库的做法（`kernel/projectgh.py` 的 `MAIN_PROTECTION`），推荐对管理员同样生效。后果：之后本机的提交不能直接 `git push` 到 `main`，要推一条分支、开 PR、四个检查全绿再合并。为了合并后本机还能直接接上（提交编号不变），推荐仓库只开「合并提交」一种合并方式（不开「压成一个」「变基」）——这一点和项目仓库「只允许压成一次提交」不同，因为工具包按提交编号装，本机和 GitHub 的编号要一致。另一条路：对管理员不生效（用户和主控能直接推 `main`，检查只是事后看），不推荐。
- 别人从分叉仓库发来的 PR 拿不到机密、`unit`、`sandbox` 会红（3-40 已写），不处理。

## 第一次：接着做的步骤（用户定了之后，下一个子代理照做）

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

## 第一次：结果

- 全部自测全过（下面「自测」一节）。
- GitHub 上：什么都没建、没改、没删。只读用了 `gh repo view C1fLly/sop`、`gh repo list C1fLly`、`gh api user`、`gh api repos/C1fLly/sop-w40-trial/commits`（只读）。
- 本机：`/tmp/sop-3-41/` 用完删了；`~/.gitconfig`、`~/.ssh`、gh 登录只读；`~/tools/wt` 没碰；`/tmp/wt-deploy/key` 没读、没动。

## 第一次：自测

做之前主控的基数：单元测试 527 项、流程沙箱 43 个剧本、总检查 108 个样例，全部通过。做完 `uv run python tests/run_all.py`：单元测试 528 项（多 1 项 `test_default_repo`）、流程沙箱 43 个剧本、总检查 108 个样例 0 个不合格、文档检查 0 处悬空，全部通过。

## 第一次：没做的

- 建仓库、开保护、推送、看真 GitHub 上的检查：全部没做，等用户定邮箱的事（上面「接着做的步骤」）。
- 3-40 留下的真 GitHub 上要看的几样（临时电脑上 bwrap、`actions/checkout` 那个提交编号、跑多久、`legacy_tiocsti`、wt 部署钥匙经 SSH 能不能取）：一样都还没看到。

## 第一次：自己出的错

- 没有。

## 第二次：用户的答复（2026-11-22，原话「按推荐」）

1. QQ 邮箱选**乙**：推送前把本地历史的作者和提交者全部换成 GitHub 不公开邮箱 `156543391+C1fLly@users.noreply.github.com`、名字 `C1fLly`；以后这个仓库的提交也用它，只设在仓库自己的 `.git/config`，不碰 `~/.gitconfig`。改写前完整备份旧历史。
2. 主线保护：对管理员也生效、必须通过 `unit`、`sandbox`、`checks`、`docs` 四个检查（要走 PR）、仓库只开「合并提交」。
3. 路径里的本机用户名 `sanchuanzl`：不抹。
4. `docs/` 里用户在用哪些程序、本机代理端口之类：用户没有要求抹，不抹（看到的类别列在下面「`docs/` 里的本机信息」）。
5. 机密 `WT_DEPLOY_KEY` 由用户自己放；子代理不读、不放、不删 `/tmp/wt-deploy/key`。

## 第二次：做了什么

### 1. 备份旧历史

`git bundle create ~/tools/backup/sop-dev-3-41改写前.bundle --all`（新建的目录 `~/tools/backup/`，0700；文件 0600，约 2.0 MB，sha256 `2c2d73a1fb89cc279caad0105802171d58006a22c9c47c429b5b60401ecd7932`）。`git bundle verify` 说完整；在 `/tmp` 里从它克隆一份，80 个提交编号和目录指纹和改写前一样、`fsck` 没报错（克隆用完删了）。**这份备份里有旧的 QQ 邮箱：不在仓库里、没推送，不要拷进仓库或传到网上。** 要退回旧历史：`git clone ~/tools/backup/sop-dev-3-41改写前.bundle`。

### 2. 改写身份

（第一次查的时候是 78 个提交；第一次自己的两个提交（记录、总账）加上之后是 80 个，这次全查、全改。）

改写前仓库只有一条分支 `main`、没有标签、没有别的工作目录、没有备注、没有签名的提交；80 个提交的作者和提交者全是 `~/.gitconfig` 里那一个身份。

`git filter-branch --env-filter … -- --all`：作者邮箱、提交者邮箱等于 `git config --global user.email` 的（旧邮箱只放在环境变量里，没写进任何文件），邮箱换成不公开邮箱、名字换成 `C1fLly`。核对：

| 核对 | 结果 |
|---|---|
| 80 个提交的目录指纹（`git log --format=%T`，按顺序）改写前后 | 一字不差 |
| 每个提交除作者、提交者、父提交、目录那几行以外（提交说明等） | 80 个都一样 |
| 作者时间、提交时间；父提交个数 | 80 个都一样 |
| 作者、提交者 | 80 个都是 `C1fLly <156543391+C1fLly@users.noreply.github.com>` |
| 所有引用 | 只剩 `refs/heads/main`；`refs/original/` 删了（目录也删了）；没有标签 |
| 旧对象 | `git reflog expire --expire=now --all` 加 `git gc --prune=now` 之后，旧的最后一个提交在对象库里已经没有 |
| 对象库里全部对象（不只是提交，也包括所有文件内容）查旧邮箱、邮箱前面那串号 | 0 处、0 处（只数了命中次数，没有打印） |
| 提交头和提交说明里旧名字 | 0 处 |
| `.git` 目录里对象以外的文件查旧邮箱 | 0 处 |

然后 `git config user.email 156543391+C1fLly@users.noreply.github.com`、`git config user.name C1fLly`（只这个仓库的 `.git/config`）；`~/.gitconfig` 没动。

### 3. 交接和总账里的旧编号改成新编号

全部被 Git 管着的文件里找 7 位以上的十六进制串、是旧提交编号开头的：只有 `docs/主控/总账.md` 43 处、`docs/交接.md` 2 处（交接第 7 条的 `256d56c` → `d73541b`、第 8 条的 `7c20a14` → `f15e76f`），共 43 个不同的编号，没有一个对得上两个提交。按位数换成新编号的开头；核对：把两份文件里所有 7 位十六进制串都换成同一个记号后，改前改后一字不差（只改了编号）。`9502f8c`（wt 的）、`5863806`（技能上游的）、`3d3c42e`（`actions/checkout` 的）不是本仓库的提交，没动。新旧编号对照表在文末。

### 4. 推送之前再做一遍保密检查（改写后的整个历史，80 个提交）

查找用的值：本机 12 个 `ANTHROPIC_…` 变量和 `CLAUDE_CODE_MESSAGING_TOKEN` 的值（都在 8 个字以上）、`ANTHROPIC_BASE_URL` 的主机名、`gh auth token` 的值，共 15 条，放在 `/tmp/sop-3-41b/`（0700）的一个临时文件里，查完删了；没有打印任何值。

| 查什么 | 结果 |
|---|---|
| 上面 15 条：每个提交 `git grep -F -l`；`git log --all -p` 加作者、提交者、提交说明；对象库里全部对象 | 0、0、0 |
| 常见密钥写法（私钥开头、`ghp_`、`gho_`、`ghs_`、`github_pat_`、`sk-ant-`、`sk-…`、`AKIA…`、`xox?-`、`AIza…`、JWT） | 0 |
| 二进制文件 | 0 |

### 5. 建仓库、推送

`gh repo view C1fLly/sop` 再看一次，还没有；`gh repo create C1fLly/sop --public --description 'AI 开发 SOP 工具包（sop 命令）'`（空仓库，不加说明文件、许可）。`git remote add origin git@github.com:C1fLly/sop.git`、`git push -u origin main`：GitHub 上 `main` 是 `1811286`，和本机一样。GitHub 上读回来的提交邮箱是不公开邮箱。

不登录也能取（在 `/tmp` 里用空的主目录、不读系统 Git 设置、不让 Git 问密码）：`git ls-remote`、`git clone --depth 1 https://github.com/C1fLly/sop.git` 都成，取到 800 个文件；`https://raw.githubusercontent.com/C1fLly/sop/main/bootstrap.sh` 下下来和本机的一字不差（3-13 记录里写的「没试过」现在试了）。

### 6. 推送触发的第一次检查（开保护之前看的）

`toolkit-check` 第 44928690351 次（提交 `1811286`）：

| 检查 | 结果 | 用时 | 说明 |
|---|---|---|---|
| `docs` | 绿 | 整个 11 秒（文档检查本身不到 1 秒） | 章节 89 个、编号 162 个，悬空 0 处；命令 128 处、路径 103 处都存在 |
| `checks` | 绿 | 整个 15 秒（总检查约 5 秒） | 108 个样例，0 个不合格 |
| `unit` | 红 | 8 秒 | 红在「准备跑检查的电脑」最后取 wt 那一步：「没给读 wt 仓库的钥匙（仓库机密设置里的 WT_DEPLOY_KEY）……」，退出码 1；「内核单元测试」那一步没跑 |
| `sandbox` | 红 | 8 秒 | 同上，「流程沙箱」那一步没跑 |

3-40 留下要在真 GitHub 上看的几样：

| 要看的 | 看到了吗 | 结果 |
|---|---|---|
| `actions/checkout` 钉的提交 `3d3c42e…`（v7.0.1）能不能用 | 看到了 | 能用，四个检查都取到了代码；`persist-credentials: false` 生效 |
| 临时电脑是什么 | 看到了 | Ubuntu 26.04.1 LTS，镜像 `ubuntu-26.04` 版本 20261116.202.1；自带 Python 3.14（uv 用的是 3.14.4）、git 2.56.1 |
| uv 0.13.7 用工具包自己的 `uv.sh` 装 | 看到了 | 装上了，版本对，约 0.5 秒 |
| `apt-get install bubblewrap` 要多久 | 看到了 | 连 `apt-get update` 约 3.6 秒，装上的是 bubblewrap 0.11.1 |
| 受限环境起不起得来（AppArmor 放不放行 bwrap） | 看到了 | 起得来：`bwrap --unshare-all … true` 过了，没去关系统限制。`kernel.apparmor_restrict_unprivileged_userns` 是多少没打出来（`prepare.sh` 只在起不来时打），所以不知道是「限制开着、规则放行」还是「限制本来就关着」 |
| `legacy_tiocsti` 是多少 | 看到了 | 本来就是 0（没有打出「设成禁用」那一行），`prepare.sh` 没动它 |
| wt 部署钥匙经 SSH 能不能取 | 没看到 | 要等机密 |
| `unit`、`sandbox` 真跑要多久、0 项跳过 | 没看到 | 要等机密 |

`checks`、`docs` 是绿的，工具包这边没有要改的。

### 7. 开主线保护、设合并方式（推送和看完检查之后）

- `gh api -X PATCH repos/C1fLly/sop -F allow_merge_commit=true -F allow_squash_merge=false -F allow_rebase_merge=false`：读回来只开「合并提交」，默认分支 `main`，公开。
- `gh api -X PUT repos/C1fLly/sop/branches/main/protection`，内容就是「第一次：接着做的步骤」第 4 步那段（四个检查名、`strict: false`、对管理员生效、要走 PR 且 0 人批准、禁止强推和删除）。另用 `GET` 读回来核对：必须通过 `checks`、`docs`、`sandbox`、`unit`，对管理员生效，要走 PR（0 人批准），禁止强推、禁止删除，没有别的限制；仓库没有另外的规则集。
- 没把自己锁死：开了保护之后仍能用接口读、改保护设置（仓库管理员改设置不受分支保护管）。

**从现在起，本机的提交不能直接推到 GitHub 的 `main`**：要推一条分支、开 PR、四个检查全绿、用「合并提交」合并，再在本机 `git fetch` 后 `git merge --ff-only origin/main`（本机的提交编号不变，多一个合并提交）。在用户放好机密之前 `unit`、`sandbox` 一直红，**什么 PR 都合不进去**；这期间本机照常提交，只是先不上 GitHub。这次任务最后那个记录提交就留在本机、比 GitHub 上多一个（下面「验证」里试推了一次，被 GitHub 挡住，正是保护生效的样子）。

## 第二次：验证

### 自测

做之前主控的基数：单元测试 528 项、流程沙箱 43 个剧本、总检查 108 个样例，全部通过。

- **第一遍**（改写身份、改文档之后）：单元测试 528 项里 **1 项出错**（`test_project_new` 的 `test_needs_git_identity`），流程沙箱 43 个、总检查 108 个样例、文档检查都过。
- 原因：这项测试把假主目录里的 `.gitconfig` 删掉，要 `sop project new` 在「这台电脑上 Git 的提交身份还没设」那一步停下。可 `kernel/projectnew.py` 的 `git_identity()` 是在**当前目录**执行 `git config --get user.name/user.email`，自测在工具包仓库里跑，而这次按用户的决定往工具包仓库自己的 `.git/config` 里设了身份，于是它说「设了」，一直走到新项目第一次提交才因为没有身份失败（Git 报 `Author identity unknown`）。这是工具包原来就有的问题：小白在任何一个自己设了身份的仓库里执行 `sop project new` 都会这样，只是以前没有哪个仓库在 `.git/config` 里设身份，没暴露。`machine/ghsetup.py` 里同样的核对早就写明「在根目录读」，这里漏了。
- 改法：`git_identity()` 改成 `git -C / config --get …`（和 `ghsetup.py` 一样，只看全局和系统的设置，正是新项目第一次提交看得到的）。加单元测试 `test_git_identity_ignores_current_repo`：在一个自己设了身份的临时仓库里、全局没设时，`git_identity()` 说没设、`sop project new` 停在提交身份那一步、没调 gh、没建项目目录。反着试：把 `projectnew.py` 换回改之前，新测试不过、原来那项出错；换回改之后 16 项全过。
- **第二遍**（改了之后）：`uv run python tests/run_all.py`：单元测试 529 项（多 1 项 `test_git_identity_ignores_current_repo`，0 项跳过）、流程沙箱 43 个剧本、总检查 108 个样例 0 个不合格、文档检查 0 处悬空（命令 128 处、路径 103 处都存在），**全部通过**。

GitHub 上 `main`（`1811286`）还没有这个改动，跟着本机的记录提交一起在 3-63 走 PR 上去（GitHub 的临时电脑上取出来的仓库没有自己的身份设置，`unit` 本来也碰不上这个问题）。

### 保护生效

提交这次的记录之后，试着直接 `git push origin main`：GitHub 拒绝了——「GH006: Protected branch update failed for refs/heads/main」「Changes must be made through a pull request」「4 of 4 required status checks are expected」，`! [remote rejected] main -> main (protected branch hook declined)`。GitHub 上 `main` 还是 `1811286`。之后用接口读保护设置照样读得到（没把自己锁死）。（试推的是补这一段之前的提交；补上这一段后用 `git commit --amend` 并进同一个提交，只在本机，没再推。）

### 本机

- 没用 sudo、没碰 Docker、没调用 AI。`~/.gitconfig`、`~/.ssh`、gh 登录只用没改；`~/tools/wt` 没碰；`/tmp/wt-deploy/key` 没读、没动。
- 新建了 `~/tools/backup/`（只有旧历史的备份一个文件）。
- 临时目录 `/tmp/sop-3-41b/`（0700：改写前后的编号和指纹清单、测试输出）用完删了；查密钥用的临时文件查完就删了。

## 第二次：`docs/` 里的本机信息（用户说不抹，只列类别和文件）

按关键词查的，没有逐字通读，没有抄内容：

- **用户电脑上装着、在用的程序**（微信、QQ、cc-switch、Codex 等）：`docs/第三段/` 的 3-06、3-12、3-23、3-24、3-25、3-50、3-58、3-41 几份记录，试验脚本 `docs/试验/脚本/AI共用/sbx.sh`、`docs/试验/脚本/S2/sandbox-ai.sh`；「微信」另出现在设计书和 `docs/历史/` 的旧版里。
- **本机代理端口**：31 个文件，包括 `bootstrap.sh`（代理的例子）、第一段的试验脚本和记录、3-13、3-50 的记录、单元测试。
- **本机的 AppArmor 规则文件名**：17 个文件，包括审查报告、3-05、3-09、3-33 到 3-35 的记录、`machine/components.py`、`machine/install/docker-rootless.sh`、`machine/migrate/inventory.py`。
- **用户那份 GitHub 凭据带删仓库权限**：15 个文件，包括交接、任务清单、设计书和旧版、审查报告、3-10 的记录、第二段小结。
- **主目录路径和本机用户名、本机其他目录的名字**（`~/Project`、`~/999_` 等，都是「不许碰」的那几个）：几十个文件，主要是各份提示词、交接、审查报告、设计书和旧版、第一段的试验脚本。
- **用户本人的原始要求、和写设计的人定下的事、调用 AI 花了多少钱**：`docs/原始要求.md`、交接、任务清单、各段的 `记账.json`。
- 没有找到：密钥、账号密码、AI 服务的地址、手机号、身份证号。

## 第二次：结果

- GitHub 上**建了、改了**（只动了 `C1fLly/sop`）：建了公开仓库 `C1fLly/sop`；推送了 `main`（80 个提交，到 `1811286`）；仓库设置里合并方式只开「合并提交」；`main` 开了分支保护。推送触发了一次检查（第 44928690351 次），`checks`、`docs` 绿，`unit`、`sandbox` 红在取 wt 那一步。另有一次被挡住的推送（见「验证」）。没碰 `C1fLly/wt`、`C1fLly/sop-w40-trial`、账号设置；没放机密。
- 代码：`kernel/projectnew.py` 的 `git_identity()` 改成在根目录读（只看全局和系统的身份设置），单元测试加 1 项（见「验证」）。
- 本机：仓库的历史改写了（提交编号全变，文件内容不变）、`.git/config` 加了 `user.name`、`user.email`、`origin` 和 `main` 跟踪 `origin/main`；新建了 `~/tools/backup/`（只放旧历史的备份）。`~/.gitconfig`、`~/.ssh`、gh 登录只用没改；`~/tools/wt` 没碰；`/tmp/wt-deploy/key` 没读、没动；没用 sudo、没碰 Docker、没调用 AI，0 美元。

## 第二次：没做的（拆成 3-63）

**用户放好机密之后**（要用户自己动手）：

1. 用户在 GitHub 网页 `C1fLly/sop` → Settings → Secrets and variables → Actions → New repository secret，名字 `WT_DEPLOY_KEY`，内容是那把只读部署钥匙的私钥全文（对应的公钥要在 `C1fLly/wt` → Settings → Deploy keys 里、不勾写权限）。
2. 主控重跑那一次：`gh run rerun 44928690351 -R C1fLly/sop --failed`（只重跑红的 `unit`、`sandbox`），然后 `gh run view 44928690351 -R C1fLly/sop --log` 看：
   - 「准备跑检查的电脑」里 wt 1.3.1 经 SSH 取到、最后打出「准备好了」；私钥是装完就删的（`prepare.sh` 的 `rm -f`）；
   - `unit`：0 项跳过（`--no-skip`）、529 项全过（这次本机记录提交里加了 1 项，走 PR 时跑的是 529；只重跑 `1811286` 那一次是 528）；
   - `sandbox`：43 个剧本全过，记下要多久（本机约 5 分钟，`timeout-minutes: 30`）；
   - 四个都绿后 `gh api repos/C1fLly/sop/commits/1811286484283c87af5bfe0746e717ec37dbd830/check-runs --jq '.check_runs[]|[.name,.conclusion]'` 四个都是 `success`。
3. 再把本机比 GitHub 多出来的提交走一遍 PR（推一条分支、开 PR、四个检查全绿、合并提交），本机 `git merge --ff-only origin/main` 接上。开 PR、合并是在 GitHub 上改东西，主控照规矩办。
4. 哪一样不对照实改，不关系统限制、不去掉 `--no-skip`。

另外：`prepare.sh` 起得来时不打 `kernel.apparmor_restrict_unprivileged_userns`，所以不知道 GitHub 的临时电脑上这个限制开没开；要知道的话可以以后顺手在 `prepare.sh` 里打一行（这次没改，`checks`、`docs` 已经绿，不为这个多推一次）。

## 第二次：自己出的错

- 动手前没想到「往工具包仓库的 `.git/config` 设身份」会改变在这个仓库里跑的自测：第一遍全部自测出了 1 项错，查明是工具包原来的问题（见「验证」），改了代码、加了测试。改的是 `kernel/projectnew.py` 的一个核对（没动隔离、放行事件、事件日志），第一次推送的 `main` 上还没有它。
- 别的没有。

## 新旧提交编号对照表（身份改写，2026-11-22）

按提交顺序（第 1 个最早）。改写只换了作者和提交者，每一对的文件内容、提交说明、时间都一样。旧编号只在本机的备份 `~/tools/backup/sop-dev-3-41改写前.bundle` 里还有。

| 序号 | 旧编号 | 新编号 |
|---|---|---|
| 1 | `961ccc73895a92b8fb6a55ca0e23b83947506a55` | `42ed4b8bbbc3663b1dc79caceca0307e44f9df6d` |
| 2 | `9355dc129e068181b5be28e27f2e63563bd5fb05` | `36f4f0678a4fe44d1578e696a8cbb65a7d903817` |
| 3 | `7861026ab2f4238a2ec3ca5842fec0c67cbdbab0` | `36010ba18191984ef4f19b906022c04a5c8f8dd4` |
| 4 | `c6bcecdfef114964f34dbd6dd4d4e2b9685ee343` | `a583ab5be282f469c5901c25a6c57d89f05f2c48` |
| 5 | `5bbf66f0e8c0a5331d40dbd93ca81c471527541f` | `ebc69909bda27f144cb23afe2b1cb3e0f7956b1f` |
| 6 | `0e287be028f946da43eb73fd66d5d3d110000bd2` | `bd3f7485a723ba9512ab6f2eee19ca2d837feb8a` |
| 7 | `d4308d705ebefc472e8d05278531219c4b4a697d` | `11f7a70a2b307d754550e0d92040b355d5d97521` |
| 8 | `7cccf765d43996f6fb4017bdc9e7762f1095c970` | `30800a1537e8726114eee0eec0aaedecb22a2fe7` |
| 9 | `0c29e2483c536b00010829f895b03c1e357883b7` | `62e0acafa759bca58c405b83143a9b51f9e41f92` |
| 10 | `7b0ceda66da8cb95a13e3b360ed9fccba434803e` | `627ebdec08fbb1eb4d9aef279c8a26c84cea39a0` |
| 11 | `d6c47010c20887743dfbf949e56a45a8cf2a60e9` | `9a87707f6a0d295abafba53e495503813425681d` |
| 12 | `33e67cec20afd970dd562345df23689f1608900a` | `8267b01317f131cef750c67da63e3722de199625` |
| 13 | `57ac64deae68c5ae5f73e5393a7e76e81ce13c47` | `a5af816e856e63595530784be1c5dee793b285fc` |
| 14 | `b3e1e2b43a1e6949c6275ed6762ad323c49c31cf` | `2cff06c9eed07a93eb2de1d06064d1d57e02cc91` |
| 15 | `f6c4b930658d75f547c7f4f6fe6d0f780b3c4544` | `fcd1b0a49bffbc287960c0763669b37003e781e3` |
| 16 | `b0726d62814b86e2af8b74d9a8a06d35e783b8c5` | `621fe15c47e0c4f61e6a48ab2971e82675c4a8ee` |
| 17 | `1cb515c0596761045b92dfa044479a6c321ae931` | `943c864ca2bc4005482baa43a09983299ecd482f` |
| 18 | `d72e4de87120521b6a5b488fa71225fc2b9e89cf` | `2c9ac8c1342c43a12da64cb4376d7f02bf3e560f` |
| 19 | `b825d94a8b6e1099cc3b059b17e515100085290f` | `ff56272d8b0f76f655b011982352cb564732fa91` |
| 20 | `33a36ead779dbba3c69f1b1b9679a2710106685e` | `65eb70c273f51a1ef42cba9345641e1fc242f437` |
| 21 | `b240e888e90555c0d5aef10a0189e40fc52375cc` | `7d375b4349d7cbfd26c6a7772351e98e29f59dc7` |
| 22 | `4926dd1dfc6d5f5dcaecaa1c193cefc209a9e8fb` | `df8ce47ee063d09c9d100df0d8761defc63859c5` |
| 23 | `8a42dd9ef05578ffba180f4d165038309beac429` | `b71f691510d1cbfc3886ab91b4ab4f849a3a3082` |
| 24 | `ffff228c157ac96c8b03ec3df1e164ae23e01a6b` | `0309787bea4c9686aaea66f0a5eb8aec4cd51fbf` |
| 25 | `c9c5a3e21358a652649074cd1330a5ba3fc9dfab` | `cbd63d0aa7d0a316f00ce4f9efd59aa277a4287c` |
| 26 | `bf41fe822333eb26cedb09d49dd4fa258a8879c4` | `8f3db2fba48919547787717c350886dea29a0454` |
| 27 | `e6e89f6272bcd8cb20c8daff998ccef0ac079ba6` | `e668ae7a15382510ea314f366ae98f1cfd603dcf` |
| 28 | `ccf4f24ed1e0b7c9f791ed4f8e0d8442c5fe6f70` | `7ce5f341726ddde7865b67a1c8e22cd80c6bdda7` |
| 29 | `fb0a80b4daf736f94fa8209ca4150ce02fb44125` | `0f922306cbec1be3d05e0c889716cab73c45f030` |
| 30 | `256d56cb57f795472ca53abc53efe6e637c5776e` | `d73541b9a9b85e00ea11527e6df385cf1ea0c7a7` |
| 31 | `98c16311ab1484065f05177ac5fd6fe6eb228d7c` | `25fc1404c27c04535f9f2e2c306b5dd8af9e8966` |
| 32 | `445e805b7770d00c4114b19001812dd2d47483a7` | `6eb1ee5d09bd971e32fb9957498204bd88d01c9d` |
| 33 | `102ec7b13cf04f7f995758ba5a6b4a682bb6eecd` | `584b7cb7835c9dbb36bb91a2aef019767dc9a76b` |
| 34 | `7328d4b2b57c6e1e06ce0979bacdffa7a3217e7d` | `d89c72111586f8dc110e3aaf41854057be6e6980` |
| 35 | `cb80ced44692f7b29acbc72d04166ac1912f4e53` | `43f2f59364a5defdac97533450c18173c1442e1e` |
| 36 | `bf88df5a37fa3ff63edd8f76eaf32c1aec82f92e` | `ed68092d06083bb4d2a57eadae6a9f9f01b974e1` |
| 37 | `2722b97a03879db17da4b175913dda177faae7cc` | `68690c5f30768cb6e3b3862f3554633b3ee12f34` |
| 38 | `5b3da9c040af8223f9c34ed7e1524f2f69ca7c57` | `68cf120e5cb16e76aca59cfc82e08e4d53352758` |
| 39 | `7c20a14b3fb00a83ca3603cd85362148dfd2de74` | `f15e76f08e5491ee699a307e4c7724b2b877bd94` |
| 40 | `a1b421b0190c779dd9b44bee47c6a28d3421cd57` | `d02e9e085f85f3bd4c2aacee61ad27f462b8f756` |
| 41 | `3a3c9cc64335ea31c7b4605a6f95aaed9fbcc319` | `693d2c7240bdbb0192449d4730d7ff21358109ab` |
| 42 | `7d191e8b9a9c5839cdbbd7ca4ab3fd7f1b216a76` | `034aa2062bedfab1e843dda308dfa9163207e47c` |
| 43 | `68b2caa23eb3fa660e522076ba0cbf48bd3daaf1` | `cc3f2f892b170cf6a78bc890f178784d2a96afd6` |
| 44 | `91b7072e02e7f80f600c32f4347f5418afb98ef1` | `074deb786e08920bfee92f09f71e2d43d7cb2301` |
| 45 | `ce1fa19fa41e54399fa60bf13330cc3937dc43c0` | `2fc5fe2a5595ba046c9ef17b181f50773e5c849e` |
| 46 | `807d85fb785f99fd437a0a087db867d2924177be` | `252a8184224e1f477c3c393605c60c10c1f0b50f` |
| 47 | `9b2406bdad46e3bb3b595fa0458bf610cfb6e017` | `0a3e7f6c1a89bcef9cbdfdb4b3f93c4a3e2ec822` |
| 48 | `be4e5e22ce14cc11eaf6248e50f3d1046c853c0a` | `131d02dd915e206eede34663afc123a178491d8f` |
| 49 | `e495b12cae71601b33539d2ea77b99eb8c1f444f` | `a58f27a319908e0aa9e9bd943e9d5517a7927ab2` |
| 50 | `7ad5717c088bfdc3472ae7b50d232893c1175934` | `b3b0ee22926e4859fae886fa358e7b1000977b7f` |
| 51 | `8e632f42f603c5b7362206f282bdd95a267d7cef` | `d124089599e6c5c779ba24ff90f0075b79840924` |
| 52 | `5db581ccbff0291025f8eaa9f998cfac3cfae7bd` | `750eb4af06d3a40b0ecd8e99e75878745afdee5f` |
| 53 | `15aabea28c77bbbd52b2395656ac4357494057f8` | `3b1ad5411936e849af4ffd572d6ab6cdfd191155` |
| 54 | `35ce6afdbc14c7fa8379f7f8aec871dd21a1dfab` | `9cf82d863b7227c00dbbd4b2d08b1920866e15d9` |
| 55 | `e7ebfe3f706a50033543452afee2d114eba5df45` | `435ff2a3b6eb590fd69f2405a8db887fac04801c` |
| 56 | `af312c419a533f3aba19f59d0f41782c9cab487f` | `908db250472cd52cf5830c7e544431ecb279bfcb` |
| 57 | `c3c14c54d0ee3bbfb78b304ecfd5e6930b48eac6` | `936196e63a5cffeab0f0778d17b43dcbe6cf5a18` |
| 58 | `a0f77a148603b3bd3b4182aaf1e4020471263006` | `869ef301ead45c62ba2e5717c038dab9e2cddb69` |
| 59 | `f7dac0557e707bd69892135c94439bbd7fc00caf` | `43fc868d9617795971441b8a655e235e0161923f` |
| 60 | `6b366787e22f171885c2835e0b28f49ee06b0f3a` | `8e191d6bcee25ae3905ce31f20cc1aaed97151db` |
| 61 | `0d87e4d10c75d863e26e8c2d14cfec3bd0b22208` | `a93e21bccd03b81f1a5317e8eb01976c26412f82` |
| 62 | `bfc450dacffa3abe525bcb6770b23a1f457170e4` | `f8b17d3d2eb42d4e9e76fd7a5324fb5c272d8dad` |
| 63 | `93269c917b61fb1872a8b6cd3adf0af61586d877` | `ab468f7defbbd4f1bccd29180800710dc36e20c5` |
| 64 | `85e2086ab6c32c2c202cd7ad37ccae8aed9ba08e` | `3b7560bbe7d36a797d01e3c5eb2f88b23c3d7f8a` |
| 65 | `aaaf46a52366dddeba391b4b5f86d0f6893cf70a` | `3bc3a8e8c5e8c8b6961a622ecf4c5961e62a321d` |
| 66 | `be20db39e5da1b53256edcb0ee3347628cad416a` | `62eaf4f227cb93f294b2a0508855cd3127844cfb` |
| 67 | `44c0ea21be35d590275feba4385219ce1d9ac693` | `2ca1ec041c402eea61d8bc9cfb0ae7cfab03ef75` |
| 68 | `fb9dd5206eb09fc185ae8fa74124d214b03ba435` | `956304dab600c8bf959984859641ebdbbdee5a3f` |
| 69 | `30432fd001e882b3375c2e69afa6f65fd280a353` | `0c1b974a708cf1b4e302a7321322420fff69c72b` |
| 70 | `a37733d0291f69289e6bb58dac5416e1937f90fd` | `82f7fadce27d5bfb3771bf3a8f15290b075916ca` |
| 71 | `b977f0aed77e24f519c23bc1e354289975cbdc80` | `1babb75f047b5c6cd39f92e00fe76f7a4311011e` |
| 72 | `abbce583bdefdad8968ddfad4329b112412476c2` | `3363adff434257de43dac80c72147ac0771d6632` |
| 73 | `45bac4fd990d0907f0c5646b8932bda941313ff7` | `8be225a38d1e3404b271072f55d4da3865408380` |
| 74 | `b5a3c9b6740fc1eb786d89b4a41b229a5bebb9b9` | `4adede4572b680c8046b22fb5d3e3c4153067ee5` |
| 75 | `904525c2254716a33f5e61ae1ec851b4a176804a` | `88d0477fa796d430976da6a2ff11283868425473` |
| 76 | `cd8cc150a1debe89813313f687c444442f02f756` | `0165fd11cef0bbd1dc24669ebc4e80d13836461b` |
| 77 | `c24d3e02bd6a7bc88f55c52008e361f94b980a85` | `9194a0c6319193616c8310f5a1dc0a391803b205` |
| 78 | `16b2715704fa38f606a9c9707c8aef6b1be2a294` | `3a809b840caac66c2f0fa6b6d2f7bea6f3f11d4f` |
| 79 | `27847dc50ea85d4a560f7c9a5cd9ea6be5a0ac96` | `181716a766ea26640d2d6bb11f0721103c386f5a` |
| 80 | `f6dff837c324e9d8699a680e380cf5ab6d3ff1a5` | `1811286484283c87af5bfe0746e717ec37dbd830` |
