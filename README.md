# Next Token Skill

让你的 AI Agent 能查到播客 [Next Token｜词元之外](https://nexttoken.tv/) 里聊过什么。

装上之后，问 Agent 任何和 AI 有关的问题，它会先检索节目的逐字稿和文章，回答时附上主理人的观点和 B 站 / YouTube 的时间戳链接，点开就能从那句话开始看。

## 它能做什么

- **回答问题时引用节目**：例如问“一人公司靠谱吗”，回答里会带上几位主理人各自的看法和视频位置。
- **话题时间线**：例如问“大家对 Muse 的看法变过吗”，按时间列出各期的说法。
- **本周速览**：问“最近 AI 圈有什么事”，给出最新一期的要点。
- **主理人观点对比**：同一个话题，杨攀、歸藏、橘子、向阳乔木分别怎么看。

节目没聊过的内容，它不会硬凑引用。

## 安装

需要 Python 3（macOS 和大多数 Linux 自带），不需要安装任何依赖。

### Claude Code

把仓库克隆下来，再把 `next-token` 目录链接到 Claude Code 的 skills 目录：

```bash
git clone <仓库地址> next-token-skill
```

```bash
mkdir -p ~/.claude/skills && ln -s "$(pwd)/next-token-skill/next-token" ~/.claude/skills/next-token
```

重新打开 Claude Code 就能用。以后更新只需要在仓库目录里执行 `git pull`。

### 其他 Agent

把 `next-token` 整个目录放进该 Agent 的 skills 目录即可。它只包含一份说明（`SKILL.md`）和一个脚本（`scripts/nexttoken.py`），任何能读说明、能运行命令的 Agent 都可以用。

## 工作方式

- **内容存在本机**：首次使用时，脚本把全部节目的逐字稿和博客文章同步到 `~/.cache/nexttoken/`，之后的检索都在本地完成，不会每次提问都请求网站。
- **自动更新**：每次运行会先检查有没有新一期，有就自动拉取（10 分钟内不重复检查）。博客文章每天最多刷新一次。
- **链接来自官网**：所有时间戳链接都是从 nexttoken.tv 的文字稿页面原样取得的，Agent 不会自己拼接。

## 直接使用脚本

不通过 Agent 也可以在终端里用：

```bash
python3 next-token/scripts/nexttoken.py search 一人公司 OPC 超级个体
```

```bash
python3 next-token/scripts/nexttoken.py timeline Muse
```

```bash
python3 next-token/scripts/nexttoken.py episodes
```

```bash
python3 next-token/scripts/nexttoken.py read 009 2
```

```bash
python3 next-token/scripts/nexttoken.py sync --full
```

| 命令 | 作用 |
|---|---|
| `search 词1 词2 ...` | 检索逐字稿和文章。可加 `--speaker 歸藏`、`--episode 009`、`--limit`、`--context` |
| `timeline 词1 ...` | 一个话题在各期里的说法，按时间排列 |
| `episodes` | 列出所有节目和章节 |
| `read 期号 [章节号]` | 读某期的章节列表，或某一章全文 |
| `sync --full` | 重新拉取全部内容，用于获取文字稿的修订 |

缓存位置可以用环境变量 `NEXTTOKEN_HOME` 修改。

## 已知限制

- **部分段落的时间是近似的**：官网约三成段落没有单独的时间戳（早期几期更多），这些段落沿用前一段的链接，输出里会标“约”。
- **依赖官网页面结构**：脚本解析的是文字稿网页，如果官网改版，同步可能失败，需要更新脚本。已同步到本地的内容不受影响。
- **只适用于能运行命令的 Agent**：ChatGPT、Claude 网页版这类不能运行本地脚本的环境用不了。
- **文字稿修订不会自动同步**：已发布的节目如果事后更正，需要手动执行 `sync --full`。
