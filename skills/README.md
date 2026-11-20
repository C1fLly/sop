# 技能副本

`mattpocock/` 下是 [mattpocock/skills](https://github.com/mattpocock/skills) 在提交 `5863806`（2026-11-12）时的 `skills/` 目录和 `LICENSE`，**原样**，路径和上游仓库里一样（设计书 3.2、W12）。技能目录里的任何文件一个字都不许改；工具包的约定写在技能之外（附录 B）。

| 文件 | 内容 |
|---|---|
| `mattpocock/LICENSE` | 上游的许可（MIT），原样 |
| `mattpocock/skills/<分类>/<技能>/` | 39 个技能目录，整个目录（含 `agents/openai.yaml`，10.2 第 4 条） |
| `source.json` | 版本记录：上游地址、完整的提交编号、每个文件的 Git 指纹和权限、`skills/` 的目录指纹 |
| `record.py` | 换版本时用：从上游的本地克隆按指纹原样取出、写版本记录（换技能版本一律算大版本，7.11） |

核对：总检查里的 `checks/skills_pristine` 每次都拿这份副本和 `source.json` 逐字比（内容、换行、执行权限、多文件、少文件都报）。`source.json` 里的目录指纹和上游 `git rev-parse 5863806:skills` 是同一个数，可以拿上游仓库自己核对：

```bash
git clone --no-checkout https://github.com/mattpocock/skills.git /tmp/<空目录>/src
git -C /tmp/<空目录>/src rev-parse 5863806:skills   # 应为 76953a7e724d1df247c12f465319563bb022f2fe
```

许可的要求（MIT）：复制全部或大部分内容时，要带上版权声明和许可声明，也就是 `mattpocock/LICENSE` 这个文件。工具包仓库里带着它；把技能复制进项目（I4，`kernel/projectnew.py`）时也把它原样带过去，放在技能目录之外：`.claude/LICENSE-mattpocock-skills`、`.agents/LICENSE-mattpocock-skills`。
