# 给 AI Agent：安装并使用知衢

用户把这个仓库的链接发给你，意思是：**安装知衢技能，然后用它帮用户做高考志愿分析。** 本文件对任何 Agent 通用（Claude Code、Codex、Kimi、豆包、DeepSeek、自建 harness 等）。先判断你有哪些能力，再按对应的一档执行。

技能本体是 `skills/zhiqu/SKILL.md`，它是唯一的工作流程说明；本文件只负责"装上"和"读到"。

## 第一档：能运行 shell 和 Python（推荐）

1. 下载仓库：

   ```bash
   git clone --depth 1 https://github.com/WJSGZZ/Zhiqu.git
   ```

   没有 git 时，下载 `https://github.com/WJSGZZ/Zhiqu/archive/refs/heads/main.zip` 并解压。

2. 如果你的 Agent 有技能目录，把 `Zhiqu/skills/zhiqu` 整个文件夹复制过去；不确定时，就留在克隆的位置，直接读取其中的 `SKILL.md`。

   | Agent | 技能目录 |
   |---|---|
   | Claude Code | `~/.claude/skills/zhiqu/` |
   | Codex | `~/.codex/skills/zhiqu/` |
   | 其他支持 `SKILL.md` 的 Agent | 该 Agent 文档规定的技能目录；常见的是 `~/.agents/skills/zhiqu/` |
   | 不支持技能的 Agent | 不用复制，每次对话先读 `skills/zhiqu/SKILL.md` |

   只写入技能目录或克隆位置，不改动用户的其他文件和系统设置。

3. 检查环境：`python3 --version` 需要 3.8 或以上。脚本只用标准库，不需要 `pip install`。生成 PDF 报告需要本机有 Chrome、Edge 或 Chromium；没有时脚本会输出 HTML。

4. 验证安装：

   ```bash
   python3 skills/zhiqu/scripts/optimize.py skills/zhiqu/examples/candidates_demo.csv --rank 30000 --slots 12 --u-fall -60
   ```

   能输出一张志愿表即可。

5. 告诉用户装到了哪里，然后按 `SKILL.md` 开始工作：请用户先填[在线问卷](https://wjsgzz.github.io/Zhiqu/)并把生成的画像发过来。

## 第二档：能联网读网页，但不能运行代码

依次读取下面的原始文件，按 `SKILL.md` 的流程工作：

- https://raw.githubusercontent.com/WJSGZZ/Zhiqu/main/skills/zhiqu/SKILL.md
- `SKILL.md` 里提到的参考文件，按需读取，地址格式为 `https://raw.githubusercontent.com/WJSGZZ/Zhiqu/main/skills/zhiqu/references/<文件名>.md`：`profile-analysis.md` `volunteer-game.md` `outlook.md` `school-research.md` `backtests.md` `report-guide.md`

这一档的限制，必须在开始前告诉用户：

- 录取概率、期望效用要靠脚本做模拟计算。不能运行代码时，只能给出近似判断，**不能写出精确的概率**，也不能冒充脚本的计算结果。
- 如果你有代码解释器或沙盒（能执行 Python，但不能访问用户电脑），把 `skills/zhiqu/scripts/` 下的脚本下载进沙盒运行，就等同于第一档。
- 生成不了 PDF 时，按 `references/report-guide.md` 的结构用文字交付，并建议用户换一个能运行代码的 Agent 出正式报告。

## 第三档：不能联网

请用户把 `skills/zhiqu/SKILL.md` 的内容复制给你，或者换一个能联网的 Agent。不要凭印象编造本技能的规则或任何录取数据。

## 无论哪一档

- 录取数据只用各省教育考试院和高校的官方发布；查不到的写"未查到"，不要编造。
- 需要问学长学姐的事，只帮用户准备问题，由考生本人去问。
- 不保证录取；以本省考试院和各校当年的招生章程为准。
