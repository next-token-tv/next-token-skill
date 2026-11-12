<div align="center">

<a href="https://nexttoken.tv/">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://nexttoken.tv/assets/brand-kit/next-token-media-lockup-inline-dark.svg">
    <img src="https://nexttoken.tv/assets/brand-kit/next-token-media-lockup-inline.svg" alt="Next Token｜词元之外" width="420">
  </picture>
</a>

# Next Token Skill

**让你的 AI Agent 听过每一期 Next Token。**

问它任何和 AI 有关的问题，它会引用四位主理人在节目里的观点，<br>
并附上 B 站 / YouTube 的时间戳链接，点开就从那句话开始看。

[![Agent Skill](https://img.shields.io/badge/Agent-Skill-111111)](next-token/SKILL.md)
[![Claude Code](https://img.shields.io/badge/Claude_Code-可用-d97757)](#安装)
[![Python 3](https://img.shields.io/badge/Python-3-3776ab)](next-token/scripts/nexttoken.py)
[![零依赖](https://img.shields.io/badge/依赖-0-2ea44f)](#工作方式)
[![License](https://img.shields.io/badge/代码-Apache_2.0-blue)](LICENSE)

[官网](https://nexttoken.tv/) · [全部节目](https://nexttoken.tv/weekly) · [B 站](https://space.bilibili.com/3745066753461159) · [YouTube](https://www.youtube.com/channel/UC_9pr_usdNG29RauPFwIFQw) · [小宇宙](https://www.xiaoyuzhoufm.com/podcast/6a9956fafbb9512fc83ddbb5)

</div>

---

[Next Token｜词元之外](https://nexttoken.tv/) 是一档从中文世界一手经验出发，聊 AI 技术、产品、创业与创作的视频播客。四位联合主理人杨攀、歸藏、橘子、向阳乔木每周一张圆桌，讨论过去一周真正值得关注的 AI 新闻。

每期一个多小时，不一定有时间听完。这个 skill 把全部节目的逐字稿和文章交给你的 Agent：你照常提问，它帮你找到节目里相关的那几句话，并把你带到视频的对应位置。

## 效果

提问时不需要提到播客。下面是一次真实回答的节选：

> **你**：Muse 这个产品最近怎么样了？大家对它的看法有变化吗
>
> **Agent**：从节目里看，大家对它的评价是越来越高的：9 月初它还只是“Meta 也出了个聊天机器人”，到 10 月已经成了主理人日常在用的生活助理。不过 10 月底开始有人质疑，它到底能撑起多大的市场。
>
> - **9 月底，爆火**：向阳乔木说它每个功能单独看都平平无奇，赢在简单、好上手、不那么极客。[#004 · 33:22](https://www.bilibili.com/video/BV1AAaa6VE88?t=2002)
> - **10 月，开放硬件生态**：杨攀认为这些开放出来的硬件，就是 Muse 这个 Personal Agent 的“物理外挂”。[#005 · 56:28](https://www.bilibili.com/video/BV1ZDHX6eEwz?t=3388)
> - **另一个角度**：杨攀转述了几次访谈里的说法，Muse 上花时间最多的场景是旅游，他觉得如果只做到这些，市场就太小了。[#007 · 31:08](https://www.bilibili.com/video/BV189nQ6SEY7?t=1868)

## 它能做什么

| 你可以这样问 | 它会 |
|---|---|
| “一人公司靠谱吗” | 先回答问题，再给出主理人各自的看法和视频位置 |
| “大家对 Muse 的看法变过吗” | 按时间列出各期的说法，指出看法是怎么变的 |
| “最近 AI 圈有什么事” | 给出最新一期的要点，每条带链接 |
| “几位主理人对这事有分歧吗” | 每人一句立场，分别附链接 |
| “有没有哪期值得听” | 按你的兴趣推荐具体章节 |
| 你正在做产品、选模型、写内容 | 把节目里的观点落到你手上的事，再给一个不同的角度 |

节目没聊过的内容，它不会硬凑引用。

## 安装

需要 Python 3（macOS 和大多数 Linux 自带），不需要安装任何依赖。

### Claude Code

把仓库克隆下来，再把 `next-token` 目录链接到 Claude Code 的 skills 目录：

```bash
git clone https://github.com/next-token-tv/next-token-skill.git next-token-skill
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
- **零依赖**：只用 Python 标准库，没有向量库，也不需要 API Key。

## 直接使用脚本

不通过 Agent 也可以在终端里用：

```bash
python3 next-token/scripts/nexttoken.py search 一人公司 OPC 超级个体
```

```bash
python3 next-token/scripts/nexttoken.py timeline Muse
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

## 收听节目

[B 站](https://space.bilibili.com/3745066753461159) · [YouTube](https://www.youtube.com/channel/UC_9pr_usdNG29RauPFwIFQw) · [小宇宙](https://www.xiaoyuzhoufm.com/podcast/6a9956fafbb9512fc83ddbb5) · [Spotify](https://open.spotify.com/show/2xCECrt8be0mcGmnlpL9Au) · [Apple Podcasts](https://podcasts.apple.com/us/podcast/id6809305832) · [官网文字稿](https://nexttoken.tv/weekly)

## 许可

- **代码**：[Apache License 2.0](LICENSE)，可以自由使用、修改和再分发。
- **节目内容**：逐字稿、文章、音视频和“Next Token｜词元之外”品牌不在开源许可范围内，版权归 Next Token 及各位主理人所有。这些内容不包含在本仓库里，由脚本在运行时从官网获取。欢迎注明出处并带链接地引用，批量转载或再分发请先联系我们。详见 [NOTICE](NOTICE)。
