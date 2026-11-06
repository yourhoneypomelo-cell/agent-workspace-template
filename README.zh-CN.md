# Agent workspace template

中文 | **[English](README.md)**

一个为 AI 编程代理设计的、基于文件的记忆系统。它让任何代理工具——Claude Code、Codex、
Cursor、Kimi Code、Kiro、DeepSeek Harness 等——拥有一份共享的持久记忆，在切换窗口、
上下文压缩和更换工具之后仍然保留。

项目的每一个事实都以纯 Markdown 文件的形式存放在 `docs/` 下。新会话读取这些文件，
从上一个会话停下的地方继续。不需要数据库，不需要服务器，没有锁定：只用 Python 标准库、
纯文本和一个命令行工具。

## 为什么需要它

AI 代理在长项目中会丢失进度。它们忘记需求、重复已完成的工作、提议用户已经否决的功能、
没有运行测试就声称任务完成。这个模板通过让代理把每一条需求、决策、任务和证据记录在文件中，
使下一个会话在动手之前就能读到它们，从而防止这些问题。

## 快速上手

1. **下载**最新发布包：
   [Releases](https://github.com/yourhoneypomelo-cell/agent-workspace-template/releases)，
   解压到一个空的项目文件夹里。

2. **在代理工具中打开项目**，然后说：

   > 读取 AGENTS.md 并开始。

3. **用一句话说明目标**。代理会创建状态文件，把目标记录为需求，然后开始工作。

4. **可选：启用钩子**，让工具自动保存聊天记录并在会话开始时注入工作区摘要：

   ```bash
   python .agents/tools/ws.py hooks enable claude
   ```

   把 `claude` 换成 `codex`、`cursor`、`gemini`、`copilot`、`kiro`、`grok`、`qwen` 或
   `codebuddy`，对应你使用的工具。

## 工作方式

```text
会话开始：  brief → 读取状态 → start → 工作并记录 → verify → checkpoint
下一次会话：  ↑                                                            |
              └────────────────────────────────────────────────────────────┘
```

- **AGENTS.md** 是每个代理都要读的根契约。它定义了会话协议、状态文件格式和保持工作区
  一致的规则。
- **`docs/state/`** 存放七个 Markdown 文件：交接卡、需求、偏好、功能、任务、架构和设计
  决策。它们是事实的唯一来源。
- **`docs/logs/`** 记录了发生了什么：会话历史、需求变更、功能变更。
- **`docs/chats/`** 保存聊天记录，不丢失任何用户消息。
- **`ws.py`** 是命令行工具，负责验证写入、分配 ID、运行验收测试、封存检查点。代理只需要
  运行它。

## 核心特性

- **先记录，再行动。** 每条用户消息在处理之前都会检查是否包含新的需求、决策和偏好。
- **验证过的完成。** 任务只有在验收命令通过之后才标记为完成。工具运行测试、保存证据、
  更新状态。
- **并行会话。** 多个代理窗口可以同时工作。任务声明通过文件路径和资源名防止冲突。过期锁
  按代际号回收，不靠猜测进程是否存活。
- **凭据安全。** 工具会询问项目如何处理凭据（保留、脱敏或每次询问），并在每次写入时遵循
  该规则。
- **宿主适配器。** AGENTS.md 是唯一契约。Claude Code、Codex、Cursor、Gemini、Kiro、
  Kimi Code、Grok、DeepSeek Harness、CodeBuddy 和 Qwen Code 的适配器原生加载它。
- **压缩存活。** 状态文件在磁盘上，不在代理的上下文窗口里。压缩之后代理重新读取它们，
  继续工作。

## 安装到已有项目

```bash
# 从模板目录运行：
python .agents/tools/ws.py install --target /path/to/your/project --merge

# 或者把发布包解压到项目根目录。
```

`--merge` 会保留你已有的 AGENTS.md，追加到"项目规则"一节。

## 设计思路

[DESIGN.zh-CN.md](DESIGN.zh-CN.md) 解释了结构背后的推理：为什么用文件而不是数据库、
为什么先记录再行动、证据如何工作、以及哪些替代方案被否决了。

## 指南

| 指南 | 用途 |
| --- | --- |
| [快速上手](.agents/guides/QUICKSTART.md) | 安装、第一个会话、日常使用 |
| [协议](.agents/guides/PROTOCOL.md) | 格式、所有权、证据和恢复 |
| [结构](.agents/guides/STRUCTURE.md) | 文件夹、命名、文档大小和写作风格 |
| [宿主](.agents/guides/HOSTS.md) | 各工具的入口文件和钩子 |

## 环境要求

Python 3.10 或更新版本。不需要安装任何包——只用标准库。

## 许可证

[MIT](LICENSE)
